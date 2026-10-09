// Where a screen's events come from. Every screen builds itself from the same event shape
// (run.started, step.status, step.item, step.data, run.finished; see starwatch/events.py), whether
// the events come live over SSE or from a recorded stream replayed at its real pace.
//
//   ?run=<run_id>                     live run over SSE; replays from the first event on connect
//   ?replay=<path to .jsonl>          recorded stream at real pace; files under /static/sample/
//                                     are SAMPLE, a real run's /runs/<id>/events.jsonl is CACHED
//   &speed=4                          replay faster (for design work and filming), default 1
//   &at=45                            start the replay 45 s in, without animating what came before
//   &hold=60                          freeze the replay 60 s in (for still frames)
//
// onEvent(event, { animate }) gets animate=false for catch-up events (a finished run opened late,
// or the part of a replay skipped by `at`), so screens move only when data actually arrives.
import { followRun } from "./run-stream.js";

export function sourceFromLocation(search = location.search) {
  const params = new URLSearchParams(search);
  const replay = params.get("replay");
  if (replay) {
    return {
      kind: "replay",
      path: replay,
      sample: /(^|\/)sample\//.test(replay),
      speed: Math.max(0.1, Number(params.get("speed")) || 1),
      at: Math.max(0, Number(params.get("at")) || 0),
      hold: params.has("hold") ? Math.max(0, Number(params.get("hold"))) : null,
    };
  }
  const run = params.get("run");
  if (run) return { kind: "live", runId: run };
  return null;
}

// The query string that opens the same source on another screen.
export function sourceQuery(source) {
  if (!source) return "";
  if (source.kind === "live") return `?run=${encodeURIComponent(source.runId)}`;
  const params = new URLSearchParams({ replay: source.path });
  if (source.speed !== 1) params.set("speed", String(source.speed));
  return `?${params}`;
}

// Mode label for the masthead stamp: live | cached | sample.
export function modeFor(source, started) {
  if (source?.kind === "replay") return source.sample || started?.sample ? "sample" : "cached";
  if (started?.sample) return "sample";
  return started?.mode === "cached" ? "cached" : "live";
}

export function open(source, onEvent) {
  if (source.kind === "live") return openLive(source, onEvent);
  return openReplay(source, onEvent);
}

function openLive(source, onEvent) {
  const opened = Date.now();
  const stop = followRun(source.runId, (event) => {
    // Events older than the connection are catch-up: build the state, do not perform it.
    const age = opened - Date.parse(event.ts);
    onEvent(event, { animate: !(age > 3000) });
  });
  return { stop, now: () => Date.now() };
}

function openReplay(source, onEvent) {
  let events = [];
  let index = 0;
  let timer = null;
  let stopped = false;
  let t0 = 0;
  let wallStart = 0;
  let frozenAt = null;

  const offsetOf = (event) => Date.parse(event.ts) - t0;
  const virtualOffset = () => {
    if (frozenAt !== null) return frozenAt;
    return source.at * 1000 + (performance.now() - wallStart) * source.speed;
  };

  function pump() {
    if (stopped) return;
    const limit = source.hold !== null ? source.hold * 1000 : Infinity;
    const now = Math.min(virtualOffset(), limit);
    while (index < events.length && offsetOf(events[index]) <= now) {
      onEvent(events[index], { animate: true });
      index += 1;
    }
    if (index >= events.length) {
      frozenAt = offsetOf(events[events.length - 1]);
      return;
    }
    const next = offsetOf(events[index]);
    if (next > limit) {
      frozenAt = limit;
      return;
    }
    timer = setTimeout(pump, Math.max(0, (next - now) / source.speed));
  }

  fetch(source.path, { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error(`Replay file not found: ${source.path}`);
      return response.text();
    })
    .then((text) => {
      events = text.split("\n").filter((line) => line.trim()).map((line) => JSON.parse(line));
      if (!events.length) return;
      t0 = Date.parse(events[0].ts);
      // Catch up to `at` without animation, then play the rest at real pace.
      const skip = source.at * 1000;
      while (index < events.length && offsetOf(events[index]) <= skip) {
        onEvent(events[index], { animate: false });
        index += 1;
      }
      wallStart = performance.now();
      pump();
    })
    .catch((error) => onEvent({ type: "replay.error", data: { message: error.message } }, { animate: false }));

  return {
    stop() {
      stopped = true;
      clearTimeout(timer);
    },
    // Virtual wall clock of the recorded run, so elapsed time reads as it did during the run.
    now: () => (events.length ? t0 + virtualOffset() : Date.now()),
  };
}
