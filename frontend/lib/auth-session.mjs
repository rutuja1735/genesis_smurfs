import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'node:crypto';

export const SESSION_COOKIE = 'agentgaurd_session';
export const SESSION_SECONDS = 60 * 60 * 24 * 10;

function encryptionKey(secret) {
  if (!secret || secret.length < 32) throw new Error('SESSION_SECRET must contain at least 32 characters.');
  return createHash('sha256').update(secret).digest();
}
export function sealSession(session, secret = process.env.SESSION_SECRET) {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', encryptionKey(secret), iv);
  cipher.setAAD(Buffer.from(SESSION_COOKIE));
  const data = Buffer.concat([cipher.update(JSON.stringify(session), 'utf8'), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), data]).toString('base64url');
}
export function openSession(value, secret = process.env.SESSION_SECRET) {
  if (!value || value.length > 3800) return null;
  try {
    const data = Buffer.from(value, 'base64url');
    if (data.length < 29) return null;
    const decipher = createDecipheriv('aes-256-gcm', encryptionKey(secret), data.subarray(0, 12));
    decipher.setAAD(Buffer.from(SESSION_COOKIE));
    decipher.setAuthTag(data.subarray(12, 28));
    const session = JSON.parse(Buffer.concat([decipher.update(data.subarray(28)), decipher.final()]).toString('utf8'));
    if (!session.access_token || !session.refresh_token || !Number.isFinite(session.created_at)) return null;
    if (Date.now() - session.created_at > SESSION_SECONDS * 1000 || session.created_at > Date.now() + 30000) return null;
    return session;
  } catch { return null; }
}
export { safeNext, normalizePhone } from './auth-input.mjs';
