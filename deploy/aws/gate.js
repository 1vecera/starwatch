// CloudFront Function (viewer request, cloudfront-js-2.0) in front of the private S3 bucket.
// 1. Only Cloudflare reaches the app: a Transform Rule adds a private origin header that is checked here.
// 2. The welcome page and its assets are public; everything else needs the signed session cookie
//    minted by the edge Worker (deploy/edge/session.mjs). Placeholders are filled at deploy time.
var crypto = require('crypto');
var SESSION_KEY = '__SESSION_KEY__';
var ORIGIN_KEY = '__ORIGIN_KEY__';
var LEGACY_ORIGIN_KEY = '__LEGACY_ORIGIN_KEY__';
var TTL = 604800;
var PUBLIC = /^\/(index\.html|welcome\.html|about\.html|robots\.txt|og\.png|favicon\.svg|manifest\.webmanifest|ds\.css|nav\.js|data\/stats\.js|(welcome|brand|fx|img|fonts)\/[^\/].*)$/;

function same(a, b) {
    if (!a || !b) return false;
    var diff = a.length ^ b.length;
    for (var i = 0; i < b.length; i++) diff |= (a.charCodeAt(i) || 0) ^ b.charCodeAt(i);
    return diff === 0;
}

function signedIn(request) {
    var c = request.cookies['__Host-sw-session'];
    if (!c || c.value.length > 200) return false;
    var p = c.value.split('.');
    if (p.length !== 4 || p[0] !== 'v1' || !/^\d+$/.test(p[1]) || !/^[a-f0-9]{32}$/.test(p[2]) || !/^[a-f0-9]{64}$/.test(p[3])) return false;
    var now = Math.floor(Date.now() / 1000), exp = Number(p[1]);
    if (!(exp > now && exp <= now + TTL)) return false;
    return same(crypto.createHmac('sha256', SESSION_KEY).update(p.slice(0, 3).join('.')).digest('hex'), p[3]);
}

function query(qs) {
    var out = [];
    for (var k in qs) {
        var v = qs[k];
        if (v.multiValue) for (var i = 0; i < v.multiValue.length; i++) out.push(k + '=' + v.multiValue[i].value);
        else out.push(k + (v.value === '' ? '' : '=' + v.value));
    }
    return out.length ? '?' + out.join('&') : '';
}

function deny(status, location) {
    var headers = { 'cache-control': { value: 'private, no-store' }, 'x-robots-tag': { value: 'noindex' } };
    if (location) headers.location = { value: location };
    return { statusCode: status, statusDescription: status === 302 ? 'Found' : status === 401 ? 'Unauthorized' : 'Forbidden', headers: headers };
}

function handler(event) {
    var request = event.request;
    var header = request.headers['x-starwatch-cloudflare-origin'];
    var value = header ? header.value : '';
    delete request.headers['x-starwatch-cloudflare-origin'];
    // The retired jury hostname (Cloudflare Access) keeps working until it is switched off.
    if (LEGACY_ORIGIN_KEY.indexOf('__') !== 0 && same(value, LEGACY_ORIGIN_KEY)) {
        if (request.uri === '/') request.uri = '/atlas.html';
        return request;
    }
    if (!same(value, ORIGIN_KEY)) return deny(403);
    if (request.uri === '/') { request.uri = '/index.html'; return request; }
    var plain = !/(\.\.|\/\/|%|\\)/.test(request.uri);
    if ((plain && PUBLIC.test(request.uri)) || signedIn(request)) return request;
    var page = /\.html$/.test(request.uri);
    return page ? deny(302, '/login?return=' + encodeURIComponent(request.uri + query(request.querystring))) : deny(401);
}
