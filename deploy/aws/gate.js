// CloudFront Function (viewer request, cloudfront-js-2.0) in front of the private S3 bucket.
// Starwatch is public: anyone can open every page, the snapshot and the media without signing in.
// 1. Only Cloudflare reaches the app: a Transform Rule adds a private origin header that is checked here,
//    so the CloudFront hostname cannot be used to bypass Cloudflare's cache and rate limits.
// 2. Folder-style and retired sign-in paths are mapped to real files. The key is filled at deploy time.
var ORIGIN_KEY = '__ORIGIN_KEY__';
var RETIRED = /^\/(login|auth\/.*|data-deletion)$/;

function same(a, b) {
    if (!a || !b) return false;
    var diff = a.length ^ b.length;
    for (var i = 0; i < b.length; i++) diff |= (a.charCodeAt(i) || 0) ^ b.charCodeAt(i);
    return diff === 0;
}

function reply(status, location) {
    var headers = { 'cache-control': { value: 'public, max-age=3600' } };
    if (location) headers.location = { value: location };
    return { statusCode: status, statusDescription: status === 301 ? 'Moved Permanently' : 'Forbidden', headers: headers };
}

function handler(event) {
    var request = event.request;
    var header = request.headers['x-starwatch-cloudflare-origin'];
    var value = header ? header.value : '';
    delete request.headers['x-starwatch-cloudflare-origin'];
    if (!same(value, ORIGIN_KEY)) return reply(403);
    var uri = request.uri;
    if (/(\.\.|\/\/|\\)/.test(uri)) return reply(403);
    if (uri === '/') { request.uri = '/index.html'; return request; }
    if (uri === '/privacy') return reply(301, '/privacy.html');
    if (RETIRED.test(uri)) return reply(301, '/');
    return request;
}
