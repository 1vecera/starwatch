// Unattended walkthrough of the demo path: sign-in → Atlas (country, city, topic lens, party) →
// Spotlight → Pulse → Radar (alert sheet) → Studio, at desktop and phone sizes.
// Usage: node tools/walkthrough.mjs [baseUrl] [outDir]   (server from ./run.sh must be running)
// PLAYWRIGHT_CORE may point at any playwright-core/index.mjs; CHROME at a Chrome binary.
const pw = await import(process.env.PLAYWRIGHT_CORE || "/home/vecera/code/daniel-ai-skills/tools/json-render-report/node_modules/playwright-core/index.mjs");
import fs from "node:fs/promises";
const base = (process.argv[2] || "http://127.0.0.1:5173").replace(/\/$/, "");
const out = process.argv[3] || "walkthrough-shots";
await fs.mkdir(out, { recursive: true });
const browser = await pw.chromium.launch({ executablePath: process.env.CHROME || "/usr/bin/google-chrome-stable", headless: true,
  args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errors = [], steps = [];
const wait = ms => new Promise(r => setTimeout(r, ms));
async function run(label, viewport) {
  const page = await browser.newPage({ viewport });
  page.on("pageerror", e => { if (!/Transition was skipped/.test(String(e))) errors.push(`${label} pageerror @${page.url().split("/").pop()}: ${(e.stack||String(e)).slice(0,400)}`); });
  page.on("console", m => { if (m.type() === "error" && !/fonts\.g/.test(m.text())) errors.push(`${label} console: ${m.text()}`); });
  const shot = async name => { await page.screenshot({ path: `${out}/${label}-${name}.png` }); steps.push(`${label}:${name}`); };
  const call = (expr) => page.evaluate(expr).catch(e => errors.push(`${label} ${expr}: ${e.message}`));
  await page.goto(`${base}/index.html`); await wait(1500); await shot("01-welcome");
  await page.goto(`${base}/atlas.html`); await wait(2500); await shot("02-atlas-country");
  await call("window.__atlas && window.__atlas.fitCity && window.__atlas.fitCity(0)"); await wait(2500); await shot("03-atlas-city");
  await call("window.__atlas && window.__atlas.setTopic && window.__atlas.setTopic(0)"); await wait(1500); await shot("04-atlas-topic");
  await call("window.__atlas && window.__atlas.setTopic && window.__atlas.setTopic(-1)");
  await call(`(()=>{const S=window.SW;let b=null;S.cands.forEach(c=>{if(c.city===0&&(!b||c.assets.length>b.assets.length))b=c});window.__demo=b&&b.i;window.__atlas&&window.__atlas.fitList&&window.__atlas.fitList(b?b.list:0)})()`);
  await wait(2500); await shot("05-atlas-party");
  await call("window.openSpotlight && window.openSpotlight({type:'cand',id:window.__demo||0})"); await wait(3500); await shot("06-spotlight");
  const sel = await page.evaluate(() => window.__spotSel ? `?${window.__spotSel[0]}=${window.__spotSel[1]}` : "").catch(() => "");
  const asset = await page.evaluate(() => { const b = SW.assets.findIndex(a => a.claims && a.claims.length > 1); return b; }).catch(() => -1);
  if (asset >= 0) { await page.goto(`${base}/spotlight.html?asset=${asset}`); await wait(2500); await call(`window.SPOT && SPOT.openDetail(${asset})`); await wait(1200); await shot("06b-spotlight-claims"); }
  await page.goto(`${base}/pulse.html${sel}`); await wait(2500); await shot("07-pulse");
  await page.goto(`${base}/radar.html${sel}`); await wait(2500); await shot("08-radar");
  const alert = await page.$("[data-alert], .alert, .al, .notif"); if (alert) { await alert.click().catch(() => {}); await wait(1800); await shot("09-radar-sheet"); }
  await page.goto(`${base}/studio.html${sel}`); await wait(3500); await shot("10-studio");
  await page.close();
}
await run("desktop", { width: 1920, height: 1080 });
await run("phone", { width: 390, height: 844 });
await browser.close();
console.log(JSON.stringify({ steps: steps.length, errors }, null, 1));
process.exit(errors.length ? 1 : 0);
