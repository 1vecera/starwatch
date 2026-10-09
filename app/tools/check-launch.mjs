// Launch checks for the public Starwatch app (headless Chromium, real snapshot, no side effects).
// Every screen loads without console errors at desktop and phone size, deep links restore state, the public
// welcome and About pages fetch only public files, the welcome opens the Atlas, every screen says "snapshot",
// and no screen shows Studio, forecasts or "live" wording.
// Usage: node tools/check-launch.mjs [baseUrl] [outDir]   (server: uv run --offline python tools/serve.py)
// PLAYWRIGHT_CORE may point at any playwright-core/index.mjs; CHROME at a Chrome or Chromium binary.
import fs from "node:fs/promises";
const pw = await import(process.env.PLAYWRIGHT_CORE || "playwright-core");
const base = (process.argv[2] || "http://127.0.0.1:5173").replace(/\/$/, "");
const out = process.argv[3] || "launch-checks";
await fs.mkdir(out, { recursive: true });
const chrome = process.env.CHROME || undefined; // default: the browser bundled with playwright-core
const browser = await pw.chromium.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const wait = ms => new Promise(r => setTimeout(r, ms));
const results = [], errors = [];
// Public without sign-in on the edge (everything else redirects to /login).
const PUBLIC = [/^\/$/, /^\/index\.html$/, /^\/welcome\.html$/, /^\/about\.html$/, /^\/og\.png$/, /^\/favicon\.svg$/, /^\/manifest\.webmanifest$/,
  /^\/ds\.css$/, /^\/nav\.js$/, /^\/data\/stats\.js$/, /^\/robots\.txt$/, /^\/(welcome|brand|fx|img|fonts)\//];
const BANNED = [/\bstudio\b/i, /\bforecast/i, /\bexpected\b/i, /\breal-time\b/i, /\bmonitoring now\b/i, /\blive (data|alerts?|feed|stream|monitoring)\b/i];

async function visit(path, { viewport = { width: 1440, height: 900 }, name, wait: ms = 3500, publicOnly = false, run } = {}) {
  const ctx = await browser.newContext({ viewport, isMobile: viewport.width < 600, hasTouch: viewport.width < 600 });
  const page = await ctx.newPage();
  const errs = [], offPublic = [];
  page.on("pageerror", e => { if (!/Transition was skipped/.test(String(e))) errs.push("pageerror " + String(e).slice(0, 300)); });
  page.on("console", m => { if (m.type() === "error") errs.push("console " + m.text().slice(0, 300)); });
  page.on("response", r => { if (r.status() >= 400) errs.push(`http ${r.status()} ${r.url()}`); });
  page.on("request", r => { const u = new URL(r.url()); if (publicOnly && u.origin === new URL(base).origin && !PUBLIC.some(p => p.test(u.pathname))) offPublic.push(u.pathname); });
  await page.goto(base + path, { waitUntil: "load" });
  await wait(ms);
  const info = await page.evaluate(BANNED_SRC => {
    const banned = BANNED_SRC.map(s => new RegExp(s.source, s.flags));
    const text = document.body.innerText;
    return {
      title: document.title, hscroll: document.documentElement.scrollWidth > innerWidth + 1,
      chip: !!document.querySelector(".sw-data") || /snapshot/i.test(text),
      studioNav: !!document.querySelector('[data-k="studio"], a[href*="studio.html"]'),
      banned: banned.filter(b => b.test(text.replace(/not live|no polls or forecasts|no polls, forecasts|not a forecast|votes, polls or forecasts/gi, ""))).map(b => b.source),
      author: !!document.querySelector('a[href*="linkedin.com/in/1vecera"]') && !!document.querySelector('a[href*="x.com/1vecera"]'),
    };
  }, BANNED.map(b => ({ source: b.source, flags: b.flags })));
  let extra = null;
  if (run) extra = await run(page).catch(e => ({ error: e.message }));
  await page.screenshot({ path: `${out}/${name}.png` });
  await ctx.close();
  const r = { name, path, viewport: `${viewport.width}x${viewport.height}`, ...info, offPublic: [...new Set(offPublic)], errs, extra };
  results.push(r);
  const bad = errs.length || info.hscroll || !info.chip || info.studioNav || info.banned.length || !info.author || r.offPublic.length || (extra && (extra.error || extra.ok === false));
  if (bad) errors.push(r);
  return r;
}

const phone = { width: 390, height: 844 };
for (const [path, name, pub] of [["/", "welcome", true], ["/welcome.html", "welcome-alias", true], ["/about.html", "about", true]]) {
  await visit(path, { name: name + "-1440", publicOnly: pub });
  await visit(path, { name: name + "-390", viewport: phone, publicOnly: pub });
}
await visit("/", { name: "welcome-click", wait: 2500, run: async p => { await p.mouse.click(1200, 450); await p.waitForURL(/atlas\.html/, { timeout: 5000 }); return { ok: /atlas\.html/.test(p.url()) }; } });
await visit("/", { name: "welcome-follow", wait: 2500, run: async p => {
  const [popup] = await Promise.all([p.waitForEvent("popup", { timeout: 5000 }), p.click('a[href*="linkedin.com/in/1vecera"]')]);
  await popup.close(); await wait(800); return { ok: !/atlas\.html/.test(p.url()) };
} });
const screens = ["atlas.html", "spotlight.html", "pulse.html", "radar.html", "data.html"];
for (const s of screens) { await visit("/" + s, { name: s.replace(".html", "") + "-1440", wait: 5000 }); await visit("/" + s, { name: s.replace(".html", "") + "-390", viewport: phone, wait: 5000 }); }
// deep links
await visit("/atlas.html?city=1", { name: "deep-atlas-city", wait: 5000, run: p => p.evaluate(() => ({ ok: __atlas.S.city === 1 })) });
await visit("/atlas.html?party=ods", { name: "deep-atlas-party", wait: 5000, run: p => p.evaluate(() => ({ ok: __atlas.S.party === "ods" && !!document.querySelector(".pon") })) });
await visit("/atlas.html?city=1&topic=0", { name: "deep-atlas-topic", wait: 5000, run: p => p.evaluate(() => ({ ok: __atlas.S.topic === 0 && !!document.querySelector("#topics .tchip.on[data-t='0']") })) });
await visit("/atlas.html", { name: "atlas-picker", wait: 4500, run: async p => {
  await p.click("#pFind"); await p.fill(".swk-in input", "ods"); await wait(300);
  const rows = await p.evaluate(() => document.querySelectorAll(".swk-r").length);
  await p.keyboard.press("Enter"); await wait(1200);
  return { ok: rows > 0 && /party=ods/.test(p.url()), rows };
} });
await visit("/spotlight.html?list=32", { name: "deep-spotlight-list", wait: 4500 });
await visit("/spotlight.html?cand=1614", { name: "deep-spotlight-cand", wait: 4500 });
await visit("/pulse.html?party=ods", { name: "deep-pulse-party", wait: 5000, run: p => p.evaluate(() => ({ ok: /mode=party/.test(location.search) && document.querySelectorAll("#dock .epill").length >= 2 })) });
await visit("/radar.html?city=2", { name: "deep-radar-city", wait: 4500, run: p => p.evaluate(() => ({ ok: document.querySelector("#cityb").textContent.includes(SW.cities[2].name) })) });
await visit("/radar.html?city=1&party=stan", { name: "deep-radar-party", wait: 4500, run: p => p.evaluate(() => ({ ok: /STAN|Starost/i.test(document.querySelector("#watch").textContent) })) });
// Atlas country view on phones: all ten city labels visible, inside the screen and not overlapping
for (const w of [360, 390, 430]) for (const q of ["", "?party=ods"]) {
  await visit("/atlas.html" + q, { name: `atlas-labels-${w}${q ? "-ods" : ""}`, viewport: { width: w, height: 844 }, wait: 4500, run: p => p.evaluate(() => {
    const W = innerWidth, bs = [...document.querySelectorAll("#marks .cm")], R = bs.filter(b => !b.classList.contains("nl")).map(b => b.querySelector("span").getBoundingClientRect());
    let ov = 0; R.forEach((a, i) => R.forEach((c, j) => { if (i < j && a.left < c.right && a.right > c.left && a.top < c.bottom && a.bottom > c.top) ov++ }));
    const clipped = R.filter(r => r.left < 0 || r.right > W).length;
    return { ok: bs.length === 10 && R.length === 10 && !ov && !clipped, visible: R.length, overlaps: ov, clipped };
  }) });
}
// Radar is purely observational: no reply drafts anywhere, including inside an opened item
await visit("/radar.html?city=1", { name: "radar-no-drafts", wait: 4500, run: async p => {
  const txt = async () => p.evaluate(() => document.body.innerText);
  const before = await txt(); const al = await p.$(".al"); if (al) { await al.click(); await wait(1200); }
  const after = await txt(); const els = await p.evaluate(() => document.querySelectorAll("#draft,#tone,#bEdit,#bCopy,.pa,.gloss").length);
  const re = /\bdrafts?\b|proposed (answer|reply|statement|post idea)|review draft/i;
  return { ok: !!al && !re.test(before) && !re.test(after) && !els, opened: !!al, draftElements: els };
} });
await browser.close();
console.log(JSON.stringify({ pass: !errors.length, checked: results.length, failures: errors }, null, 1));
process.exit(errors.length ? 1 : 0);
