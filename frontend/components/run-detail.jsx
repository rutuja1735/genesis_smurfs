'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useWorkspace } from './workspace-provider';
import { MarkdownResponse } from './markdown-response';
import { active, api, date, download, pretty } from '../lib/api';
import { Button, Empty, Header, Icon, Panel, Stat } from './ui';

export function RunDetail({ id }) {
  const { refresh } = useWorkspace();
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState('');
  const [connection, setConnection] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); let stream; let fallback; let inFlight = false;
    setRun(null); setEvents([]); setError(''); setConnection('');
    async function update() {
      if (inFlight || controller.signal.aborted) return null;
      inFlight = true;
      try {
        const [detail, history] = await Promise.all([api(`/runs/${encodeURIComponent(id)}`, { signal: controller.signal }), api(`/runs/${encodeURIComponent(id)}/events`, { signal: controller.signal })]);
        if (controller.signal.aborted) return null;
        setRun(detail); setEvents(history); setError('');
        if (!active(detail.status)) { stream?.close(); clearInterval(fallback); setConnection(''); refresh(); }
        return detail;
      } catch (e) { if (e.name !== 'AbortError') setError(e.message); return null; }
      finally { inFlight = false; }
    }
    update().then(detail => {
      if (!detail || controller.signal.aborted || !active(detail.status)) return;
      stream = new EventSource(`/api/runs/${encodeURIComponent(id)}/stream`);
      stream.onmessage = update;
      stream.onopen = () => setConnection('');
      stream.onerror = () => setConnection('Reconnecting to live events…');
      // Poll as a fallback if a proxy or temporary network failure interrupts SSE.
      fallback = setInterval(update, 4000);
    });
    return () => { controller.abort(); stream?.close(); clearInterval(fallback); };
  }, [id, retry, refresh]);
  if (error && !run) return <><Header title="Run unavailable" description={error} /><Button onClick={() => setRetry(n => n + 1)}>Retry</Button> <Link href="/runs" className="button secondary">Back to runs</Link></>;
  if (!run) return <div className="loading">Loading execution…</div>;
  const result = run.result;
  return <><Header title="Run details" description={run.command}><Link href="/runs" className="button secondary"><Icon name="back" />All runs</Link><Button icon="download" variant="secondary" onClick={() => download(`agentgaurd-${id}-events.json`, events)}>Export events</Button></Header>{(error || connection) && <div className="note">{error || connection}</div>}<div className="stats"><Stat label="Status" value={<span style={{ fontSize: 22 }}>{pretty(run.status)}</span>} detail={id} icon="clock" /><Stat label="Defense" value={<span style={{ fontSize: 21 }}>{run.defense === 'ours' ? 'Plan-first' : pretty(run.defense)}</span>} detail="Execution protection" icon="shield" /><Stat label="Executed tools" value={result?.executed_calls?.length || 0} detail="Completed tool calls" icon="check" /><Stat label="Events recorded" value={events.length} detail="Full execution trail" icon="file" /></div><div className="two-columns"><div className="stack"><Panel title="Agent response"><div className="panel-pad">{run.status === 'done' ? <MarkdownResponse>{result?.answer || 'Run completed without an answer.'}</MarkdownResponse> : run.status === 'error' ? <div className="error-banner">{run.summary?.error || 'The run could not complete. Inspect the execution trail for details.'}</div> : <Empty title="Your agents are working" description="Planning, validating, and executing your request. This page updates automatically." />}</div></Panel><Panel title="Run configuration"><div className="list"><div className="list-row"><div><h3>Created</h3><p>{date(run.created_at)}</p></div></div><div className="list-row"><div><h3>Attack pattern</h3><p>{run.attack ? pretty(run.attack) : 'No injection'}</p></div></div><div className="list-row"><div><h3>Injection goal</h3><p>{run.injection_goal || 'None'}</p></div></div></div></Panel></div><Panel title="Execution trail" className="execution-trail-panel"><details key={id} className="execution-trail"><summary><span className="trail-expand">Expand execution trail</span><span className="trail-collapse">Collapse execution trail</span><span className="trail-count">{events.length} {events.length === 1 ? 'event' : 'events'}</span></summary><div className="execution-trail-events">{events.length ? events.map((event, i) => <div key={`${id}-${i}`} className={`event ${event.event === 'RUN_ERROR' ? 'error' : ''}`}><h3>{pretty(event.event)}</h3><time>{date(event.ts)}</time>{(event.reason_human || event.reason) && <p>{event.reason_human || event.reason}</p>}{event.tool && <p className="mono">{event.tool}</p>}<details><summary>Event data</summary><pre>{JSON.stringify(event, null, 2)}</pre></details></div>) : <Empty title="Waiting for events" description="Events appear as the run progresses." />}</div></details></Panel></div></>;
}
