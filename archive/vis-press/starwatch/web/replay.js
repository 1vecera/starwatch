// Replay harness: plays a recorded event stream at its real pace, so the screens can be designed,
// rehearsed and filmed before (or without) a live run. A recording is JSON Lines with one event per
// line, the same shape as the SSE stream: web/sample/*.jsonl (design data, labelled SAMPLE) or a
// real run's runs/<run_id>/events.jsonl (labelled CACHED).

export async function loadRecording(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`Recording ${url} could not load (${response.status})`);
  const text = await response.text();
  const events = text.split("\n").filter((line) => line.trim()).map((line) => JSON.parse(line));
  if (!events.length || events[0].type !== "run.started") throw new Error(`Recording ${url} does not start with run.started`);
  return events;
}

/**
 * A player that delivers events by their `ts` deltas once start() is called.
 *   speed  pace multiplier; 1 is the recorded pace
 *   at     seconds into the recording to start from; earlier events arrive at once as backlog,
 *          so the screen builds that state without motion
 *   until  seconds into the recording to stop at; the screen then stays still (for stills)
 * onEvent(event, { backlog }) runs for every event. now() is the recording's clock in epoch
 * milliseconds, for elapsed-time displays; it stands still at `until`.
 */
export function createPlayer(events, onEvent, { speed = 1, at = 0, until = Infinity } = {}) {
  const t0 = Date.parse(events[0].ts);
  const offset = (event) => (Date.parse(event.ts) - t0) / 1000;
  let startedWall = null;
  let index = 0;
  let timer = null;
  let stopped = false;
  const clock = () => Math.min(until, at + (startedWall === null ? 0 : ((performance.now() - startedWall) / 1000) * speed));

  const schedule = () => {
    if (stopped || index >= events.length) return;
    const due = offset(events[index]);
    if (due > until) return;
    const waitMs = Math.max(0, ((due - clock()) / speed) * 1000);
    timer = setTimeout(() => {
      const now = clock() + 0.0005;
      while (index < events.length && offset(events[index]) <= now && offset(events[index]) <= until) {
        onEvent(events[index], { backlog: false });
        index += 1;
      }
      schedule();
    }, waitMs);
  };

  return {
    start() {
      startedWall = performance.now();
      while (index < events.length && offset(events[index]) <= Math.min(at, until)) {
        onEvent(events[index], { backlog: true });
        index += 1;
      }
      schedule();
    },
    stop() {
      stopped = true;
      clearTimeout(timer);
    },
    now: () => t0 + clock() * 1000,
  };
}
