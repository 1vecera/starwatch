// S3, the front page: the network as a printed explainer graphic beside the live feed.
// Subject → accounts → posts → claims, built only from run events (source.js), with real post
// thumbnails visible without hovering. Nodes appear when their record arrives; edges draw in when
// both ends exist. Collected text goes in through textContent, never innerHTML.
//   ?focus=F1   lights one claim's sources (for stills)    ?tour=1   steps through the claims (for film)
import { connect, sourceFromLocation } from "./source.js";
import {
  COVERAGE_WORDS, PLATFORMS, PRESET_NAMES, arrive, clockTime, compact, count, el, frame, frameWidthRem,
  link, motionAllowed, pagePath, plural, pmark, shortDate, tick, timecode,
} from "./common.js";
import { navLinks, renderCosts, renderFolio, renderMasthead, resetCosts } from "./masthead.js";

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const NET_THUMB_REM = 5.125;
const POST_GAP_REM = 0.4;
const MORE_RESERVE_REM = 4.2;
const MAX_POSTS = 5;
const MAX_CLAIMS = 6;
const FEED_KEEP = 18;
const KIND_WORDS = { fact: "Fact", inference: "Inference", open_question: "Open question", missing_source: "Missing source" };
const KIND_ORDER = { fact: 0, inference: 1, open_question: 2, missing_source: 3 };
const ID_GLYPH = { accepted: "✓", unconfirmed: "?", rejected: "✗" };
const params = new URLSearchParams(location.search);

let state = fresh();
let clockTimer = null;
let edgeFrame = 0;
let tourTimer = null;

function fresh() {
  return {
    ctl: null,
    run: null,
    rows: new Map(),
    items: new Map(),
    byUrl: new Map(),
    posts: 0,
    pages: 0,
    accepted: new Map(),
    detachedKeys: new Map(),
    claims: new Map(),
    shown: [],
    claimNodes: new Map(),
    kept: null,
    dropped: null,
    writeDone: false,
    edges: new Map(),
    animateEdges: false,
    hoverFocus: null,
    tourFocus: params.get("focus"),
    feedCount: 0,
    firstCollected: null,
    lastCollected: null,
  };
}

const sampleMode = () => state.ctl?.view.state === "sample";
const rootPx = () => parseFloat(getComputedStyle(document.documentElement).fontSize);

function normUrl(url) {
  try {
    const u = new URL(url);
    return `${u.hostname.replace(/^www\./, "")}${u.pathname.replace(/\/$/, "")}`.toLowerCase();
  } catch {
    return String(url || "").toLowerCase();
  }
}

function displayHandle(account) {
  const handle = (account.handle || "").trim();
  if (handle) return ["instagram", "tiktok", "x"].includes(account.platform) && !handle.startsWith("@") ? `@${handle}` : handle;
  try {
    const u = new URL(account.url);
    return `${u.hostname.replace(/^www\./, "")}${u.pathname.replace(/\/$/, "")}`;
  } catch {
    return account.url;
  }
}

// --- lede, column heads, legend, source line -----------------------------------------------------

function renderLede() {
  const run = state.run;
  if (!run) return;
  const lead = { live: "Live", cached: "Cached run", sample: "Sample run" }[state.ctl.view.state] || "";
  const goal = run.goal || {};
  $("kicker").textContent = [lead, "The network", PRESET_NAMES[goal.preset] || goal.preset, goal.text ? `„${goal.text}“` : ""].filter(Boolean).join(" · ");
  $("headline").textContent = `The public footprint of ${run.subject}`;
  const frags = [];
  const linked = [...state.rows.values()].filter((r) => r.linkKind === "accepted").length;
  frags.push(linked ? `${plural(linked, "linked account")}` : "accounts not yet resolved");
  const sofar = run.finishedAt ? "" : " so far";
  if (state.posts || state.pages) {
    frags.push(`${[state.posts ? plural(state.posts, "post") : "", state.pages ? plural(state.pages, "page") : ""].filter(Boolean).join(" and ")} collected${sofar}`);
  }
  if (state.kept !== null) frags.push(`${count(state.kept)} claims kept, ${count(state.dropped || 0)} dropped`);
  for (const row of state.rows.values()) {
    if (row.gapWord) frags.push(`${PLATFORMS[row.platform]?.name || row.platform} ${row.gapWord.toLowerCase()}${row.gapNote ? `: ${row.gapNote}` : ""}`);
  }
  $("deck").replaceChildren(...frags.map((f) => el("span", "frag", f)));
}

function renderHeads() {
  const posts = $("network").querySelector(".h-posts");
  posts.replaceChildren(el("b", "", "3"), document.createTextNode("Posts"), el("span", "head-note", `up to ${MAX_POSTS} per account`));
  const claims = $("network").querySelector(".h-claims");
  const total = state.kept ?? state.claims.size;
  claims.replaceChildren(el("b", "", "4"), document.createTextNode("Claims"), el("span", "head-note", state.shown.length ? `${state.shown.length} of ${count(total)} shown` : ""));
}

function renderLegend() {
  const legend = $("legend");
  const item = (...nodes) => {
    const span = el("span", "lg");
    span.append(...nodes);
    return span;
  };
  const kind = (k) => {
    const node = el("span", "kind", KIND_WORDS[k]);
    node.dataset.kind = k;
    return node;
  };
  const mark = (k) => {
    const node = el("span", "id-mark", ID_GLYPH[k]);
    node.dataset.id = k;
    return node;
  };
  legend.replaceChildren(
    item(el("i", "lg-line"), document.createTextNode("linked account")),
    item(el("i", "lg-cite"), document.createTextNode("claim quotes this post")),
    item(el("i", "lg-infer"), document.createTextNode("inference rests on facts")),
    item(mark("rejected"), document.createTextNode("rejected, not linked")),
    item(el("i", "lg-hatch hatch"), document.createTextNode("platform missing")),
    item(kind("fact"), kind("inference"), kind("open_question"), kind("missing_source")),
    item(document.createTextNode("high · medium · low: confidence in the claim, never in the person")),
  );
}

function renderSourceLine() {
  const run = state.run;
  if (!run) return;
  const view = state.ctl.view;
  const what = {
    sample: "SAMPLE design data, not a real run",
    cached: `CACHED replay of the run of ${shortDate(run.startedAt)} ${clockTime(run.startedAt)}`,
    live: `LIVE run of ${shortDate(run.startedAt)} ${clockTime(run.startedAt)}`,
  }[view.state] || "";
  const actors = [...run.plan.values()].filter((s) => s.actor).map((s) => s.actor.split("/").pop());
  const window = state.firstCollected ? ` · counts as collected ${clockTime(state.firstCollected)}–${clockTime(state.lastCollected)}` : "";
  const line = $("source-line");
  line.replaceChildren(el("b", "", "Source:"), document.createTextNode(` ${what} · Apify Actors ${actors.join(", ")} · ElevenLabs Scribe v2${window}`));
}

// --- rows: accounts with their posts --------------------------------------------------------------

function rowFor(step) {
  const node = el("li", "net-row");
  node.dataset.platform = step.platform;
  node.dataset.status = step.status || "queued";
  const acct = el("div", "acct");
  const handle = el("span", "acct-handle", step.platform === "website" ? state.run.anchor : PLATFORMS[step.platform]?.name || step.label);
  const metric = el("span", "acct-metric", step.platform === "website" ? "the anchor site" : "");
  const stateNode = el("span", "acct-state", "Queued");
  acct.append(pmark(step.platform), handle, metric, stateNode);
  const posts = el("div", "posts");
  const more = el("p", "posts-more");
  more.hidden = true;
  const gap = el("div", "posts-gap hatch wipe");
  gap.hidden = true;
  posts.append(more, gap);
  node.append(acct, el("span", "row-ch"), posts);
  const row = { node, step, platform: step.platform, acct, handle, metric, stateNode, posts, more, gap, shown: [], widths: new Map(), total: 0, status: "queued", linkKind: step.platform === "website" ? "anchor" : null };
  if (row.linkKind) node.dataset.linked = "";
  return row;
}

function renderRowState(row) {
  const word = row.platform === "website" ? (row.total === 1 ? "page" : "pages") : row.total === 1 ? "post" : "posts";
  let text;
  if (row.gapWord) text = row.gapWord;
  else if (row.status === "running") text = row.total ? `Collecting · ${count(row.total)} so far` : "Collecting";
  else if (row.status === "done") text = `${count(row.total)} ${word} collected`;
  else if (row.status === "queued") text = "Queued";
  else text = row.status;
  row.stateNode.textContent = text;
  row.node.dataset.status = row.status;
  const hidden = row.total - row.shown.length;
  row.more.hidden = hidden <= 0 || Boolean(row.gapWord);
  if (hidden > 0) row.more.replaceChildren(el("b", "", `+${hidden}`), document.createTextNode("more"));
}

function rowGap(row, word, note, animate) {
  row.gapWord = word;
  row.gapNote = note || "";
  row.node.dataset.gap = "";
  const label = el("p", "gap-label");
  label.append(el("b", "", word), document.createTextNode(note || ""));
  row.gap.replaceChildren(label);
  if (row.gap.hidden) {
    row.gap.hidden = false;
    arrive(row.gap, animate);
  }
  renderRowState(row);
}

function postNode(item, animate) {
  const anchor = link(item.url, "post");
  anchor.dataset.itemId = item.id;
  anchor.append(frame(item, { sample: sampleMode(), height: `${NET_THUMB_REM}rem` }));
  anchor.addEventListener("mouseenter", () => focusFromPost(item.id));
  anchor.addEventListener("mouseleave", () => setFocus(null, "hover"));
  arrive(anchor, animate);
  return anchor;
}

function fits(row, item) {
  const available = row.posts.clientWidth / rootPx() - MORE_RESERVE_REM;
  let used = 0;
  for (const width of row.widths.values()) used += width + POST_GAP_REM;
  return used + frameWidthRem(item, NET_THUMB_REM, sampleMode()) <= available + 0.01;
}

function placePost(row, item, animate) {
  if (row.shown.length < MAX_POSTS && fits(row, item)) {
    row.posts.insertBefore(postNode(item, animate), row.more);
    row.shown.push(item.id);
    row.widths.set(item.id, frameWidthRem(item, NET_THUMB_REM, sampleMode()));
  }
  renderRowState(row);
}

/** A claim cites a post that is not on show: swap it in for the last uncited post in its row. */
function ensureVisible(itemId) {
  const record = state.items.get(itemId);
  if (!record) return;
  const row = state.rows.get(record.item.platform);
  if (!row || row.shown.includes(itemId) || row.gapWord) return;
  const cited = citedItemIds();
  const victim = [...row.shown].reverse().find((id) => !cited.has(id));
  const fresh = postNode(record.item, false);
  if (victim) {
    const old = row.posts.querySelector(`.post[data-item-id="${CSS.escape(victim)}"]`);
    old?.replaceWith(fresh);
    row.shown[row.shown.indexOf(victim)] = itemId;
    row.widths.delete(victim);
  } else if (row.shown.length < MAX_POSTS) {
    row.posts.insertBefore(fresh, row.more);
    row.shown.push(itemId);
  } else {
    return;
  }
  row.widths.set(itemId, frameWidthRem(record.item, NET_THUMB_REM, sampleMode()));
  // Keep the row within its width after a wider image comes in.
  while (row.shown.length > 1 && !fitsAll(row)) {
    const drop = [...row.shown].reverse().find((id) => id !== itemId && !cited.has(id));
    if (!drop) break;
    row.posts.querySelector(`.post[data-item-id="${CSS.escape(drop)}"]`)?.remove();
    row.shown.splice(row.shown.indexOf(drop), 1);
    row.widths.delete(drop);
  }
  renderRowState(row);
}

function fitsAll(row) {
  const available = row.posts.clientWidth / rootPx() - MORE_RESERVE_REM;
  let used = -POST_GAP_REM;
  for (const width of row.widths.values()) used += width + POST_GAP_REM;
  return used <= available + 0.01;
}

// --- identity: linked accounts, and what is not linked ----------------------------------------------

function renderIdentity(data, animate) {
  const accounts = data.accounts || [];
  for (const account of accounts.filter((a) => a.status === "accepted")) {
    const row = state.rows.get(account.platform);
    if (!row || state.accepted.has(account.platform)) continue;
    state.accepted.set(account.platform, account);
    row.linkKind = "accepted";
    row.node.dataset.linked = "";
    row.handle.replaceChildren(link(account.url, "", displayHandle(account)), el("span", "id-glyph", "✓"));
    row.handle.title = (account.match_basis || []).join(" · ");
    arrive(row.handle, animate);
  }
  const detached = [
    ...accounts.filter((a) => a.status !== "accepted").map((a) => ({ account: a, kind: "unconfirmed", why: (a.match_basis || []).join(" · ") || "could not be confirmed" })),
    ...(data.rejected || []).map((r) => ({ account: r, kind: "rejected", why: r.reason })),
  ];
  const list = $("detached-list");
  for (const entry of detached) {
    const key = `${entry.kind}|${entry.account.url}`;
    if (state.detachedKeys.has(key)) continue;
    const item = el("li", "detached-item arrive-fade");
    item.dataset.id = entry.kind;
    const who = el("span", "who");
    const mark = el("span", "id-mark", ID_GLYPH[entry.kind]);
    mark.dataset.id = entry.kind;
    const handle = el("span", "detached-handle");
    const anchor = link(entry.account.url, "", displayHandle(entry.account));
    if (entry.kind === "rejected") {
      const struck = el("span", "struck");
      struck.append(anchor);
      handle.append(struck);
      arrive(struck, animate);
    } else {
      handle.append(anchor);
    }
    who.append(mark, pmark(entry.account.platform || "website"), handle);
    const why = el("p", "detached-why");
    why.append(el("b", "", entry.kind === "rejected" ? "Rejected" : "Unconfirmed"), document.createTextNode(entry.why || ""));
    item.append(who, why);
    state.detachedKeys.set(key, item);
    if (entry.kind === "rejected") list.append(item);
    else list.prepend(item);
    arrive(item, animate);
  }
  $("detached").hidden = state.detachedKeys.size === 0;
  const extra = state.detachedKeys.size - 3;
  let countLine = $("detached").querySelector(".detached-count");
  if (!countLine) {
    countLine = el("p", "detached-count");
    $("detached").append(countLine);
  }
  countLine.textContent = extra > 0 ? `+${extra} more not linked, each with its reason on the desk` : "";
  renderLede();
  scheduleEdges(animate);
}

function renderProfile(profile, animate) {
  const row = state.rows.get(profile.platform);
  if (!row || profile.followers === undefined || profile.followers === null) return;
  row.metric.replaceChildren();
  const n = el("span", "num");
  n.dataset.value = "0";
  row.metric.append(n, document.createTextNode(` followers at ${clockTime(profile.collected_at)}`));
  tick(n, profile.followers, { format: count, animate, ms: 700 });
}

// --- claims ----------------------------------------------------------------------------------------

function itemIdFor(evidence) {
  if (evidence.item_id && state.items.has(evidence.item_id)) return evidence.item_id;
  return state.byUrl.get(normUrl(evidence.url)) || null;
}

function citedItemIds(claimIds = state.shown) {
  const ids = new Set();
  for (const cid of claimIds) {
    for (const evidence of state.claims.get(cid)?.evidence || []) {
      const id = itemIdFor(evidence);
      if (id) ids.add(id);
    }
  }
  return ids;
}

function evidenceLabel(evidence) {
  const code = PLATFORMS[evidence.platform]?.code || evidence.platform;
  if (evidence.timecode !== null && evidence.timecode !== undefined) return `${code} ${timecode(evidence.timecode)}`;
  return `${code} ${shortDate(evidence.published_at)}`.trim();
}

function claimCard(claim) {
  const card = el("li", "claim arrive-slide");
  card.dataset.kind = claim.kind;
  card.dataset.claimId = claim.id;
  card.tabIndex = 0;
  const head = el("div", "claim-head");
  const kind = el("span", "kind", KIND_WORDS[claim.kind] || claim.kind);
  kind.dataset.kind = claim.kind;
  head.append(el("span", "claim-id", claim.id), kind);
  if (claim.kind !== "missing_source" && claim.confidence) {
    const conf = el("span", "claim-conf", claim.confidence);
    conf.dataset.confidence = claim.confidence;
    conf.title = `${claim.confidence} confidence in this claim`;
    head.append(conf);
  }
  const ev = el("span", "claim-ev");
  if (claim.kind === "inference" && claim.based_on?.length) {
    ev.append(document.createTextNode(`from ${claim.based_on.join(" ")}`));
  } else {
    for (const evidence of (claim.evidence || []).slice(0, 2)) ev.append(link(evidence.url, "", evidenceLabel(evidence)));
  }
  head.append(ev);
  card.append(head, el("p", "claim-text", claim.text));
  card.addEventListener("mouseenter", () => setFocus(claim.id, "hover"));
  card.addEventListener("mouseleave", () => setFocus(null, "hover"));
  card.addEventListener("focus", () => setFocus(claim.id, "hover"));
  card.addEventListener("blur", () => setFocus(null, "hover"));
  return card;
}

function chooseClaims() {
  const all = [...state.claims.values()];
  const chosen = state.shown.map((id) => state.claims.get(id)).filter(Boolean);
  const factCap = state.writeDone || state.run.finishedAt ? MAX_CLAIMS : MAX_CLAIMS - 3;
  const add = (claim) => {
    if (chosen.length < MAX_CLAIMS && !chosen.includes(claim)) chosen.push(claim);
  };
  for (const kind of ["inference", "open_question", "missing_source"]) {
    const first = all.find((c) => c.kind === kind);
    if (first && !chosen.some((c) => c.kind === kind)) add(first);
  }
  for (const claim of all.filter((c) => c.kind === "fact")) {
    if (chosen.filter((c) => c.kind === "fact").length >= factCap) break;
    add(claim);
  }
  for (const claim of all) add(claim);
  return chosen;
}

function renderClaims(animate) {
  if (!state.claims.size) return;
  const chosen = chooseClaims();
  const ordered = [...chosen].sort((a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || a.id.localeCompare(b.id, "en", { numeric: true }));
  const list = $("net-claims");
  let stagger = 0;
  const nodes = ordered.map((claim) => {
    let node = state.claimNodes.get(claim.id);
    if (!node) {
      node = claimCard(claim);
      state.claimNodes.set(claim.id, node);
      arrive(node, animate, stagger);
      stagger += 90;
    }
    return node;
  });
  const total = state.kept ?? state.claims.size;
  const more = total > ordered.length ? el("li", "claims-more", `${count(total - ordered.length)} more claims in the brief`) : null;
  list.replaceChildren(...nodes, ...(more ? [more] : []));
  state.shown = ordered.map((c) => c.id);
  for (const id of citedItemIds()) ensureVisible(id);
  renderHeads();
  applyFocus();
  scheduleEdges(animate);
  startTour();
}

function renderClaimsWaiting(status, note) {
  if (state.claims.size) return;
  const list = $("net-claims");
  const box = el("li", "claims-wait");
  const words = {
    queued: "Claims arrive when extraction lands",
    running: "Extracting claims from posts and transcripts",
    not_implemented: "Claim extraction is not built yet",
    skipped: `Claim extraction skipped${note ? `: ${note}` : ""}`,
    failed: `Claim extraction failed${note ? `: ${note}` : ""}`,
    done: "No claims were kept in this run",
  };
  box.append(el("b", "", `Extract · ${status.replace("_", " ")}`), document.createTextNode(words[status] || ""));
  list.replaceChildren(box);
}

// --- edges -------------------------------------------------------------------------------------------

function scheduleEdges(animate = false) {
  state.animateEdges = state.animateEdges || animate;
  cancelAnimationFrame(edgeFrame);
  edgeFrame = requestAnimationFrame(drawEdges);
}

/** An orthogonal path through the given points with small rounded corners, like a printed leader line. */
function orthPath(points, radius) {
  let d = `M ${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`;
  for (let i = 1; i < points.length - 1; i += 1) {
    const [px, py] = points[i - 1];
    const [cx, cy] = points[i];
    const [nx, ny] = points[i + 1];
    const inLen = Math.hypot(cx - px, cy - py);
    const outLen = Math.hypot(nx - cx, ny - cy);
    const r = Math.min(radius, inLen / 2, outLen / 2);
    if (r < 0.5) {
      d += ` L ${cx.toFixed(1)} ${cy.toFixed(1)}`;
      continue;
    }
    const ax = cx - ((cx - px) / inLen) * r;
    const ay = cy - ((cy - py) / inLen) * r;
    const bx = cx + ((nx - cx) / outLen) * r;
    const by = cy + ((ny - cy) / outLen) * r;
    d += ` L ${ax.toFixed(1)} ${ay.toFixed(1)} Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${bx.toFixed(1)} ${by.toFixed(1)}`;
  }
  const last = points[points.length - 1];
  return `${d} L ${last[0].toFixed(1)} ${last[1].toFixed(1)}`;
}

function drawEdges() {
  const svg = $("net-edges");
  const body = $("net-body");
  const base = body.getBoundingClientRect();
  const rem = rootPx();
  const box = (node) => {
    const r = node.getBoundingClientRect();
    return { l: r.left - base.left, r: r.right - base.left, t: r.top - base.top, b: r.bottom - base.top, cx: (r.left + r.right) / 2 - base.left, cy: (r.top + r.bottom) / 2 - base.top };
  };
  const wanted = new Map();
  const add = (key, kind, d, meta = {}) => wanted.set(key, { kind, d, ...meta });

  // Subject → accounts: a spine from the subject to every linked account.
  const subject = box($("subject-block"));
  const spineX = box($("net-subject")).r + 1.1 * rem;
  const originY = subject.t + 1.4 * rem;
  for (const row of state.rows.values()) {
    if (!row.linkKind) continue;
    const mark = box(row.acct.querySelector(".pmark"));
    add(`spine:${row.platform}`, "edge", orthPath([[subject.r - 0.2 * rem, originY], [spineX, originY], [spineX, mark.cy], [mark.l - 0.2 * rem, mark.cy]], 0.45 * rem));
    const first = row.posts.querySelector(".post");
    if (first) {
      const f = box(first);
      const acct = box(row.acct);
      add(`stem:${row.platform}`, "edge edge-stem", `M ${(acct.r + 0.15 * rem).toFixed(1)} ${f.cy.toFixed(1)} H ${(f.l - 0.15 * rem).toFixed(1)}`);
    }
  }

  // Posts → claims: down into the row's gutter, along it, up or down a bus lane, into the card.
  const postsRight = box($("net-rows")).r;
  state.shown.forEach((cid, k) => {
    const claim = state.claims.get(cid);
    const card = state.claimNodes.get(cid);
    if (!claim || !card?.isConnected) return;
    const c = box(card);
    const portY = c.t + 1.0 * rem;
    const busX = postsRight + 0.55 * rem + k * 0.5 * rem;
    for (const evidence of claim.evidence || []) {
      const itemId = itemIdFor(evidence);
      const post = itemId && document.querySelector(`#net-rows .post[data-item-id="${CSS.escape(itemId)}"]`);
      if (!post) continue;
      const p = box(post);
      const gutterY = p.b + 0.22 * rem + k * 0.1 * rem;
      add(`cite:${cid}:${itemId}`, "edge edge-cite", orthPath([[p.cx, p.b], [p.cx, gutterY], [busX, gutterY], [busX, portY], [c.l, portY]], 0.3 * rem), { claim: cid, item: itemId });
      add(`dot:${itemId}:${cid}`, "dot", "", { x: p.cx, y: p.b, claim: cid, item: itemId });
    }
    if (claim.evidence?.length) add(`port:${cid}`, "dot", "", { x: c.l, y: portY, claim: cid });
    if (claim.kind === "inference") {
      (claim.based_on || []).forEach((fid, j) => {
        const factCard = state.claimNodes.get(fid);
        if (!factCard?.isConnected) return;
        const f = box(factCard);
        const x = c.r + 0.5 * rem + j * 0.4 * rem;
        add(`infer:${cid}:${fid}`, "edge edge-infer", orthPath([[c.r, portY], [x, portY], [x, f.t + 1.0 * rem], [f.r, f.t + 1.0 * rem]], 0.3 * rem), { claim: cid, fact: fid });
      });
    }
  });

  const animate = state.animateEdges && motionAllowed();
  state.animateEdges = false;
  for (const [key, node] of state.edges) {
    if (!wanted.has(key)) {
      node.remove();
      state.edges.delete(key);
    }
  }
  let stagger = 0;
  for (const [key, spec] of wanted) {
    let node = state.edges.get(key);
    const isNew = !node;
    if (spec.kind === "dot") {
      if (isNew) node = document.createElementNS(SVG, "circle");
      node.setAttribute("cx", spec.x.toFixed(1));
      node.setAttribute("cy", spec.y.toFixed(1));
      node.setAttribute("r", (0.21 * rem).toFixed(1));
      node.setAttribute("class", "edge-dot");
    } else {
      if (isNew) node = document.createElementNS(SVG, "path");
      node.setAttribute("d", spec.d);
      node.setAttribute("class", spec.kind);
      node.setAttribute("pathLength", "1");
      if (spec.kind === "edge edge-infer") node.removeAttribute("pathLength");
    }
    node.dataset.claim = spec.claim || "";
    node.dataset.item = spec.item || "";
    node.dataset.fact = spec.fact || "";
    if (isNew) {
      svg.append(node);
      state.edges.set(key, node);
      if (animate && spec.kind !== "edge edge-infer") {
        node.classList.add("arriving");
        node.style.animationDelay = `${stagger}ms`;
        stagger += 45;
        node.addEventListener("animationend", () => {
          node.classList.remove("arriving");
          node.style.animationDelay = "";
        }, { once: true });
      }
    }
  }
  applyFocus();
}

// --- focus: a claim lights its sources -------------------------------------------------------------

function setFocus(claimId, reason) {
  if (reason === "hover") {
    state.hoverFocus = claimId;
    if (claimId) stopTour();
  } else {
    state.tourFocus = claimId;
  }
  applyFocus();
}

function focusFromPost(itemId) {
  const citing = state.shown.find((cid) => (state.claims.get(cid)?.evidence || []).some((e) => itemIdFor(e) === itemId));
  if (citing) setFocus(citing, "hover");
}

function applyFocus() {
  const id = state.hoverFocus || state.tourFocus;
  const network = $("network");
  const claim = id && state.claims.get(id);
  if (!claim || !state.shown.includes(id)) {
    delete network.dataset.focus;
    for (const node of document.querySelectorAll(".is-focus, .is-cited")) node.classList.remove("is-focus", "is-cited");
    return;
  }
  network.dataset.focus = id;
  const related = new Set([id, ...(claim.kind === "inference" ? claim.based_on || [] : [])]);
  for (const [cid, card] of state.claimNodes) card.classList.toggle("is-focus", related.has(cid));
  for (const node of state.edges.values()) node.classList.toggle("is-focus", related.has(node.dataset.claim));
  const cited = citedItemIds([...related]);
  for (const post of document.querySelectorAll("#net-rows .post")) post.classList.toggle("is-cited", cited.has(post.dataset.itemId));
  for (const entry of document.querySelectorAll("#feed-list .entry")) entry.classList.toggle("is-cited", cited.has(entry.dataset.itemId));
}

function startTour() {
  if (params.get("tour") !== "1" || tourTimer || !state.shown.length) return;
  let index = -1;
  const step = () => {
    if (!state.shown.length) return;
    index = (index + 1) % state.shown.length;
    setFocus(state.shown[index], "tour");
  };
  tourTimer = setInterval(step, 3200);
  setTimeout(step, 1400);
}

function stopTour() {
  clearInterval(tourTimer);
  tourTimer = null;
}

// --- the feed --------------------------------------------------------------------------------------

function metricsLine(metrics) {
  if (!metrics) return "";
  const parts = [];
  if (metrics.views) parts.push(`${compact(metrics.views)} views`);
  if (metrics.likes) parts.push(`${count(metrics.likes)} likes`);
  if (metrics.comments) parts.push(`${count(metrics.comments)} comments`);
  if (metrics.shares && parts.length < 3) parts.push(`${count(metrics.shares)} shares`);
  return parts.join(" · ");
}

function addFeedEntry(item, at, animate) {
  state.feedCount += 1;
  tick($("feed-count"), state.feedCount, { animate });
  const entry = el("li", "entry");
  entry.dataset.itemId = item.id;
  const thumb = link(item.url, "entry-thumb");
  thumb.append(frame(item, { sample: sampleMode(), height: "var(--sw-thumb-feed)" }));
  const body = el("div", "entry-body");
  const meta = el("div", "entry-meta");
  meta.append(
    el("span", "entry-time", clockTime(at, { seconds: true })),
    pmark(item.platform),
    el("span", "entry-posted", item.published_at ? `posted ${shortDate(item.published_at)}` : item.kind === "page" ? pagePath(item.url) : ""),
  );
  body.append(meta, el("p", "entry-text", item.text || pagePath(item.url)));
  const metrics = metricsLine(item.metrics);
  if (metrics) body.append(el("p", "entry-metrics", metrics));
  entry.append(thumb, body);
  const list = $("feed-list");
  list.querySelector(".feed-empty")?.remove();
  list.prepend(entry);
  arrive(entry, animate);
  while (list.children.length > FEED_KEEP) list.lastElementChild.remove();
  requestAnimationFrame(updateFeedMore);
}

function updateFeedMore() {
  const list = $("feed-list");
  const bottom = list.getBoundingClientRect().bottom;
  let visible = 0;
  for (const entry of list.children) {
    if (entry.getBoundingClientRect().bottom <= bottom + 1) visible += 1;
  }
  const hidden = state.feedCount - visible;
  const more = $("feed-more");
  more.hidden = hidden <= 0;
  more.textContent = hidden > 0 ? `${count(hidden)} earlier ${hidden === 1 ? "item" : "items"} below · every lane is on the desk` : "";
}

// --- events ----------------------------------------------------------------------------------------

function onRunStarted(event) {
  const d = event.data;
  state.run = {
    startedAt: d.started_at || event.ts,
    finishedAt: null,
    subject: d.subject,
    anchor: d.anchor,
    goal: d.goal,
    pause: d.step_pause_s,
    plan: new Map(d.plan.map((s) => [s.id, s])),
  };
  document.title = `Starwatch · Front page · ${d.subject}`;
  $("subject-name").textContent = d.subject;
  const anchor = $("subject-anchor");
  anchor.replaceChildren(el("b", "", "Anchor"), document.createTextNode(d.anchor));
  const rows = d.plan.filter((s) => s.group === "collect").map(rowFor);
  state.rows = new Map(rows.map((r) => [r.platform, r]));
  $("net-rows").replaceChildren(...rows.map((r) => r.node));
  for (const row of rows) renderRowState(row);
  $("detached-list").replaceChildren();
  $("detached").hidden = true;
  $("feed-list").replaceChildren(el("li", "feed-empty", "Nothing collected yet."));
  $("feed-count").textContent = "0";
  $("feed-count").dataset.value = "0";
  const extract = d.plan.find((s) => s.id === "extract");
  renderClaimsWaiting(extract?.status || "queued");
  $("feed-sub").textContent = sampleMode() ? "SAMPLE posts as they arrive, newest first" : "Posts as they are collected, newest first";
  resetCosts();
  renderMasthead(state.ctl, state.run);
  renderFolio(state.run, "Front page");
  renderLede();
  renderHeads();
  renderLegend();
  renderSourceLine();
  clearInterval(clockTimer);
  clockTimer = setInterval(() => renderMasthead(state.ctl, state.run), 500);
  scheduleEdges(false);
}

function onStatus(event, animate) {
  const step = state.run?.plan.get(event.step);
  if (!step) return;
  if (step.group === "collect") {
    const row = state.rows.get(step.platform);
    if (!row) return;
    row.status = event.status;
    if (event.status === "failed") rowGap(row, "Missing", event.note || "the Actor failed", animate);
    else if (event.status === "skipped") rowGap(row, "Skipped", event.note, animate);
    else if (event.status === "not_implemented") rowGap(row, "Skipped", "collector not built yet", animate);
    else if (event.status === "done" && row.total === 0) rowGap(row, "Not found", event.note || "no items in the collection window", animate);
    renderRowState(row);
    renderLede();
    return;
  }
  if (event.step === "extract") renderClaimsWaiting(event.status, event.note);
  if (event.step === "write" && event.status === "done") {
    state.writeDone = true;
    renderClaims(animate);
  }
}

function onItem(event, animate) {
  const item = event.item;
  if (!item || state.items.has(item.id)) return;
  const at = item.collected_at || event.ts;
  state.items.set(item.id, { item, at });
  state.byUrl.set(normUrl(item.url), item.id);
  if (item.kind === "page") state.pages += 1;
  else state.posts += 1;
  state.firstCollected = state.firstCollected || at;
  state.lastCollected = at;
  addFeedEntry(item, at, animate);
  const row = state.rows.get(item.platform);
  if (row) {
    row.total += 1;
    if (row.gapWord) {
      row.gapWord = null;
      delete row.node.dataset.gap;
      row.gap.hidden = true;
    }
    placePost(row, item, animate);
  }
  renderLede();
  renderSourceLine();
  scheduleEdges(animate);
}

function onData(event, animate) {
  const data = event.data || {};
  if (data.costs) renderCosts(data.costs, animate);
  if (event.step === "identity" && (data.accounts || data.rejected)) renderIdentity(data, animate);
  if (data.profile) renderProfile(data.profile, animate);
  if (data.kept !== undefined) {
    state.kept = data.kept;
    state.dropped = data.dropped ?? 0;
    renderLede();
    renderHeads();
  }
  const list = [...(Array.isArray(data.claims) ? data.claims : []), ...(Array.isArray(data.items) ? data.items : [])];
  if (list.length) {
    for (const claim of list) {
      if (!claim?.id || !claim.kind) continue;
      state.claims.set(claim.id, { ...state.claims.get(claim.id), ...claim });
    }
    renderClaims(animate);
  }
}

async function loadBrief() {
  if (!state.ctl.briefUrl || state.claims.size) return;
  try {
    const response = await fetch(state.ctl.briefUrl, { cache: "no-store" });
    if (!response.ok) return;
    const brief = await response.json();
    for (const section of brief.sections || []) {
      for (const item of section.items || []) state.claims.set(item.id, { ...item, section: section.title });
    }
    state.writeDone = true;
    renderClaims(false);
  } catch {
    /* no brief for this run: the claims column says so */
  }
}

function onFinished(event, animate) {
  state.run.finishedAt = event.data?.finished_at || event.ts;
  clearInterval(clockTimer);
  for (const cov of event.data?.coverage || []) {
    const row = state.rows.get(cov.platform);
    if (!row || cov.status === "collected") continue;
    rowGap(row, COVERAGE_WORDS[cov.status] || cov.status, cov.note || (cov.status === "not_found" ? "no items in the collection window" : ""), animate);
  }
  renderCosts(event.data?.costs, animate);
  renderMasthead(state.ctl, state.run);
  state.writeDone = true;
  if (state.claims.size) renderClaims(animate);
  else loadBrief();
  renderLede();
  renderSourceLine();
  scheduleEdges(animate);
}

function onEvent(event, { backlog }) {
  const animate = !backlog;
  switch (event.type) {
    case "run.started": onRunStarted(event); break;
    case "step.status": onStatus(event, animate); break;
    case "step.item": onItem(event, animate); break;
    case "step.data": onData(event, animate); break;
    case "run.finished": onFinished(event, animate); break;
  }
}

// --- start -----------------------------------------------------------------------------------------

window.addEventListener("resize", () => scheduleEdges(false));
$("net-body").addEventListener("load", () => scheduleEdges(false), true);
document.fonts?.ready.then(() => scheduleEdges(false));

navLinks();
renderMasthead(null, null, "Open a run from the desk");
renderFolio(null, "Front page");
renderLegend();
const source = sourceFromLocation();
if (source.kind === "idle") {
  const deck = $("deck");
  deck.replaceChildren(document.createTextNode("Start a run on the desk, or "), Object.assign(el("a", "", "play the sample run"), { href: "/static/s3.html?replay=/static/sample/run-g1.jsonl" }), document.createTextNode(" (labelled SAMPLE)."));
} else {
  state.ctl = connect(source, onEvent);
  state.ctl.ready.catch((failure) => {
    $("deck").textContent = failure.message;
  });
}
