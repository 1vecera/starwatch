// S1: research input and live progress. Built only from run events; all collected text goes in
// through textContent, never innerHTML.
import { followRun, health, startRun } from "./run-stream.js";

const $ = (id) => document.getElementById(id);
const STATUS_TEXT = {
  queued: "queued",
  running: "running",
  done: "done",
  failed: "failed",
  skipped: "skipped",
  not_implemented: "not implemented",
};
const PLATFORM_SHORT = { website: "WEB", facebook: "FB", instagram: "IG", tiktok: "TT", youtube: "YT", x: "X" };
const PRESET_NAMES = { G1: "G1 Debate prep", G2: "G2 Respond to this post", G3: "G3 Background check" };

let stopFollowing = null;
let clock = null;
let run = null; // { startedAt, finishedAt, mode, pause, plan: Map(stepId -> descriptor) }

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function formatTime(iso) {
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Prague",
  });
}

function formatElapsed(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// --- masthead -------------------------------------------------------------------------------

function renderRunline(costs) {
  const line = $("runline");
  const finished = Boolean(run.finishedAt);
  line.dataset.state = run.mode;
  line.dataset.finished = finished ? "yes" : "no";
  $("state-label").textContent = run.mode === "cached" ? "Cached" : "Live";
  const parts = [
    `run ${formatTime(run.startedAt)}`,
    `${formatElapsed((finished ? Date.parse(run.finishedAt) : Date.now()) - Date.parse(run.startedAt))} ${finished ? "total" : "elapsed"}`,
  ];
  if (costs) parts.push(`Apify $${costs.apify_usd.toFixed(2)}`, `Scribe ${costs.scribe_minutes.toFixed(1)} min`);
  if (run.pause) parts.push(`slowed ${run.pause} s per step for UI testing`);
  $("run-meta").textContent = parts.join(" · ");
}

async function showCredentials() {
  const { missing } = await health();
  const note = $("credentials");
  note.hidden = missing.length === 0;
  note.textContent = `Missing ${missing.join(", ")}: steps that need ${missing.length > 1 ? "them" : "it"} report skipped.`;
}

// --- plan -------------------------------------------------------------------------------------

function laneFor(step) {
  const lane = el("li", "lane");
  lane.dataset.step = step.id;
  lane.dataset.status = step.status;
  lane.dataset.platform = step.platform;
  lane.append(
    el("span", "lane-platform", PLATFORM_SHORT[step.platform] || step.platform),
    el("span", "lane-label", step.label),
    el("code", "lane-actor", step.actor),
    el("span", "lane-status", STATUS_TEXT[step.status]),
    el("span", "lane-count", step.max_items ? `0 of max ${step.max_items}` : ""),
    el("ol", "lane-strip"),
    el("p", "lane-note", ""),
  );
  return lane;
}

function rowFor(step) {
  const row = el("li", "step");
  row.dataset.step = step.id;
  row.dataset.status = step.status;
  row.append(
    el("span", "step-label", step.label),
    el("span", "step-status", STATUS_TEXT[step.status]),
    el("span", "step-count", ""),
    el("span", "step-note", ""),
  );
  return row;
}

function renderPlan(plan) {
  $("lanes").replaceChildren(...plan.filter((s) => s.group === "collect").map(laneFor));
  $("downstream").replaceChildren(...plan.filter((s) => s.group === "downstream").map(rowFor));
  // Identity has two rows: the anchor read before collection and the look-alike check beside it.
  $("identity-step").replaceChildren(...plan.filter((s) => s.group === "identity").map(rowFor));
  $("accounts").replaceChildren();
  $("rejected").replaceChildren();
}

// --- events -----------------------------------------------------------------------------------

function stepNode(stepId) {
  return document.querySelector(`[data-step="${CSS.escape(stepId)}"]`);
}

function applyStatus(event) {
  const node = stepNode(event.step);
  if (!node) return;
  node.dataset.status = event.status;
  const isLane = node.classList.contains("lane");
  node.querySelector(isLane ? ".lane-status" : ".step-status").textContent = STATUS_TEXT[event.status] || event.status;
  if (event.count !== undefined) {
    const step = run.plan.get(event.step);
    node.querySelector(isLane ? ".lane-count" : ".step-count").textContent =
      isLane && step.max_items ? `${event.count} of max ${step.max_items}` : String(event.count);
  }
  if (event.note) node.querySelector(isLane ? ".lane-note" : ".step-note").textContent = event.note;
}

function applyItem(event) {
  const lane = stepNode(event.step);
  if (!lane) return;
  const { item } = event;
  const entry = el("li", "item");
  entry.dataset.kind = item.kind;
  const link = el("a");
  link.href = item.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.title = [item.published_at, item.text].filter(Boolean).join(" · ");
  if (item.thumb && item.media_kind === "image") {
    const img = el("img");
    img.src = item.thumb;
    img.alt = item.text ? item.text.slice(0, 80) : `${item.platform} ${item.kind}`;
    img.loading = "lazy";
    if (item.width && item.height) img.style.aspectRatio = `${item.width} / ${item.height}`;
    link.append(img);
  } else {
    // No image collected: say what arrived instead of drawing a placeholder.
    link.append(el("span", "item-text", item.published_at ? item.published_at.slice(0, 10) : item.kind));
  }
  entry.append(link);
  lane.querySelector(".lane-strip").append(entry);
  if (event.count !== undefined) applyStatus({ ...event, status: lane.dataset.status });
}

function applyData(event) {
  if (event.step === "identity") {
    const { accounts = [], rejected = [] } = event.data;
    $("accounts").replaceChildren(...accounts.map((a) => {
      const li = el("li", "account");
      li.dataset.status = a.status;
      const link = el("a", "account-link", `${PLATFORM_SHORT[a.platform] || a.platform} ${a.handle || a.url}`);
      link.href = a.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      li.append(el("span", "account-mark", a.status === "accepted" ? "✓" : "?"), link,
        el("span", "account-basis", (a.match_basis || []).join(", ") || a.status));
      return li;
    }));
    $("rejected").replaceChildren(...rejected.map((r) => {
      const li = el("li", "rejected-account");
      const link = el("a", "account-link", r.url);
      link.href = r.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      li.append(el("span", "account-mark", "✗"), link, el("span", "account-basis", `rejected: ${r.reason}`));
      return li;
    }));
    return;
  }
  const node = stepNode(event.step);
  if (node && event.data.summary) node.querySelector(".step-note").textContent = event.data.summary;
}

function applyFinished(event) {
  run.finishedAt = event.data.finished_at;
  clearInterval(clock);
  for (const row of event.data.coverage || []) {
    const lane = document.querySelector(`.lane[data-platform="${CSS.escape(row.platform)}"]`);
    if (!lane) continue;
    lane.dataset.coverage = row.status;
    const reason = row.note ? ` · ${row.note}` : "";
    lane.querySelector(".lane-note").textContent = `${row.status.replace("_", " ")}${reason}`;
  }
  renderRunline(event.data.costs);
  const counts = {};
  for (const node of document.querySelectorAll("[data-step]")) {
    counts[node.dataset.status] = (counts[node.dataset.status] || 0) + 1;
  }
  const tally = Object.entries(counts).map(([s, n]) => `${n} ${STATUS_TEXT[s] || s}`).join(" · ");
  $("receipt").textContent = `Run ${event.status} · ${tally}`;
  $("run-button").disabled = false;
}

function onEvent(event) {
  switch (event.type) {
    case "run.started": {
      const d = event.data;
      run = {
        startedAt: d.started_at, finishedAt: null, mode: d.mode, pause: d.step_pause_s,
        plan: new Map(d.plan.map((s) => [s.id, s])),
      };
      $("run").hidden = false;
      const goal = `${PRESET_NAMES[d.goal.preset]}${d.goal.text ? ` · ${d.goal.text}` : ""}`;
      const basis = d.goal_basis === "chosen" ? "" : ` (${d.goal_basis})`;
      $("run-request").textContent = `${d.subject} · anchored by ${d.anchor} · goal ${goal}${basis}`;
      $("receipt").textContent = "";
      renderPlan(d.plan);
      renderRunline();
      clearInterval(clock);
      clock = setInterval(() => renderRunline(), 1000);
      break;
    }
    case "step.status": applyStatus(event); break;
    case "step.item": applyItem(event); break;
    case "step.data": applyData(event); break;
    case "run.finished": applyFinished(event); break;
  }
}

function follow(runId) {
  if (stopFollowing) stopFollowing();
  stopFollowing = followRun(runId, onEvent);
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
    follow(created.run_id);
  } catch (failure) {
    error.textContent = failure.message;
    error.hidden = false;
    $("run-button").disabled = false;
  }
});

showCredentials();
const existing = new URLSearchParams(location.search).get("run");
if (existing) follow(existing);
