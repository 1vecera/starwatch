// S3 · The chart. The subject's public footprint set as a printed star chart: the subject in its
// cartouche, one band per account, every post a star at its publication date (size = likes at
// collection, stated in the key, never a score), inset plates with the post images on leader lines,
// claims as constellation lines between the posts they cite, and beside it the night log of posts in
// arrival order. Built only from run events, live over SSE or replayed (see stream.js). Collected
// text goes in through textContent, never innerHTML.
import { modeFor, open, sourceFromLocation, sourceQuery } from "./stream.js";
import {
  PLATFORM_CODE, PLATFORM_NAME, PRESET_NAMES, STATUS_TEXT, el, formatClock, formatDay, formatDayTime, formatElapsed,
  formatInt, plate, plateWidth, platformMark, reducedMotion, renderStamp, svg, tick, wireScreenLinks,
} from "./atlas.js";

const $ = (id) => document.getElementById(id);
const DAY = 86400000;
const COL = 344; // the account column, left of the time area
const BUCKET = 66; // "before" bucket at the left edge of the time area
const MAX_PLATES = 8;
const PLATES_PER_ROW = 2;
const MAX_CLAIMS = 6;
const MAX_LOG = 12;
const KIND_WORD = { fact: "Fact", inference: "Inference", open_question: "Open question", missing_source: "Missing source" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

let source = sourceFromLocation();
let stream = null;
let S = null;
let clock = null;
let frame = 0;
let frameAnimate = false;

// --- state --------------------------------------------------------------------------------------

function begin(data) {
  const plan = data.plan || [];
  const social = plan.filter((s) => s.group === "collect" && s.platform && s.platform !== "website");
  S = {
    data,
    mode: modeFor(source, data),
    startedAt: Date.parse(data.started_at),
    finishedAt: null,
    rows: social.map((step, index) => ({
      index, platform: step.platform, step: step.id, actor: step.actor, status: step.status, note: "", count: 0,
    })),
    rowMap: new Map(),
    stepRow: new Map(),
    websiteStep: plan.find((s) => s.group === "collect" && s.platform === "website")?.id ?? null,
    websiteStatus: "queued",
    items: new Map(),
    perPlatform: new Map(),
    pages: [],
    accounts: [],
    rejected: [],
    coverage: new Map(),
    claims: [],
    claimSource: null,
    kept: null,
    dropped: null,
    extractStatus: "queued",
    lastArrival: null,
    fresh: new Set(),
    nodes: { stars: new Map(), plates: new Map(), leaders: new Map(), paths: new Map(), labels: new Map() },
    focus: null,
  };
  for (const row of S.rows) {
    S.rowMap.set(row.platform, row);
    S.stepRow.set(row.step, row);
  }
  document.body.dataset.mode = S.mode;
  $("empty").hidden = true;
  $("page").hidden = false;
  $("subject-name").textContent = data.subject;
  $("subject-anchor").textContent = data.anchor;
  const goal = $("subject-goal");
  goal.replaceChildren(el("span", "caps", "goal"), ` ${PRESET_NAMES[data.goal.preset] || data.goal.preset}`);
  if (data.goal.text) goal.append(` · ${data.goal.text}`);
  for (const layer of ["layer-grid", "layer-leaders", "layer-claims", "layer-stars"]) $(layer).replaceChildren();
  for (const layer of ["layer-axis", "layer-rows", "layer-plates", "layer-claim-labels", "log-list", "claims-list"]) {
    $(layer).replaceChildren();
  }
  renderMasthead();
  clearInterval(clock);
  clock = setInterval(renderMasthead, 1000);
  schedule(false);
}

function hashUnit(text, salt = 0) {
  let h = 2166136261 ^ salt;
  for (let i = 0; i < text.length; i += 1) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return ((h >>> 0) % 10000) / 10000;
}

function addItem(event, animate) {
  const item = event.item;
  const n = (S.perPlatform.get(item.platform) || 0) + 1;
  S.perPlatform.set(item.platform, n);
  const t = item.published_at ? Date.parse(item.published_at) : null;
  const rec = {
    item,
    platform: item.platform,
    number: n,
    arrivedAt: Date.parse(event.ts),
    t: Number.isFinite(t) ? t : null,
    likes: typeof item.metrics?.likes === "number" ? item.metrics.likes : null,
    hasImage: Boolean((item.thumb && item.media_kind === "image") || (S.mode === "sample" && item.width && item.height)),
  };
  S.items.set(item.id, rec);
  S.lastArrival = rec.arrivedAt;
  if (item.platform === "website") S.pages.push(rec);
  if (animate) S.fresh.add(item.id);
  prependLog(rec, animate);
}

// --- geometry -----------------------------------------------------------------------------------

function monthStart(ms) {
  const d = new Date(ms);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1);
}

function geometry() {
  const chart = $("chart");
  const W = chart.clientWidth;
  const H = chart.clientHeight;
  const x0 = COL + 16;
  const x1 = W - 6;
  const xs = x0 + BUCKET;
  const plateH = Math.round(Math.min(132, Math.max(96, H * 0.13)));
  const plateTop = 30;
  const galleryBottom = plateTop + plateH;
  const axisY = galleryBottom + 40;
  const rowsTop = axisY + 10;
  const band = 268;
  const rowsBottom = Math.max(rowsTop + 200, H - band);
  const rowH = (rowsBottom - rowsTop) / Math.max(1, S.rows.length);
  const t1 = S.startedAt;
  const t0 = monthStart(t1 - 92 * DAY);
  const span = Math.max(DAY, t1 - t0);
  const tx = (t) => xs + 6 + ((Math.min(t, t1) - t0) / span) * (x1 - 14 - xs);
  return { W, H, x0, x1, xs, plateH, plateTop, galleryBottom, axisY, rowsTop, rowsBottom, rowH, t0, t1, tx, bandTop: rowsBottom + 34 };
}

function rowCenter(row, G) {
  return G.rowsTop + G.rowH * (row.index + 0.5);
}

function starPoint(rec, G) {
  const row = S.rowMap.get(rec.platform);
  if (!row || rec.t === null) return null;
  const y = rowCenter(row, G) + (hashUnit(rec.item.id) * 2 - 1) * G.rowH * 0.3;
  if (rec.t < G.t0) {
    return { x: G.x0 + 12 + hashUnit(rec.item.id, 7) * (BUCKET - 24), y, before: true };
  }
  return { x: G.tx(rec.t), y };
}

// Website pages are the anchor's own documents: they sit in the cartouche, not on the time axis.
function pagePoint(rec) {
  const glyph = document.querySelector(`[data-page="${CSS.escape(rec.item.id)}"]`);
  if (!glyph) return null;
  const box = glyph.getBoundingClientRect();
  const chart = $("chart").getBoundingClientRect();
  return { x: box.left - chart.left + box.width / 2, y: box.top - chart.top + box.height / 2 };
}

function pointFor(rec, G) {
  return rec.platform === "website" ? pagePoint(rec) : starPoint(rec, G);
}

const radius = (likes) => (likes === null ? 3.6 : Math.min(12.5, 2.4 + 2.15 * Math.log10(1 + likes)));

// --- drawing ------------------------------------------------------------------------------------

function schedule(animate) {
  frameAnimate = frameAnimate || animate;
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    const animateNow = frameAnimate && !reducedMotion();
    frameAnimate = false;
    draw(animateNow);
  });
}

function draw(animate) {
  if (!S) return;
  const G = geometry();
  const sky = $("sky");
  sky.setAttribute("viewBox", `0 0 ${G.W} ${G.H}`);
  sky.setAttribute("width", G.W);
  sky.setAttribute("height", G.H);
  drawGrid(G);
  drawRows(G);
  drawPages();
  drawStars(G, animate);
  drawPlates(G, animate);
  drawClaims(G, animate);
  drawNamesakes(G);
  drawKey(G);
  const claims = $("claims");
  claims.style.transform = `translate(${G.x0}px, ${G.bandTop}px)`;
  claims.style.width = `${G.x1 - G.x0}px`;
  drawTally(animate);
  S.fresh.clear();
}

function drawGrid(G) {
  const grid = $("layer-grid");
  const axis = $("layer-axis");
  grid.replaceChildren();
  axis.replaceChildren();
  const h = G.rowsBottom - G.rowsTop;

  // Rows: hairline separators, hatched where a platform is missing.
  S.rows.forEach((row, i) => {
    const y = G.rowsTop + G.rowH * i;
    if (i > 0) grid.append(svg("line", { x1: G.x0, y1: y, x2: G.x1, y2: y, class: "grid-row" }));
    if (rowGap(row)) {
      grid.append(svg("rect", { x: G.x0 + 2, y: y + 2, width: G.x1 - G.x0 - 4, height: G.rowH - 4, class: "gap-hatch", fill: "url(#hatch)" }));
    }
  });

  // Months: engraved meridians with their names above the neat line.
  for (let m = G.t0; m <= G.t1; m = Date.UTC(new Date(m).getUTCFullYear(), new Date(m).getUTCMonth() + 1, 1)) {
    const x = G.tx(m);
    grid.append(svg("line", { x1: x, y1: G.rowsTop, x2: x, y2: G.rowsBottom, class: "grid-month" }));
    grid.append(svg("line", { x1: x, y1: G.rowsTop - 9, x2: x, y2: G.rowsTop, class: "tick-major" }));
    const d = new Date(m);
    const label = el("span", "axis-month", `${MONTHS[d.getUTCMonth()]}${d.getUTCMonth() === 0 || m === G.t0 ? ` ${d.getUTCFullYear()}` : ""}`);
    label.style.transform = `translate(${x + 6}px, ${G.axisY - 26}px)`;
    axis.append(label);
  }
  // Week ticks along the top and bottom neat lines.
  for (let w = G.t0; w <= G.t1; w += 7 * DAY) {
    const x = G.tx(w);
    grid.append(svg("line", { x1: x, y1: G.rowsTop, x2: x, y2: G.rowsTop + 5, class: "tick-minor" }));
    grid.append(svg("line", { x1: x, y1: G.rowsBottom - 5, x2: x, y2: G.rowsBottom, class: "tick-minor" }));
  }
  // The "before" bucket and the run's own date at the right edge.
  grid.append(svg("line", { x1: G.xs, y1: G.rowsTop, x2: G.xs, y2: G.rowsBottom, class: "grid-bucket" }));
  const before = el("span", "axis-before");
  before.append(el("span", "", "before"), el("span", "", formatDay(new Date(G.t0).toISOString())));
  before.style.transform = `translate(${G.x0 + 6}px, ${G.rowsBottom + 8}px)`;
  axis.append(before);
  const now = el("span", "axis-now");
  now.append(el("span", "caps", "run"), ` ${formatDayTime(S.startedAt)}`);
  now.style.transform = `translate(${G.x1}px, ${G.axisY - 26}px) translateX(-100%)`;
  axis.append(now);
  const span = el("span", "axis-span", `posts by publication date · ${formatDay(new Date(G.t0).toISOString())} to ${formatDay(new Date(G.t1).toISOString())}`);
  span.style.transform = `translate(${G.x1}px, ${G.rowsBottom + 8}px) translateX(-100%)`;
  axis.append(span);

  // Neat line: a strong frame and a hairline inside it, as printed charts have.
  grid.append(svg("rect", { x: G.x0, y: G.rowsTop, width: G.x1 - G.x0, height: h, class: "neat-outer" }));
  grid.append(svg("rect", { x: G.x0 + 4, y: G.rowsTop + 4, width: G.x1 - G.x0 - 8, height: h - 8, class: "neat-inner" }));

  // Subject → accounts: a spine from the cartouche, one branch per account band.
  const cartouche = $("cartouche");
  const top = cartouche.offsetTop + cartouche.offsetHeight + 10;
  const last = S.rows.length ? rowCenter(S.rows[S.rows.length - 1], G) : top;
  if (S.rows.length) grid.append(svg("path", { d: `M 14 ${top} V ${last}`, class: "spine" }));
  grid.append(svg("circle", { cx: 14, cy: top, r: 4, class: "spine-root" }));
  for (const row of S.rows) {
    const y = rowCenter(row, G);
    grid.append(svg("path", { d: `M 14 ${y} H 30`, class: rowGap(row) ? "branch branch-gap" : "branch" }));
    // Account → posts: the band's own baseline runs out from the label to the neat line.
    grid.append(svg("line", { x1: COL - 8, y1: y, x2: G.x0, y2: y, class: "band-lead" }));
  }
}

function rowAccount(row) {
  return S.accounts.filter((a) => a.platform === row.platform);
}

function rowGap(row) {
  const cov = S.coverage.get(row.platform);
  const count = S.perPlatform.get(row.platform) || 0;
  if (count > 0) return null;
  if (cov && cov.status !== "collected") return [cov.status.replace("_", " "), cov.note].filter(Boolean).join(" · ");
  if (row.status === "failed") return ["unavailable", row.note].filter(Boolean).join(" · ");
  if (row.status === "skipped") return ["skipped", row.note].filter(Boolean).join(" · ");
  if (row.status === "not_implemented") return "collector not built yet";
  if (row.status === "done") return "nothing found";
  return null;
}

function drawRows(G) {
  const layer = $("layer-rows");
  layer.replaceChildren();
  for (const row of S.rows) {
    const y = rowCenter(row, G);
    const label = el("div", "row-label");
    label.style.transform = `translate(36px, ${y}px) translateY(-50%)`;
    label.style.width = `${COL - 52}px`;
    const accounts = rowAccount(row);
    const first = accounts[0];
    const line = el("p", "row-handle");
    line.append(platformMark(row.platform));
    line.append(el("span", "row-handle-text", first ? first.handle || first.url.replace(/^https?:\/\/(www\.)?/, "") : PLATFORM_NAME[row.platform]));
    if (accounts.length > 1) line.append(el("span", "row-more", `+${accounts.length - 1}`));
    const count = S.perPlatform.get(row.platform) || 0;
    const sub = el("p", "row-sub");
    const gap = rowGap(row);
    if (gap) {
      sub.append(el("span", "row-state row-state-missing", "Missing"));
    } else if (first) {
      sub.append(el("span", `row-state row-state-${first.status}`, first.status));
    } else {
      sub.append(el("span", "row-state", STATUS_TEXT[row.status] || row.status));
    }
    if (!gap) sub.append(el("span", "row-count", `${formatInt(count)} ${count === 1 ? "post" : "posts"}`));
    const undated = [...S.items.values()].filter((r) => r.platform === row.platform && r.t === null).length;
    if (undated) sub.append(el("span", "row-count", `${undated} undated`));
    label.append(line, sub);
    layer.append(label);

    if (gap) {
      const note = el("p", "gap-label");
      note.append(el("b", "", "Missing"), el("span", "", `${PLATFORM_NAME[row.platform]} · ${gap}`));
      note.style.transform = `translate(${G.xs + 24}px, ${y}px) translateY(-50%)`;
      layer.append(note);
    } else if (!count && row.status === "running") {
      const wait = el("p", "row-waiting", "waiting for the first dataset items");
      wait.style.transform = `translate(${G.xs + 24}px, ${y}px) translateY(-50%)`;
      layer.append(wait);
    }
  }
}

function drawPages() {
  const holder = $("cartouche-pages") || (() => {
    const p = el("p", "cartouche-pages");
    p.id = "cartouche-pages";
    $("cartouche").append(p);
    return p;
  })();
  if (!S.pages.length) {
    holder.replaceChildren();
    if (S.websiteStatus === "running") holder.append(el("span", "caps", "reading the anchor site"));
    return;
  }
  if (holder.childElementCount === S.pages.length + 1) return;
  const glyphs = S.pages.map((rec) => {
    const g = el("span", "page-glyph");
    g.dataset.page = rec.item.id;
    g.title = rec.item.text;
    return g;
  });
  holder.replaceChildren(el("span", "caps", `${S.pages.length} ${S.pages.length === 1 ? "page" : "pages"} from the anchor`), ...glyphs);
}

function drawStars(G, animate) {
  const layer = $("layer-stars");
  const cited = citedIds();
  const keep = new Set();
  let stagger = 0;
  for (const rec of S.items.values()) {
    const p = starPoint(rec, G);
    if (!p) continue;
    const id = rec.item.id;
    keep.add(id);
    let node = S.nodes.stars.get(id);
    const r = radius(rec.likes);
    if (!node) {
      node = svg("g", { class: "star" });
      const core = svg("circle", { r: r.toFixed(2), class: rec.likes === null ? "star-core star-hollow" : "star-core" });
      const ring = svg("circle", { r: (r + 4.5).toFixed(2), class: "star-ring" });
      const title = svg("title");
      title.textContent = `${PLATFORM_CODE[rec.platform]} ${rec.number} · ${formatDay(rec.item.published_at)}${rec.likes !== null ? ` · ${formatInt(rec.likes)} likes at collection` : ""}`;
      node.append(ring, core, title);
      if (animate && S.fresh.has(id)) {
        const delay = `${Math.min(stagger, 8) * 70}ms`;
        stagger += 1;
        node.classList.add("igniting");
        node.style.setProperty("--delay", delay);
        const flash = svg("circle", { r: (r + 2).toFixed(2), class: "star-flash" });
        flash.style.setProperty("--delay", delay);
        node.append(flash);
        flash.addEventListener("animationend", () => flash.remove(), { once: true });
      }
      layer.append(node);
      S.nodes.stars.set(id, node);
    }
    node.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`);
    node.classList.toggle("cited", cited.has(id));
    node.classList.toggle("before", Boolean(p.before));
    node.classList.toggle("dim", Boolean(S.focus) && !focusIds().has(id));
  }
  for (const [id, node] of S.nodes.stars) {
    if (!keep.has(id)) {
      node.remove();
      S.nodes.stars.delete(id);
    }
  }
}

function citedIds() {
  const ids = new Set();
  for (const claim of S.claims) for (const id of claim.item_ids) ids.add(id);
  return ids;
}

function focusIds() {
  const claim = S.claims.find((c) => c.id === S.focus);
  return new Set(claim ? claim.item_ids : []);
}

// Plates: the posts the claims cite most, then each account's newest, capped and packed along the
// top margin in date order so every leader line runs almost straight down to its star.
function choosePlates(G) {
  const counts = new Map();
  for (const claim of S.claims) for (const id of claim.item_ids) counts.set(id, (counts.get(id) || 0) + 1);
  const candidates = [...S.items.values()].filter((r) => r.hasImage && S.rowMap.has(r.platform) && r.t !== null);
  const chosen = [];
  const take = (rec) => {
    if (chosen.includes(rec) || chosen.length >= MAX_PLATES) return;
    chosen.push(rec);
  };
  candidates
    .filter((r) => counts.has(r.item.id))
    .sort((a, b) => counts.get(b.item.id) - counts.get(a.item.id) || b.t - a.t)
    .forEach(take);
  const perRow = S.rows.map((row) => candidates.filter((r) => r.platform === row.platform).sort((a, b) => b.t - a.t));
  for (let round = 0; round < PLATES_PER_ROW && chosen.length < MAX_PLATES; round += 1) {
    for (const list of perRow) {
      const already = chosen.filter((r) => r.platform === list[0]?.platform).length;
      if (list[round] && already < PLATES_PER_ROW) take(list[round]);
    }
  }
  // Fit the margin: drop the last choices until the plates fit side by side.
  const gap = 18;
  const room = G.x1 - G.x0;
  const width = (rec) => plateWidth(rec.item, G.plateH) || G.plateH;
  while (chosen.length && chosen.reduce((sum, r) => sum + width(r) + gap, -gap) > room) chosen.pop();
  return chosen.map((rec) => ({ rec, w: width(rec), want: starPoint(rec, G).x }));
}

function pack(plates, left, right, gap) {
  plates.sort((a, b) => a.want - b.want);
  let x = left;
  for (const p of plates) {
    p.x = Math.max(x, p.want - p.w / 2);
    x = p.x + p.w + gap;
  }
  let limit = right;
  for (let i = plates.length - 1; i >= 0; i -= 1) {
    const p = plates[i];
    if (p.x + p.w > limit) p.x = limit - p.w;
    limit = p.x - gap;
  }
  return plates;
}

function drawPlates(G, animate) {
  const layer = $("layer-plates");
  const leaders = $("layer-leaders");
  const placed = pack(choosePlates(G), G.x0, G.x1, 18);
  const cited = citedIds();
  const keep = new Set();
  let stagger = 0;
  for (const p of placed) {
    const id = p.rec.item.id;
    keep.add(id);
    const star = starPoint(p.rec, G);
    let node = S.nodes.plates.get(id);
    let leader = S.nodes.leaders.get(id);
    const fresh = !node;
    if (!node) {
      node = el("figure", "chart-plate");
      const caption = el("figcaption", "chart-plate-caption");
      caption.append(el("b", "", `${PLATFORM_CODE[p.rec.platform]} ${p.rec.number}`), ` · ${formatDay(p.rec.item.published_at)}`);
      node.append(caption, plate(p.rec.item, { height: G.plateH, sample: S.mode === "sample" }));
      layer.append(node);
      S.nodes.plates.set(id, node);
      leader = svg("path", { class: "leader" });
      leaders.append(leader);
      S.nodes.leaders.set(id, leader);
    }
    node.style.transform = `translate(${p.x.toFixed(1)}px, ${G.plateTop - 28}px)`;
    const cx = p.x + p.w / 2;
    const yTop = G.plateTop + G.plateH + 6;
    const bend = G.rowsTop - 14;
    leader.setAttribute("d", `M ${cx.toFixed(1)} ${yTop} V ${bend} L ${star.x.toFixed(1)} ${(star.y - radius(p.rec.likes) - 2).toFixed(1)}`);
    leader.classList.toggle("leader-cited", cited.has(id));
    node.classList.toggle("dim", Boolean(S.focus) && !focusIds().has(id));
    leader.classList.toggle("dim", Boolean(S.focus) && !focusIds().has(id));
    if (fresh && animate) {
      const delay = Math.min(stagger, 6) * 110;
      stagger += 1;
      node.animate([{ opacity: 0, transform: `${node.style.transform} translateY(-10px)` }, { opacity: 1, transform: node.style.transform }],
        { duration: 420, delay, easing: "cubic-bezier(0.16, 1, 0.3, 1)", fill: "backwards" });
      const length = leader.getTotalLength();
      leader.animate([{ strokeDasharray: `${length}`, strokeDashoffset: `${length}` }, { strokeDasharray: `${length}`, strokeDashoffset: "0" }],
        { duration: 620, delay: delay + 200, easing: "cubic-bezier(0.65, 0, 0.35, 1)", fill: "backwards" });
    }
  }
  for (const [id, node] of S.nodes.plates) {
    if (keep.has(id)) continue;
    const leader = S.nodes.leaders.get(id);
    S.nodes.plates.delete(id);
    S.nodes.leaders.delete(id);
    if (animate) {
      node.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 240, fill: "forwards" }).onfinish = () => node.remove();
      leader.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 240, fill: "forwards" }).onfinish = () => leader.remove();
    } else {
      node.remove();
      leader.remove();
    }
  }
}

function drawClaims(G, animate) {
  const layer = $("layer-claims");
  const labels = $("layer-claim-labels");
  const shown = S.claims.slice(0, MAX_CLAIMS);
  const keep = new Set();
  const placedLabels = [];
  let stagger = 0;
  for (const claim of shown) {
    const pts = claim.item_ids
      .map((id) => S.items.get(id))
      .filter(Boolean)
      .map((rec) => pointFor(rec, G))
      .filter(Boolean)
      .sort((a, b) => a.x - b.x);
    if (!pts.length) continue;
    keep.add(claim.id);
    let path = S.nodes.paths.get(claim.id);
    let label = S.nodes.labels.get(claim.id);
    const fresh = !path;
    if (!path) {
      path = svg("path", { class: `constellation kind-${claim.kind}` });
      layer.append(path);
      S.nodes.paths.set(claim.id, path);
      label = el("span", `claim-tag kind-${claim.kind}`, claim.id);
      labels.append(label);
      S.nodes.labels.set(claim.id, label);
    }
    const d = pts.length > 1 ? `M ${pts.map((p) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" L ")}` : "";
    path.setAttribute("d", d);
    const spot = labelSpot(pts, placedLabels);
    placedLabels.push(spot);
    label.style.transform = `translate(${spot.x.toFixed(1)}px, ${spot.y.toFixed(1)}px) translate(-50%, -50%)`;
    const dim = Boolean(S.focus) && S.focus !== claim.id;
    path.classList.toggle("dim", dim);
    label.classList.toggle("dim", dim);
    path.classList.toggle("focus", S.focus === claim.id);
    if (fresh && animate && d) {
      const delay = stagger * 260;
      stagger += 1;
      const length = path.getTotalLength();
      if (claim.kind === "fact") {
        path.animate([{ strokeDasharray: `${length}`, strokeDashoffset: `${length}` }, { strokeDasharray: `${length}`, strokeDashoffset: "0" }],
          { duration: 820, delay, easing: "cubic-bezier(0.65, 0, 0.35, 1)", fill: "backwards" });
      } else {
        path.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 520, delay, easing: "ease-out", fill: "backwards" });
      }
      label.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, delay: delay + 520, fill: "backwards" });
    }
  }
  for (const [id, path] of S.nodes.paths) {
    if (keep.has(id)) continue;
    path.remove();
    S.nodes.labels.get(id)?.remove();
    S.nodes.paths.delete(id);
    S.nodes.labels.delete(id);
  }
  renderClaimList(shown);
}

// Put a claim's tag on its longest segment, clear of the tags already placed.
function labelSpot(pts, placed) {
  const candidates = [];
  for (let i = 1; i < pts.length; i += 1) {
    const a = pts[i - 1];
    const b = pts[i];
    candidates.push({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, len: Math.hypot(b.x - a.x, b.y - a.y) });
  }
  if (!candidates.length) candidates.push({ x: pts[0].x + 22, y: pts[0].y - 18, len: 0 });
  candidates.sort((a, b) => b.len - a.len);
  for (const offset of [0, -22, 22, -40, 40]) {
    for (const c of candidates) {
      const spot = { x: c.x, y: c.y + offset };
      if (placed.every((p) => Math.abs(p.x - spot.x) > 46 || Math.abs(p.y - spot.y) > 28)) return spot;
    }
  }
  return candidates[0];
}

function renderClaimList(shown) {
  const list = $("claims-list");
  const waiting = $("claims-waiting");
  const aside = $("claims-aside");
  aside.textContent = S.kept !== null ? `${S.kept} kept · ${S.dropped} dropped: quote not found verbatim` : "";
  if (!S.claims.length) {
    list.replaceChildren();
    waiting.hidden = false;
    waiting.textContent = {
      queued: "Claims join the chart when extraction lands.",
      running: "Extracting claims with exact quotes…",
      not_implemented: "Extraction not built yet: no claims in this run.",
      skipped: "Extraction skipped: no claims in this run.",
      failed: "Extraction failed: no claims in this run.",
      done: S.claimSource === "none" ? "No claims in this run’s record." : "No claims with collected sources.",
    }[S.extractStatus] || "";
    return;
  }
  waiting.hidden = true;
  if (list.dataset.key === shown.map((c) => c.id).join(",") && list.dataset.focus === String(S.focus)) return;
  list.dataset.key = shown.map((c) => c.id).join(",");
  list.dataset.focus = String(S.focus);
  list.replaceChildren(...shown.map((claim) => {
    const row = el("li", `claim kind-${claim.kind}`);
    row.dataset.claim = claim.id;
    row.classList.toggle("focus", S.focus === claim.id);
    const sample = svg("svg", { class: "claim-line", viewBox: "0 0 48 12", "aria-hidden": "true" });
    if (claim.kind !== "missing_source") sample.append(svg("line", { x1: 2, y1: 6, x2: 46, y2: 6, class: `constellation kind-${claim.kind}` }));
    const posts = claim.item_ids.filter((id) => S.items.has(id)).length;
    row.append(
      sample,
      el("span", `claim-tag kind-${claim.kind}`, claim.id),
      el("span", "claim-kind", `${KIND_WORD[claim.kind] || claim.kind} · ${claim.confidence}`),
      el("span", "claim-text", claim.text),
      el("span", "claim-posts", claim.kind === "missing_source" ? "no source" : `${posts} ${posts === 1 ? "post" : "posts"}`),
    );
    row.addEventListener("mouseenter", () => setFocus(claim.id));
    row.addEventListener("mouseleave", () => setFocus(null));
    return row;
  }));
}

function setFocus(id) {
  if (!S || S.focus === id) return;
  S.focus = id;
  for (const row of $("claims-list").children) row.classList.toggle("focus", row.dataset.claim === id);
  schedule(false);
}

function drawNamesakes(G) {
  const box = $("namesakes");
  box.style.transform = `translate(0px, ${G.bandTop}px)`;
  box.style.width = `${COL - 24}px`;
  if (!S.rejected.length) {
    box.replaceChildren();
    return;
  }
  if (box.dataset.count === String(S.rejected.length)) return;
  box.dataset.count = String(S.rejected.length);
  box.replaceChildren(...S.rejected.map((r) => {
    const node = el("div", "namesake");
    const handle = el("p", "namesake-handle");
    handle.append(platformMark(r.platform || "website"), el("span", "namesake-text", r.handle || r.url.replace(/^https?:\/\/(www\.)?/, "")));
    node.append(el("p", "namesake-state", "Rejected namesake · not linked"), handle, el("p", "namesake-reason", r.reason));
    return node;
  }));
}

function drawKey(G) {
  const key = $("key");
  key.style.transform = `translate(0px, ${G.H}px) translateY(-100%)`;
  key.style.width = `${COL - 24}px`;
  if (key.dataset.ready) return;
  key.dataset.ready = "yes";
  const stars = $("key-stars");
  const sizes = [10, 100, 1000, 10000];
  const width = 300;
  const row = svg("svg", { viewBox: `0 0 ${width} 34`, width, height: 34, "aria-hidden": "true" });
  sizes.forEach((likes, i) => {
    const x = 16 + i * 62;
    row.append(svg("circle", { cx: x, cy: 17, r: radius(likes).toFixed(2), class: "star-core" }));
  });
  row.append(svg("circle", { cx: 16 + 4 * 62, cy: 17, r: radius(null).toFixed(2), class: "star-core star-hollow" }));
  const labels = el("p", "key-scale");
  for (const text of ["10", "100", "1 000", "10 000", "n/a"]) labels.append(el("span", "", text));
  stars.replaceChildren(row, labels);
  $("key-note").textContent = S.mode === "sample"
    ? "Star size: likes at collection (log scale). Plates: SAMPLE frames, not images."
    : "Star size: likes at collection (log scale). Plates: post images saved at collection.";
}

// --- night log and tally ------------------------------------------------------------------------

function logThumb(item) {
  if (!(item.thumb && item.media_kind === "image") && !(S.mode === "sample" && item.width && item.height)) {
    return el("span", "log-noimage", item.kind === "page" ? "page" : "text");
  }
  const height = item.width && item.height ? Math.min(72, Math.round((96 * item.height) / item.width)) : 72;
  return plate(item, { height, sample: S.mode === "sample" });
}

function prependLog(rec, animate) {
  const list = $("log-list");
  const motion = animate && !reducedMotion();
  const before = motion ? new Map([...list.children].map((node) => [node, node.offsetTop])) : null;
  const entry = el("li", "log-entry");
  entry.dataset.platform = rec.platform;
  const thumb = el("div", "log-thumb");
  thumb.append(logThumb(rec.item));
  const meta = el("p", "log-meta");
  meta.append(
    el("span", "log-time", formatClock(rec.arrivedAt, true)),
    el("b", "log-no", `${PLATFORM_CODE[rec.platform]} ${rec.number}`),
    el("span", "log-date", rec.item.published_at ? `posted ${formatDay(rec.item.published_at)}` : rec.item.kind),
  );
  entry.append(thumb, meta, el("p", "log-text", rec.item.text || rec.item.url));
  list.prepend(entry);
  while (list.children.length > MAX_LOG) list.lastElementChild.remove();
  if (!motion) return;
  for (const [node, top] of before) {
    if (!node.isConnected) continue;
    const dy = top - node.offsetTop;
    if (dy) node.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 320, easing: "cubic-bezier(0.16, 1, 0.3, 1)" });
  }
  entry.animate([{ opacity: 0, transform: "translateY(-18px)" }, { opacity: 1, transform: "none" }],
    { duration: 380, easing: "cubic-bezier(0.16, 1, 0.3, 1)" });
}

function drawTally(animate) {
  const grid = $("tally");
  const platforms = [...S.rows.map((r) => r.platform)];
  if (S.websiteStep) platforms.push("website");
  if (grid.dataset.ready !== "yes") {
    grid.dataset.ready = "yes";
    grid.replaceChildren(...platforms.map((platform) => {
      const cell = el("li", "tally-cell");
      cell.dataset.platform = platform;
      const value = el("span", "tally-value", "0");
      value.dataset.value = "0";
      cell.append(platformMark(platform), value, el("span", "tally-unit", platform === "website" ? "pages" : "posts"));
      return cell;
    }));
  }
  for (const cell of grid.children) {
    const platform = cell.dataset.platform;
    const count = S.perPlatform.get(platform) || 0;
    const row = S.rowMap.get(platform);
    const missing = row ? Boolean(rowGap(row)) : false;
    cell.classList.toggle("missing", missing);
    const value = cell.querySelector(".tally-value");
    const unit = cell.querySelector(".tally-unit");
    if (missing) {
      value.textContent = "—";
      value.dataset.value = "0";
      unit.textContent = "missing";
    } else {
      tick(value, count, { animate });
      unit.textContent = platform === "website" ? (count === 1 ? "page" : "pages") : (count === 1 ? "post" : "posts");
    }
  }
  const total = S.items.size;
  $("log-aside").textContent = `${formatInt(total)} items`;
  $("tally-aside").textContent = S.lastArrival ? `last item ${formatClock(S.lastArrival, true)} · Apify datasets` : "from Apify datasets";
}

// --- events -------------------------------------------------------------------------------------

function applyStatus(event) {
  const row = S.stepRow.get(event.step);
  if (row) {
    row.status = event.status;
    if (event.note) row.note = event.note;
    return;
  }
  if (event.step === S.websiteStep) S.websiteStatus = event.status;
  if (event.step === "extract") S.extractStatus = event.status;
}

function applyData(event) {
  const data = event.data || {};
  if (Array.isArray(data.accounts) || Array.isArray(data.rejected)) {
    S.accounts = data.accounts || [];
    S.rejected = data.rejected || [];
  }
  if (typeof data.kept === "number") {
    S.kept = data.kept;
    S.dropped = data.dropped ?? 0;
  }
  if (Array.isArray(data.claims)) {
    S.claims = normaliseClaims(data.claims);
    S.claimSource = "event";
  }
}

function normaliseClaims(claims) {
  const byUrl = new Map([...S.items.values()].map((rec) => [rec.item.url, rec.item.id]));
  const out = claims.map((c, i) => {
    const ids = new Set(c.item_ids || []);
    for (const ev of c.evidence || []) {
      if (ev.item_id) ids.add(ev.item_id);
      else if (byUrl.has(ev.url)) ids.add(byUrl.get(ev.url));
    }
    return { id: c.id || `C${i + 1}`, kind: c.kind || "fact", confidence: c.confidence || "", text: c.text || "", item_ids: [...ids], based_on: c.based_on || [] };
  });
  // An inference rests on facts: it joins the posts of the facts it names.
  const byId = new Map(out.map((c) => [c.id, c]));
  for (const c of out) {
    if (c.kind !== "inference" || c.item_ids.length) continue;
    c.item_ids = [...new Set(c.based_on.flatMap((f) => byId.get(f)?.item_ids || []))];
  }
  const order = { fact: 0, inference: 1, open_question: 2, missing_source: 3 };
  return out.sort((a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9));
}

// A real run whose extraction sends no claim event: take the claims from its finished brief.
async function claimsFromBrief(runId) {
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/brief`);
    if (!response.ok) {
      S.claimSource = "none";
      return;
    }
    const brief = await response.json();
    const items = (brief.sections || []).flatMap((s) => s.items || []);
    S.claims = normaliseClaims(items.map((it) => ({ ...it, evidence: it.evidence || [] })));
    S.claimSource = "brief";
  } catch {
    S.claimSource = "none";
  }
  schedule(true);
}

function finish(event) {
  const data = event.data || {};
  S.finishedAt = Date.parse(data.finished_at || event.ts);
  clearInterval(clock);
  for (const row of data.coverage || []) S.coverage.set(row.platform, row);
  renderMasthead();
  if (!S.claims.length && source.kind === "live" && S.mode !== "sample") claimsFromBrief(source.runId);
}

function renderMasthead() {
  renderStamp($("stamp"), S.mode, { finished: Boolean(S.finishedAt) });
  const now = S.finishedAt ?? stream.now();
  const line = $("runline");
  line.replaceChildren("run ", el("b", "", formatDayTime(S.startedAt)));
  line.append(` · ${formatElapsed(now - S.startedAt)} ${S.finishedAt ? "total" : "elapsed"}`);
}

function onEvent(event, { animate }) {
  if (event.type === "replay.error") {
    $("empty").textContent = event.data.message;
    $("empty").hidden = false;
    return;
  }
  if (event.type === "run.started") {
    begin(event.data);
    return;
  }
  if (!S) return;
  switch (event.type) {
    case "step.status": applyStatus(event); break;
    case "step.item": addItem(event, animate); break;
    case "step.data": applyData(event); break;
    case "run.finished": finish(event); break;
  }
  schedule(animate);
}

addEventListener("resize", () => schedule(false));

if (source) {
  wireScreenLinks(sourceQuery(source));
  stream = open(source, onEvent);
} else {
  $("empty").hidden = false;
}
