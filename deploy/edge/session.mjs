// Signed cookies shared with the CloudFront gate (deploy/aws/gate.js).
// Session format: v1.<expires>.<32 hex random>.<64 hex HMAC-SHA256 of the first three parts>.
// The key is the hex string itself, used as UTF-8 bytes, exactly like the CloudFront Function.

const enc = new TextEncoder();
const keys = new Map();

async function hmacKey(secret) {
  let key = keys.get(secret);
  if (!key) {
    key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    keys.set(secret, key);
  }
  return key;
}

const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');

export async function sign(secret, text) {
  return hex(await crypto.subtle.sign('HMAC', await hmacKey(secret), enc.encode(text)));
}

export function safeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return diff === 0;
}

export function randomHex(bytes = 16) {
  return hex(crypto.getRandomValues(new Uint8Array(bytes)));
}

export async function mintSession(secret, ttl, now = Math.floor(Date.now() / 1000)) {
  const body = `v1.${now + ttl}.${randomHex(16)}`;
  return `${body}.${await sign(secret, body)}`;
}

export async function validSession(secret, ttl, value, now = Math.floor(Date.now() / 1000)) {
  if (typeof value !== 'string' || value.length > 200) return false;
  const parts = value.split('.');
  if (parts.length !== 4 || parts[0] !== 'v1' || !/^\d+$/.test(parts[1]) ||
      !/^[a-f0-9]{32}$/.test(parts[2]) || !/^[a-f0-9]{64}$/.test(parts[3])) return false;
  const expires = Number(parts[1]);
  if (!(expires > now && expires <= now + ttl)) return false;
  return safeEqual(await sign(secret, parts.slice(0, 3).join('.')), parts[3]);
}

const b64url = (text) => btoa(String.fromCharCode(...enc.encode(text))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const unb64url = (text) => new TextDecoder().decode(Uint8Array.from(atob(text.replace(/-/g, '+').replace(/_/g, '/')), (c) => c.charCodeAt(0)));

// Short-lived, purpose-bound state for one OAuth round trip.
export async function seal(secret, purpose, payload) {
  const raw = b64url(JSON.stringify(payload));
  return `${raw}.${await sign(secret, `${purpose}.${raw}`)}`;
}

export async function unseal(secret, purpose, value, now = Math.floor(Date.now() / 1000)) {
  if (typeof value !== 'string' || value.length > 2048) return null;
  const dot = value.lastIndexOf('.');
  if (dot < 1) return null;
  const raw = value.slice(0, dot);
  if (!safeEqual(await sign(secret, `${purpose}.${raw}`), value.slice(dot + 1))) return null;
  try {
    const payload = JSON.parse(unb64url(raw));
    return typeof payload.e === 'number' && payload.e > now && payload.e <= now + 900 ? payload : null;
  } catch {
    return null;
  }
}

export function readCookie(request, name) {
  const header = request.headers.get('cookie') || '';
  for (const part of header.split(';')) {
    const i = part.indexOf('=');
    if (i > 0 && part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return null;
}

export function cookie(name, value, maxAge) {
  return `${name}=${value}; Max-Age=${maxAge}; Path=/; Secure; HttpOnly; SameSite=Lax`;
}

// Only same-site paths into the app; never back into the login flow.
export function safeReturn(value, fallback = '/atlas.html') {
  if (typeof value !== 'string' || value.length > 1024 || !value.startsWith('/') || value.startsWith('//') ||
      value.includes('\\') || /[\u0000-\u001f\u007f]/.test(value) || /^\/(auth\/|login)/.test(value)) return fallback;
  return value;
}

export async function pkcePair() {
  const verifier = randomHex(32);
  const digest = await crypto.subtle.digest('SHA-256', enc.encode(verifier));
  const challenge = btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return { verifier, challenge };
}
