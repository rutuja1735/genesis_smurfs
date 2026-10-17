import test from 'node:test';
import assert from 'node:assert/strict';
import { openSession, sealSession, SESSION_SECONDS } from '../lib/auth-session.mjs';
import { normalizePhone, safeNext } from '../lib/auth-input.mjs';
import { authenticate, AuthError, minimoth, sameOrigin } from '../lib/minimoth.mjs';

const secret = 'test-only-secret-that-has-more-than-32-characters';
const session = () => ({ access_token: 'access-test-value', refresh_token: 'refresh-test-value', created_at: Date.now(), phone: '+919876543210' });

test('session encryption hides tokens and rejects forged, expired, and wrong-key cookies', () => {
  const original = session(); const encoded = sealSession(original, secret);
  assert.ok(!encoded.includes(original.access_token));
  assert.deepEqual(openSession(encoded, secret), original);
  const data = Buffer.from(encoded, 'base64url'); data[30] ^= 1;
  assert.equal(openSession(data.toString('base64url'), secret), null);
  assert.equal(openSession(encoded, secret + '-different'), null);
  assert.equal(openSession('not-a-cookie', secret), null);
  assert.equal(openSession(sealSession({ ...original, created_at: Date.now() - (SESSION_SECONDS + 1) * 1000 }, secret), secret), null);
});
test('login return paths stay within the workspace', () => {
  for (const value of ['https://evil.example', '//evil.example', '/\\evil.example', '/login', ['dashboard'], null]) assert.equal(safeNext(value), '/dashboard');
  assert.equal(safeNext('/runs/run123'), '/runs/run123');
  assert.equal(safeNext('/agents/email'), '/agents/email');
});
test('phone normalization accepts international and Indian local forms and rejects invalid input', () => {
  assert.equal(normalizePhone('98765 43210'), '+919876543210');
  assert.equal(normalizePhone('+91 (98765) 43210'), '+919876543210');
  assert.equal(normalizePhone('hello'), null);
  assert.equal(normalizePhone('12345'), null);
});
test('origin protection rejects cross-site and missing-origin mutations', () => {
  const request = (origin, site) => ({ nextUrl: new URL('http://localhost:3000/api/auth/send'), headers: new Headers({ ...(origin ? { origin } : {}), ...(site ? { 'sec-fetch-site': site } : {}) }) });
  assert.equal(sameOrigin(request('http://localhost:3000')), true);
  assert.equal(sameOrigin(request('https://evil.example')), false);
  assert.equal(sameOrigin(request()), false);
});
test('authentication validates server-side and rotates both tokens after expiry', async () => {
  const originalFetch = globalThis.fetch; const previousSecret = process.env.SESSION_SECRET; const previousKey = process.env.MINIMOTH_API_KEY;
  process.env.SESSION_SECRET = secret; process.env.MINIMOTH_API_KEY = 'mm_test_fake_unit_key';
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    assert.ok(url.startsWith('https://api.minimoth.dev/v1/'));
    assert.equal(options.headers['X-Api-Key'], 'mm_test_fake_unit_key');
    if (url.endsWith('/validate')) return Response.json({ valid: false });
    return Response.json({ access_token: 'rotated-access', refresh_token: 'rotated-refresh', expires_at: '2099-01-01T00:00:00Z' });
  };
  try {
    const result = await authenticate(sealSession(session(), secret));
    assert.equal(result.changed, true); assert.equal(result.session.access_token, 'rotated-access'); assert.equal(result.session.refresh_token, 'rotated-refresh');
    assert.equal(calls.length, 2);
    assert.equal(await authenticate('forged'), null);
  } finally { globalThis.fetch = originalFetch; if (previousSecret == null) delete process.env.SESSION_SECRET; else process.env.SESSION_SECRET = previousSecret; if (previousKey == null) delete process.env.MINIMOTH_API_KEY; else process.env.MINIMOTH_API_KEY = previousKey; }
});
test('provider failures return sanitized errors without echoing credentials', async () => {
  const originalFetch = globalThis.fetch; const previousKey = process.env.MINIMOTH_API_KEY;
  process.env.MINIMOTH_API_KEY = 'mm_live_private_unit_key';
  globalThis.fetch = async () => Response.json({ error: 'INVALID_API_KEY', message: 'mm_test_private_unit_key' }, { status: 401 });
  try { await assert.rejects(() => minimoth('/otp/send', { phone: '+919876543210' }), error => error instanceof AuthError && error.status === 503 && !error.message.includes('mm_test_')); }
  finally { globalThis.fetch = originalFetch; if (previousKey == null) delete process.env.MINIMOTH_API_KEY; else process.env.MINIMOTH_API_KEY = previousKey; }
});

test('OTP requests reject sandbox keys before contacting the provider', async () => {
  const previousKey = process.env.MINIMOTH_API_KEY;
  process.env.MINIMOTH_API_KEY = 'mm_test_fake_unit_key';
  try {
    for (const path of ['/otp/send', '/otp/verify']) await assert.rejects(() => minimoth(path, {}), error => error instanceof AuthError && error.status === 503 && error.message.includes('live'));
  } finally { if (previousKey == null) delete process.env.MINIMOTH_API_KEY; else process.env.MINIMOTH_API_KEY = previousKey; }
});
