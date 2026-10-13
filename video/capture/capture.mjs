// Capture the live Starwatch app as PNG frame sequences for the showreel.
//
//   CHROME=/path/to/chrome node capture/capture.mjs [take ...]   (default: every take)
//
// Nothing is redrawn: every frame is a screenshot of https://starwatch.danielvecera.com in headless
// Chromium. Motion comes from the camera, never from screen recording: the script sets the map camera
// or the scroll position for each frame, waits until the map is idle and visible images have decoded,
// then takes the screenshot. The app runs with reduced motion, so each frame shows a settled state.
// Output: video/tmp/captures/<take>/NNNN.png (ignored by Git) plus take.json with the URL, the per-frame
// camera or scroll value and the boxes of the elements the reel annotates.

import { mkdir, rm, writeFile } from "node:fs/promises";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const BASE = "https://starwatch.danielvecera.com/";
const ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const OUT = join(ROOT, "tmp/captures");
const DESKTOP = { viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1.5 };
const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true };

const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
const pad = (n) => String(n).padStart(4, "0");

/** Wait until every image intersecting the viewport (or a scroller) has decoded. */
async function settleImages(page, timeout = 4000) {
  await page
    .waitForFunction(
      () =>
        [...document.images].every((img) => {
          const r = img.getBoundingClientRect();
          const visible = r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth && r.width > 0;
          return !visible || (img.complete && img.naturalWidth > 0);
        }),
      null,
      { timeout, polling: 100 },
    )
    .catch(() => {});
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
}

/** Boxes (CSS px) of elements the reel points at, keyed by name. */
const boxes = (page, selectors) =>
  page.evaluate((selectors) => {
    const out = {};
    for (const [name, selector] of Object.entries(selectors)) {
      const el = typeof selector === "string" ? document.querySelector(selector) : null;
      if (!el) continue;
      const r = el.getBoundingClientRect();
      out[name] = { x: r.x, y: r.y, w: r.width, h: r.height };
    }
    return out;
  }, selectors);

/** Record a page-scroll take: frames ease from `from` to `to` over `count` frames. */
async function scrollTake(page, dir, { from, to, count, scroller = null, hold = 0 }) {
  const values = [];
  for (let i = 0; i < count + hold; i++) {
    const t = Math.min(1, i / Math.max(1, count - 1));
    const y = Math.round((from + (to - from) * ease(t)) * 2) / 2;
    await page.evaluate(
      ({ y, scroller }) => {
        const el = scroller ? document.querySelector(scroller) : document.scrollingElement;
        el.scrollTop = y;
      },
      { y, scroller },
    );
    await settleImages(page);
    await page.screenshot({ path: join(dir, `${pad(i)}.png`) });
    values.push(y);
  }
  return values;
}

async function open(browser, options, path) {
  const context = await browser.newContext({ ...options, reducedMotion: "reduce", colorScheme: "light", locale: "en-GB" });
  const page = await context.newPage();
  await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 90000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1500);
  await settleImages(page, 8000);
  return { context, page };
}

const TAKES = {
  // Czechia overview, a camera flight into Prague, the city with its party islands, then a slow drift.
  async atlas(browser, dir) {
    const { context, page } = await open(browser, DESKTOP, "atlas.html");
    await page.waitForFunction(() => window.map && map.loaded(), null, { timeout: 30000 });
    // Settled = no camera movement and every tile in view loaded; then two frames so it is painted.
    const idle = () =>
      page.evaluate(
        () =>
          new Promise((done) => {
            const started = performance.now();
            const check = () => {
              if ((!map.isMoving() && map.areTilesLoaded() && map.loaded()) || performance.now() - started > 5000) {
                requestAnimationFrame(() => requestAnimationFrame(() => done()));
              } else setTimeout(check, 25);
            };
            requestAnimationFrame(check);
          }),
      );
    const c0 = await page.evaluate(() => ({ lng: map.getCenter().lng, lat: map.getCenter().lat, zoom: map.getZoom() }));
    // Where selecting Prague puts the camera (measured once in the same viewport, reduced motion).
    const c1 = await page.evaluate(() => {
      const before = { center: map.getCenter(), zoom: map.getZoom() };
      selectCity(0);
      const after = { lng: map.getCenter().lng, lat: map.getCenter().lat, zoom: map.getZoom() };
      S.city = -1;
      update();
      map.jumpTo(before);
      return after;
    });
    await idle();
    const overview = await boxes(page, { praha: '#marks .cm[data-c="0"]', side: "#side", insp: "#insp", legend: "#legend" });
    const FLIGHT = 110;
    const DRIFT = 170;
    const frames = [];
    // Zoom into a point: the target moves on a straight screen line while the zoom eases exponentially.
    const merc = (lng, lat) => [(lng + 180) / 360, (1 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / Math.PI) / 2];
    const unmerc = ([x, y]) => [x * 360 - 180, (Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180) / Math.PI];
    const p0 = merc(c0.lng, c0.lat);
    const p1 = merc(c1.lng, c1.lat);
    const k0 = 2 ** c0.zoom;
    for (let i = 0; i < FLIGHT; i++) {
      const u = ease(i / (FLIGHT - 1));
      const zoom = c0.zoom + (c1.zoom - c0.zoom) * u;
      const k = 2 ** zoom;
      const d = [(p1[0] - p0[0]) * k0 * (1 - u), (p1[1] - p0[1]) * k0 * (1 - u)];
      const [lng, lat] = unmerc([p1[0] - d[0] / k, p1[1] - d[1] / k]);
      await page.evaluate(({ lng, lat, zoom }) => map.jumpTo({ center: [lng, lat], zoom }), { lng, lat, zoom });
      await idle();
      await page.screenshot({ path: join(dir, `${pad(i)}.png`) });
      frames.push({ lng, lat, zoom });
    }
    await page.evaluate(() => selectCity(0));
    await page.waitForTimeout(1200);
    await idle();
    await settleImages(page, 8000);
    const city = await boxes(page, { side: "#side", insp: "#insp", legend: "#legend" });
    const end = await page.evaluate(() => ({ lng: map.getCenter().lng, lat: map.getCenter().lat, zoom: map.getZoom() }));
    for (let i = 0; i < DRIFT; i++) {
      const t = i / (DRIFT - 1);
      const zoom = end.zoom + 0.16 * t;
      const lng = end.lng + 0.012 * t;
      await page.evaluate(({ lng, lat, zoom }) => map.jumpTo({ center: [lng, lat], zoom }), { lng, lat: end.lat, zoom });
      await idle();
      await settleImages(page, 3000);
      await page.screenshot({ path: join(dir, `${pad(FLIGHT + i)}.png`) });
      frames.push({ lng, lat: end.lat, zoom, city: 0 });
    }
    await context.close();
    return { url: BASE + "atlas.html", flight: FLIGHT, drift: DRIFT, c0, c1, frames, boxes: { overview, city } };
  },

  // Petr Hlaváček's Spotlight: profile and 2026 result, then down to the grid of his best posts.
  async spotlight(browser, dir) {
    const { context, page } = await open(browser, DESKTOP, "spotlight.html");
    const top = await boxes(page, { name: "h1", best: "h2" });
    const values = await scrollTake(page, dir, { from: 0, to: 700, count: 150 });
    await context.close();
    return { url: BASE + "spotlight.html", scroll: values, boxes: { top } };
  },

  // Pulse: the head-to-head chart, then down to the 2022 and 2026 results next to attention.
  async pulse(browser, dir) {
    const { context, page } = await open(browser, DESKTOP, "pulse.html");
    const top = await boxes(page, { title: "h1" });
    const values = await scrollTake(page, dir, { from: 0, to: 1170, count: 150 });
    await context.close();
    return { url: BASE + "pulse.html", scroll: values, boxes: { top } };
  },

  // Radar: the watchlist and the snapshot replay feed scrolling.
  async radar(browser, dir) {
    const { context, page } = await open(browser, DESKTOP, "radar.html");
    const top = await boxes(page, { feed: "#scroll", watch: "aside.side.l" });
    const values = await scrollTake(page, dir, { from: 0, to: 760, count: 150, scroller: "#scroll" });
    await context.close();
    return { url: BASE + "radar.html", scroll: values, boxes: { top } };
  },

  // By the numbers: the snapshot totals, the official 2026 results, then every list in Prague.
  async results(browser, dir) {
    const { context, page } = await open(browser, DESKTOP, "data.html");
    const values = await scrollTake(page, dir, { from: 0, to: 2150, count: 210 });
    await context.close();
    return { url: BASE + "data.html", scroll: values };
  },

  // Phone: the welcome screen and the Atlas at 390 px.
  async phone(browser, dir) {
    const out = {};
    for (const [name, path] of [["welcome", ""], ["atlas", "atlas.html"]]) {
      const { context, page } = await open(browser, PHONE, path);
      if (name === "atlas") await page.waitForFunction(() => window.map && map.loaded(), null, { timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(2500);
      await settleImages(page, 8000);
      await page.screenshot({ path: join(dir, `${name}.png`) });
      out[name] = BASE + path;
      await context.close();
    }
    return { urls: out };
  },

  // Desktop welcome: the candidate wall and the Starwatch card.
  async welcome(browser, dir) {
    const { context, page } = await open(browser, DESKTOP, "");
    await page.waitForTimeout(2500);
    await settleImages(page, 10000);
    await page.screenshot({ path: join(dir, "0000.png") });
    const card = await boxes(page, { h1: "h1" });
    await context.close();
    return { url: BASE, boxes: { card } };
  },
};

const wanted = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(TAKES);
const browser = await chromium.launch({
  executablePath: process.env.CHROME,
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--hide-scrollbars"],
});
try {
  for (const name of wanted) {
    const dir = join(OUT, name);
    await rm(dir, { recursive: true, force: true });
    await mkdir(dir, { recursive: true });
    const started = Date.now();
    const meta = await TAKES[name](browser, dir);
    await writeFile(
      join(dir, "take.json"),
      JSON.stringify({ take: name, captured: new Date().toISOString(), ...DESKTOP, ...meta }, null, 2),
    );
    console.log(`${name}: ${((Date.now() - started) / 1000).toFixed(0)} s`);
  }
} finally {
  await browser.close();
}
