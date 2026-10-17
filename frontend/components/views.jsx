'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useWorkspace } from './workspace-provider';
import { active, date, download, money, pretty, post } from '../lib/api';
import { AgentCards } from './agents';
import { Badge, Button, Chart, DefenseSelect, Empty, Field, Header, Icon, NeutralizeSelect, Note, Panel, RunTable, SectionHeading, Stat } from './ui';
export function Overview() {
  const { runs, stats, loading, newRun } = useWorkspace();
  const [mode, setMode] = useState('runs');
  const done = runs.filter(r => r.status === 'done').length;
  const running = runs.filter(r => active(r.status)).length;
  return <><Header title="Welcome back, Founder" description="Your agent workspace"><span className="date-pill"><Icon name="calendar" />{new Date().toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'short', month: 'short', day: 'numeric' })}</span></Header><div className="stats">
    <Stat label="Runs completed" value={done} detail={`${runs.length} total runs`} icon="check" green /><Stat label="Active agents" value="3" detail="Email, Slack, and Banking" icon="agents" /><Stat label="Execution progress" value={`${runs.length ? Math.round(done / runs.length * 100) : 0}%`} detail={`${running} runs currently in progress`} icon="clock" /><Stat label="Threats blocked" value={stats.decisions.BLOCK || 0} detail="Deterministic policy protection" icon="shield" />
  </div><div className="grid-main"><Panel title="Execution over time" action={<select className="compact" aria-label="Chart metric" value={mode} onChange={e => setMode(e.target.value)}><option value="runs">Agent runs</option><option value="done">Runs completed</option></select>}><Chart runs={runs} mode={mode} /></Panel><Panel title="Quick actions"><div className="quick-actions"><button className="quick-action" onClick={() => newRun()}><Icon name="play" /><span><strong>New agent run</strong><small>Give your agents a task</small></span><Icon name="chevron" className="arrow" /></button><Link className="quick-action" href="/agents"><Icon name="agents" /><span><strong>Explore your agents</strong><small>Email, Slack, and Banking</small></span><Icon name="chevron" className="arrow" /></Link><Link className="quick-action" href="/testing"><Icon name="shield" /><span><strong>Test your defenses</strong><small>Run an injection scenario</small></span><Icon name="chevron" className="arrow" /></Link></div></Panel></div><SectionHeading title="Your agents" href="/agents" label="View all agents" /><AgentCards /><SectionHeading title="Recent execution" href="/runs" label="View all runs" /><section className="panel">{loading ? <div className="loading">Loading execution history…</div> : <RunTable runs={runs.slice(0, 5)} newRun={newRun} />}</section><div className="footer-note">Plan first. Execute safely. Keep a clear record.</div></>;
}

export function Runs() {
  const { runs, refresh, newRun, loading } = useWorkspace();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [pending, setPending] = useState(false);
  const filtered = runs.filter(r => (status === 'all' || r.status === status) && r.command.toLowerCase().includes(search.toLowerCase()));
  return <><Header title="Agent runs" description="Plan, execute, and follow every step your agents take."><Button icon="plus" onClick={() => newRun()}>New agent run</Button></Header><Panel title="Execution history" subtitle={`${runs.length} runs in this workspace`} action={<Button icon="refresh" variant="secondary small" disabled={pending} onClick={async () => { setPending(true); await refresh(); setPending(false); }}>Refresh</Button>}><div className="toolbar"><div className="search"><Icon name="search" /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search commands…" aria-label="Search runs" /></div><select value={status} onChange={e => setStatus(e.target.value)} aria-label="Filter by status">{['all', 'done', 'running', 'pending', 'error'].map(v => <option key={v} value={v}>{v === 'all' ? 'All statuses' : pretty(v)}</option>)}</select></div>{loading ? <div className="loading">Loading runs…</div> : <RunTable runs={filtered} newRun={newRun} filtered={!!search || status !== 'all'} />}</Panel></>;
}

export function Analytics() {
  const { runs, stats, config } = useWorkspace();
  const done = runs.filter(r => r.status === 'done').length;
  const decisions = Object.values(stats.decisions).reduce((a, b) => a + b, 0);
  const reliability = runs.length ? Math.round(done / runs.length * 100) : 0;
  return <><Header title="Analytics" description="Derived from agent execution and policy decision data."><Button icon="download" variant="secondary" onClick={() => download('agentgaurd-runs.json', runs)}>Export runs</Button></Header><div className="stats"><Stat label="Runs completed" value={done} detail={`${runs.length} total (${reliability}%)`} icon="check" /><Stat label="Policy decisions" value={decisions} detail="Across all agent runs" icon="shield" /><Stat label="Execution reliability" value={`${reliability}%`} detail="Runs completed successfully" icon="trend" /><Stat label="Model spend" value={money(config.spent_usd)} detail={`$${Number(config.budget_usd || 4).toFixed(2)} workspace budget`} icon="wallet" /></div><div className="two-columns"><Panel title="Runs completed over time"><Chart runs={runs} mode="done" /></Panel><Panel title="Policy decision breakdown"><div className="panel-pad">{decisions ? Object.entries(stats.decisions).map(([label, count]) => <div className="bar-row" key={label}><span>{pretty(label)}</span><div className="progress-track"><span style={{ width: `${count / decisions * 100}%` }} /></div><b>{count}</b></div>) : <Empty title="No decisions recorded" description="Run an agent to see how your defenses respond." icon="shield" />}</div></Panel></div><SectionHeading title="Rule activity" href="/decisions" label="View audit decisions" /><Panel title="Deterministic policy rules">{Object.keys(stats.rules).length ? <div className="list">{Object.entries(stats.rules).map(([rule, count]) => <div className="list-row" key={rule}><Icon name="shield" /><div><h3>{rule || 'General checks'}</h3><p>Recorded policy decisions</p></div><span className="badge gray">{count}</span></div>)}</div> : <Empty title="Your policy activity will appear here" description="Decisions are recorded automatically during agent runs." icon="chart" />}</Panel></>;
}

export function Decisions() {
  const { decisions } = useWorkspace();
  const [filter, setFilter] = useState('all');
  const rows = decisions.filter(d => filter === 'all' || d.decision === filter);
  return <><Header title="Audit decisions" description="A transparent record of what was allowed, held, or blocked."><Button icon="download" variant="secondary" onClick={() => download('agentgaurd-decisions.json', rows)}>Export decisions</Button></Header><Panel title="Decision log" subtitle="Human-readable reasons for every policy check" action={<select className="compact" value={filter} onChange={e => setFilter(e.target.value)} aria-label="Filter decisions">{['all', 'ALLOW', 'BLOCK', 'FLAG', 'NEEDS_CONFIRM', 'SKIP'].map(v => <option key={v} value={v}>{v === 'all' ? 'All decisions' : pretty(v)}</option>)}</select>}>{rows.length ? <div className="table-wrap"><table><thead><tr><th>DECISION</th><th>TOOL / RULE</th><th>REASON</th><th>RUN</th></tr></thead><tbody>{rows.map(d => <tr key={d.id}><td><Badge value={d.decision} /></td><td><span className="mono">{d.tool || 'Output filter'}</span><p>{d.rule || 'General policy'}</p></td><td className="wrap">{d.reason_human || d.reason || 'All policy checks passed.'}</td><td><Link className="text-link mono" href={`/runs/${d.run_id}`}>{d.run_id}<Icon name="chevron" /></Link></td></tr>)}</tbody></table></div> : <Empty title="No matching decisions" description="Policy decisions from your agent runs will be collected here." icon="shield" />}</Panel></>;
}

export function Settings() {
  const { preferences, savePreferences, config, online, emailStatus, refresh } = useWorkspace();
  const [emailPending, setEmailPending] = useState(false);
  const [emailMsg, setEmailMsg] = useState('');
  const [allowlistInput, setAllowlistInput] = useState(emailStatus?.send_allowlist?.join(', ') || '');

  function submit(e) { e.preventDefault(); const data = new FormData(e.currentTarget); savePreferences({ defense: data.get('defense'), neutralize: data.get('neutralize'), output_filter: data.has('output_filter') }); }

  async function saveEmailConfig(e) {
    e.preventDefault(); setEmailPending(true); setEmailMsg('');
    const data = new FormData(e.currentTarget);
    const body = {
      email_agent: data.get('email_agent'),
      mode: data.get('email_mode'),
      dry_run: data.has('dry_run'),
      send_allowlist: allowlistInput.split(',').map(s => s.trim()).filter(Boolean),
    };
    try {
      await post('/email/config', body);
      await refresh();
      setEmailMsg('Email agent settings saved.');
    } catch (err) { setEmailMsg(`Error: ${err.message}`); }
    finally { setEmailPending(false); }
  }

  const es = emailStatus;
  return <><Header title="Settings" description="Your workspace configuration and execution preferences." />
    <div className="two-columns">
      <Panel title="Execution defaults" subtitle="Used when starting a new agent run">
        <form className="panel-pad" onSubmit={submit} key={JSON.stringify(preferences)}>
          <Field label="Defense mode" name="defense"><DefenseSelect defaultValue={preferences.defense} /></Field>
          <Field label="Injection neutralization" name="neutralize"><NeutralizeSelect defaultValue={preferences.neutralize} /></Field>
          <label className="switch-line"><span><h3>Filter final answers</h3><p>Check sensitive content and grounding</p></span><input className="switch" type="checkbox" name="output_filter" defaultChecked={preferences.output_filter} /></label>
          <Note>Preferences are saved in this browser and applied to new runs. Model and budget settings are managed by the backend environment.</Note>
          <Button type="submit">Save preferences</Button>
        </form>
      </Panel>
      <div className="stack">
        <Panel title="Model &amp; connection">
          <div className="panel-pad">
            <div className="switch-line"><div><h3>Backend</h3><p>Python API through the Next.js server</p></div><span className="connection-line"><span className={`status-dot ${online ? '' : 'offline'}`} />{online ? 'Connected' : 'Offline'}</span></div>
            <div className="switch-line"><div><h3>OpenRouter model</h3><p className="setting-value">{config.model || 'Not configured'}</p></div></div>
            <div className="switch-line"><div><h3>API version</h3><p>{config.version || '—'}</p></div><a href="/docs" target="_blank" rel="noopener" className="text-link">API docs<Icon name="external" /></a></div>
          </div>
        </Panel>
        <Panel title="Workspace budget">
          <div className="panel-pad">
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><h3>{money(config.spent_usd)} spent</h3><span className="split-note">${Number(config.budget_usd || 4).toFixed(2)} cap</span></div>
            <div className="progress-track"><span style={{ width: `${Math.min(100, (config.spent_usd || 0) / (config.budget_usd || 4) * 100)}%` }} /></div>
            <p style={{ marginTop: 15, fontSize: 10 }}>Recorded model spend. The backend checks the configured budget before each model request.</p>
          </div>
        </Panel>
      </div>
    </div>

    <SectionHeading title="Email agent" />
    <div className="two-columns">
      <Panel title="Email agent configuration" subtitle="Controls how the email agent accesses your mailbox">
        <form className="panel-pad" onSubmit={saveEmailConfig}>
          <div className="field"><label htmlFor="email_agent">Data source</label>
            <select id="email_agent" name="email_agent" defaultValue={es?.configured_agent || 'mock'}>
              <option value="mock">Mock environment (isolated JSON)</option>
              <option value="real">Real email (IMAP / Gmail)</option>
            </select>
          </div>
          <div className="field"><label htmlFor="email_mode">Operation mode</label>
            <select id="email_mode" name="email_mode" defaultValue={es?.mode || 'readonly'}>
              <option value="readonly">Read-only</option>
              <option value="draft_only">Draft only</option>
              <option value="draft">Draft + read</option>
              <option value="full">Full (send enabled)</option>
            </select>
          </div>
          <label className="switch-line">
            <span><h3>Dry-run mode</h3><p>Simulate writes without touching the mailbox</p></span>
            <input className="switch" type="checkbox" name="dry_run" defaultChecked={es?.dry_run !== false} />
          </label>
          <div className="field">
            <label htmlFor="allowlist">Send allowlist <small>(comma-separated)</small></label>
            <input id="allowlist" value={allowlistInput} onChange={e => setAllowlistInput(e.target.value)} placeholder="alice@example.com, bob@example.com" />
          </div>
          {emailMsg && <div className={emailMsg.startsWith('Error') ? 'error-banner' : 'note'} role="status">{emailMsg}</div>}
          <Note>Changes take effect immediately for new runs. Dry-run and allowlist are safety backstops in addition to the security gate.</Note>
          <Button type="submit" disabled={emailPending}>{emailPending ? 'Saving…' : 'Save email settings'}</Button>
        </form>
      </Panel>
      <Panel title="Email backend status">
        <div className="panel-pad">
          {es ? <>
            <div className="switch-line"><div><h3>Active agent</h3></div><Badge value={es.active_agent || es.configured_agent || 'mock'} /></div>
            <div className="switch-line"><div><h3>Backend type</h3><p>{es.backend_type}</p></div></div>
            <div className="switch-line"><div><h3>Dry-run</h3></div><Badge value={es.dry_run ? 'on' : 'off'} /></div>
            <div className="switch-line"><div><h3>Mode</h3></div><Badge value={es.mode || 'readonly'} /></div>
            {es.inbox_stats?.unread != null && <div className="switch-line"><div><h3>Inbox</h3><p>{es.inbox_stats.unread} unread / {es.inbox_stats.total} total</p></div></div>}
            {es.inbox_stats?.error && <Note>Inbox probe: {es.inbox_stats.error}</Note>}
            <hr style={{ margin: '14px 0', border: 'none', borderTop: '1px solid #edf0f4' }} />
            <h3 style={{ fontSize: 12, marginBottom: 8 }}>Credentials</h3>
            {es.auth?.error
              ? <div className="error-banner" style={{ fontSize: 12 }}>{es.auth.error}</div>
              : <div className="switch-line"><div><h3>{es.auth?.type === 'imap' ? 'IMAP' : 'Gmail OAuth'}</h3><p>{es.auth?.type === 'imap' ? es.auth?.host || 'host not set' : es.auth?.credentials_exist ? 'credentials.json found' : 'credentials.json missing'}</p></div><Badge value={es.auth?.configured ? 'configured' : 'missing'} /></div>
            }
          </> : <div className="loading">Loading email status…</div>}
        </div>
      </Panel>
    </div>
  </>;
}
