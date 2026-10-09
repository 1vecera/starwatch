"use strict";
const $ = (id) => document.getElementById(id);
const zone = {
  timeZone: "Europe/Prague",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
};
const at = (value) =>
  value
    ? new Intl.DateTimeFormat("en-GB", zone).format(new Date(value))
    : "unknown";
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const add = (node, ...children) => {
  children.filter(Boolean).forEach((child) => node.append(child));
  return node;
};
const pill = (text, tone = "gray") => el("span", `pill ${tone}`, text);
const money = (value) =>
  value === null || value === undefined ? "Unknown" : `$${value.toFixed(2)}`;
const fresh = (value) =>
  !value || !value.at
    ? "Missing evidence"
    : `${value.state === "fresh" ? "Updated" : value.state === "future" ? "Future file timestamp" : "Stale"} ${at(value.at)} · ${Math.floor(value.age_seconds / 60)}m ago`;
const short = (text, limit = 230) =>
  text.length > limit
    ? `${text.slice(0, limit).replace(/\s+\S*$/, "")}…`
    : text;
const sourceButton = (id, label = "Evidence ↗") => {
  const button = el("button", "text-button", label);
  button.dataset.source = id;
  return button;
};
let current = null;
let serverClock = 0;
let receivedClock = 0;
let signature = "";
const states = {
  active: ["Working", "green"],
  active_stale: ["Working · report missing / stale", "amber"],
  idle: ["Idle", "amber"],
  completed: ["Turn finished", "gray"],
  absent: ["Not in live session", "gray"],
  unknown: ["Activity unknown", "amber"],
  blocked: ["Blocked", "red"],
  stopped: ["Stopped", "gray"],
  error: ["Error", "red"],
};

function renderReadiness(state) {
  $("readiness").replaceChildren(
    ...state.readiness.map((item) => {
      const article = el("article");
      add(
        article,
        add(
          el("div", "title-row"),
          el("h2", "", item.title),
          pill(
            `${item.done}/${item.total} recorded done`,
            item.state === "reported_complete" ? "green" : "amber",
          ),
        ),
      );
      add(article, el("p", "", short(item.next, 210)));
      return article;
    }),
  );
  $("completed").replaceChildren(
    ...state.completed
      .slice(0, 3)
      .map((task) =>
        add(
          el("div", "item"),
          pill(
            task.status === "done_evidence"
              ? "Done · evidence recorded"
              : "Done · reported",
            task.status === "done_evidence" ? "green" : "gray",
          ),
          el("p", "", short(task.text, 195)),
          sourceButton("todo", `TODO · line ${task.line} ↗`),
        ),
      ),
  );
}

function renderWorkers(state) {
  $("worker-observed").textContent =
    `Herdr observed ${at(state.live.observed_at)}`;
  $("workers").replaceChildren(
    ...state.workers.map((worker) => {
      const [label, tone] = states[worker.state] || states.unknown;
      const identity = add(
        el("div"),
        el("h3", "", worker.title),
        el("span", "name", worker.name),
        pill(label, tone),
        el("span", "fresh", fresh(worker.freshness)),
      );
      const content = add(
        el("div"),
        el("p", "", short(worker.progress, 340)),
        sourceButton(worker.source, "Last progress & evidence ↗"),
      );
      if (worker.needs)
        add(content, el("p", "caption", `Question: ${worker.needs}`));
      return add(el("article", "worker"), identity, content);
    }),
  );
}

function renderDecisions(state) {
  $("decision-count").textContent = `${state.decisions.length} open in TODO`;
  $("decisions").replaceChildren(
    ...state.decisions
      .slice(0, 4)
      .map((task) =>
        add(
          el("div", "item"),
          el("div", "section", task.section),
          el("p", "", short(task.text, 270)),
          sourceButton("todo", `TODO · line ${task.line} ↗`),
        ),
      ),
  );
  if (state.decisions.length > 4)
    $("decisions").append(
      sourceButton(
        "todo",
        `+ ${state.decisions.length - 4} more decision checkpoints ↗`,
      ),
    );
  if (!state.decisions.length)
    $("decisions").append(
      el("p", "empty", "No open decision checkpoints found in TODO."),
    );
  $("blockers").replaceChildren(
    ...state.blockers
      .slice(0, 3)
      .map((task) =>
        add(
          el("div", "item"),
          el("p", "", short(task.text, 270)),
          sourceButton("todo"),
        ),
      ),
  );
  const missing = state.workers.filter((w) => w.freshness.state !== "fresh");
  if (missing.length)
    $("blockers").append(
      add(
        el("div", "item"),
        el(
          "p",
          "",
          `Progress evidence needs refresh: ${missing.map((w) => w.name).join(", ")}. Live activity is shown separately.`,
        ),
      ),
    );
  if (!state.blockers.length && !missing.length)
    $("blockers").append(
      el(
        "p",
        "empty",
        "No explicit blocker matched in TODO. Open checkpoints still apply.",
      ),
    );
}

function renderMilestones(state) {
  $("milestones").replaceChildren(
    ...state.milestones.map((task) =>
      add(
        el("div", `milestone${task.overdue ? " overdue" : ""}`),
        el("span", "time", at(task.due)),
        el("p", "", short(task.text, 230)),
        pill(
          task.overdue ? "Past checkpoint · open" : "Open",
          task.overdue ? "red" : "gray",
        ),
      ),
    ),
  );
  if (!state.milestones.length)
    $("milestones").append(
      el(
        "p",
        "empty",
        "No timed open checkpoints found. Inspect TODO for untimed work.",
      ),
    );
}

function renderChanges(state) {
  $("changes").replaceChildren(
    ...state.changes.slice(0, 5).map((item) => {
      const source = state.sources.find((s) => s.id === item.source);
      return add(
        el("article", "change"),
        el("h3", "", `${item.source.replace("report:", "")} · ${item.heading}`),
        el("p", "", short(item.progress, 340)),
        el("p", "evidence", short(item.evidence, 230)),
        add(
          el("div", "change-bottom"),
          el("span", "fresh", fresh(item.freshness)),
          sourceButton(
            item.source,
            source?.future_headings?.length
              ? "Future heading flagged · inspect ↗"
              : "Report ↗",
          ),
        ),
      );
    }),
  );
}

function renderBudgets(state) {
  $("budgets").replaceChildren(
    ...state.budgets.map((item) => {
      const amounts = el("div", "amounts");
      [
        ["SPENT", item.spent],
        ["RESERVED", item.reserved],
        ["REMAINING", item.remaining],
      ].forEach(([label, value]) =>
        amounts.append(
          add(
            el("div"),
            el("small", "", label),
            el("strong", "", money(value)),
          ),
        ),
      );
      const card = add(
        el("div", "budget"),
        el("h3", "", `${item.name}${item.cap ? ` · cap $${item.cap}` : ""}`),
        amounts,
        el("p", "", item.basis),
        el("span", "fresh", fresh(item.freshness)),
      );
      if (item.reservation_freshness)
        add(
          card,
          el(
            "p",
            "fresh",
            `Reservation file: ${fresh(item.reservation_freshness)}`,
          ),
        );
      return card;
    }),
  );
}

function renderPublication(state) {
  const tasks = state.tasks.filter(
    (t) =>
      t.section.startsWith("Delivery") &&
      /repository publicly|Save.*URL|Upload|Submit.*HQ|prize box/i.test(t.text),
  );
  $("publication").replaceChildren(
    ...tasks.map((task) =>
      add(
        el("div", "item"),
        pill(
          task.done ? "Done · TODO record" : "Pending",
          task.done ? "green" : "gray",
        ),
        el("p", "", short(task.text, 190)),
      ),
    ),
  );
}

function imageButton(screen, thumbnail = false) {
  const button = el("button", thumbnail ? "screen" : "text-button");
  button.dataset.image = screen.id;
  button.dataset.name = `${screen.group} · ${screen.name}`;
  if (thumbnail) {
    const img = el("img");
    img.src = `/api/screenshot?id=${encodeURIComponent(screen.id)}`;
    img.alt = `${screen.group} existing screenshot ${screen.name}`;
    img.loading = "lazy";
    add(
      button,
      img,
      add(
        el("div"),
        el("p", "", `${screen.group} · ${screen.name}`),
        el(
          "span",
          "fresh",
          `Captured ${at(screen.freshness.at)} · existing evidence`,
        ),
      ),
    );
  } else button.textContent = `${screen.group} · ${screen.name}`;
  return button;
}

function renderScreens(state) {
  const selected = [];
  ["vis-press", "vis-atlas", "collect"].forEach((group) => {
    const candidates = state.screenshots.filter((s) => s.group === group);
    const item =
      candidates.find((s) =>
        /s3-real|s3-draft-done|fiala-3-finished\.png/.test(s.name),
      ) || candidates[0];
    if (item) selected.push(item);
  });
  $("screenshots").replaceChildren(
    ...selected.map((screen) => imageButton(screen, true)),
  );
  $("more-screens").replaceChildren(
    ...state.screenshots.map((screen) => imageButton(screen)),
  );
  $("demos").replaceChildren(
    ...state.demos.map((demo) => {
      const link = el("a", "demo-link", `${demo.name} ↗`);
      link.href = demo.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      return add(link, el("span", "", demo.state));
    }),
  );
}

function renderSources(state) {
  $("history").replaceChildren(
    ...state.history.slice(-3).map((item) => el("p", "", item)),
  );
  $("sources").replaceChildren(
    ...state.sources.map((source) =>
      add(
        el("div", "source-row"),
        sourceButton(source.id, source.name),
        el(
          "span",
          "fresh",
          `${fresh(source.freshness)}${source.future_headings?.length ? ` · future headings: ${source.future_headings.join(", ")}` : ""}`,
        ),
      ),
    ),
  );
  $("branches").replaceChildren(
    add(
      el("div", "branch-list"),
      ...state.live.branches.map((branch) =>
        pill(
          `${branch.name} · ${branch.commit}${branch.dirty ? " · edits" : " · clean tracked files"}`,
        ),
      ),
    ),
  );
}

function renderNotes(state) {
  $("notes").replaceChildren(
    ...state.notes
      .slice(-5)
      .reverse()
      .map((note) =>
        add(
          el("div", "note"),
          el("p", "", note.text),
          el("span", "fresh", `${at(note.at)} · ${note.status}`),
        ),
      ),
  );
}

function tick() {
  if (!current) return;
  const now = new Date(serverClock + Date.now() - receivedClock);
  const seconds = Math.max(
    0,
    Math.floor((new Date(current.freeze.deadline) - now) / 1000),
  );
  const passed = now >= new Date(current.freeze.deadline);
  $("countdown").textContent = passed
    ? "Freeze passed"
    : [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
        .map((n) => String(n).padStart(2, "0"))
        .join(":");
  $("freeze-label").textContent = passed ? "DEADLINE PASSED" : "UNTIL FREEZE";
  $("countdown").parentElement.classList.toggle("passed", passed);
  $("clock").textContent =
    `Now ${new Intl.DateTimeFormat("en-GB", { ...zone, second: "2-digit" }).format(now)} Prague`;
}

async function refresh() {
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw Error(`Server returned ${response.status}`);
    const state = await response.json();
    current = state;
    serverClock = new Date(state.observed_at).getTime();
    receivedClock = Date.now();
    $("connection").textContent = `Updated ${at(state.observed_at)} · auto 5s`;
    $("connection-dot").classList.remove("error");
    $("offline").hidden = !state.live.herdr_error;
    $("offline").textContent = state.live.herdr_error || "";
    $("headline").textContent = short(`Decision / risk: ${state.risk}`, 330);
    // Preserve focus, input and expanded evidence while live observations refresh.
    const nextSignature = JSON.stringify(
      [
        state.tasks,
        state.workers,
        state.changes,
        state.budgets,
        state.notes,
        state.screenshots,
        state.sources,
        state.live.branches,
      ],
      (key, value) => (key === "age_seconds" ? undefined : value),
    );
    if (nextSignature !== signature) {
      renderReadiness(state);
      renderWorkers(state);
      renderDecisions(state);
      renderMilestones(state);
      renderChanges(state);
      renderBudgets(state);
      renderPublication(state);
      renderScreens(state);
      renderSources(state);
      renderNotes(state);
      signature = nextSignature;
    }
    $("worker-observed").textContent =
      `Herdr observed ${at(state.live.observed_at)}`;
    if (document.activeElement !== $("summary"))
      $("summary").value = state.summary;
    tick();
  } catch {
    $("connection").textContent = "Connection lost · retrying";
    $("connection-dot").classList.add("error");
    $("offline").hidden = false;
    $("offline").textContent =
      "Local server unavailable. Displayed evidence is from the last successful refresh.";
  } finally {
    setTimeout(refresh, 5000);
  }
}

document.addEventListener("click", async (event) => {
  const source = event.target.closest("[data-source]");
  if (source) {
    $("evidence-title").textContent = "Loading evidence…";
    $("evidence-body").textContent = "";
    $("evidence").showModal();
    try {
      const response = await fetch(
        `/api/source?id=${encodeURIComponent(source.dataset.source)}`,
      );
      if (!response.ok) throw Error();
      const content = await response.json();
      $("evidence-title").textContent = content.name;
      $("evidence-body").textContent = content.text;
    } catch {
      $("evidence-title").textContent = "Evidence unavailable";
      $("evidence-body").textContent =
        "The source is missing or outside the preview allowlist.";
    }
  }
  const screen = event.target.closest("[data-image]");
  if (screen) {
    $("image-title").textContent = screen.dataset.name;
    $("large-image").src =
      `/api/screenshot?id=${encodeURIComponent(screen.dataset.image)}`;
    $("image-view").showModal();
  }
});
$("close-evidence").onclick = () => $("evidence").close();
$("close-image").onclick = () => $("image-view").close();
$("copy").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("summary").value);
    $("copy-result").textContent = "Copied. Ready for you to send.";
  } catch {
    $("summary").focus();
    $("summary").select();
    $("copy-result").textContent = "Select and copy the summary with Ctrl+C.";
  }
};
$("note-form").onsubmit = async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: $("note").value }),
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error);
    $("note").value = "";
    $("note-result").textContent = "Saved locally · pending acknowledgement";
  } catch (error) {
    $("note-result").textContent = error.message || "Could not save note";
  } finally {
    button.disabled = false;
  }
};
setInterval(tick, 1000);
refresh();
