import { openSession, sealSession, SESSION_COOKIE, SESSION_SECONDS } from './auth-session.mjs';

export class AuthError extends Error {
  constructor(message, status = 400, code = '') { super(message); this.status = status; this.code = code; }
}
const messages = {
  INVALID_OTP: 'That code is incorrect. Check the code and try again.',
  OTP_NOT_FOUND: 'Your code expired or was not found. Request a new code.',
  INVALID_PHONE: 'Enter a valid phone number with its country code.',
  RATE_LIMITED: 'Too many requests. Please wait before trying again.',
  VERIFY_RATE_LIMITED: 'Too many verification attempts. Request a new code.',
  REGION_NOT_ENABLED: 'This phone region is not enabled for this project.',
  INSUFFICIENT_BALANCE: 'OTP delivery is unavailable. Please contact the workspace owner.',
};
export async function minimoth(path, payload) {
  const key = process.env.MINIMOTH_API_KEY;
  if (!key) throw new AuthError('Sign-in is not configured yet.', 503);
  if (path.startsWith('/otp/') && !key.startsWith('mm_live_')) throw new AuthError('Phone sign-in requires a live MiniMoth project key.', 503);
  let response;
  try { response = await fetch('https://api.minimoth.dev/v1' + path, { method: 'POST', headers: { 'X-Api-Key': key, 'Content-Type': 'application/json' }, body: JSON.stringify(payload), cache: 'no-store', signal: AbortSignal.timeout(15000) }); }
  catch { throw new AuthError('The sign-in service could not be reached. Please try again.', 503); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = data.code || data.error?.code || data.error || '';
    const status = response.status === 429 ? 429 : response.status >= 500 || /API_KEY|UNAUTHORIZED|FORBIDDEN/.test(String(code)) ? 503 : response.status;
    throw new AuthError(messages[code] || (status === 429 ? messages.RATE_LIMITED : 'Sign-in could not complete. Please try again.'), status, typeof code === 'string' ? code : '');
  }
  return data;
}

// Deduplicate concurrent refresh calls within a server process. MiniMoth also
// provides a short grace window for refreshes across separate server instances.
const refreshes = new Map();
export async function authenticate(cookie) {
  const session = openSession(cookie);
  if (!session) return null;
  const validation = await minimoth('/session/validate', { access_token: session.access_token });
  if (validation.valid) return { session, changed: false };
  let promise = refreshes.get(session.refresh_token);
  if (!promise) {
    promise = minimoth('/session/refresh', { refresh_token: session.refresh_token });
    refreshes.set(session.refresh_token, promise);
    // The cached result expires within MiniMoth's duplicate-request grace window.
    promise.finally(() => { const timer = setTimeout(() => refreshes.delete(session.refresh_token), 8000); timer.unref?.(); }).catch(() => {});
  }
  try {
    const tokens = await promise;
    if (!tokens.access_token || !tokens.refresh_token) return null;
    return { session: { ...session, ...tokens }, changed: true };
  } catch (error) { if (error.status === 401 || error.status === 403 || error.status === 400) return null; throw error; }
}
export function cookieOptions(request, session) {
  const secure = request.nextUrl.protocol === 'https:' || request.headers.get('x-forwarded-proto')?.split(',')[0] === 'https';
  const remaining = session ? Math.max(0, SESSION_SECONDS - Math.floor((Date.now() - session.created_at) / 1000)) : SESSION_SECONDS;
  return { httpOnly: true, secure, sameSite: 'lax', path: '/', maxAge: remaining };
}
export function setSession(response, request, session) {
  const encrypted = sealSession(session);
  if (encrypted.length > 3800) throw new AuthError('The sign-in session could not be saved.', 503);
  response.cookies.set(SESSION_COOKIE, encrypted, cookieOptions(request, session));
}
export function clearSession(response, request) { response.cookies.set(SESSION_COOKIE, '', { ...cookieOptions(request), maxAge: 0 }); }
export function sameOrigin(request) {
  const origin = request.headers.get('origin');
  if (!origin || request.headers.get('sec-fetch-site') === 'cross-site') return false;
  const expected = process.env.APP_ORIGIN || request.nextUrl.origin;
  return origin === expected;
}
