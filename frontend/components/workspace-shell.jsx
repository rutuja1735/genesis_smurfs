'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { useWorkspace } from './workspace-provider';
import { Icon } from './ui';

const navigation = [['/dashboard', 'home', 'Overview'], ['/runs', 'clock', 'Agent runs'], ['/analytics', 'chart', 'Analytics'], ['/agents', 'agents', 'My agents'], ['/testing', 'shield', 'Attack testing'], ['/decisions', 'file', 'Audit decisions'], ['/settings', 'settings', 'Settings']];
export function WorkspaceShell({ children }) {
  const pathname = usePathname();
  const router = useRouter();
  const { online, error, refresh } = useWorkspace();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState('');
  useEffect(() => {
    // Keep previously shared hash URLs working after moving to App Router paths.
    if (location.hash && /^#(overview|runs|analytics|agents|testing|decisions|settings)(\/|$)/.test(location.hash)) {
      const path = location.hash.slice(1); router.replace(path === 'overview' ? '/dashboard' : '/' + path);
    }
  }, [router]);
  useEffect(() => { const close = e => { if (e.key === 'Escape') setOpen(false); }; document.addEventListener('keydown', close); return () => document.removeEventListener('keydown', close); }, []);
  async function signOut() {
    setSigningOut(true); setSignOutError('');
    try {
      // Attempt logout if auth is configured; otherwise just navigate home.
      if (process.env.NEXT_PUBLIC_MINIMOTH_KEY) {
        const response = await fetch('/api/auth/logout', { method: 'POST' });
        if (!response.ok) throw new Error('Could not sign out.');
      }
      location.assign('/');
    } catch (error) { setSignOutError(error.message); setSigningOut(false); }
  }
  const Brand = () => <Link className="brand" href="/dashboard" onClick={() => setOpen(false)}><span className="brand-mark" aria-hidden="true" />Agentguard</Link>;
  return <>
    <aside className={`sidebar ${open ? 'open' : ''}`}>
      <Brand /><Link className="workspace-link" href="/dashboard" onClick={() => setOpen(false)}><Icon name="grid" />Workspaces</Link>
      <div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">{navigation.map(([href, name, label]) => {
        const selected = pathname.startsWith(href);
        return <Link key={href} href={href} className={selected ? 'active' : ''} aria-current={selected ? 'page' : undefined} onClick={() => setOpen(false)}><Icon name={name} />{label}</Link>;
      })}</nav>
      <div className="sidebar-bottom"><div className="environment"><span className={`status-dot ${online ? '' : 'offline'}`} />{online ? 'Local workspace' : 'Connecting…'}<span className="mini-badge">DEV</span></div><Link className="profile" href="/settings" onClick={() => setOpen(false)}><span className="avatar">AG</span><span><strong>Agentguard</strong><small>Your agent workspace</small></span><Icon name="chevron" /></Link><button className="workspace-signout" disabled={signingOut} onClick={signOut}><Icon name="back" />{signingOut ? 'Signing out…' : 'Sign out'}</button>{signOutError && <p role="alert">{signOutError}</p>}</div>
    </aside>
    <div className="mobile-bar"><button className="icon-button" aria-label="Toggle navigation" aria-expanded={open} onClick={() => setOpen(!open)}><Icon name="menu" /></button><Brand /></div>
    <main id="main" tabIndex={-1}>{error && <div className="error-banner">Could not reach the backend: {error}. <button className="button secondary small" onClick={refresh}>Retry</button></div>}{children}</main>
  </>;
}
