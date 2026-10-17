'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { agentInfo, api } from '../lib/api';
import { useWorkspace } from './workspace-provider';
import { Badge, Button, Header, Icon, Note, Panel, SectionHeading } from './ui';

export function AgentCards() {
  const { tasks } = useWorkspace();
  return <div className="agent-grid">{Object.entries(agentInfo).map(([id, a]) => <article className="panel agent-card" key={id}><div className="agent-header"><span className={`agent-symbol ${id}`}><Icon name={a.icon} /></span><span className="badge gray">Mock environment</span></div><h3>{a.name}</h3><p>{a.desc}</p><div className="agent-footer"><span>{tasks.filter(t => t.suite === id).length} available tasks</span><Link href={`/agents/${id}`}>Open agent <Icon name="chevron" /></Link></div></article>)}</div>;
}
export function Agents() { return <><Header title="My agents" description="A focused workspace for every part of your workflow." /><AgentCards /><SectionHeading title="How your agents work" /><div className="two-columns"><Panel title="Plan-first execution"><div className="panel-pad"><p>Your request becomes a validated tool dependency graph before execution. Every action passes deterministic policy and provenance checks.</p><Note>These agents use isolated JSON mock data. Email, Slack, and banking actions do not affect real accounts.</Note></div></Panel><Panel title="A record of every action"><div className="panel-pad"><p>Inspect tool execution, injection detections, output filtering, and policy decisions from the run detail page.</p><Link className="text-link" style={{ marginTop: 20 }} href="/runs">Explore execution history<Icon name="arrow" /></Link></div></Panel></div></>; }
export function AgentDetail({ id }) {
  const { tasks, config, preferences, newRun } = useWorkspace();
  const [tab, setTab] = useState('tasks');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const a = agentInfo[id];
  useEffect(() => { if (tab !== 'data') return; const controller = new AbortController(); setData(null); setError(''); api(`/data/${id}`, { signal: controller.signal }).then(setData).catch(e => { if (e.name !== 'AbortError') setError(e.message); }); return () => controller.abort(); }, [id, tab]);
  return <><Header title={a.name} description={a.short}><Button icon="plus" onClick={() => newRun(null, id)}>New agent run</Button></Header><div className="two-columns"><section className="panel panel-pad"><div className="agent-detail-head"><span className={`agent-symbol ${id}`}><Icon name={a.icon} /></span><div><h2>{a.name}</h2><p>Isolated mock environment</p></div></div><p>{a.desc}</p><Note>Use a preset below or give this agent your own command. Runs use your configured OpenRouter model.</Note><div className="tab-list" role="tablist" aria-label="Agent views">{['tasks', 'data'].map(value => <button key={value} role="tab" aria-selected={tab === value} aria-controls="agent-content" onClick={() => setTab(value)} className={tab === value ? 'active' : ''}>{value === 'tasks' ? 'Available tasks' : 'Agent data'}</button>)}</div><div id="agent-content" role="tabpanel">{tab === 'tasks' ? tasks.filter(t => t.suite === id).map(t => <div className="list-row" key={t.id}><Icon name="file" /><div><h3>{t.prompt}</h3><p>Task {t.id}</p></div><button className="text-link" onClick={() => newRun(t, id)}>Run<Icon name="arrow" /></button></div>) : error ? <div className="error-banner">{error}</div> : data ? <pre>{JSON.stringify(data, null, 2)}</pre> : <div className="loading">Loading agent data…</div>}</div></section><Panel title="Agent configuration"><div className="panel-pad"><div className="switch-line"><div><h3>Execution mode</h3><p>Plan-first defense</p></div><Badge value="protected" /></div><div className="switch-line"><div><h3>Data source</h3><p>JSON-backed mock environment</p></div><Badge value="local" /></div><div className="switch-line"><div><h3>Model</h3><p>{config.model || 'Not configured'}</p></div></div><div className="switch-line"><div><h3>Prompt injection scanning</h3><p>Scan tool output before use</p></div><Badge value="enabled" /></div><div className="switch-line"><div><h3>Output filtering</h3><p>Check grounding and sensitive content</p></div><Badge value={preferences.output_filter ? 'enabled' : 'disabled'} /></div></div></Panel></div></>;
}
