"""Exercise automatic browser refresh and inert notes on a disposable localhost fixture."""

import json
import os
import tempfile
import threading
from datetime import timedelta
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from project_tracker.__main__ import DashboardServer
from project_tracker.model import DEADLINE
from tests.test_tracker import IN_FLIGHT, RANK_ENTRY


def main():
    scratch = Path.cwd() / "tmp"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as directory:
        root = Path(directory)
        (root / "docs/reports").mkdir(parents=True)
        todo = root / "TODO.md"
        todo.write_text(
            IN_FLIGHT + "## Build\n- [ ] 02:45 — Waiting on briefs\n## Next decision\n- [ ] Pick a subject\n"
        )
        report = root / "docs/reports/hos-brief.md"
        report.write_text("## Old report\n\nResult: still working, according to old prose\n")
        now = DEADLINE + timedelta(minutes=1)
        os.utime(report, ((now - timedelta(minutes=30)).timestamp(),) * 2)
        server = DashboardServer(root, 0)
        live = {
            "observed_at": now.isoformat(),
            "agents": [{"name": "hos-brief", "agent_status": "working"}],
            "branches": [],
            "herdr_error": None,
        }
        server.project.live = lambda worker_names: live
        snapshot = server.project.snapshot
        server.project.snapshot = lambda: snapshot(now)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as browser_api:
                browser = browser_api.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(server.origin, wait_until="networkidle")
                page.wait_for_selector(".worker")
                assert page.locator("#countdown").inner_text() == "Freeze passed"
                assert "report missing / stale" in page.locator(".worker .pill").first.inner_text()
                page.locator("#note").fill("Unsaved note survives refresh")
                live["agents"][0]["agent_status"] = "idle"
                todo.write_text(IN_FLIGHT + "## Build\n- [x] Brief fixture is complete. Evidence: tests passed\n")
                expect(page.locator(".worker .pill").first).to_have_text("Idle", timeout=12000)
                assert "Brief fixture is complete" in page.locator("#completed").inner_text()
                assert page.locator("#note").input_value() == "Unsaved note survives refresh"
                live["agents"].append({"name": "hos-rank", "agent_status": "done"})
                (root / "docs/reports/hos-rank.md").write_text(
                    "Result: rank fixture prepared\n"
                    "Evidence: tmp/prioritization/{universe.json,summary.json,summary.csv,manifest.json}\n"
                )
                todo.write_text(todo.read_text().replace("\n## Build", "\n" + RANK_ENTRY + "\n## Build"))
                expect(page.locator(".worker")).to_have_count(5, timeout=12000)
                expect(page.locator(".worker").filter(has_text="hos-rank").locator(".pill")).to_have_text(
                    "Turn finished"
                )
                todo.write_text(todo.read_text().replace(RANK_ENTRY, ""))
                expect(page.locator(".worker")).to_have_count(4, timeout=12000)
                note = "<script>window.injected=true</script> a local question"
                page.locator("#note").fill(note)
                page.get_by_role("button", name="Save local note").click()
                expect(page.locator("#note-result")).to_contain_text("Saved locally")
                expect(page.locator("#notes")).to_contain_text("a local question", timeout=12000)
                assert page.evaluate("window.injected === undefined")
                assert "Pending acknowledgement" in page.locator("#notes").inner_text()
                assert json.loads((root / "tmp/project-tracker/inbox.jsonl").read_text())["text"] == note
                page.locator("#completed [data-source]").click()
                expect(page.locator("#evidence-body")).to_contain_text("Brief fixture")
                assert page.locator("#evidence").is_visible()
                page.get_by_role("button", name="Close", exact=True).first.click()
                page.set_viewport_size({"width": 390, "height": 844})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                assert not errors, errors
                print(
                    "Browser passed: automatic worker arrival/removal + done state, TODO refresh, stale report, "
                    "passed deadline, preserved input, "
                    "inert persisted notes, evidence preview, narrow layout; no JavaScript errors."
                )
                context.close()
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
