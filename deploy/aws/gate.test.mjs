// node --test deploy/aws/gate.test.mjs
// The CloudFront Function runs in a restricted ES5 runtime; exercise it in a VM with the origin key filled in.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const KEY = 'o'.repeat(64);

function gate() {
  const ctx = {};
  vm.runInNewContext(readFileSync(new URL('./gate.js', import.meta.url), 'utf8').replace('__ORIGIN_KEY__', KEY), ctx);
  return (uri, origin = KEY) => ctx.handler({ request: { uri, querystring: {}, headers: origin ? { 'x-starwatch-cloudflare-origin': { value: origin } } : {}, cookies: {} } });
}

test('only requests that came through Cloudflare reach the bucket', () => {
  const g = gate();
  assert.equal(g('/atlas.html', null).statusCode, 403);
  assert.equal(g('/atlas.html', 'x'.repeat(64)).statusCode, 403);
  assert.equal(g('/atlas.html', KEY.slice(1)).statusCode, 403);
});

test('every page, the snapshot and media are public; the origin header never reaches S3', () => {
  const g = gate();
  assert.equal(g('/').uri, '/index.html');
  for (const uri of ['/atlas.html', '/spotlight.html', '/data/real.js', '/data/results2026.js', '/media/a.mp4', '/welcome/tile.jpg', '/privacy.html']) {
    const out = g(uri);
    assert.equal(out.uri, uri);
    assert.equal(out.headers['x-starwatch-cloudflare-origin'], undefined);
  }
});

test('retired sign-in paths go home and the old privacy path moves', () => {
  const g = gate();
  for (const uri of ['/login', '/auth/logout', '/auth/callback/github', '/data-deletion']) {
    const out = g(uri);
    assert.equal(out.statusCode, 301);
    assert.equal(out.headers.location.value, '/');
  }
  assert.equal(g('/privacy').headers.location.value, '/privacy.html');
});

test('dot segments and doubled slashes are refused', () => {
  const g = gate();
  assert.equal(g('/welcome/../data/real.js').statusCode, 403);
  assert.equal(g('//atlas.html').statusCode, 403);
});
