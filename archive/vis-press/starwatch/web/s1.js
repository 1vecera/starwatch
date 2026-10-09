// S1, the desk: the request set as one sentence, then the research visibly running. Built only from
// run events (source.js): a live SSE stream, or a recorded stream replayed at its real pace.
// Collected text goes in through textContent, never innerHTML.
import { health, startRun } from "./run-stream.js";
import { connect, sourceFromLocation } from "./source.js";
import {
  COVERAGE_WORDS, PLATFORMS, PRESET_NAMES, STATUS_WORDS, arrive, clockTime, count, dayMonth, el,
  elapsedWords, frame, frameWidthRem, link, plural, pmark, tick,
} from "./common.js";
import { navLinks, renderCosts as renderEditionCosts, renderFolio as renderDateline, renderMasthead as renderBug, resetCosts } from "./masthead.js";

const $ = (id) => document.getElementById(id);
const LANE_THUMB_REM = 5.25;
const SLOT_GAP_REM = 0.375;
const MAX_SLOTS = 40;
const CELL_BYLINES = { transcribe: "ElevenLabs Scribe v2", extract: "quotes checked verbatim", render: "brief · network · alert" };
const ID_GLYPH = { accepted: "✓", unconfirmed: "?", rejected: "✗" };

let state = freshState();
let clockTimer = null;

function freshState() {
  return {
    ctl: null,
    run: null,
    lanes: new Map(),
    cells: new Map(),
    posts: 0,
    pages: 0,
    sources: new Set(),
    accountKeys: new Map(),
    rejectedCount: 0,
    gaps: new Map(),
    claims: null,
    costs: null,
  };
}

const sampleMode = () => state.ctl?.view.state === "sample";

// --- masthead and folio ------------------------------------------------------------------------

function renderMasthead() {
  renderBug(state.ctl, state.run);
}

function renderFolio() {
  renderDateline(state.run, "Research desk");
}

function renderCosts(costs, animate) {
  if (!costs) return;
  state.costs = costs;
  renderEditionCosts(costs, animate);
}

// --- the lede: kicker, headline and deck written from the run's own numbers ----------------------

function renderLede() {
  const run = state.run;
  if (!run) return;
  const view = state.ctl.view;
  const goal = run.goal;
  const lead = { live: "Live research", cached: "Cached run", sample: "Sample run" }[view.state] || "Research";
  $("kicker").textContent = [lead, PRESET_NAMES[goal.preset] || goal.preset, goal.text ? `„${goal.text}“` : "", run.goalBasis && run.goalBasis !== "chosen" ? `goal ${run.goalBasis}` : ""]
    .filter(Boolean).join(" · ");

  const headline = $("headline");
  if (run.finishedAt) {
    headline.textContent = state.posts
      ? `${count(state.posts)} public posts of ${run.subject}, collected in ${elapsedWords(Date.parse(run.finishedAt) - Date.parse(run.startedAt))}`
      : `No public posts of ${run.subject} were collected in this run`;
  } else {
    headline.textContent = `Collecting the public posts of ${run.subject}`;
  }

  const frags = [`anchored by ${run.anchor}`];
  const sources = state.sources.size;
  const sofar = run.finishedAt ? "" : " so far";
  if (state.posts || state.pages) {
    const what = [state.posts ? plural(state.posts, "post") : "", state.pages ? plural(state.pages, "page") : ""].filter(Boolean).join(" and ");
    frags.push(`${what} from ${plural(sources, "source")}${sofar}`);
  } else if (!run.finishedAt) {
    frags.push("waiting for the first item");
  }
  if (state.rejectedCount) frags.push(`${plural(state.rejectedCount, "look-alike")} rejected`);
  for (const [platform, gap] of state.gaps) {
    frags.push({ text: `${PLATFORMS[platform]?.name || platform} ${gap.word.toLowerCase()}${gap.note ? `: ${gap.note}` : ""}`, gap: true });
  }
  if (state.claims) frags.push(`${count(state.claims.kept)} claims kept, ${count(state.claims.dropped)} dropped`);
  const deck = $("deck");
  deck.replaceChildren(...frags.map((f) => el("span", `frag${f.gap ? " frag-gap" : ""}`, typeof f === "string" ? f : f.text)));
}

// --- plan: lanes, identity and analysis ----------------------------------------------------------

function statusWord(step, status) {
  if (status === "running") return step.group === "collect" ? "Collecting" : step.group === "identity" ? "Resolving" : "Running";
  return STATUS_WORDS[status] || status;
}

function laneFor(step) {
  const node = el("li", "lane");
  node.dataset.step = step.id;
  node.dataset.platform = step.platform;
  node.dataset.status = step.status || "queued";
  const statusNode = el("span", "status-word", statusWord(step, node.dataset.status));
  const head = el("div", "lane-head");
  head.append(pmark(step.platform), el("span", "lane-name", PLATFORMS[step.platform]?.name || step.label), el("code", "lane-actor", step.actor || ""), statusNode);
  const counter = el("div", "lane-count");
  const countNode = el("span", "count-n", "0");
  countNode.dataset.value = "0";
  counter.append(countNode, el("span", "count-cap", step.max_items ? `of max ${step.max_items}` : "items"));
  const box = el("div", "lane-strip");
  const strip = el("ol", "strip");
  const more = el("p", "strip-more");
  more.hidden = true;
  const gap = el("div", "lane-gap hatch wipe");
  gap.hidden = true;
  box.append(strip, more, gap);
  node.append(head, counter, box);
  return { node, step, platform: step.platform, strip, box, more, gap, countNode, statusNode, items: 0, widths: [] };
}

function cellFor(step) {
  const node = el("li", "cell");
  node.dataset.step = step.id;
  node.dataset.status = step.status || "queued";
  const head = el("div", "cell-head");
  const statusNode = el("span", "status-word", statusWord(step, node.dataset.status));
  head.append(el("span", "cell-name", step.label), statusNode);
  const by = step.id === "write" ? `${PRESET_NAMES[state.run.goal.preset] || ""} brief` : CELL_BYLINES[step.id] || "";
  const text = el("p", "cell-text", "Waiting for collection");
  node.append(head, el("span", "cell-by", by), text);
  return { node, step, statusNode, text, summary: "" };
}

function renderPlan(plan) {
  state.lanes.clear();
  state.cells.clear();
  const lanes = plan.filter((s) => s.group === "collect").map(laneFor);
  for (const lane of lanes) state.lanes.set(lane.step.id, lane);
  $("lanes").replaceChildren(...lanes.map((l) => l.node));
  const cells = plan.filter((s) => s.group === "downstream").map(cellFor);
  for (const cell of cells) state.cells.set(cell.step.id, cell);
  $("downstream").replaceChildren(...cells.map((c) => c.node));
  const identity = plan.find((s) => s.group === "identity");
  const idStep = $("identity-step");
  idStep.dataset.status = identity?.status || "queued";
  idStep.querySelector(".status-word").textContent = statusWord(identity || { group: "identity" }, idStep.dataset.status);
  $("accounts").replaceChildren();
  $("identity-empty").textContent = "";
  $("identity-tally").textContent = "";
  delete idStep.dataset.summary;
  $("anchor").textContent = state.run.anchor;

  const note = $("wire-note");
  note.className = "section-note";
  note.replaceChildren();
  if (sampleMode()) {
    note.classList.add("sample-note");
    note.append(el("b", "", "SAMPLE"), document.createTextNode("flat frames stand in for post images"));
  } else if (state.ctl.view.state === "cached") {
    note.textContent = "Images as downloaded during the recorded run";
  } else {
    note.textContent = "Images are the subject's own posts, downloaded as they arrive";
  }
}

// --- lanes ---------------------------------------------------------------------------------------

function laneGap(lane, word, note, animate) {
  lane.node.dataset.gap = "";
  state.gaps.set(lane.platform, { word, note });
  const label = el("p", "gap-label");
  label.append(el("b", "", word), document.createTextNode(note || ""));
  lane.gap.replaceChildren(label);
  if (lane.gap.hidden) {
    lane.gap.hidden = false;
    arrive(lane.gap, animate);
  }
  lane.more.hidden = true;
}

function clearGap(lane) {
  delete lane.node.dataset.gap;
  lane.gap.hidden = true;
  state.gaps.delete(lane.platform);
}

function gapFromStatus(lane, status, note, animate) {
  if (status === "failed") laneGap(lane, "Missing", note || "the Actor failed", animate);
  else if (status === "skipped") laneGap(lane, "Skipped", note, animate);
  else if (status === "not_implemented") laneGap(lane, "Skipped", "collector not built yet", animate);
  else if (status === "done" && lane.items === 0) laneGap(lane, "Not found", note || "no items in the collection window", animate);
}

function updateOverflow(lane) {
  const rootPx = parseFloat(getComputedStyle(document.documentElement).fontSize);
  const limitRem = lane.box.clientWidth / rootPx;
  let used = 0;
  let visible = 0;
  for (const width of lane.widths) {
    if (used + width - SLOT_GAP_REM > limitRem) break;
    used += width;
    visible += 1;
  }
  const hidden = lane.items - visible;
  lane.more.hidden = hidden <= 0 || lane.node.dataset.gap !== undefined;
  if (hidden > 0) lane.more.replaceChildren(el("b", "", `+${hidden}`), document.createTextNode("earlier"));
}

function addItem(lane, item, animate) {
  lane.items += 1;
  if (item.kind === "page") state.pages += 1;
  else state.posts += 1;
  state.sources.add(item.platform);
  if (lane.node.dataset.gap !== undefined) clearGap(lane);
  const sample = sampleMode();
  const slot = el("li", "slot");
  const anchor = link(item.url, "slot-link");
  anchor.append(frame(item, { sample, height: `${LANE_THUMB_REM}rem` }));
  slot.append(anchor);
  const width = frameWidthRem(item, LANE_THUMB_REM, sample) + SLOT_GAP_REM;
  slot.style.setProperty("--slot-w", `${width}rem`);
  lane.strip.prepend(slot);
  lane.widths.unshift(width);
  if (lane.strip.children.length > MAX_SLOTS) {
    lane.strip.lastElementChild.remove();
    lane.widths.length = MAX_SLOTS;
  }
  arrive(slot, animate);
  updateOverflow(lane);
}

// --- identity ------------------------------------------------------------------------------------

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

function accountRow(account, kind, animate) {
  const row = el("li", "account arrive-fade");
  row.dataset.id = kind;
  const handleBox = el("span", "account-handle");
  const anchor = link(account.url, "", displayHandle(account));
  if (kind === "rejected") {
    const struck = el("span", "struck");
    struck.append(anchor);
    handleBox.append(struck);
    arrive(struck, animate);
  } else {
    handleBox.append(anchor);
  }
  const basis = el("span", "account-basis");
  if (kind !== "accepted") basis.append(el("span", "account-state", kind === "rejected" ? "Rejected" : "Unconfirmed"));
  basis.append(document.createTextNode(kind === "rejected" ? account.reason || "" : (account.match_basis || []).join(" · ") || "no match basis recorded"));
  const mark = el("span", "id-mark", ID_GLYPH[kind]);
  mark.dataset.id = kind;
  mark.title = kind;
  row.append(mark, pmark(account.platform || "website"), handleBox, basis);
  arrive(row, animate);
  return row;
}

function renderIdentity(data, animate) {
  const list = $("accounts");
  const accounts = data.accounts || [];
  const rejected = data.rejected || [];
  const order = { accepted: 0, unconfirmed: 1, rejected: 2 };
  const entries = [
    ...accounts.map((a) => ({ account: a, kind: a.status === "accepted" ? "accepted" : "unconfirmed" })),
    ...rejected.map((r) => ({ account: r, kind: "rejected" })),
  ].sort((a, b) => order[a.kind] - order[b.kind]);
  let stagger = 0;
  const rows = entries.map(({ account, kind }) => {
    const key = `${kind}|${account.url}`;
    if (!state.accountKeys.has(key)) {
      const row = accountRow(account, kind, animate);
      if (animate) row.style.animationDelay = `${stagger}ms`;
      stagger += 70;
      state.accountKeys.set(key, row);
    }
    return state.accountKeys.get(key);
  });
  list.replaceChildren(...rows);
  state.rejectedCount = rejected.length;
  const accepted = accounts.filter((a) => a.status === "accepted").length;
  const unconfirmed = accounts.length - accepted;
  $("identity-step").dataset.summary = [`${accepted} accepted`, unconfirmed ? `${unconfirmed} unconfirmed` : "", rejected.length ? `${rejected.length} rejected` : ""].filter(Boolean).join(" · ");
  updateIdentityStatus();
}

function updateIdentityStatus() {
  const node = $("identity-step");
  const status = node.dataset.status;
  const word = node.querySelector(".status-word");
  word.textContent = statusWord({ group: "identity" }, status);
  $("identity-tally").textContent = node.dataset.summary || "";
  const empty = $("identity-empty");
  if (status === "not_implemented") empty.textContent = "Identity resolution is not built yet, so no account is accepted or rejected in this run.";
  else if (status === "skipped" || status === "failed") empty.textContent = `Identity could not be resolved${node.dataset.note ? `: ${node.dataset.note}` : ""}.`;
  else empty.textContent = "";
}

// --- analysis cells ------------------------------------------------------------------------------

function renderCell(cell, status, { note = "", count: n } = {}) {
  cell.node.dataset.status = status;
  cell.statusNode.textContent = statusWord(cell.step, status);
  let text = cell.summary || note;
  if (!text) {
    if (status === "queued") text = "Waiting for collection";
    else if (status === "running") text = n !== undefined && n !== null ? `${count(n)} so far` : "Running";
    else if (status === "done") text = n !== undefined && n !== null ? `${count(n)} done` : "Done";
    else if (status === "not_implemented") text = "Not built yet";
    else text = STATUS_WORDS[status] || status;
  }
  cell.text.textContent = text;
}

// --- events --------------------------------------------------------------------------------------

function onRunStarted(event) {
  const d = event.data;
  state.run = {
    startedAt: d.started_at || event.ts,
    finishedAt: null,
    subject: d.subject,
    anchor: d.anchor,
    goal: d.goal,
    goalBasis: d.goal_basis,
    pause: d.step_pause_s,
    plan: new Map(d.plan.map((s) => [s.id, s])),
  };
  $("commission").hidden = true;
  $("run").hidden = false;
  document.title = `Starwatch · ${d.subject}`;
  renderPlan(d.plan);
  renderMasthead();
  renderFolio();
  renderLede();
  resetCosts();
  clearInterval(clockTimer);
  clockTimer = setInterval(renderMasthead, 500);
}

function onStatus(event, animate) {
  const lane = state.lanes.get(event.step);
  if (lane) {
    lane.node.dataset.status = event.status;
    lane.statusNode.textContent = statusWord(lane.step, event.status);
    if (event.count !== undefined && event.count !== null && event.count >= lane.items) tick(lane.countNode, event.count, { animate });
    gapFromStatus(lane, event.status, event.note, animate);
    renderLede();
    return;
  }
  const cell = state.cells.get(event.step);
  if (cell) {
    renderCell(cell, event.status, { note: event.note, count: event.count });
    return;
  }
  if (event.step === "identity") {
    const node = $("identity-step");
    node.dataset.status = event.status;
    node.dataset.note = event.note || "";
    updateIdentityStatus();
  }
}

function onItem(event, animate) {
  const lane = state.lanes.get(event.step);
  if (!lane || !event.item) return;
  addItem(lane, event.item, animate);
  tick(lane.countNode, event.count ?? lane.items, { animate });
  renderLede();
}

function onData(event, animate) {
  const data = event.data || {};
  if (data.costs) renderCosts(data.costs, animate);
  if (event.step === "identity" && (data.accounts || data.rejected)) {
    renderIdentity(data, animate);
    renderLede();
  }
  if (data.kept !== undefined || data.dropped !== undefined) {
    state.claims = { kept: data.kept || 0, dropped: data.dropped || 0 };
    renderLede();
  }
  const cell = state.cells.get(event.step);
  if (cell) {
    if (data.summary) cell.summary = data.summary;
    else if (data.kept !== undefined) cell.summary = `${count(data.kept)} claims kept · ${count(data.dropped || 0)} dropped: quote not found verbatim`;
    if (cell.summary) cell.text.textContent = cell.summary;
  }
}

function onFinished(event, animate) {
  state.run.finishedAt = event.data?.finished_at || event.ts;
  clearInterval(clockTimer);
  for (const row of event.data?.coverage || []) {
    const lane = [...state.lanes.values()].find((l) => l.platform === row.platform);
    if (!lane) continue;
    if (row.status === "collected") continue;
    laneGap(lane, COVERAGE_WORDS[row.status] || row.status, row.note || (row.status === "not_found" ? "no items in the collection window" : ""), animate);
  }
  renderCosts(event.data?.costs, animate);
  renderMasthead();
  renderLede();
  $("run-button").disabled = false;
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

function follow(source) {
  state.ctl?.stop();
  clearInterval(clockTimer);
  state = freshState();
  state.ctl = connect(source, onEvent);
  state.ctl.ready.catch((failure) => {
    $("form-error").textContent = failure.message;
    $("form-error").hidden = false;
  });
}

// --- the commission form and the index of runs -----------------------------------------------------

async function showCredentials() {
  try {
    const { missing } = await health();
    const note = $("credentials");
    note.hidden = missing.length === 0;
    note.textContent = `Missing ${missing.join(", ")}: steps that need ${missing.length > 1 ? "them" : "it"} report skipped.`;
  } catch {
    /* the server says nothing; the form still works */
  }
}

async function showRecentRuns() {
  const list = $("recent");
  try {
    const response = await fetch("/api/runs");
    const runs = (await response.json()).slice(0, 6);
    if (!runs.length) {
      list.replaceChildren(el("li", "index-empty", "No runs yet on this machine."));
      return;
    }
    list.replaceChildren(...runs.map((r) => {
      const item = el("li");
      const a = el("a");
      a.href = `/?run=${encodeURIComponent(r.id)}`;
      a.append(
        el("span", "index-time", clockTime(r.created_at)),
        el("span", "index-subject", r.subject),
        el("span", "index-meta", [dayMonth(r.created_at), r.goal_preset, r.mode, r.status].join(" · ")),
      );
      item.append(a);
      return item;
    }));
  } catch {
    list.replaceChildren(el("li", "index-empty", "The run index is unavailable."));
  }
}

$("request").addEventListener("submit", async (submit) => {
  submit.preventDefault();
  const form = new FormData(submit.target);
  const error = $("form-error");
  error.hidden = true;
  $("run-button").disabled = true;
  try {
    const created = await startRun({
      subject: form.get("subject"),
      anchor: form.get("anchor"),
      goal_preset: form.get("goal_preset") || null,
      goal_text: form.get("goal_text") || "",
    });
    history.pushState({}, "", `?run=${created.run_id}`);
    navLinks();
    follow({ kind: "run", runId: created.run_id });
  } catch (failure) {
    error.textContent = failure.message;
    error.hidden = false;
    $("run-button").disabled = false;
  }
});

window.addEventListener("resize", () => {
  for (const lane of state.lanes.values()) updateOverflow(lane);
});

navLinks();
renderMasthead();
renderFolio();
const source = sourceFromLocation();
if (source.kind === "idle") {
  showCredentials();
  showRecentRuns();
} else {
  follow(source);
}
