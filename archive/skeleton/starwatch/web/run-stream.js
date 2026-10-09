// Shared by every screen: start a run, and follow a run's events from the first one.
// Events are replayed from seq 1 on every connect, so a screen opened mid-run or after the run
// builds the same state. See starwatch/events.py for the event shapes.

export async function startRun(request) {
  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = Array.isArray(body.detail)
      ? body.detail.map((d) => `${d.loc?.at(-1)}: ${d.msg}`).join("; ")
      : body.detail;
    throw new Error(detail || `Run could not start (${response.status})`);
  }
  return response.json();
}

export function followRun(runId, onEvent) {
  const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
  source.onmessage = (message) => {
    const event = JSON.parse(message.data);
    onEvent(event);
    if (event.type === "run.finished") source.close();
  };
  return () => source.close();
}

export async function health() {
  const response = await fetch("/api/health");
  return response.json();
}
