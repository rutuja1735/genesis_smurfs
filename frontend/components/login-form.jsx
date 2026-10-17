'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { safeNext } from '../lib/auth-input.mjs';

export default function LoginForm({ next, signup = false }) {
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [stage, setStage] = useState('phone');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [cooldown, setCooldown] = useState(0);
  useEffect(() => { if (!cooldown) return; const timer = setTimeout(() => setCooldown(n => n - 1), 1000); return () => clearTimeout(timer); }, [cooldown]);
  async function request(action, payload) {
    const response = await fetch('/api/auth/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Sign-in could not complete. Please try again.');
    return data;
  }
  async function send() {
    setPending(true); setError(''); setMessage('');
    try { const data = await request('send', { phone }); setPhone(data.phone); setStage('code'); setCooldown(30); setMessage('Your code is on its way via WhatsApp or SMS.'); }
    catch (error) { setError(error.message); }
    finally { setPending(false); }
  }
  async function submit(event) {
    event.preventDefault();
    if (stage === 'phone') { await send(); return; }
    setPending(true); setError('');
    try { await request('verify', { phone, code }); window.location.assign(safeNext(next)); }
    catch (error) { setError(error.message); setPending(false); }
  }
  return <div className="auth-card"><h1>{stage === 'code' ? 'Check your phone' : signup ? 'Create your account' : 'Sign in'}</h1><p className="auth-subtitle">{stage === 'code' ? `Enter the 6-digit code for ${phone}` : signup ? 'A safer workspace for your agents starts here.' : 'Welcome back to your agent workspace.'}</p><div className="auth-provider"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h10v18H7z M10 17h4 M10 6h4" /></svg>Continue with your phone</div><div className="auth-divider"><span>{stage === 'code' ? 'verify your number' : 'secure, password-free sign in'}</span></div><form onSubmit={submit}>{stage === 'phone' ? <div className="auth-field"><label htmlFor="phone">Phone number</label><input id="phone" autoComplete="tel" type="tel" inputMode="tel" placeholder="+91 98765 43210" value={phone} onChange={e => setPhone(e.target.value)} maxLength={24} required /><small>We’ll send a verification code via WhatsApp or SMS.</small></div> : <><div className="auth-field"><label htmlFor="code">Verification code</label><input id="code" className="otp-input" type="text" inputMode="numeric" autoComplete="one-time-code" placeholder="6-digit code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))} required autoFocus /></div><button className="auth-change" type="button" disabled={pending} onClick={() => { setStage('phone'); setError(''); setMessage(''); setCode(''); }}>Use a different number</button></>}{message && <p className="auth-message" role="status">{message}</p>}{error && <div className="auth-error" role="alert">{error}</div>}<button className="auth-submit" type="submit" disabled={pending}>{pending ? stage === 'phone' ? 'Sending code…' : 'Verifying…' : stage === 'phone' ? 'Send verification code' : 'Verify & continue'}</button>{stage === 'code' && <button type="button" className="auth-resend" disabled={pending || cooldown > 0} onClick={send}>{cooldown ? `Resend code in ${cooldown}s` : 'Resend verification code'}</button>}</form><p className="auth-switch">{signup ? 'Already have an account?' : 'New to Agentguard?'} <Link href={signup ? '/login' : '/signup'}>{signup ? 'Sign in' : 'Get started'}</Link></p><div className="auth-powered"><span className="tiny-lock">♧</span> Secured with MiniMoth</div></div>;
}
