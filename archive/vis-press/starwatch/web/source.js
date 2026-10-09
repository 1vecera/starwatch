// Where a screen's events come from, and how honestly to label them.
//   ?run=<run_id>                     the run's SSE stream: LIVE (or CACHED if the run says so)
//   ?replay=<url>[&speed=&at=&until=] a recorded stream at its real pace (replay.js):
//                                     /static/sample/*.jsonl is SAMPLE, a real run's events.jsonl is CACHED
// Events that describe the past (a stream joined mid-run, or a seek) arrive flagged as backlog, so
// screens build that state without motion: things move only when data arrives now.
import { followRun } from "./run-stream.js";
import { createPlayer, loadRecording } from "./replay.js";

const BACKLOG_MS = 4000;

export function sourceFromLocation() {
  const params = new URLSearchParams(location.search);
  const replay = params.get("replay");
  if (replay) {
    return {
      kind: "replay",
      url: replay,
      speed: Number(params.get("speed")) || 1,
      at: Number(params.get("at")) || 0,
      until: params.has("until") ? Number(params.get("until")) : Infinity,
    };
  }
  const run = params.get("run");
  if (run) return { kind: "run", runId: run };
  return { kind: "idle" };
}

/**
 * Connect a screen to its events. Returns a controller { view, now(), stop(), briefUrl, ready }.
 * view = { state: "idle" | "live" | "cached" | "sample", running, speed } is updated in place before
 * the screen sees run.started and run.finished. onEvent(event, { backlog }).
 */
export function connect(source, onEvent) {
  const ctl = {
    view: { state: "idle", running: false, speed: 1 },
    now: () => Date.now(),
    stop() {},
    briefUrl: null,
    ready: Promise.resolve(),
  };
  const observe = (event) => {
    if (event.type === "run.started") {
      const mode = event.data?.mode;
      if (source.kind === "replay") {
        ctl.view.state = mode === "sample" || /\/sample\//.test(source.url) ? "sample" : "cached";
        ctl.view.speed = source.speed;
      } else {
        ctl.view.state = mode === "cached" ? "cached" : mode === "sample" ? "sample" : "live";
      }
      ctl.view.running = true;
    }
    if (event.type === "run.finished") ctl.view.running = false;
  };

  if (source.kind === "run") {
    ctl.briefUrl = `/api/runs/${encodeURIComponent(source.runId)}/brief`;
    ctl.stop = followRun(source.runId, (event) => {
      observe(event);
      onEvent(event, { backlog: Date.now() - Date.parse(event.ts) > BACKLOG_MS });
    });
  } else if (source.kind === "replay") {
    if (/^\/runs\/[^/]+\/events\.jsonl$/.test(source.url)) ctl.briefUrl = source.url.replace(/events\.jsonl$/, "brief.json");
    ctl.ready = loadRecording(source.url).then((events) => {
      const player = createPlayer(
        events,
        (event, meta) => {
          observe(event);
          onEvent(event, meta);
        },
        { speed: source.speed, at: source.at, until: source.until },
      );
      ctl.now = player.now;
      ctl.stop = player.stop;
      player.start();
    });
  }
  return ctl;
}
