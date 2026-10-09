// The masthead and folio every screen carries: the state bug (LIVE, CACHED, SAMPLE), the run clock,
// the edition's cost in the right ear, the dateline, and links between screens that keep the query.
import { PRESET_NAMES, el, longDate, renderStateBug, stateLine, tick, usd } from "./common.js";

const $ = (id) => document.getElementById(id);

export function renderMasthead(ctl, run, idleLine = "Ready for a request") {
  const view = ctl?.view || { state: "idle" };
  renderStateBug($("state-bug"), view);
  $("state-line").textContent = run ? stateLine(view, run, ctl.now()) : idleLine;
}

export function renderFolio(run, desk) {
  const parts = [longDate(run?.startedAt), desk];
  if (run) {
    const goal = run.goal || {};
    parts.push(run.subject, `${PRESET_NAMES[goal.preset] || goal.preset || ""}${goal.text ? ` „${goal.text}“` : ""}`);
  } else {
    parts.push("Public sources only");
  }
  const folio = $("folio-left");
  folio.replaceChildren();
  parts.filter(Boolean).forEach((part, index) => {
    if (index) folio.append(el("span", "sep", "·"));
    folio.append(document.createTextNode(part));
  });
  if (run?.pause) {
    folio.append(el("span", "sep", "·"), el("span", "folio-note", `slowed ${run.pause} s per step for UI testing`));
  }
}

export function resetCosts() {
  const money = $("cost-apify");
  money.textContent = usd(0);
  money.dataset.value = "0";
  $("cost-detail").textContent = "Apify Actors";
}

export function renderCosts(costs, animate) {
  if (!costs) return;
  tick($("cost-apify"), costs.apify_usd || 0, { format: usd, animate });
  const detail = ["Apify Actors"];
  if (costs.scribe_minutes) detail.push(`Scribe ${Number(costs.scribe_minutes).toFixed(1)} min`);
  if (costs.llm_tokens) detail.push(`${Math.round(costs.llm_tokens / 1000)}k model tokens`);
  $("cost-detail").textContent = detail.join(" · ");
}

export function navLinks() {
  for (const a of document.querySelectorAll(".folio-nav a")) {
    a.href = `${a.dataset.nav === "front" ? "/static/s3.html" : "/"}${location.search}`;
  }
}
