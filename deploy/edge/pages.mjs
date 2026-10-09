// Public pages rendered at the edge: sign-in, privacy notice and data deletion.

export const AUTHOR = {
  name: 'Daniel Večeřa',
  role: 'Data scientist, Prague',
  linkedin: 'https://www.linkedin.com/in/1vecera/',
  x: 'https://x.com/1vecera',
  repo: 'https://github.com/1vecera/starwatch',
};

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const ICON = {
  mark: '<svg class="mark" viewBox="-32 -32 64 64" aria-hidden="true"><g fill="currentColor"><path d="M-30,0L-10.06,8.55L-6.77,-1.31L-5.21,-0.79L-0.91,-5.09L-10.59,-8.32Z"/><path d="M0,30L8.55,10.06L-1.31,6.77L-0.79,5.21L-5.09,0.91L-8.32,10.59Z"/><path d="M30,0L10.06,-8.55L6.77,1.31L5.21,0.79L0.91,5.09L10.59,8.32Z"/><path d="M0,-30L-8.55,-10.06L1.31,-6.77L0.79,-5.21L5.09,-0.91L8.32,-10.59Z"/></g></svg>',
  github: '<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>',
  google: '<svg viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>',
  facebook: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.971H15.83c-1.491 0-1.956.93-1.956 1.886v2.267h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z"/></svg>',
  linkedin: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>',
  x: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z"/></svg>',
};

const CSS = `:root{--canvas:#F2F7F7;--surface:#FFFFFF;--ink:#0F172A;--ink2:#475569;--ink3:#5B6A7E;--teal:#0E6E6B;--rule:rgba(22,37,36,.14);--shadow:0 1px 2px rgb(15 23 42/.06),0 24px 60px -24px rgb(15 23 42/.22)}
@media (prefers-color-scheme:dark){:root{--canvas:#0B1414;--surface:#121D1D;--ink:#E6EEEE;--ink2:#A3B3B3;--ink3:#8A9C9C;--teal:#5FC4BE;--rule:rgba(230,238,238,.14);--shadow:0 1px 2px rgb(0 0 0/.3),0 24px 60px -24px rgb(0 0 0/.6)}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}body{margin:0;min-height:100vh;background:var(--canvas);color:var(--ink);font:16px/1.55 'Schibsted Grotesk',system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--teal)}a:focus-visible,.btn:focus-visible,.follow:focus-visible{outline:2px solid var(--teal);outline-offset:3px}
.top{display:flex;align-items:center;justify-content:space-between;gap:16px;max-width:1080px;margin:0 auto;padding:22px 20px}
.brand{display:flex;align-items:center;gap:10px;color:var(--ink);text-decoration:none;font:700 19px/1 'Sora','Schibsted Grotesk',system-ui,sans-serif;letter-spacing:-.01em}
.brand .mark{width:26px;height:26px;color:#0E6E6B}.top nav{display:flex;gap:18px;font-size:15px}.top nav a{color:var(--ink2);text-decoration:none}.top nav a:hover{color:var(--ink)}
main{max-width:1080px;margin:0 auto;padding:12px 20px 64px}
.signin{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);gap:56px;align-items:center;min-height:calc(100vh - 220px)}
h1{font:720 clamp(36px,5.2vw,64px)/1.02 'Bricolage Grotesque','Schibsted Grotesk',system-ui,sans-serif;letter-spacing:-.03em;margin:0 0 20px}
h1 .quiet{color:var(--ink3)}.lede{font-size:19px;color:var(--ink2);max-width:34em;margin:0 0 22px}
.chip{display:inline-flex;align-items:center;gap:8px;font-size:14px;color:var(--ink2);border:1px solid var(--rule);border-radius:999px;padding:6px 12px}
.chip::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--ink3)}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:16px;box-shadow:var(--shadow);padding:28px}
.card h2{font-size:20px;margin:0 0 4px;letter-spacing:-.01em}.card p{margin:0 0 20px;color:var(--ink2);font-size:15px}
.btn{display:flex;align-items:center;justify-content:center;gap:12px;width:100%;min-height:48px;margin:0 0 12px;border-radius:10px;font:600 16px/1 'Schibsted Grotesk',system-ui,sans-serif;text-decoration:none;transition:transform .15s ease,box-shadow .15s ease}
.btn:hover{transform:translateY(-1px)}.btn svg{width:20px;height:20px;flex:none}
.btn.github{background:#24292F;color:#fff}.btn.google{background:#fff;color:#1F1F1F;border:1px solid #747775}.btn.facebook{background:#1877F2;color:#fff}
.fine{font-size:13.5px;color:var(--ink3);margin:16px 0 0}.fine a{color:var(--ink2)}
.alert{border:1px solid #B42318;color:#B42318;background:rgb(180 35 24/.06);border-radius:10px;padding:10px 12px;font-size:14px;margin:0 0 16px}
.author{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;border-top:1px solid var(--rule);margin-top:48px;padding-top:24px}
.author b{display:block;font-size:17px}.author span{color:var(--ink2);font-size:15px}.follows{display:flex;gap:10px;flex-wrap:wrap}
.follow{display:inline-flex;align-items:center;gap:9px;min-height:42px;padding:0 16px;border-radius:999px;border:1px solid var(--rule);background:var(--surface);color:var(--ink);text-decoration:none;font-weight:600;font-size:15px}
.follow svg{width:17px;height:17px}.follow.li svg{color:#0A66C2}.follow:hover{border-color:var(--ink3)}
.doc{max-width:720px}.doc h1{font-size:clamp(34px,5vw,48px)}.doc h2{font-size:20px;margin:36px 0 8px}.doc p,.doc li{color:var(--ink2)}.doc strong{color:var(--ink)}
@media (max-width:820px){.signin{grid-template-columns:1fr;gap:28px;min-height:0}.top nav{display:none}.lede{font-size:17px}}
@media (prefers-reduced-motion:reduce){.btn{transition:none}.btn:hover{transform:none}}`;

const FONTS = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@400..800&family=Bricolage+Grotesque:opsz,wght@12..96,600..800&family=Sora:wght@700&display=swap" rel="stylesheet">';

const authorBlock = () => `<section class="author" aria-label="Author"><div><b>Made by ${esc(AUTHOR.name)}</b><span>${esc(AUTHOR.role)} · open source on <a href="${AUTHOR.repo}">GitHub</a></span></div>
<div class="follows"><a class="follow li" href="${AUTHOR.linkedin}" rel="me noopener" target="_blank">${ICON.linkedin}Follow on LinkedIn</a><a class="follow" href="${AUTHOR.x}" rel="me noopener" target="_blank">${ICON.x}Follow on X</a></div></section>`;

export function shell(title, body, description = 'Who is being heard in the 2026 Czech municipal elections: public posts by candidates in ten cities, mapped by party, person and topic.') {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title><meta name="description" content="${esc(description)}"><meta name="theme-color" content="#F2F7F7">
<link rel="icon" href="/brand/favicon.svg" type="image/svg+xml">${FONTS}<style>${CSS}</style></head><body>
<header class="top"><a class="brand" href="/">${ICON.mark}Starwatch</a><nav><a href="/about.html">About</a><a href="${AUTHOR.repo}">Open source</a><a href="${AUTHOR.linkedin}" rel="me noopener" target="_blank">LinkedIn</a><a href="${AUTHOR.x}" rel="me noopener" target="_blank">X</a></nav></header>
<main>${body}${authorBlock()}</main></body></html>`;
}

export function loginPage({ providers, returnTo, error }) {
  const buttons = providers.length
    ? providers.map((id) => `<a class="btn ${id}" href="/auth/start/${id}?return=${encodeURIComponent(returnTo)}">${ICON[id]}Continue with ${id === 'github' ? 'GitHub' : id[0].toUpperCase() + id.slice(1)}</a>`).join('')
    : '<p class="alert" role="status">Sign-in is being set up. Please try again in a few minutes.</p>';
  return shell('Sign in · Starwatch', `<section class="signin"><div>
<h1>Who's being heard.<br><span class="quiet">Not just who's talking.</span></h1>
<p class="lede">Starwatch maps 12,595 public posts by candidates in the 2026 Czech municipal elections across ten cities, by party, person and topic, with a link to every original.</p>
<span class="chip">Snapshot collected 8–9 October 2026 · not live</span></div>
<div class="card"><h2>Sign in to explore</h2><p>Use an account you already have. Signing in keeps automated traffic off the servers.</p>
${error ? '<p class="alert" role="alert">That sign-in did not complete. Please try again.</p>' : ''}${buttons}
<p class="fine">Starwatch only checks that the account exists. Nothing from it is stored; you get a signed cookie for seven days. <a href="/privacy">Privacy</a> · <a href="/data-deletion">Data deletion</a></p></div></section>`);
}

const CONTACT = `<a href="${AUTHOR.repo}/issues">github.com/1vecera/starwatch/issues</a>`;

export const PRIVACY = shell('Privacy · Starwatch', `<article class="doc"><h1>Privacy</h1><p>Starwatch is an independent, non-commercial open-source project by Daniel Večeřa, Prague, Czech Republic. It shows public social-media activity of candidates in the 2026 Czech municipal elections. Questions and requests: ${CONTACT}.</p>
<h2>When you sign in</h2><p>You sign in with GitHub, Google or Facebook. Starwatch only asks the provider to confirm that you have an account: no extra GitHub permissions, Google's <code>openid</code> scope and Facebook's <code>public_profile</code>. Starwatch never sees your password.</p><p><strong>Starwatch stores nothing from your account.</strong> It keeps no database of users, names or email addresses. After the provider confirms you, your browser gets a signed session cookie that contains only a random identifier and an expiry time (seven days). Signing out or clearing cookies removes it.</p>
<h2>Hosting</h2><p>Pages are delivered by Cloudflare and Amazon Web Services (Frankfurt, EU). Like any website, their systems process your IP address and the requests you make, to deliver pages and stop abuse, and keep short-lived logs. Starwatch has no advertising, analytics or tracking cookies.</p>
<h2>Data about candidates</h2><p>Starwatch shows a snapshot of public posts collected on 8–9 October 2026 from public profiles of candidates in ten Czech cities, with links to the originals, alongside official open data from <a href="https://volby.gov.cz/opendata/">volby.gov.cz</a> and the Czech Statistical Office, and the lists' own published programs. It does not monitor accounts live.</p><p>The purpose is public-interest research into political communication during an election. The legal basis is legitimate interest (GDPR Art. 6(1)(f)); candidates made their political affiliation public themselves (Art. 9(2)(e)). Starwatch does not profile voters, infer sensitive traits or score anyone's character or trustworthiness. Metrics are dated observations, not measures of support.</p><p>If you are a candidate and want something corrected or removed, open a request at ${CONTACT}. You also have the rights of access, rectification, erasure and objection, and you can complain to the Czech data protection authority, <a href="https://uoou.gov.cz/">ÚOOÚ</a>.</p>
<p class="fine">Updated 9 October 2026.</p></article>`);

export const DELETION = shell('Data deletion · Starwatch', `<article class="doc"><h1>Delete your data</h1><p>Starwatch does not store any data from your GitHub, Google or Facebook account, so there is nothing to delete on our side. Your session lives only in a cookie in your browser and expires after seven days.</p>
<h2>Remove Starwatch's access</h2><ul><li><strong>Facebook:</strong> Settings &amp; privacy → Settings → Apps and websites → Starwatch → Remove.</li><li><strong>Google:</strong> <a href="https://myaccount.google.com/connections">myaccount.google.com/connections</a> → Starwatch → Delete all connections.</li><li><strong>GitHub:</strong> Settings → Applications → Authorized OAuth Apps → Starwatch → Revoke.</li></ul>
<h2>End your session</h2><p><a href="/auth/logout">Sign out</a>, or clear cookies for starwatch.agenticanalytics.cz.</p><p>Anything else: ${CONTACT}.</p></article>`);
