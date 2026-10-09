// Starwatch edge: social sign-in and public legal pages on Cloudflare.
// Routes: /login, /auth/*, /privacy, /data-deletion. Everything else goes straight to the
// CloudFront origin, whose gate (deploy/aws/gate.js) checks the session cookie minted here.

import { cookie, mintSession, pkcePair, readCookie, safeReturn, seal, unseal, validSession, randomHex } from './session.mjs';
import { PROVIDERS, enabledProviders } from './providers.mjs';
import { DELETION, PRIVACY, loginPage } from './pages.mjs';

const SESSION = '__Host-sw-session';
const FLOW = '__Host-sw-oauth';

const BASE_HEADERS = {
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'strict-origin-when-cross-origin',
  'x-frame-options': 'DENY',
  'permissions-policy': 'camera=(), microphone=(), geolocation=()',
  'strict-transport-security': 'max-age=31536000',
};
const CSP = "default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'";

function html(body, status = 200, extra = {}, cookies = []) {
  const headers = new Headers({ ...BASE_HEADERS, 'content-type': 'text/html; charset=utf-8', 'content-security-policy': CSP, 'cache-control': 'private, no-store', ...extra });
  for (const c of cookies) headers.append('set-cookie', c);
  return new Response(body, { status, headers });
}

function redirect(location, cookies = [], status = 302) {
  const headers = new Headers({ ...BASE_HEADERS, location, 'cache-control': 'private, no-store' });
  for (const c of cookies) headers.append('set-cookie', c);
  return new Response(null, { status, headers });
}

const ttl = (env) => Number(env.SESSION_TTL || 604800);

export async function handle(request, env, fetcher = fetch) {
  const url = new URL(request.url);
  if (url.hostname !== env.PUBLIC_HOST) return new Response('Not found', { status: 404 });
  const path = url.pathname.replace(/\/+$/, '') || '/';
  const callback = (id) => `https://${env.PUBLIC_HOST}/auth/callback/${id}`;

  if (path === '/privacy') return html(PRIVACY, 200, { 'cache-control': 'public, max-age=600' });
  if (path === '/data-deletion') return html(DELETION, 200, { 'cache-control': 'public, max-age=600' });
  if (!['GET', 'HEAD'].includes(request.method)) return new Response('Method not allowed', { status: 405, headers: { allow: 'GET, HEAD' } });

  if (path === '/login') {
    const returnTo = safeReturn(url.searchParams.get('return'));
    if (await validSession(env.SESSION_KEY, ttl(env), readCookie(request, SESSION))) return redirect(returnTo);
    return html(loginPage({ providers: enabledProviders(env), returnTo, error: url.searchParams.has('error') }));
  }

  if (path === '/auth/logout') return redirect('/', [cookie(SESSION, '', 0)]);

  const start = path.match(/^\/auth\/start\/(github|google|facebook)$/);
  if (start) {
    const id = start[1];
    if (!enabledProviders(env).includes(id)) return redirect('/login');
    const provider = PROVIDERS[id];
    const state = randomHex(16);
    const { verifier, challenge } = provider.pkce ? await pkcePair() : { verifier: null, challenge: null };
    const flow = await seal(env.SESSION_KEY, 'oauth', { p: id, s: state, v: verifier, r: safeReturn(url.searchParams.get('return')), e: Math.floor(Date.now() / 1000) + 600 });
    return redirect(provider.authorize(env, callback(id), state, challenge), [cookie(FLOW, flow, 600)]);
  }

  const back = path.match(/^\/auth\/callback\/(github|google|facebook)$/);
  if (back) {
    const id = back[1];
    const clear = cookie(FLOW, '', 0);
    const flow = await unseal(env.SESSION_KEY, 'oauth', readCookie(request, FLOW));
    const code = url.searchParams.get('code');
    if (!flow || flow.p !== id || flow.s !== url.searchParams.get('state') || !code || code.length > 2048 || !enabledProviders(env).includes(id)) {
      return redirect('/login?error=1', [clear]);
    }
    try {
      await PROVIDERS[id].identify(env, callback(id), code, flow.v, fetcher);
    } catch (err) {
      console.log(JSON.stringify({ event: 'signin_failed', provider: id, reason: String(err && err.message).slice(0, 80) }));
      return redirect(`/login?error=1&return=${encodeURIComponent(flow.r)}`, [clear]);
    }
    console.log(JSON.stringify({ event: 'signin', provider: id }));
    return redirect(safeReturn(flow.r), [clear, cookie(SESSION, await mintSession(env.SESSION_KEY, ttl(env)), ttl(env))], 303);
  }

  return new Response('Not found', { status: 404, headers: { 'cache-control': 'no-store' } });
}

export default { fetch: (request, env) => handle(request, env) };
