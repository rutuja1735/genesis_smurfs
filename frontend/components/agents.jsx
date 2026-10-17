'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { agentInfo, api, post, pretty, date } from '../lib/api';
import { useWorkspace } from './workspace-provider';
import { Badge, Button, Header, Icon, Note, Panel, SectionHeading } from './ui';

export function AgentCards() {
  const { tasks } = useWorkspace();
  return <div className="agent-grid">{Object.entries(agentInfo).map(([id, a]) => <article className="panel agent-card" key={id}><div className="agent-header"><span className={`agent-symbol ${id}`}><Icon name={a.icon} /></span><span className="badge gray">Mock environment</span></div><h3>{a.name}</h3><p>{a.desc}</p><div className="agent-footer"><span>{tasks.filter(t => t.suite === id).length} available tasks</span><Link href={`/agents/${id}`}>Open agent <Icon name="chevron" /></Link></div></article>)}</div>;
}
export function Agents() { return <><Header title="My agents" description="A focused workspace for every part of your workflow." /><AgentCards /><SectionHeading title="How your agents work" /><div className="two-columns"><Panel title="Plan-first execution"><div className="panel-pad"><p>Your request becomes a validated tool dependency graph before execution. Every action passes deterministic policy and provenance checks.</p><Note>These agents use isolated JSON mock data. Email, Slack, and banking actions do not affect real accounts.</Note></div></Panel><Panel title="A record of every action"><div className="panel-pad"><p>Inspect tool execution, injection detections, output filtering, and policy decisions from the run detail page.</p><Link className="text-link" style={{ marginTop: 20 }} href="/runs">Explore execution history<Icon name="arrow" /></Link></div></Panel></div></>; }

// ---------------------------------------------------------------------------
// EmailAgentPanel — real-email inbox browser and action ledger
// ---------------------------------------------------------------------------
function EmailAgentPanel({ emailStatus }) {
  const [tab, setTab] = useState('inbox');
  const [emails, setEmails] = useState([]);
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [ledger, setLedger] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [composing, setComposing] = useState(false);
  const [draft, setDraft] = useState({ to: '', subject: '', body: '' });
  const [sendPending, setSendPending] = useState(false);
  const [sendResult, setSendResult] = useState('');
  const [notify, setNotify] = useState('');
  const source = emailStatus?.configured_agent || 'mock';

  function flash(msg) { setNotify(msg); setTimeout(() => setNotify(''), 3500); }

  async function loadInbox() {
    setLoading(true); setError(''); setSelectedEmail(null);
    try {
      const params = new URLSearchParams();
      if (unreadOnly) params.set('unread_only', 'true');
      if (search) params.set('query', search);
      params.set('limit', '50');
      const data = await api(`/email/inbox?${params}`);
      setEmails(data.emails || []);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function loadLedger() {
    setLoading(true); setError('');
    try {
      const data = await api('/email/actions');
      setLedger(data.actions || []);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function openEmail(id) {
    try {
      const data = await api(`/email/messages/${id}`);
      setSelectedEmail(data.email);
    } catch (e) { flash(`Could not load message: ${e.message}`); }
  }

  async function markRead(id) {
    try { await api(`/email/messages/${id}/read`, { method: 'POST' }); flash('Marked as read'); loadInbox(); }
    catch (e) { flash(`Error: ${e.message}`); }
  }

  async function deleteMsg(id) {
    if (!confirm('Move this message to trash?')) return;
    try { await api(`/email/messages/${id}`, { method: 'DELETE' }); flash('Message trashed'); setSelectedEmail(null); loadInbox(); }
    catch (e) { flash(`Error: ${e.message}`); }
  }

  async function sendDraft(e) {
    e.preventDefault(); setSendPending(true); setSendResult('');
    try {
      const to = draft.to.split(',').map(s => s.trim()).filter(Boolean);
      const data = await post('/email/draft', { to, subject: draft.subject, body: draft.body });
      setSendResult(`Draft created (${data.result?.id || 'ok'})`);
      setDraft({ to: '', subject: '', body: '' }); setComposing(false);
      flash('Draft saved');
    } catch (e) { setSendResult(`Error: ${e.message}`); }
    finally { setSendPending(false); }
  }

  async function clearLedger() {
    if (!confirm('Clear all action ledger entries?')) return;
    try { await api('/email/actions', { method: 'DELETE' }); setLedger([]); flash('Ledger cleared'); }
    catch (e) { flash(`Error: ${e.message}`); }
  }

  useEffect(() => {
    if (tab === 'inbox') loadInbox();
    else if (tab === 'ledger') loadLedger();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, unreadOnly]);

  const isReal = source === 'real';

  return <div className="email-agent-panel">
    {notify && <div className="email-toast" role="status">{notify}</div>}
    <div className="tab-list" role="tablist" aria-label="Email agent views">
      {['inbox', 'compose', 'ledger'].map(t => (
        <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={tab === t ? 'active' : ''}>
          {t === 'inbox' ? 'Inbox' : t === 'compose' ? 'Compose' : 'Action ledger'}
        </button>
      ))}
    </div>

    {tab === 'inbox' && <>
      <div className="inbox-toolbar">
        <div className="search" style={{ flex: 1 }}>
          <Icon name="search" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search emails…" aria-label="Search emails"
            onKeyDown={e => e.key === 'Enter' && loadInbox()} />
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <input type="checkbox" checked={unreadOnly} onChange={e => setUnreadOnly(e.target.checked)} />
          Unread only
        </label>
        <Button variant="secondary small" onClick={loadInbox}>Refresh</Button>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {loading ? <div className="loading">Loading inbox…</div> : selectedEmail ? (
        <div className="email-detail">
          <button className="text-link" onClick={() => setSelectedEmail(null)} style={{ marginBottom: 12 }}>
            <Icon name="chevron" /> Back to inbox
          </button>
          <div className="email-header-row">
            <h3>{selectedEmail.subject || '(no subject)'}</h3>
            <div style={{ display: 'flex', gap: 8 }}>
              {!selectedEmail.read && <Button variant="secondary small" onClick={() => markRead(selectedEmail.id)}>Mark read</Button>}
              <Button variant="secondary small" onClick={() => deleteMsg(selectedEmail.id)}>Trash</Button>
            </div>
          </div>
          <div className="email-meta">
            <span>From: <strong>{selectedEmail.from_display || selectedEmail.from}</strong></span>
            <span>{date(selectedEmail.date)}</span>
          </div>
          {selectedEmail.auth_results && (
            <div className="auth-pills">
              {['spf', 'dkim', 'dmarc'].map(k => (
                <span key={k} className={`auth-pill ${selectedEmail.auth_results[k]}`}>{k.toUpperCase()}: {selectedEmail.auth_results[k]}</span>
              ))}
            </div>
          )}
          <pre className="email-body">{selectedEmail.body || '(no body)'}</pre>
          {selectedEmail.was_truncated && <Note>Message was truncated to fit the body limit.</Note>}
        </div>
      ) : emails.length === 0 ? (
        <div className="empty"><div className="empty-icon"><Icon name="mail" /></div><h3>No emails found</h3><p>{isReal ? 'No messages matching your filters.' : 'Mock inbox is empty.'}</p></div>
      ) : (
        <div className="email-list">
          {emails.map(email => (
            <button key={email.id} className={`email-row ${email.read ? 'read' : 'unread'}`} onClick={() => openEmail(email.id)}>
              <div className="email-row-from">{email.from_display || email.from || '—'}</div>
              <div className="email-row-subject">{email.subject || '(no subject)'}</div>
              <div className="email-row-date">{date(email.date)}</div>
            </button>
          ))}
        </div>
      )}
    </>}

    {tab === 'compose' && <form className="compose-form" onSubmit={sendDraft}>
      <div className="field"><label>To (comma-separated)</label><input value={draft.to} onChange={e => setDraft(d => ({ ...d, to: e.target.value }))} placeholder="alice@example.com" required /></div>
      <div className="field"><label>Subject</label><input value={draft.subject} onChange={e => setDraft(d => ({ ...d, subject: e.target.value }))} placeholder="Subject" /></div>
      <div className="field"><label>Body</label><textarea rows={8} value={draft.body} onChange={e => setDraft(d => ({ ...d, body: e.target.value }))} placeholder="Write your message…" /></div>
      {sendResult && <div className={sendResult.startsWith('Error') ? 'error-banner' : 'note'}>{sendResult}</div>}
      <Note>{isReal ? 'Saves a draft to your real mailbox. Dry-run mode is active unless disabled in Email settings.' : 'Uses mock email agent — no real draft is created.'}</Note>
      <div style={{ display: 'flex', gap: 10 }}>
        <Button type="submit" variant="blue" disabled={sendPending}>{sendPending ? 'Saving…' : 'Save draft'}</Button>
      </div>
    </form>}

    {tab === 'ledger' && <>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <Button variant="secondary small" onClick={clearLedger}>Clear ledger</Button>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {loading ? <div className="loading">Loading ledger…</div> : ledger.length === 0 ? (
        <div className="empty"><div className="empty-icon"><Icon name="shield" /></div><h3>No actions recorded</h3><p>Write operations (drafts, sends, deletes) appear here with their outcome.</p></div>
      ) : (
        <div className="list">
          {ledger.map((entry, i) => (
            <div className="list-row" key={i}>
              <Icon name={entry.outcome?.status === 'dry_run' ? 'clock' : 'check'} />
              <div>
                <h3><code>{entry.action}</code> {entry.outcome?.status === 'dry_run' && <span className="badge gray">dry run</span>}</h3>
                <p>{date(entry.ts)}</p>
              </div>
              <pre style={{ fontSize: 11, maxWidth: 280, overflow: 'auto' }}>{JSON.stringify(entry.args, null, 1)}</pre>
            </div>
          ))}
        </div>
      )}
    </>}
  </div>;
}

// ---------------------------------------------------------------------------
// AgentDetail
// ---------------------------------------------------------------------------
export function AgentDetail({ id }) {
  const { tasks, config, preferences, newRun, emailStatus } = useWorkspace();
  const [tab, setTab] = useState('tasks');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const a = agentInfo[id];
  const isEmailReal = id === 'email' && emailStatus?.configured_agent === 'real';
  const dataSource = isEmailReal ? 'Real mailbox' : 'JSON-backed mock environment';
  const dataSourceBadge = isEmailReal ? 'real' : 'local';

  useEffect(() => {
    if (tab !== 'data') return;
    const controller = new AbortController(); setData(null); setError('');
    api(`/data/${id}`, { signal: controller.signal }).then(setData).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, [id, tab]);

  const emailTabs = id === 'email' ? ['tasks', 'email', 'data'] : ['tasks', 'data'];

  return <><Header title={a.name} description={a.short}><Button icon="plus" onClick={() => newRun(null, id)}>New agent run</Button></Header>
    <div className="two-columns">
      <section className="panel panel-pad">
        <div className="agent-detail-head">
          <span className={`agent-symbol ${id}`}><Icon name={a.icon} /></span>
          <div><h2>{a.name}</h2><p>{dataSource}</p></div>
        </div>
        <p>{a.desc}</p>
        <Note>Use a preset below or give this agent your own command. Runs use your configured OpenRouter model.</Note>
        <div className="tab-list" role="tablist" aria-label="Agent views">
          {emailTabs.map(value => (
            <button key={value} role="tab" aria-selected={tab === value} aria-controls="agent-content"
              onClick={() => setTab(value)} className={tab === value ? 'active' : ''}>
              {value === 'tasks' ? 'Available tasks' : value === 'email' ? 'Email workspace' : 'Agent data'}
            </button>
          ))}
        </div>
        <div id="agent-content" role="tabpanel">
          {tab === 'tasks' && tasks.filter(t => t.suite === id).map(t => (
            <div className="list-row" key={t.id}>
              <Icon name="file" />
              <div><h3>{t.prompt}</h3><p>Task {t.id}</p></div>
              <button className="text-link" onClick={() => newRun(t, id)}>Run<Icon name="arrow" /></button>
            </div>
          ))}
          {tab === 'email' && <EmailAgentPanel emailStatus={emailStatus} />}
          {tab === 'data' && (error ? <div className="error-banner">{error}</div> : data ? <pre>{JSON.stringify(data, null, 2)}</pre> : <div className="loading">Loading agent data…</div>)}
        </div>
      </section>
      <Panel title="Agent configuration">
        <div className="panel-pad">
          <div className="switch-line"><div><h3>Execution mode</h3><p>Plan-first defense</p></div><Badge value="protected" /></div>
          <div className="switch-line"><div><h3>Data source</h3><p>{dataSource}</p></div><Badge value={dataSourceBadge} /></div>
          {id === 'email' && emailStatus && <>
            <div className="switch-line"><div><h3>Email backend</h3><p>{emailStatus.backend_type || 'imap'}</p></div><Badge value={emailStatus.active_agent || 'mock'} /></div>
            <div className="switch-line"><div><h3>Dry-run mode</h3><p>{emailStatus.dry_run ? 'Writes are simulated — no real mutations' : 'Live writes enabled'}</p></div><Badge value={emailStatus.dry_run ? 'on' : 'off'} /></div>
            <div className="switch-line"><div><h3>Operation mode</h3><p>{emailStatus.mode}</p></div></div>
            {emailStatus.inbox_stats?.unread != null && <div className="switch-line"><div><h3>Inbox</h3><p>{emailStatus.inbox_stats.unread} unread / {emailStatus.inbox_stats.total} total</p></div></div>}
            {emailStatus.auth?.error && <Note>{emailStatus.auth.error}</Note>}
          </>}
          <div className="switch-line"><div><h3>Model</h3><p>{config.model || 'Not configured'}</p></div></div>
          <div className="switch-line"><div><h3>Prompt injection scanning</h3><p>Scan tool output before use</p></div><Badge value="enabled" /></div>
          <div className="switch-line"><div><h3>Output filtering</h3><p>Check grounding and sensitive content</p></div><Badge value={preferences.output_filter ? 'enabled' : 'disabled'} /></div>
        </div>
      </Panel>
    </div>
  </>;
}
