import Link from 'next/link';
import { useId } from 'react';
import { paths } from '../lib/icons';
import { date, pretty } from '../lib/api';

export function Icon({ name, className = '' }) { return <svg className={`icon ${className}`} viewBox="0 0 24 24" aria-hidden="true"><path d={paths[name] || paths.file} /></svg>; }
export function Button({ children, icon, variant = '', ...props }) { return <button type="button" className={`button ${variant}`} {...props}>{icon && <Icon name={icon} />}{children}</button>; }
export function Header({ title, description, children }) { return <header className="page-header"><div><h1>{title}</h1><p>{description}</p></div><div className="header-actions">{children}</div></header>; }
export function Stat({ label, value, detail, icon, green = false }) { return <div className="stat"><div className="stat-top"><span className="stat-icon"><Icon name={icon} /></span><span>{label}</span></div><div className="stat-value">{value}</div><div className={`stat-detail ${green ? 'green' : ''}`}>{detail}</div></div>; }
export function Panel({ title, subtitle, action, children, className = '' }) { return <section className={`panel ${className}`}><div className="panel-header"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>; }
export function SectionHeading({ title, href, label }) { return <div className="section-heading"><h2>{title}</h2>{href && <Link className="text-link" href={href}>{label}<Icon name="arrow" /></Link>}</div>; }
export function Empty({ title, description, icon = 'clock', children }) { return <div className="empty"><div className="empty-icon"><Icon name={icon} /></div><h3>{title}</h3><p>{description}</p>{children}</div>; }
export function Badge({ value }) { return <span className={`badge ${String(value).toLowerCase()}`}>{pretty(value)}</span>; }
export function Note({ children }) { return <div className="note"><Icon name="info" /><span>{children}</span></div>; }
export function Field({ label, name, children, hint }) { return <div className="field"><label htmlFor={name}>{label}</label>{children}{hint && <small>{hint}</small>}</div>; }
export function DefenseSelect({ name = 'defense', value, onChange, defaultValue }) { return <select id={name} name={name} value={value} onChange={onChange} defaultValue={defaultValue}><option value="ours">Plan-first defense</option><option value="spotlighting">Spotlighting baseline</option><option value="none">No defense baseline</option></select>; }
export function NeutralizeSelect({ name = 'neutralize', defaultValue }) { return <select id={name} name={name} defaultValue={defaultValue}>{['redact', 'annotate', 'off'].map(v => <option key={v} value={v}>{pretty(v)}</option>)}</select>; }
export function RunTable({ runs, newRun, filtered = false }) {
  if (!runs.length) return <Empty title={filtered ? 'No matching runs' : 'No agent runs yet'} description={filtered ? 'Try another command or status filter.' : 'Give an agent a task to see its execution and policy decisions here.'}>{!filtered && <Button icon="plus" variant="small" onClick={() => newRun()}>Start your first run</Button>}</Empty>;
  return <div className="table-wrap"><table><thead><tr><th>COMMAND</th><th>STATUS</th><th>DEFENSE</th><th>CREATED</th><th /></tr></thead><tbody>{runs.map(r => <tr key={r.run_id}><td className="command-cell"><Link href={`/runs/${r.run_id}`}>{r.command}</Link></td><td><Badge value={r.status} /></td><td>{r.defense === 'ours' ? 'Plan-first' : pretty(r.defense)}</td><td>{date(r.created_at)}</td><td><Link className="text-link" href={`/runs/${r.run_id}`} aria-label={`View run ${r.run_id}`}>View<Icon name="chevron" /></Link></td></tr>)}</tbody></table></div>;
}
export function Chart({ runs, mode = 'runs' }) {
  const gradient = useId().replaceAll(':', '');
  const days = Array.from({ length: 6 }, (_, i) => { const d = new Date(); d.setDate(d.getDate() - 5 + i); return d; });
  const dayKey = d => d.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
  const counts = days.map(d => runs.filter(r => dayKey(new Date(r.created_at)) === dayKey(d) && (mode !== 'done' || r.status === 'done')).length);
  const maximum = Math.max(3, ...counts);
  const points = counts.map((n, i) => [48 + i * 92, 157 - n / maximum * 123]);
  const line = points.map(p => p.join(',')).join(' ');
  const total = counts.reduce((a, b) => a + b, 0);
  return <><div className="chart-sub">Last 6 days · {mode === 'done' ? 'completed runs' : 'run count'}</div><div className="chart"><svg viewBox="0 0 550 195" role="img" aria-label={`${total} runs over the last six days`}><defs><linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#1687ec" stopOpacity=".14" /><stop offset="100%" stopColor="#1687ec" stopOpacity=".01" /></linearGradient></defs>{[0, 1, 2, 3].map(i => <g key={i}><line x1="45" y1={34 + i * 41} x2="518" y2={34 + i * 41} stroke="#edf0f4" strokeDasharray="3 4" /><text x="15" y={38 + i * 41}>{Math.round(maximum * (1 - i / 3))}</text></g>)}<polygon points={`48,158 ${line} 508,158`} fill={`url(#${gradient})`} /><polyline points={line} fill="none" stroke="#1687ec" strokeWidth="2.2" strokeLinejoin="round" />{points.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="3" fill="white" stroke="#1687ec" strokeWidth="1.6" />)}{days.map((d, i) => <text key={i} x={48 + i * 92} y="184" textAnchor="middle">{d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' })}</text>)}</svg>{!total && <div className="chart-empty">Your execution history will appear here</div>}</div><div className="chart-caption"><i />{mode === 'done' ? 'Runs completed' : 'Agent runs'}</div></>;
}
