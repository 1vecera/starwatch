// Isolated checks for the map-first Star Atlas (design wave 3): full-bleed map (MapLibre over OpenFreeMap, local SVG
// fallback), ten city markers sized by the ranked metric, fly into a city, party islands with reach-sized mosaics
// (no circles), party focus with "Open in Spotlight", collapsible translucent panels, ranked candidates, topic lens,
// real video playback, no never-reported metrics and only platforms with data in the controls.
// Usage: node tools/check-atlas-c.mjs [baseUrl] [outDir]
const pw = await import(process.env.PLAYWRIGHT_CORE || "playwright-core");
import fs from "node:fs/promises";
const base = (process.argv[2] || "http://127.0.0.1:5173").replace(/\/$/, ""), out = process.argv[3] || "atlas-c-checks";
await fs.mkdir(out, { recursive: true });
const b = await pw.chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true, args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const p = await b.newPage({ viewport: { width: 1600, height: 950 } });
const errors = [], checks = {};
p.on("pageerror", e => { if (!/Transition was skipped/.test(String(e))) errors.push(String(e)); });
const wait = ms => new Promise(r => setTimeout(r, ms));
const shot = n => p.screenshot({ path: `${out}/${n}.png` });
const isles = () => p.waitForFunction(() => document.querySelectorAll(".isl:not(.gone)").length > 0, null, { timeout: 8000 }).then(() => wait(700));
await p.goto(`${base}/atlas.html`); await wait(3500); await shot("01-country");
checks.map_mode = await p.evaluate(() => __atlas.mapMode);
checks.full_bleed_map = await p.evaluate(() => { const r = document.querySelector("#mapwrap").getBoundingClientRect(); return r.left === 0 && r.top === 0 && r.width === innerWidth && r.height === innerHeight; });
checks.picker_visible_on_load = await p.evaluate(() => !document.querySelector("#picker").classList.contains("gone"));
checks.city_markers = await p.evaluate(() => { const m = [...document.querySelectorAll("#marks .cm")]; const r = m.map(x => parseFloat(x.style.getPropertyValue("--r"))); return { n: m.length, sized: Math.max(...r) > Math.min(...r) }; });
checks.no_region_hover = await p.evaluate(() => [...document.querySelectorAll("#svgmap path")].every(x => getComputedStyle(x).pointerEvents === "none") && !document.querySelector(".kraj:hover"));
checks.no_circles = await p.evaluate(() => !document.querySelector(".grp,#world"));
const brno = await p.evaluate(() => SW.cities.findIndex(c => c.name === "Brno"));
await p.click(`.crow[data-c="${brno}"]`); await isles(); await shot("02-city");
checks.picker_dismissed_after_city = await p.evaluate(() => document.querySelector("#picker").classList.contains("gone"));
checks.city_boundary = await p.evaluate(() => __atlas.mapMode === "maplibre" ? true : !!document.querySelector("#svgmap .muni.on"));
checks.islands = await p.evaluate(() => document.querySelectorAll(".isl").length);
checks.metric_stated = await p.evaluate(() => document.querySelector("#subtitle").textContent);
checks.islands_ordered = await p.evaluate(() => { const m = [...document.querySelectorAll(".isl")].map(x => +x.dataset.m); return m.every((v, i) => !i || v <= m[i - 1]); });
checks.islands_no_overlap = await p.evaluate(() => { const r = [...document.querySelectorAll(".isl")].map(x => x.getBoundingClientRect()); return r.every((a, i) => r.every((c, j) => i >= j || a.right <= c.left || c.right <= a.left || a.bottom <= c.top || c.bottom <= a.top)); });
checks.tile_size_classes = await p.evaluate(() => ({ s3: document.querySelectorAll(".isl .th.s3").length, s2: document.querySelectorAll(".isl .th.s2").length, s1: document.querySelectorAll(".isl .th.s1").length }));
checks.biggest_tile_first = await p.evaluate(() => [...document.querySelectorAll(".isl")].every(g => { const t = [...g.querySelectorAll(".th[data-a]")].map(x => SW.assets[+x.dataset.a].reach); return t.length < 2 || t[0] === Math.max(...t); }));
await p.click('#fRank button[data-k="eng"]'); await wait(700); await shot("03-rank-engagement");
checks.rank_by_engagement = await p.evaluate(() => ({ on: document.querySelector("#fRank .on").textContent, head: /likes \+ comments/.test(document.querySelector("#subtitle").textContent), isle: /likes \+ comments/.test(document.querySelector(".isl .ih small").textContent) }));
await p.click('#fRank button[data-k="reach"]'); await wait(400);
checks.media_toggle = await p.evaluate(() => { const bt = document.querySelector("#fBare"); return { hidden: !__atlas.S.bare, label: bt.hidden ? null : bt.textContent, tilesWithoutMedia: [...document.querySelectorAll(".isl .th[data-a]")].filter(x => { const a = SW.assets[+x.dataset.a]; return !a.img && !a.vsrc; }).length }; });
const topName = await p.evaluate(() => document.querySelector("#topc .rk.top b").textContent);
await p.click("#bigc"); await wait(600);
checks.biggest_candidate_one_click = await p.evaluate(n => ({ name: n, inspector: /Candidate #/.test(document.querySelector("#insp").textContent) && document.querySelector("#insp h2").textContent.includes(n), isBiggest: __atlas.S.cand === __atlas.biggestCand() }), topName);
await shot("04-biggest-candidate");
await p.evaluate(() => __atlas.selectCity(SW.cities.findIndex(c => c.name === "Brno"))); await wait(500);
const tilesBefore = await p.evaluate(() => document.querySelector(".isl").querySelectorAll(".th[data-a]").length);
await p.click(".isl .ih"); await wait(1100); await shot("05a-party-focus");
checks.list_inspector = await p.evaluate(() => /Party list/.test(document.querySelector("#insp").textContent));
checks.party_focus = await p.evaluate(b => { const on = document.querySelector(".isl.on"); return { focused: !!on, tilesBefore: b, tilesAfter: on ? on.querySelectorAll(".th[data-a]").length : 0, spotlight: !!(on && on.querySelector('[data-spot^="list:"]')), others_dimmed: document.querySelectorAll(".isl.dim").length, back: !document.querySelector("#zback").hidden }; }, tilesBefore);
checks.list_hierarchy_expands = await p.evaluate(() => document.querySelectorAll("#lists .cr2[data-k]").length);
const person = await p.$("#lists .cr2[data-k], #insp .plist button");
if (person) { await person.click(); await wait(500); }
checks.person_inspector = await p.evaluate(() => /Candidate #/.test(document.querySelector("#insp").textContent));
checks.breadcrumb = await p.evaluate(() => [...document.querySelectorAll("#crumbs button")].map(b => b.textContent));
await shot("05-person");
await p.evaluate(() => __atlas.selectCity(SW.cities.findIndex(c => c.name === "Brno"))); await wait(500);
const before = await p.evaluate(() => document.querySelectorAll(".isl .th[data-a]").length);
await p.click("#topics .tchip[data-t]:not([data-t='-1'])"); await wait(700); await shot("06-topic");
checks.topic_lens = await p.evaluate(b => { const t = __atlas.S.topic; const tiles = [...document.querySelectorAll(".isl:not(.gone) .th[data-a]")].map(x => SW.assets[+x.dataset.a]); return { topic: t >= 0 ? SW.TOP[t][0] : null, chipCount: document.querySelector("#topics .tchip.on em")?.textContent, allTilesOnTopic: tiles.every(a => a.topics.includes(t)), tilesBefore: b, tilesAfter: tiles.length, inspector: /Top posts on/.test(document.querySelector("#insp").textContent) }; }, before);
await p.evaluate(() => __atlas.setTopic(-1)); await wait(300);
const vi = await p.evaluate(() => SW.assets.findIndex(a => a.vsrc && SW.cities[a.city].name === "Brno"));
await p.evaluate(i => __atlas.fitAsset(i), vi); await wait(800); await shot("07-asset-video");
checks.source_link = await p.evaluate(() => { const a = [...document.querySelectorAll("#insp a")].find(x => /Open source/.test(x.textContent)); return a ? a.href : null; });
checks.video = await p.evaluate(async () => { const v = document.querySelector("#insp video"); if (!v) return { ok: false };
  v.muted = true; await new Promise(r => v.readyState >= 1 ? r() : v.addEventListener("loadedmetadata", r, { once: true }));
  await v.play(); await new Promise(r => setTimeout(r, 1500)); const t = v.currentTime; v.pause();
  return { ok: t > 0.5, duration: v.duration, currentTime: t, controls: v.controls, playsinline: v.playsInline, preload: v.preload, poster: !!v.poster }; });
checks.no_unreported_shares = await p.evaluate(() => { const a = SW.assets[__atlas.S.asset]; const shown = /Shares/.test(document.querySelector("#insp").textContent); return a.na.shares ? !shown : true; });
checks.playable_videos_total = await p.evaluate(() => SW.assets.filter(a => a.vsrc).length);
await p.evaluate(() => __atlas.selectCity(SW.cities.findIndex(c => c.name === "Brno"))); await wait(500);
checks.hover_preview = await p.evaluate(() => { const t = [...document.querySelectorAll(".isl .th[data-a]")].find(x => SW.assets[+x.dataset.a].vsrc); if (!t) return null; t.dispatchEvent(new MouseEvent("mouseover", { bubbles: true })); const v = t.querySelector("video.hp"); return v ? { muted: v.muted, loop: v.loop } : (matchMedia("(hover:hover)").matches ? false : "no-hover device"); });
checks.only_platforms_with_data = await p.evaluate(() => { const chips = [...document.querySelectorAll("#fPlat .pchip[data-p]:not([data-p=all])")]; return { chips: chips.map(c => c.textContent.trim()), allHaveData: chips.every(c => SW.platformCoverage.find(x => x.platform === SW.PLAT[+c.dataset.p].k).verified_assets > 0), noNodata: !document.querySelector(".nodata"), noNotObserved: !/not observed/i.test(document.body.innerText) }; });
if (checks.only_platforms_with_data.chips.length) { await p.click('#fPlat .pchip[data-p]:not([data-p=all])'); await wait(400); }
checks.platform_selected = await p.evaluate(() => [...document.querySelectorAll("#fPlat .pchip.on")].map(b => b.textContent.trim()));
await shot("08-platform");
await p.click("#fPlat .pchip[data-p=all]").catch(() => {});
await p.click("#sideX"); await p.click("#inspX"); await wait(600); await shot("09-panels-hidden");
checks.panels_collapse = await p.evaluate(() => ({ side: document.querySelector("#side").classList.contains("shut"), insp: document.querySelector("#insp").classList.contains("shut"), reopen: !document.querySelector("#sideOpen").hidden && !document.querySelector("#inspOpen").hidden }));
await p.click("#sideOpen"); await p.click("#inspOpen"); await wait(600);
checks.panels_reopen = await p.evaluate(() => !document.querySelector("#side").classList.contains("shut") && !document.querySelector("#insp").classList.contains("shut"));
await p.click(".isl .ih"); await wait(500);
await p.keyboard.press("Escape"); await wait(500);
checks.unfocus_on_esc = await p.evaluate(() => !document.querySelector(".isl.on") && __atlas.S.list < 0);
await p.click("#home"); await wait(2200); await shot("10-back-to-country");
checks.change_location_reopens = await p.evaluate(() => !document.querySelector("#picker").classList.contains("gone") && !document.querySelector("#marks").classList.contains("off") && !document.querySelector(".isl:not(.gone)"));
checks.url_params = await (async () => { await p.goto(`${base}/atlas.html?city=${brno}&list=` + await p.evaluate(b => SW.cities[b].lists.find(i => SW.lists[i].observed), brno)); await wait(3500); return p.evaluate(() => ({ list: __atlas.S.list, focused: !!document.querySelector(".isl.on") })); })();
await shot("11-url-list");
const m = await b.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
m.on("pageerror", e => errors.push("mobile: " + e));
await m.goto(`${base}/atlas.html?city=${brno}`); await wait(3500); await m.screenshot({ path: `${out}/12-mobile-city.png` });
checks.mobile = await m.evaluate(() => ({ noHScroll: document.documentElement.scrollWidth <= innerWidth, islands: document.querySelectorAll(".isl").length, sideShut: document.querySelector("#side").classList.contains("shut") }));
await m.click(".isl .th[data-a]"); await wait(800); await m.screenshot({ path: `${out}/13-mobile-asset.png` });
checks.mobile_inspector_opens = await m.evaluate(() => !document.querySelector("#insp").classList.contains("shut"));
await b.close();
const pass = checks.full_bleed_map && checks.picker_visible_on_load && checks.city_markers.n === 10 && checks.city_markers.sized && checks.no_region_hover && checks.no_circles
  && checks.picker_dismissed_after_city && checks.city_boundary && checks.islands > 0 && checks.islands_ordered && checks.islands_no_overlap
  && checks.tile_size_classes.s2 + checks.tile_size_classes.s3 > 0 && checks.biggest_tile_first
  && checks.rank_by_engagement.head && checks.rank_by_engagement.isle && checks.media_toggle.hidden && checks.media_toggle.tilesWithoutMedia === 0
  && checks.biggest_candidate_one_click.inspector && checks.biggest_candidate_one_click.isBiggest && checks.list_inspector && checks.person_inspector
  && checks.party_focus.focused && checks.party_focus.tilesAfter > checks.party_focus.tilesBefore && checks.party_focus.spotlight && checks.party_focus.back
  && checks.topic_lens.topic && checks.topic_lens.allTilesOnTopic && checks.topic_lens.inspector
  && checks.source_link && checks.video.ok && checks.no_unreported_shares && checks.only_platforms_with_data.allHaveData && checks.only_platforms_with_data.noNodata && checks.only_platforms_with_data.noNotObserved
  && checks.panels_collapse.side && checks.panels_collapse.insp && checks.panels_collapse.reopen && checks.panels_reopen && checks.unfocus_on_esc && checks.change_location_reopens
  && checks.url_params.focused && checks.mobile.noHScroll && checks.mobile.islands > 0 && checks.mobile_inspector_opens && !errors.length;
console.log(JSON.stringify({ pass, checks, errors }, null, 1));
process.exit(pass ? 0 : 1);
