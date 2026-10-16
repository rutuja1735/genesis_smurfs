'use client';

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api, active } from '../lib/api';
import { RunDialog, EvaluationDialog } from './dialogs';

const WorkspaceContext = createContext(null);
const initial = { runs: [], stats: { decisions: {}, rules: {} }, tasks: [], attacks: [], goals: [], config: {}, decisions: [], evals: [] };
const defaultPreferences = { defense: 'ours', neutralize: 'redact', output_filter: true };
const endpoints = { runs: '/runs?limit=500', stats: '/stats', tasks: '/tasks', attacks: '/attacks', goals: '/goals', config: '/config', decisions: '/decisions?limit=500', evals: '/evals' };

export function WorkspaceProvider({ children }) {
  const [data, setData] = useState(initial);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [preferences, setPreferences] = useState(defaultPreferences);
  const [dialog, setDialog] = useState(null);
  const [message, setMessage] = useState('');
  const toastTimer = useRef(null);
  const request = useRef(0);
  const notify = useCallback(text => {
    setMessage(text); clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setMessage(''), 4500);
  }, []);
  const refresh = useCallback(async () => {
    const version = ++request.current;
    try {
      const results = await Promise.all(Object.entries(endpoints).map(async ([key, path]) => [key, await api(path)]));
      if (version !== request.current) return;
      setData(Object.fromEntries(results)); setError('');
    } catch (e) { if (version === request.current) setError(e.message); }
    finally { if (version === request.current) setLoading(false); }
  }, []);
  useEffect(() => {
    refresh();
    try { const saved = JSON.parse(localStorage.getItem('agentgaurd.defaults') || 'null'); if (saved) setPreferences({ ...defaultPreferences, ...saved }); } catch { /* Retain valid defaults if saved data is malformed. */ }
    return () => { request.current++; clearTimeout(toastTimer.current); };
  }, [refresh]);
  const hasActive = data.runs.some(r => active(r.status)) || data.evals.some(e => active(e.status));
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(refresh, 4000);
    return () => clearInterval(timer);
  }, [hasActive, refresh]);
  function savePreferences(value) {
    try { localStorage.setItem('agentgaurd.defaults', JSON.stringify(value)); setPreferences(value); notify('Execution preferences saved'); }
    catch { notify('Your browser could not save preferences.'); }
  }
  const value = { ...data, loading, error, online: !loading && !error, preferences, savePreferences, refresh, notify, newRun: (task = null, agent = null) => setDialog({ type: 'run', task, agent }), newEvaluation: () => setDialog({ type: 'evaluation' }) };
  return <WorkspaceContext.Provider value={value}>
    {children}
    {dialog?.type === 'run' && <RunDialog task={dialog.task} agent={dialog.agent} close={() => setDialog(null)} />}
    {dialog?.type === 'evaluation' && <EvaluationDialog close={() => setDialog(null)} />}
    <div id="toast" className={message ? 'visible' : ''} role="status" aria-live="polite">{message}</div>
  </WorkspaceContext.Provider>;
}
export function useWorkspace() { return useContext(WorkspaceContext); }
