'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useWorkspace } from './workspace-provider';
import { agentInfo, post, pretty } from '../lib/api';
import { Button, DefenseSelect, Field, Icon, NeutralizeSelect, Note } from './ui';

function Modal({ title, close, children, onSubmit, submitLabel, pending, error }) {
  const ref = useRef(null);
  useEffect(() => { const dialog = ref.current; dialog.showModal(); return () => dialog.close(); }, []);
  return <dialog ref={ref} onCancel={e => { e.preventDefault(); if (!pending) close(); }} aria-labelledby="dialog-title"><form onSubmit={onSubmit}><div className="dialog-head"><h2 id="dialog-title">{title}</h2><button className="icon-button" type="button" aria-label="Close dialog" disabled={pending} onClick={close}><Icon name="close" /></button></div>{children}{error && <div className="error-banner" role="alert">{error}</div>}<div className="dialog-footer"><Button variant="secondary" onClick={close} disabled={pending}>Cancel</Button><Button type="submit" variant="blue" disabled={pending}>{pending ? 'Starting…' : submitLabel}</Button></div></form></dialog>;
}
export function RunDialog({ task, agent, close }) {
  const { preferences, emailStatus, refresh, notify } = useWorkspace();
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [selectedAgents, setSelectedAgents] = useState(
    Object.keys(agentInfo).filter(id => !agent || id === agent)
  );
  const realEmailReady = emailStatus?.auth?.configured === true;

  // Auto-detect email-related prompts and switch to real email when configured
  const EMAIL_KEYWORDS = /\b(email|mail|inbox|unread|send|draft|forward|reply|message|read my)\b/i;
  function shouldUseRealEmail(command, agents) {
    return agents.includes('email') && realEmailReady && EMAIL_KEYWORDS.test(command);
  }

  async function submit(e) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const command = data.get('command').trim();
    const agents = data.getAll('agents');
    if (!command || !agents.length) { setError(!command ? 'Enter a command.' : 'Select at least one agent.'); return; }
    setPending(true); setError('');
    try {
      const body = { command, agents, defense: data.get('defense'), neutralize: data.get('neutralize'), output_filter: data.has('output_filter') };
      if (shouldUseRealEmail(command, agents)) body.email_agent = 'real';
      const result = await post('/runs', body);
      await refresh(); router.push(`/runs/${result.run_id}`); notify('Agent run started'); close();
    } catch (e) { setError(e.message); setPending(false); }
  }

  return <Modal title="New agent run" close={close} onSubmit={submit} submitLabel="Start run" pending={pending} error={error}>
    <Field label="What should your agents do?" name="run-command"><textarea id="run-command" name="command" required maxLength={12000} placeholder="e.g. Summarize my unread emails" defaultValue={task?.prompt || ''} /></Field>
    <div className="field"><span className="field-label">Agents</span><div className="agent-checks">{Object.entries(agentInfo).map(([id, a]) => <label key={id}><input type="checkbox" name="agents" value={id} defaultChecked={!agent || id === agent} onChange={e => setSelectedAgents(prev => e.target.checked ? [...prev, id] : prev.filter(x => x !== id))} /><Icon name={a.icon} />{pretty(id)}</label>)}</div></div>
    <div className="form-grid"><Field label="Defense" name="defense"><DefenseSelect defaultValue={preferences.defense} /></Field><Field label="Neutralization" name="neutralize"><NeutralizeSelect defaultValue={preferences.neutralize} /></Field></div>
    <label className="switch-line"><span className="field-label">Filter final answer</span><input type="checkbox" className="switch" name="output_filter" defaultChecked={preferences.output_filter} /></label>
    <Note>Runs use mock agents by default. Email-related prompts automatically use your real inbox when credentials are configured. All runs go through the security pipeline.</Note>
  </Modal>;
}
export function EvaluationDialog({ close }) {
  const { attacks, refresh, notify } = useWorkspace();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  async function submit(e) {
    e.preventDefault(); const data = new FormData(e.currentTarget); setPending(true); setError('');
    try { await post('/evals', { suite: data.get('suite'), batch_size: Number(data.get('batch_size')), attack: data.get('attack'), defense: data.get('defense'), track: 'mock', mode: 'attack_defended', confirm_cost: true }); await refresh(); notify('Evaluation batch started'); close(); }
    catch (e) { setError(e.message); setPending(false); }
  }
  return <Modal title="New evaluation batch" close={close} onSubmit={submit} submitLabel="Start evaluation" pending={pending} error={error}><div className="form-grid">
    <Field label="Agent suite" name="eval-suite"><select id="eval-suite" name="suite">{['all', 'email', 'slack', 'banking', 'cross'].map(v => <option key={v} value={v}>{pretty(v)}</option>)}</select></Field>
    <Field label="Number of cases" name="eval-count"><input id="eval-count" name="batch_size" type="number" min="1" max="5" defaultValue="5" required /></Field>
    <Field label="Attack pattern" name="eval-attack"><select id="eval-attack" name="attack"><option value="all">All patterns</option>{attacks.map(a => <option key={a.id} value={a.id}>{pretty(a.id)}</option>)}</select></Field>
    <Field label="Defense" name="defense"><DefenseSelect /></Field>
  </div><Note>Each case makes model requests. Batches are capped at 5 and use the configured backend budget.</Note></Modal>;
}
