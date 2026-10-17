import { NextResponse } from 'next/server';
import { authenticate, AuthError, clearSession, minimoth, sameOrigin, setSession } from '../../../../lib/minimoth.mjs';
import { normalizePhone, SESSION_COOKIE } from '../../../../lib/auth-session.mjs';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
function json(body, status = 200) { return NextResponse.json(body, { status, headers: { 'Cache-Control': 'no-store', Vary: 'Cookie' } }); }
export async function POST(request, { params }) {
  const { action } = await params;
  if (!sameOrigin(request)) return json({ error: 'This request must come from the app.' }, 403);
  if (!['send', 'verify', 'logout'].includes(action)) return json({ error: 'Not found' }, 404);
  try {
    if (action === 'logout') {
      let auth;
      try { auth = await authenticate(request.cookies.get(SESSION_COOKIE)?.value); if (auth) await minimoth('/session/logout', { access_token: auth.session.access_token }); }
      catch { return json({ error: 'Could not revoke your session. Please try signing out again.' }, 503); }
      const response = json({ ok: true }); clearSession(response, request); return response;
    }
    if (Number(request.headers.get('content-length') || 0) > 2048) return json({ error: 'Request too large.' }, 413);
    const body = await request.json().catch(() => { throw new AuthError('Enter a valid phone number.', 400); });
    const phone = normalizePhone(body.phone);
    if (!phone) return json({ error: 'Enter a valid phone number with its country code.' }, 400);
    if (action === 'send') {
      const data = await minimoth('/otp/send', { phone });
      return json({ ok: true, phone, expires_at: data.expires_at });
    }
    const code = String(body.code || '');
    if (!/^\d{6}$/.test(code)) return json({ error: 'Enter the 6-digit verification code.' }, 400);
    const tokens = await minimoth('/otp/verify', { phone, code });
    if (!tokens.access_token || !tokens.refresh_token) throw new AuthError('Verification did not return a session. Please try again.', 502);
    const session = { access_token: tokens.access_token, refresh_token: tokens.refresh_token, expires_at: tokens.expires_at, identity_id: tokens.identity_id || null, phone, created_at: Date.now() };
    const response = json({ ok: true }); setSession(response, request, session); return response;
  } catch (error) { return json({ error: error instanceof AuthError ? error.message : 'Sign-in could not complete. Please try again.' }, error instanceof AuthError ? error.status : 500); }
}
export async function GET(request, { params }) {
  const { action } = await params;
  if (action !== 'me') return json({ error: 'Not found' }, 404);
  try {
    const auth = await authenticate(request.cookies.get(SESSION_COOKIE)?.value);
    if (!auth) { const response = json({ authenticated: false }, 401); clearSession(response, request); return response; }
    const response = json({ authenticated: true, phone: auth.session.phone, identity_id: auth.session.identity_id });
    if (auth.changed) setSession(response, request, auth.session);
    return response;
  } catch { return json({ error: 'The sign-in service could not be reached.' }, 503); }
}
