import test from 'node:test';
import assert from 'node:assert/strict';

const origin = process.env.AUTH_TEST_ORIGIN;
test('anonymous requests cannot bypass login or call agent APIs', { skip: !origin }, async () => {
  for (const path of ['/dashboard', '/runs', '/agents/email', '/analytics', '/testing', '/settings', '/decisions']) {
    const response = await fetch(origin + path, { redirect: 'manual' });
    assert.equal(response.status, 307, path);
    assert.ok(new URL(response.headers.get('location'), origin).pathname === '/login');
  }
  for (const path of ['/api/config', '/api/runs', '/api/data/email']) {
    const response = await fetch(origin + path, { headers: { 'x-agentgaurd-internal': 'forged' } });
    assert.equal(response.status, 401, path);
  }
});
test('authentication endpoints reject cross-origin and invalid phone requests locally', { skip: !origin }, async () => {
  const crossSite = await fetch(origin + '/api/auth/send', { method: 'POST', headers: { Origin: 'https://evil.example', 'Content-Type': 'application/json' }, body: JSON.stringify({ phone: '+919876543210' }) });
  assert.equal(crossSite.status, 403);
  const invalidPhone = await fetch(origin + '/api/auth/send', { method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' }, body: JSON.stringify({ phone: 'not-a-phone' }) });
  assert.equal(invalidPhone.status, 400);
  const me = await fetch(origin + '/api/auth/me');
  assert.equal(me.status, 401);
});
