// S1 · The run, set as an observing log. One lane per Apify Actor fills with the subject's post
// images as items arrive, identification accepts accounts and strikes out a namesake, and a platform
// that came back empty shows as a hatched gap with its reason. Built only from run events, live over
// SSE or replayed from a recording (see stream.js). Collected text goes in through textContent.
import { health, startRun } from "./run-stream.js";
import { modeFor, open, sourceFromLocation, sourceQuery } from "./stream.js";
import {
  PLATFORM_NAME, PRESET_NAMES, STATUS_TEXT, el, formatDayTime, formatElapsed, formatInt, formatUsd, plate,
  platformMark, reducedMotion, renderStamp, tick, wireScreenLinks,
} from "./atlas.js";

const $ = (id) => document.getElementById(id);
const THUMB = 96; // px, --sw-thumb-height
const EARLIER = 88; // px, width of the "+N earlier" box
const INSTRUMENT = {
  transcribe: "ElevenLabs Scribe v2",
  extract: "quotes checked verbatim",
  write: "goal-specific brief",
  render: "brief, chart, alert",
};

let source = sourceFromLocation();
let stream = null;
let run = null;
let clock = null;

// --- run start ----------------------------------------------------------------------------------

function begin(data) {
  run = {
    data,
    mode: modeFor(source, data),
    startedAt: Date.parse(data.started_at),
    finishedAt: null,
    lanes: new Map(),
    rows: new Map(),
    identityStep: null,
    apify: null,
    scribe: null,
    total: 0,
    kept: null,
    dropped: null,
  };
  document.body.dataset.mode = run.mode;
  $("request").hidden = true;
  $("run").hidden = false;
  $("subject-name").textContent = data.subject;
  $("subject-anchor").textContent = data.anchor;
  const goal = $("subject-goal");
  goal.replaceChildren(PRESET_NAMES[data.goal.preset] || data.goal.preset);
  if (data.goal.text) goal.append(` · ${data.goal.text}`);
  if (data.goal_basis && data.goal_basis !== "chosen") goal.append(el("span", "basis", ` (${data.goal_basis})`));
  renderPlan(data.plan);
  renderMasthead();
  renderLedger(false);
  clearInterval(clock);
  clock = setInterval(renderMasthead, 1000);
}

function renderPlan(plan) {
  $("lanes").replaceChildren(...plan.filter((s) => s.group === "collect").map(laneFor));
  $("downstream").replaceChildren(...plan.filter((s) => s.group === "downstream").map(rowFor));
  $("accounts").replaceChildren();
  $("identity-aside").textContent = "";
  const identity = plan.find((s) => s.group === "identity");
  run.identityStep = identity ? identity.id : null;
  renderIdentityStatus(identity ? identity.status : "queued", "");
  renderTotal();
}

function laneFor(step) {
  const node = el("li", "lane");
  node.dataset.step = step.id;
  node.dataset.status = step.status;
  node.dataset.platform = step.platform;

  const meta = el("div", "lane-meta");
  const status = el("span", "lane-status", STATUS_TEXT[step.status] || step.status);
  const cost = el("span", "lane-cost");
  const sub = el("p", "lane-sub");
  sub.append(el("span", "lane-name", PLATFORM_NAME[step.platform] || step.label), status, cost);
  meta.append(el("code", "lane-actor", step.actor || ""), sub);

  const count = el("div", "lane-count");
  const value = el("span", "lane-count-value", "0");
  value.dataset.value = "0";
  count.append(value, el("span", "lane-count-cap", step.max_items ? `of max ${step.max_items}` : ""));

  const strip = el("div", "lane-strip");
  const track = el("ol", "lane-track settling");
  const earlier = el("p", "lane-earlier");
  const waiting = el("p", "lane-waiting", "waiting for the first dataset items");
  const gap = el("p", "lane-gap");
  earlier.hidden = waiting.hidden = gap.hidden = true;
  strip.append(track, earlier, waiting, gap);

  node.append(platformMark(step.platform, "lane-mark"), meta, count, strip);
  run.lanes.set(step.id, {
    node, step, status, cost, value, strip, track, earlier, waiting, gap,
    items: 0, note: "", usage: null, coverage: null, burst: { at: 0, n: 0 },
  });
  return node;
}

function rowFor(step) {
  const node = el("li", "step");
  node.dataset.step = step.id;
  node.dataset.status = step.status;
  const label = el("span", "step-label", step.label);
  if (INSTRUMENT[step.id]) label.append(el("span", "step-instrument", ` · ${INSTRUMENT[step.id]}`));
  const status = el("span", "step-status", STATUS_TEXT[step.status] || step.status);
  const note = el("span", "step-note");
  node.append(label, status, note);
  run.rows.set(step.id, { node, status, note });
  return node;
}

// --- events -------------------------------------------------------------------------------------

function applyStatus(event, animate) {
  const lane = run.lanes.get(event.step);
  if (lane) {
    lane.node.dataset.status = event.status;
    lane.status.textContent = STATUS_TEXT[event.status] || event.status;
    if (event.note) lane.note = event.note;
    if (event.count !== undefined && event.count !== null) tick(lane.value, event.count, { animate });
    refreshLane(lane);
    renderTotal();
    return;
  }
  const row = run.rows.get(event.step);
  if (row) {
    row.node.dataset.status = event.status;
    row.status.textContent = STATUS_TEXT[event.status] || event.status;
    if (event.note) row.note.textContent = event.note;
    else if (event.status === "not_implemented") row.note.textContent = "step not built yet";
    return;
  }
  if (event.step === run.identityStep) renderIdentityStatus(event.status, event.note || "");
}

function applyItem(event, animate) {
  const lane = run.lanes.get(event.step);
  if (!lane) return;
  lane.items += 1;
  run.total += 1;
  const entry = el("li", "lane-item");
  entry.append(plate(event.item, { height: THUMB, sample: run.mode === "sample", number: lane.items }));
  if (animate && !reducedMotion()) {
    // Items from one dataset poll arrive together; stagger them so each plate is seen landing.
    const now = performance.now();
    if (now - lane.burst.at > 450) lane.burst.n = 0;
    lane.burst.at = now;
    entry.classList.add("arriving");
    entry.style.animationDelay = `${Math.min(lane.burst.n, 8) * 90}ms`;
    lane.burst.n += 1;
  }
  lane.track.append(entry);
  layoutStrip(lane, animate);
  tick(lane.value, event.count ?? lane.items, { animate });
  refreshLane(lane);
  renderTotal();
}

function applyData(event, animate) {
  const data = event.data || {};
  if (event.step === run.identityStep) {
    renderIdentity(data, animate);
    return;
  }
  const lane = run.lanes.get(event.step);
  if (lane) {
    if (typeof data.usage_usd === "number") {
      lane.usage = data.usage_usd;
      lane.cost.textContent = formatUsd(lane.usage);
      run.apify = [...run.lanes.values()].reduce((sum, l) => sum + (l.usage || 0), 0);
      renderLedger(animate);
    }
    return;
  }
  const row = run.rows.get(event.step);
  if (!row) return;
  if (typeof data.kept === "number") {
    run.kept = data.kept;
    run.dropped = data.dropped ?? 0;
    row.note.textContent = `${data.kept} claims kept · ${run.dropped} dropped: quote not found verbatim`;
  } else if (data.summary) {
    row.note.textContent = data.summary;
  }
  if (typeof data.minutes === "number") {
    run.scribe = data.minutes;
    renderLedger(animate);
  }
}

function finish(event, animate) {
  const data = event.data || {};
  run.finishedAt = Date.parse(data.finished_at || event.ts);
  clearInterval(clock);
  for (const row of data.coverage || []) {
    for (const lane of run.lanes.values()) {
      if (lane.step.platform === row.platform) {
        lane.coverage = row;
        refreshLane(lane);
      }
    }
  }
  const costs = data.costs || {};
  if (typeof costs.apify_usd === "number") run.apify = costs.apify_usd;
  if (typeof costs.scribe_minutes === "number") run.scribe = costs.scribe_minutes;
  renderMasthead();
  renderLedger(animate);
  run.coverage = data.coverage || [];
  renderTotal();
  $("receipt").textContent = `Run ${event.status} ${formatDayTime(run.finishedAt)}.`;
  $("ledger-aside").textContent = "final, from the run record";
}

// --- lanes --------------------------------------------------------------------------------------

// Keep the newest plate in view: once a lane is full, the strip shifts left and the plates it
// hides are counted in the "+N earlier" box. Every item stays in the lane; none is dropped.
function layoutStrip(lane, animate) {
  lane.track.classList.toggle("settling", !animate || reducedMotion());
  const visible = lane.strip.clientWidth;
  const offset = Math.max(0, lane.track.scrollWidth - visible);
  lane.track.style.transform = offset ? `translateX(${-offset}px)` : "";
  if (!offset) {
    lane.earlier.hidden = true;
    return;
  }
  let hidden = 0;
  for (const entry of lane.track.children) {
    if (entry.offsetLeft + entry.offsetWidth <= offset + EARLIER) hidden += 1;
    else break;
  }
  lane.earlier.hidden = false;
  lane.earlier.replaceChildren(el("b", "", `+${hidden}`), el("span", "", "earlier"));
}

function refreshLane(lane) {
  const status = lane.node.dataset.status;
  lane.waiting.hidden = !(status === "running" && lane.items === 0);
  let gap = null;
  if (lane.coverage && lane.coverage.status !== "collected") {
    gap = [lane.coverage.status.replace("_", " "), lane.coverage.note].filter(Boolean).join(" · ");
  } else if (!lane.coverage) {
    if (status === "failed") gap = ["unavailable", lane.note].filter(Boolean).join(" · ");
    else if (status === "skipped") gap = ["skipped", lane.note].filter(Boolean).join(" · ");
    else if (status === "not_implemented") gap = "collector not built yet";
    else if (status === "done" && lane.items === 0) gap = "nothing found";
  }
  if (gap && lane.items === 0) {
    lane.node.dataset.gap = "yes";
    lane.gap.hidden = false;
    lane.gap.replaceChildren(el("b", "", "Missing"), el("span", "", gap));
  } else {
    delete lane.node.dataset.gap;
    lane.gap.hidden = true;
  }
}

function renderTotal() {
  const running = [...run.lanes.values()].filter((l) => l.node.dataset.status === "running").length;
  const parts = [`${formatInt(run.total)} items collected`];
  if (running) parts.push(`${running} Actor${running > 1 ? "s" : ""} running`);
  if (run.coverage?.length) {
    const collected = run.coverage.filter((c) => c.status === "collected").length;
    parts.push(`${collected} of ${run.coverage.length} sources`);
  }
  $("collect-total").textContent = parts.join(" · ");
}

// --- identity -----------------------------------------------------------------------------------

function renderIdentityStatus(status, note) {
  const text = {
    queued: "Accounts are resolved from the anchor first.",
    running: "Resolving the accounts from the anchor…",
    not_implemented: "Identity step not built yet: no account confirmed.",
    skipped: `Identity skipped${note ? ` · ${note}` : ""}.`,
    failed: `Identity failed${note ? ` · ${note}` : ""}.`,
  }[status];
  const hasAccounts = $("accounts").children.length > 0;
  $("identity-status").textContent = status === "done" ? (hasAccounts ? "" : "No accounts found from the anchor.") : text || "";
}

function shortUrl(url) {
  return (url || "").replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
}

function accountRow(account, status, basis, sample) {
  const row = el("li", "account");
  row.dataset.status = status;
  const word = { accepted: "Accepted", unconfirmed: "Unconfirmed", rejected: "Rejected namesake" }[status] || status;
  const handle = el("p", "account-handle");
  const label = account.handle || shortUrl(account.url);
  let text;
  if (sample || !account.url) {
    text = el("span", "handle handle-text", label);
  } else {
    text = el("a", "handle-text", label);
    text.href = account.url;
    text.target = "_blank";
    text.rel = "noopener noreferrer";
  }
  handle.append(platformMark(account.platform || "website"), text);
  row.append(el("span", "account-state", word), handle, el("p", "account-basis", basis));
  return row;
}

function renderIdentity(data, animate) {
  const { accounts = [], rejected = [] } = data;
  const sample = run.mode === "sample";
  const rows = [
    ...accounts.map((a) => accountRow(a, a.status, (a.match_basis || []).join(" · ") || a.status, sample)),
    ...rejected.map((r) => accountRow(r, "rejected", r.reason, sample)),
  ];
  rows.forEach((row, index) => {
    if (animate && !reducedMotion()) {
      row.classList.add("arriving");
      row.style.animationDelay = `${index * 90}ms`;
      // The strike draws after the row has landed.
      row.style.setProperty("--strike-delay", `${index * 90 + 200}ms`);
    } else {
      row.classList.add("settled");
    }
  });
  $("accounts").replaceChildren(...rows);
  renderIdentityStatus("done", "");
}

// --- masthead and ledger ------------------------------------------------------------------------

function renderMasthead() {
  renderStamp($("stamp"), run.mode, { finished: Boolean(run.finishedAt) });
  const now = run.finishedAt ?? stream.now();
  const line = $("runline");
  line.replaceChildren("run ", el("b", "", formatDayTime(run.startedAt)));
  line.append(` · ${formatElapsed(now - run.startedAt)} ${run.finishedAt ? "total" : "elapsed"}`);
  if (run.data.step_pause_s) line.append(el("br"), `slowed ${run.data.step_pause_s} s per step for UI testing`);
  $("ledger-elapsed-label").textContent = run.finishedAt ? "Total" : "Elapsed";
  $("ledger-elapsed").textContent = formatElapsed(now - run.startedAt);
}

function renderLedger(animate) {
  const apify = $("ledger-apify");
  apify.classList.toggle("pending", run.apify === null);
  if (run.apify === null) apify.textContent = "—";
  else tick(apify, run.apify, { format: formatUsd, animate });
  const scribe = $("ledger-scribe");
  scribe.classList.toggle("pending", run.scribe === null);
  if (run.scribe === null) scribe.textContent = "—";
  else tick(scribe, run.scribe, { format: (v) => `${v.toFixed(1)} min`, animate });
  if (!run.finishedAt) $("ledger-aside").textContent = run.apify === null ? "costs arrive per Actor run" : "reported per Actor run";
}

// --- wiring -------------------------------------------------------------------------------------

function onEvent(event, { animate }) {
  if (event.type === "replay.error") {
    showForm(event.data.message);
    return;
  }
  if (event.type === "run.started") {
    begin(event.data);
    return;
  }
  if (!run) return;
  switch (event.type) {
    case "step.status": applyStatus(event, animate); break;
    case "step.item": applyItem(event, animate); break;
    case "step.data": applyData(event, animate); break;
    case "run.finished": finish(event, animate); break;
  }
}

function follow() {
  if (stream) stream.stop();
  wireScreenLinks(sourceQuery(source));
  stream = open(source, onEvent);
}

function showForm(message) {
  $("run").hidden = true;
  $("request").hidden = false;
  const error = $("form-error");
  error.hidden = !message;
  error.textContent = message || "";
}

async function showCredentials() {
  try {
    const { missing } = await health();
    const note = $("credentials");
    note.hidden = missing.length === 0;
    note.textContent = `Missing ${missing.join(", ")}: steps that need ${missing.length > 1 ? "them" : "it"} report skipped.`;
  } catch {
    // The page also works as a static replay without the API.
  }
}

$("request").addEventListener("submit", async (submit) => {
  submit.preventDefault();
  const form = new FormData(submit.target);
  $("form-error").hidden = true;
  $("run-button").disabled = true;
  try {
    const created = await startRun({
      subject: form.get("subject"),
      anchor: form.get("anchor"),
      goal_preset: form.get("goal_preset") || null,
      goal_text: form.get("goal_text") || "",
    });
    history.pushState({}, "", `?run=${created.run_id}`);
    source = { kind: "live", runId: created.run_id };
    follow();
  } catch (failure) {
    showForm(failure.message);
  } finally {
    $("run-button").disabled = false;
  }
});

addEventListener("resize", () => {
  if (run) for (const lane of run.lanes.values()) layoutStrip(lane, false);
});

if (source) follow();
else showCredentials();
