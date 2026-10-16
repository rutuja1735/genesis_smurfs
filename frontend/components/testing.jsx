'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useWorkspace } from './workspace-provider';
import { agentInfo, date, post, pretty } from '../lib/api';
import { Badge, Button, DefenseSelect, Empty, Field, Header, Note, Panel, SectionHeading, Stat } from './ui';

export function Testing() {
  const { tasks, attacks, goals, evals, preferences, refresh, notify, newEvaluation } = useWorkspace();
  const router = useRouter();
  const [taskId, setTaskId] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const task = tasks.find(t => t.id === taskId) || tasks[0];
  const compatible = goals.filter(g => task?.suite === 'cross' || g.suite === task?.suite || g.suite === 'cross');
  const availableGoals = compatible.length ? compatible : goals;
  async function submit(e) {
    e.preventDefault(); const data = new FormData(e.currentTarget); if (!task) return;
    setPending(true); setError('');
    try { const result = await post('/runs', { command: task.prompt, agents: agentInfo[task.suite] ? [task.suite] : Object.keys(agentInfo), defense: data.get('defense'), attack: data.get('attack'), injection_goal: data.get('goal'), neutralize: preferences.neutralize, output_filter: preferences.output_filter }); await refresh(); notify('Attack scenario started'); router.push(`/runs/${result.run_id}`); }
    catch (e) { setError(e.message); } finally { setPending(false); }
  }
  return <><Header title="Attack testing" description="Understand how your agents respond to prompt injection."><Button icon="plus" onClick={newEvaluation}>New evaluation</Button></Header><div className="stats"><Stat label="Attack patterns" value={attacks.length} detail="Reusable injection patterns" icon="shield" /><Stat label="Security goals" value={goals.length} detail="Deterministic attack objectives" icon="file" /><Stat label="Preset tasks" value={tasks.length} detail="Across individual and cross-agent tasks" icon="agents" /><Stat label="Evaluation batches" value={evals.length} detail="Up to 5 cases per batch" icon="chart" /></div><div className="two-columns"><Panel title="Test a single scenario"><form className="panel-pad" onSubmit={submit}><Field label="Agent task" name="attack-task"><select id="attack-task" value={task?.id || ''} onChange={e => setTaskId(e.target.value)} required>{tasks.map(t => <option key={t.id} value={t.id}>{t.id} · {t.prompt}</option>)}</select></Field><Field label="Attack pattern" name="attack-pattern"><select id="attack-pattern" name="attack" required>{attacks.map(a => <option key={a.id} value={a.id}>{pretty(a.id)}{a.held_out ? ' · held out' : ''}</option>)}</select></Field><Field label="Injection goal" name="attack-goal"><select key={task?.suite} id="attack-goal" name="goal" required>{availableGoals.map(g => <option key={g.id} value={g.id}>{g.description || g.id}</option>)}</select></Field><Field label="Defense" name="defense"><DefenseSelect /></Field><Note>Scenarios run on mock data and make paid model requests within the configured workspace budget.</Note>{error && <div className="error-banner" role="alert">{error}</div>}<Button type="submit" variant="blue" icon="play" disabled={pending || !task}>{pending ? 'Starting…' : 'Run scenario'}</Button></form></Panel><Panel title="Attack pattern library" subtitle="Inspect the injection templates used in evaluations."><div className="list">{attacks.map(a => <details key={a.id}><summary>{pretty(a.id)}{a.held_out ? ' · Held out' : ''}</summary><pre>{a.template || 'Poisons a tool argument in the mock data.'}</pre></details>)}</div></Panel></div><SectionHeading title="Evaluation history" /><section className="panel">{evals.length ? <div className="table-wrap"><table><thead><tr><th>BATCH</th><th>STATUS</th><th>COMPLETED</th><th>UTILITY</th><th>ATTACK SUCCESS</th><th>CREATED</th></tr></thead><tbody>{evals.map(e => <EvaluationRow key={e.eval_id} item={e} />)}</tbody></table></div> : <Empty title="No evaluation batches yet" description="Create a small batch to compare agent utility and attack outcomes." icon="chart"><Button icon="plus" variant="small" onClick={newEvaluation}>Create evaluation</Button></Empty>}</section></>;
}
function EvaluationRow({ item: e }) { return <><tr><td className="mono">{e.eval_id}</td><td><Badge value={e.status} /></td><td>{e.done || 0} / {e.total || 0}</td><td>{e.utility == null ? '—' : Math.round(e.utility * 100) + '%'}</td><td>{e.asr == null ? '—' : Math.round(e.asr * 100) + '%'}</td><td>{date(e.created_at)}</td></tr>{e.status === 'error' && <tr><td colSpan={6} className="wrap">{e.params?.error || 'Evaluation could not complete.'}</td></tr>}</>; }
