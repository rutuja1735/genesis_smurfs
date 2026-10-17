import { NextResponse } from 'next/server';
import { authenticate, clearSession, sameOrigin, setSession } from './lib/minimoth.mjs';
import { SESSION_COOKIE } from './lib/auth-session.mjs';

export async function proxy(request) {
  const path = request.nextUrl.pathname;
  const isAPI = path.startsWith('/api/');

  // Local development bypass: when MiniMoth is not configured, skip auth so
  // the workspace is accessible without phone OTP. Production deployments
  // must set MINIMOTH_API_KEY and SESSION_SECRET to enforce authentication.
  if (!process.env.MINIMOTH_API_KEY) {
    const headers = new Headers(request.headers);
    if (process.env.INTERNAL_API_SECRET) headers.set('x-agentgaurd-internal', process.env.INTERNAL_API_SECRET);
    const response = NextResponse.next({ request: { headers } });
    response.headers.set('Cache-Control', 'no-store');
    return response;
  }

  if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method) && !sameOrigin(request)) return NextResponse.json({ error: 'Cross-origin requests are not allowed.' }, { status: 403 });
  if (path.startsWith('/api/auth/')) return NextResponse.next();
  let auth;
  try { auth = await authenticate(request.cookies.get(SESSION_COOKIE)?.value); }
  catch { return isAPI ? NextResponse.json({ detail: 'Authentication is temporarily unavailable.' }, { status: 503 }) : new NextResponse('Sign-in is temporarily unavailable. Please refresh to try again.', { status: 503 }); }
  if (!auth) {
    const login = new URL('/login', request.url);
    login.searchParams.set('next', path + request.nextUrl.search);
    const response = isAPI ? NextResponse.json({ detail: 'Please sign in to continue.' }, { status: 401 }) : NextResponse.redirect(login);
    clearSession(response, request); response.headers.set('Cache-Control', 'no-store'); return response;
  }
  const headers = new Headers(request.headers);
  headers.delete('x-agentgaurd-internal');
  if (process.env.INTERNAL_API_SECRET) headers.set('x-agentgaurd-internal', process.env.INTERNAL_API_SECRET);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set('Cache-Control', 'no-store');
  if (auth.changed) setSession(response, request, auth.session);
  return response;
}
export const config = { matcher: ['/dashboard/:path*', '/runs/:path*', '/agents/:path*', '/analytics/:path*', '/testing/:path*', '/decisions/:path*', '/settings/:path*', '/api/:path*', '/docs', '/openapi.json'] };
