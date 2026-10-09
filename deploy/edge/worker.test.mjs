import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { handle } from './worker.mjs';
import { mintSession, validSession, safeReturn, seal, unseal } from './session.mjs';

const KEY = 'a'.repeat(64);
const env = { PUBLIC_HOST: 'starwatch.example.org', SESSION_KEY: KEY, SESSION_TTL: '604800',
  GITHUB_ID: 'gh-id', GITHUB_SECRET: 'gh-secret', GOOGLE_ID: 'g-id', GOOGLE_SECRET: 'g-secret' };
const req = (path, headers = {}) => new Request(`https://starwatch.example.org${path}`, { headers });
const setCookies = (res) => res.headers.getSetCookie();

test('session cookie round-trips and matches the CloudFront HMAC', async () => {
  const value = await mintSession(KEY, 604800);
  assert.ok(await validSession(KEY, 604800, value));
  const p = value.split('.');
  assert.equal(createHmac('sha256', KEY).update(p.slice(0, 3).join('.')).digest('hex'), p[3]);
  assert.equal(await validSession(KEY, 604800, value.slice(0, -1) + (value.endsWith('0') ? '1' : '0')), false);
  assert.equal(await validSession('b'.repeat(64), 604800, value), false);
});

test('return paths stay on site and out of the login flow', () => {
  for (const bad of ['//evil.com', 'https://evil.com', '/\\evil', '/auth/start/github', '/login?x', '/a\nb', null]) assert.equal(safeReturn(bad), '/atlas.html');
  assert.equal(safeReturn('/spotlight.html?who=x'), '/spotlight.html?who=x');
});

test('sealed flow state rejects tampering and other purposes', async () => {
  const sealed = await seal(KEY, 'oauth', { p: 'github', e: Math.floor(Date.now() / 1000) + 60 });
  assert.equal((await unseal(KEY, 'oauth', sealed)).p, 'github');
  assert.equal(await unseal(KEY, 'other', sealed), null);
  assert.equal(await unseal(KEY, 'oauth', 'x' + sealed), null);
});

test('login page lists only configured providers and promotes the author', async () => {
  const res = await handle(req('/login?return=/pulse.html'), env);
  const body = await res.text();
  assert.equal(res.status, 200);
  assert.match(body, /\/auth\/start\/github\?return=%2Fpulse\.html/);
  assert.match(body, /\/auth\/start\/google/);
  assert.doesNotMatch(body, /\/auth\/start\/facebook/);
  assert.match(body, /linkedin\.com\/in\/1vecera/);
  assert.match(body, /x\.com\/1vecera/);
  assert.match(res.headers.get('content-security-policy'), /frame-ancestors 'none'/);
});

test('signed-in visitors skip the login page', async () => {
  const session = await mintSession(KEY, 604800);
  const res = await handle(req('/login?return=/radar.html', { cookie: `__Host-sw-session=${session}` }), env);
  assert.equal(res.status, 302);
  assert.equal(res.headers.get('location'), '/radar.html');
});

test('full GitHub round trip mints a session and returns to the page', async () => {
  const start = await handle(req('/auth/start/github?return=/spotlight.html?who=1'), env);
  assert.equal(start.status, 302);
  const to = new URL(start.headers.get('location'));
  assert.equal(to.origin + to.pathname, 'https://github.com/login/oauth/authorize');
  assert.equal(to.searchParams.get('redirect_uri'), 'https://starwatch.example.org/auth/callback/github');
  assert.equal(to.searchParams.get('code_challenge_method'), 'S256');
  const flow = setCookies(start)[0].split(';')[0];
  const calls = [];
  const fake = async (url, init = {}) => {
    calls.push(url);
    if (url.startsWith('https://github.com/login/oauth/access_token')) {
      const body = JSON.parse(init.body);
      assert.equal(body.client_secret, 'gh-secret');
      assert.ok(body.code_verifier);
      return Response.json({ access_token: 'tok' });
    }
    if (url === 'https://api.github.com/user') return Response.json({ id: 42 });
    throw new Error('unexpected ' + url);
  };
  const back = await handle(req(`/auth/callback/github?code=abc&state=${to.searchParams.get('state')}`, { cookie: flow }), env, fake);
  assert.equal(back.status, 303);
  assert.equal(back.headers.get('location'), '/spotlight.html?who=1');
  const session = setCookies(back).find((c) => c.startsWith('__Host-sw-session=')).split(';')[0].split('=')[1];
  assert.ok(await validSession(KEY, 604800, session));
  assert.equal(calls.length, 2);
});

test('callback with a wrong state or no flow cookie never mints a session', async () => {
  const start = await handle(req('/auth/start/google'), env);
  const flow = setCookies(start)[0].split(';')[0];
  const bad = await handle(req('/auth/callback/google?code=abc&state=nope', { cookie: flow }), env, () => { throw new Error('no network'); });
  assert.equal(bad.status, 302);
  assert.match(bad.headers.get('location'), /^\/login\?error=1/);
  assert.ok(!setCookies(bad).some((c) => c.startsWith('__Host-sw-session=') && !c.includes('Max-Age=0')));
  const none = await handle(req('/auth/callback/google?code=abc&state=x'), env);
  assert.match(none.headers.get('location'), /^\/login\?error=1/);
});

test('Google ID tokens with a foreign audience are refused', async () => {
  const start = await handle(req('/auth/start/google'), env);
  const state = new URL(start.headers.get('location')).searchParams.get('state');
  const flow = setCookies(start)[0].split(';')[0];
  const claims = Buffer.from(JSON.stringify({ aud: 'someone-else', iss: 'https://accounts.google.com', exp: Math.floor(Date.now() / 1000) + 60, sub: '1' })).toString('base64url');
  const fake = async () => Response.json({ id_token: `x.${claims}.y` });
  const res = await handle(req(`/auth/callback/google?code=abc&state=${state}`, { cookie: flow }), env, fake);
  assert.match(res.headers.get('location'), /^\/login\?error=1/);
});

test('logout clears the session; other hosts and methods are refused', async () => {
  const out = await handle(req('/auth/logout'), env);
  assert.equal(out.headers.get('location'), '/');
  assert.ok(setCookies(out).some((c) => c.startsWith('__Host-sw-session=;') && c.includes('Max-Age=0')));
  assert.equal((await handle(new Request('https://evil.example.org/login'), env)).status, 404);
  assert.equal((await handle(new Request('https://starwatch.example.org/auth/start/github', { method: 'POST' }), env)).status, 405);
  assert.equal((await handle(req('/auth/start/facebook'), env)).headers.get('location'), '/login');
});

// The CloudFront Function runs in a restricted ES5 runtime; exercise it in a VM with the same placeholders filled in.
function gate(legacy = '') {
  const src = readFileSync(new URL('../aws/gate.js', import.meta.url), 'utf8')
    .replace('__SESSION_KEY__', KEY).replace('__ORIGIN_KEY__', 'o'.repeat(64)).replace('__LEGACY_ORIGIN_KEY__', legacy || '__LEGACY_ORIGIN_KEY__');
  const ctx = { require: (m) => (m === 'crypto' ? { createHmac } : null) };
  vm.runInNewContext(src, ctx);
  return (uri, { origin = 'o'.repeat(64), session = null, qs = {} } = {}) => ctx.handler({ request: {
    uri, querystring: qs, headers: origin ? { 'x-starwatch-cloudflare-origin': { value: origin } } : {},
    cookies: session ? { '__Host-sw-session': { value: session } } : {} } });
}

test('gate: Cloudflare-only, public welcome, signed-in app', async () => {
  const g = gate('l'.repeat(64));
  assert.equal(g('/atlas.html', { origin: null }).statusCode, 403);
  assert.equal(g('/atlas.html', { origin: 'x'.repeat(64) }).statusCode, 403);
  assert.equal(g('/').uri, '/index.html');
  assert.equal(g('/welcome/tile-01.jpg').uri, '/welcome/tile-01.jpg');
  const anon = g('/spotlight.html', { qs: { who: { value: 'kv2026:1' } } });
  assert.equal(anon.statusCode, 302);
  assert.equal(anon.headers.location.value, '/login?return=' + encodeURIComponent('/spotlight.html?who=kv2026:1'));
  assert.equal(g('/data/real.js').statusCode, 401);
  assert.equal(g('/media/a.mp4').statusCode, 401);
  const session = await mintSession(KEY, 604800);
  const ok = g('/data/real.js', { session });
  assert.equal(ok.uri, '/data/real.js');
  assert.equal(ok.headers['x-starwatch-cloudflare-origin'], undefined);
  assert.equal(g('/data/real.js', { session: session.replace(/.$/, (c) => (c === 'a' ? 'b' : 'a')) }).statusCode, 401);
  assert.equal(g('/', { origin: 'l'.repeat(64) }).uri, '/atlas.html');
  assert.equal(gate()('/atlas.html', { origin: '__LEGACY_ORIGIN_KEY__' }).statusCode, 403);
});
