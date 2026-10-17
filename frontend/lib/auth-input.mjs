export function safeNext(value) {
  if (typeof value !== 'string' || !/^\/(dashboard|runs|agents|analytics|testing|decisions|settings)(\/|\?|$)/.test(value) || /[\\\r\n]/.test(value)) return '/dashboard';
  return value;
}
export function normalizePhone(value) {
  let phone = String(value || '').replace(/[\s()-]/g, '');
  if (/^[6-9]\d{9}$/.test(phone)) phone = '+91' + phone;
  if (!/^\+[1-9]\d{7,14}$/.test(phone)) return null;
  return phone;
}
