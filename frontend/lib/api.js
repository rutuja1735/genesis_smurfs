export async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
    cache: 'no-store',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
  }
  return response.json();
}
export const post = (path, data) => api(path, { method: 'POST', body: JSON.stringify(data) });
export const pretty = value => String(value ?? '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
export const date = value => value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
export const money = value => `$${Number(value || 0).toFixed(4)}`;
export const active = status => ['pending', 'running'].includes(status);
export const agentInfo = {
  email: { name: 'Email agent', icon: 'mail', desc: 'Read, summarize, draft, and manage email with plan-first protection.', short: 'Your inbox, with a safety layer.' },
  slack: { name: 'Slack agent', icon: 'slack', desc: 'Read channels, follow conversations, and share updates with your team.', short: 'Keep your conversations moving.' },
  banking: { name: 'Banking agent', icon: 'bank', desc: 'Review balances, transactions, and payments with policy checks.', short: 'Financial actions with guardrails.' },
};
export function download(name, data) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = name; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
