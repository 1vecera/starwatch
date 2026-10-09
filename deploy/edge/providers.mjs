// OAuth providers. Each one only proves that the visitor has an account there:
// minimal scopes, one identity call, nothing stored.

import { sign } from './session.mjs';

const UA = 'Starwatch (+https://github.com/1vecera/starwatch)';

async function json(response, what) {
  if (!response.ok) throw new Error(`${what} ${response.status}`);
  return response.json();
}

export const PROVIDERS = {
  github: {
    label: 'GitHub',
    env: ['GITHUB_ID', 'GITHUB_SECRET'],
    pkce: true,
    authorize(env, redirect, state, challenge) {
      const q = new URLSearchParams({ client_id: env.GITHUB_ID, redirect_uri: redirect, state, scope: '', allow_signup: 'true',
        code_challenge: challenge, code_challenge_method: 'S256' });
      return `https://github.com/login/oauth/authorize?${q}`;
    },
    async identify(env, redirect, code, verifier, fetcher) {
      const token = await json(await fetcher('https://github.com/login/oauth/access_token', {
        method: 'POST',
        headers: { accept: 'application/json', 'content-type': 'application/json', 'user-agent': UA },
        body: JSON.stringify({ client_id: env.GITHUB_ID, client_secret: env.GITHUB_SECRET, code, redirect_uri: redirect, code_verifier: verifier }),
      }), 'github token');
      if (!token.access_token) throw new Error('github token missing');
      const user = await json(await fetcher('https://api.github.com/user', {
        headers: { authorization: `Bearer ${token.access_token}`, accept: 'application/vnd.github+json', 'user-agent': UA },
      }), 'github user');
      if (!Number.isInteger(user.id)) throw new Error('github user id missing');
      return `github:${user.id}`;
    },
  },

  google: {
    label: 'Google',
    env: ['GOOGLE_ID', 'GOOGLE_SECRET'],
    pkce: true,
    authorize(env, redirect, state, challenge) {
      const q = new URLSearchParams({ client_id: env.GOOGLE_ID, redirect_uri: redirect, response_type: 'code', scope: 'openid',
        state, code_challenge: challenge, code_challenge_method: 'S256', prompt: 'select_account' });
      return `https://accounts.google.com/o/oauth2/v2/auth?${q}`;
    },
    async identify(env, redirect, code, verifier, fetcher) {
      const token = await json(await fetcher('https://oauth2.googleapis.com/token', {
        method: 'POST',
        headers: { 'content-type': 'application/x-www-form-urlencoded', accept: 'application/json' },
        body: new URLSearchParams({ code, client_id: env.GOOGLE_ID, client_secret: env.GOOGLE_SECRET, redirect_uri: redirect,
          grant_type: 'authorization_code', code_verifier: verifier }),
      }), 'google token');
      // The ID token comes straight from Google's token endpoint over TLS, so its claims can be read without a JWKS
      // check (OpenID Connect Core 3.1.3.7); audience, issuer and expiry are still enforced.
      const parts = String(token.id_token || '').split('.');
      if (parts.length !== 3) throw new Error('google id token missing');
      const claims = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
      const now = Math.floor(Date.now() / 1000);
      if (claims.aud !== env.GOOGLE_ID || !['https://accounts.google.com', 'accounts.google.com'].includes(claims.iss) ||
          !(claims.exp > now) || typeof claims.sub !== 'string') throw new Error('google id token invalid');
      return `google:${claims.sub}`;
    },
  },

  facebook: {
    label: 'Facebook',
    env: ['FACEBOOK_ID', 'FACEBOOK_SECRET'],
    pkce: false,
    authorize(env, redirect, state) {
      const q = new URLSearchParams({ client_id: env.FACEBOOK_ID, redirect_uri: redirect, state, scope: 'public_profile', response_type: 'code' });
      return `https://www.facebook.com/dialog/oauth?${q}`;
    },
    async identify(env, redirect, code, _verifier, fetcher) {
      const q = new URLSearchParams({ client_id: env.FACEBOOK_ID, client_secret: env.FACEBOOK_SECRET, redirect_uri: redirect, code });
      const token = await json(await fetcher(`https://graph.facebook.com/oauth/access_token?${q}`, { headers: { accept: 'application/json' } }), 'facebook token');
      if (!token.access_token) throw new Error('facebook token missing');
      const proof = await sign(env.FACEBOOK_SECRET, token.access_token);
      const me = await json(await fetcher(`https://graph.facebook.com/me?${new URLSearchParams({ fields: 'id', access_token: token.access_token, appsecret_proof: proof })}`,
        { headers: { accept: 'application/json' } }), 'facebook me');
      if (typeof me.id !== 'string') throw new Error('facebook id missing');
      return `facebook:${me.id}`;
    },
  },
};

export const enabledProviders = (env) => Object.entries(PROVIDERS).filter(([, p]) => p.env.every((k) => env[k])).map(([id]) => id);
