"""Exercise actionable React surfaces against canonical records in an isolated fixture."""

import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

import project_tracker.records as records_module
from project_tracker.__main__ import DashboardServer
from project_tracker.records import CHIEF_PANE, CHIEF_SESSION


def main():
    scratch = Path.cwd() / "tmp"
    scratch.mkdir(exist_ok=True)
    captures = scratch / "control-room-one-page-browser"
    captures.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as directory:
        root = Path(directory).resolve()
        (root / "docs/reports").mkdir(parents=True)
        todo = root / "TODO.md"
        todo.write_text(
            "# Project tasks\n\nKeep original opening prose.\n\n## Build\n"
            "- [ ] Original **prose** [evidence](https://example.com/source)\n\n"
            "## Delivery\n- [ ] Keep publication pending.\n\n## Done\n- [x] Completed fixture milestone\n"
        )
        (root / "docs/learnings.md").write_text("# Learnings\n\nExisting history.\n")
        (root / "docs/atlas-rescope.md").write_text(
            "# Current Atlas direction\n\nArea → Entity → Asset. Next.js and DuckDB are target stack choices, "
            "not a completed migration. Overall overnight ceiling is $120.\n"
        )
        product = root / "docs/product-state.md"
        product.write_text("# Fixture Starwatch\n\nPublic-source evidence.\n\n[Scope](atlas-rescope.md)\n")
        report = root / "docs/reports/hos-control.md"
        report.write_text("## Fixture report\n\nResult: initial fixture progress\n")
        server = DashboardServer(root, 0)
        server.store.migrate()
        archived_card = server.store.mutate(
            {"op": "task.create", "actor": "fixture", "title": "Archived fixture card", "archived": True}
        )["result"]
        server.project.live = lambda names: {
            "observed_at": "2026-10-08T23:40:00Z",
            "agents": [],
            "branches": [],
            "herdr_error": None,
        }
        server.store.chief = lambda refresh=False: {
            "pane_id": CHIEF_PANE,
            "session_id": CHIEF_SESSION,
            "status": "working",
            "observed_at": "2026-10-08T23:40:00Z",
            "connection": "verified",
            "error": None,
        }
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def cli(envelope):
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "project_tracker.cli",
                    "--root",
                    str(root),
                    "mutate",
                    "--no-dispatch",
                    "--json",
                    json.dumps(envelope),
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
            return json.loads(completed.stdout)

        def state():
            return server.store.snapshot(include_project=False, observe=False)

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(server.origin, wait_until="domcontentloaded")

                def navigate(section):
                    container = page.locator("#section-" + section)
                    if section != "tasks" and not container.get_attribute("open") == "":
                        container.locator(":scope > summary").click()
                    container.scroll_into_view_if_needed()

                expect(page.get_by_test_id("unified-workspace")).to_be_visible()
                expect(page.get_by_test_id("kanban")).to_be_visible()
                expect(page.get_by_test_id("product-page")).to_contain_text("Fixture Starwatch")
                assert page.get_by_test_id("project-evidence").count() == 0
                assert page.get_by_test_id("decision-open-decision-subject").count() == 0
                expect(
                    page.get_by_test_id("product-rendered").locator('a[href="/api/source?id=atlas-rescope"]')
                ).to_be_visible()
                completed_id = next(t["id"] for t in state()["tasks"] if t["status"] == "done")
                assert page.get_by_test_id("task-card-" + completed_id).count() == 0
                assert page.get_by_test_id("task-card-" + archived_card["id"]).count() == 0
                page.get_by_label("Completed", exact=True).check()
                expect(page.get_by_test_id("task-card-" + completed_id)).to_be_visible()
                page.get_by_label("Completed", exact=True).uncheck()
                page.get_by_label("Archived", exact=True).check()
                expect(page.get_by_test_id("task-card-" + archived_card["id"])).to_be_visible()
                page.get_by_label("Archived", exact=True).uncheck()
                page.get_by_test_id("product-edit").click()
                draft = "# Daniel draft\n\n**Editable** product.  \n\n<script>window.productInjected=true</script>\n\n[Unsafe](javascript:alert(1))\n\n![Untrusted](https://outside.invalid/image.png)\n"
                page.get_by_test_id("product-markdown-input").fill(draft)
                page.reload(wait_until="domcontentloaded")
                page.get_by_test_id("product-edit").click()
                expect(page.get_by_test_id("product-markdown-input")).to_have_value(draft)
                expect(page.get_by_test_id("product-rendered").get_by_text("Editable", exact=True)).to_be_visible()
                assert page.get_by_test_id("product-rendered").locator('a[href^="javascript:"]').count() == 0
                assert page.get_by_test_id("product-rendered").locator("img, script").count() == 0
                assert page.evaluate("window.productInjected === undefined")
                original = product.read_text()
                product.write_text("# Agent file edit\n\nIndependent addition.\n")
                expect(page.get_by_test_id("product-conflict")).to_be_visible(timeout=12000)
                expect(page.get_by_label("Latest saved product Markdown")).to_have_value(product.read_text())
                expect(page.get_by_test_id("product-markdown-input")).to_have_value(draft)
                expect(page.get_by_test_id("product-save")).to_be_disabled()
                page.reload(wait_until="domcontentloaded")
                page.get_by_test_id("product-edit").click()
                expect(page.get_by_test_id("product-conflict")).to_be_visible()
                expect(page.get_by_test_id("product-markdown-input")).to_have_value(draft)
                page.get_by_role("button", name="I reviewed latest; keep my draft", exact=True).click()
                merged = draft + "\nIndependent addition retained after review.\n"
                page.get_by_test_id("product-markdown-input").fill(merged)
                page.get_by_test_id("product-save").click()
                expect(page.get_by_test_id("product-markdown-input")).not_to_be_visible()
                assert product.read_text() == merged
                assert any(
                    f.read_text() == "# Agent file edit\n\nIndependent addition.\n"
                    for f in (root / "tmp/control-room/product-history").glob("*.md")
                )
                assert original != product.read_text()
                page.reload(wait_until="domcontentloaded")
                expect(page.get_by_test_id("product-rendered")).to_contain_text(
                    "Independent addition retained after review"
                )
                product.write_text("# Agent updated product\n\nUpdated from the exact local file.\n")
                expect(page.get_by_test_id("product-rendered")).to_contain_text("Agent updated product", timeout=12000)
                page.screenshot(path=str(captures / "one-page-desktop.png"), full_page=True)
                navigate("context")
                expect(
                    page.get_by_test_id("atlas-rescope").locator('a[href="/api/source?id=atlas-rescope"]')
                ).to_be_visible()
                page.locator("#section-context > summary").click()
                assert page.locator(".freeze").count() == 0
                navigate("tasks")
                page.get_by_test_id("task-create").click()
                page.get_by_test_id("task-title").fill("Browser-created card")
                page.get_by_test_id("task-description").fill(
                    "A real <script>window.injected=true</script> persisted description"
                )
                page.get_by_label("Evidence — one link or path per line", exact=True).fill("report:hos-control")
                page.get_by_test_id("task-status").select_option("ready")
                page.get_by_test_id("task-save").click()
                expect(page.get_by_test_id("task-editor")).not_to_be_visible()
                created = next(task for task in state()["tasks"] if task["title"] == "Browser-created card")
                identifier = created["id"]
                card = page.get_by_test_id("task-card-" + identifier)
                expect(card).to_be_visible()
                assert created["evidence"] == ["report:hos-control"]
                assert "Browser-created card" in todo.read_text()
                assert page.evaluate("window.injected === undefined")
                page.get_by_test_id("task-status-" + identifier).select_option("doing")
                expect(page.get_by_test_id("column-doing")).to_contain_text("Browser-created card")
                expect(card).to_have_attribute("draggable", "true")
                # Position both columns before starting the native drag; target auto-scroll would move the source.
                page.get_by_test_id("kanban").evaluate("element => { element.scrollLeft = 0; }")
                source_box = card.bounding_box()
                target_box = page.get_by_test_id("column-review").get_by_role("heading").bounding_box()
                assert source_box and target_box
                page.mouse.move(source_box["x"] + 8, source_box["y"] + 8)
                page.mouse.down()
                page.mouse.move(source_box["x"] + 24, source_box["y"] + 18, steps=4)
                page.mouse.move(target_box["x"] + 20, target_box["y"] + 8, steps=10)
                page.mouse.up()
                expect(page.get_by_test_id("column-review")).to_contain_text("Browser-created card")
                page.reload(wait_until="domcontentloaded")
                navigate("tasks")
                expect(page.get_by_test_id("column-review")).to_contain_text("Browser-created card")

                # Agent update reaches an open browser without destroying its draft, then conflicts safely.
                page.get_by_test_id("task-edit-" + identifier).click()
                page.get_by_test_id("task-description").fill("Unsaved Daniel draft")
                cli({"op": "task.update", "id": identifier, "patch": {"owner": "CLI agent"}})
                expect(page.get_by_text("This task changed since you opened it.", exact=False)).to_be_visible(
                    timeout=12000
                )
                assert page.get_by_test_id("task-description").input_value() == "Unsaved Daniel draft"
                page.get_by_test_id("task-save").click()
                expect(page.get_by_test_id("conflict-banner")).to_be_visible()
                page.get_by_role("button", name="Reapply draft to latest").click()
                expect(page.get_by_test_id("task-editor")).not_to_be_visible()
                latest = next(task for task in state()["tasks"] if task["id"] == identifier)
                assert latest["owner"] == "CLI agent", latest
                assert latest["description"] == "Unsaved Daniel draft"
                page.get_by_test_id("task-edit-" + identifier).click()
                page.get_by_label("Comment", exact=True).fill("A retained one-page comment")
                page.get_by_role("button", name="Add comment", exact=True).click()
                expect(page.get_by_test_id("task-editor")).to_contain_text("A retained one-page comment")
                expect(
                    page.get_by_test_id("task-editor").locator('a[href="/api/source?id=report%3Ahos-control"]')
                ).to_be_visible()
                page.get_by_role("button", name="Close editor", exact=True).click()
                original = state()["tasks"][0]
                page.get_by_test_id("task-edit-" + original["id"]).click()
                page.get_by_label("Owner", exact=True).fill("Daniel")
                page.get_by_test_id("task-save").click()
                expect(page.get_by_test_id("task-editor")).not_to_be_visible()
                assert "Original **prose** [evidence](https://example.com/source)" in todo.read_text()

                # Existing and custom choices save auditable records, with no selected action execution.
                navigate("decisions")
                page.get_by_test_id("decision-open-decision-subject").click()
                page.get_by_test_id("decision-option-fiala").check()
                page.get_by_test_id("decision-rationale").fill("Fixture decision rationale")
                page.get_by_test_id("decision-save").click()
                expect(page.get_by_test_id("decision-editor")).not_to_be_visible()
                page.get_by_test_id("decision-open-decision-subject").click()
                page.get_by_text("Enter another choice", exact=True).click()
                page.get_by_test_id("decision-custom").fill("Fixture subject + anchor")
                page.get_by_test_id("decision-save").click()
                expect(page.get_by_test_id("decision-editor")).not_to_be_visible()
                assert "Fixture subject + anchor" in (root / "docs/learnings.md").read_text()
                assert all(m["status"] == "held" for m in state()["messages"])
                page.get_by_role("button", name="New decision", exact=True).click()
                page.get_by_label("Decision title", exact=True).fill("Fixture new decision")
                page.get_by_label("Options — label | detail, one per line", exact=True).fill("A | First\nB | Second")
                page.get_by_role("button", name="Create decision", exact=True).click()
                expect(page.get_by_test_id("decision-editor")).not_to_be_visible()
                expect(page.get_by_text("Fixture new decision", exact=True)).to_be_visible()

                navigate("architecture")
                expect(page.get_by_test_id("architecture-flow")).to_be_visible()
                expect(page.locator(".react-flow__node")).to_have_count(
                    sum(n["data"]["group"] == "product" for n in state()["architecture"]["nodes"])
                )
                page.get_by_label("Architecture group", exact=True).select_option("product")
                page.get_by_label("Select architecture node", exact=True).select_option("identity")
                panel = page.get_by_test_id("node-details-identity")
                panel.get_by_label("Node feedback", exact=True).fill("Persist this actual node feedback")
                panel.get_by_role("button", name="Add node feedback", exact=True).click()
                expect(panel).to_contain_text("Persist this actual node feedback")
                old = next(node for node in state()["architecture"]["nodes"] if node["id"] == "identity")["position"]
                node = page.locator('.react-flow__node[data-id="identity"]')
                box = node.bounding_box()
                assert box
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.mouse.down()
                page.mouse.move(box["x"] + box["width"] / 2 + 65, box["y"] + box["height"] / 2 + 30, steps=8)
                page.mouse.up()
                expect(page.get_by_text("Saved.", exact=True)).to_be_visible()
                assert next(n for n in state()["architecture"]["nodes"] if n["id"] == "identity")["position"] != old
                page.reload(wait_until="domcontentloaded")
                navigate("architecture")
                page.get_by_label("Select architecture node", exact=True).select_option("identity")
                expect(page.get_by_test_id("node-details-identity")).to_contain_text(
                    "Persist this actual node feedback"
                )
                page.screenshot(path=str(captures / "architecture-desktop.png"), full_page=True)

                navigate("live")
                expect(page.get_by_test_id("quiet-policy")).to_contain_text("worker pings")
                page.get_by_test_id("message-compose").fill("Unsent chief draft")
                page.reload(wait_until="domcontentloaded")
                navigate("live")
                expect(page.get_by_test_id("message-compose")).to_have_value("Unsent chief draft")
                report.write_text("## Fresh fixture report\n\nResult: incremental report change observed\n")
                expect(page.get_by_test_id("activity-stream")).to_contain_text(
                    "incremental report change observed", timeout=12000
                )
                page.get_by_test_id("message-compose").fill("Harmless fixture ping")
                page.get_by_test_id("message-send").click()
                expect(page.get_by_test_id("message-compose")).to_have_value("")
                # Only the Herdr transport is faked here; persistence, UI, CLI ack and state stream are real.
                adapter = SimpleNamespace(
                    run=lambda argv, **kwargs: subprocess.CompletedProcess(
                        argv, 0, '{"result":{"submitted":true}}', ""
                    ),
                    SubprocessError=subprocess.SubprocessError,
                )
                with patch.object(records_module, "subprocess", adapter):
                    assert server.store.dispatch_pending() == 1
                message = next(m for m in state()["messages"] if m["text"] == "Harmless fixture ping")
                expect(page.get_by_test_id("message-" + message["id"])).to_contain_text("Submitted", timeout=12000)
                cli({"op": "message.ack", "id": message["id"], "reply": "Explicit fixture reply"})
                expect(page.get_by_test_id("message-" + message["id"])).to_contain_text("Acknowledged", timeout=12000)
                expect(page.get_by_test_id("message-" + message["id"])).to_contain_text("Explicit fixture reply")
                # Reopening never automatically releases an old worker notification.
                held = next(m for m in state()["messages"] if m["status"] == "held")
                page.once("dialog", lambda dialog: dialog.accept())
                page.get_by_test_id("quiet-toggle").click()
                expect(page.get_by_test_id("quiet-policy")).to_contain_text("Previously held messages remain held")
                with patch.object(records_module, "subprocess", adapter):
                    assert server.store.dispatch_pending() == 0
                page.once("dialog", lambda dialog: dialog.accept())
                page.get_by_test_id("message-" + held["id"]).get_by_role("button", name="Release held message").click()
                expect(page.get_by_test_id("message-" + held["id"])).to_contain_text("Queued", timeout=12000)
                with patch.object(records_module, "subprocess", adapter):
                    assert server.store.dispatch_pending() == 1
                expect(page.get_by_test_id("message-" + held["id"])).to_contain_text("Submitted", timeout=12000)
                page.once("dialog", lambda dialog: dialog.accept())
                page.get_by_test_id("quiet-toggle").click()
                expect(page.get_by_test_id("quiet-policy")).to_contain_text("worker pings")
                page.set_viewport_size({"width": 390, "height": 844})
                for tab in ("architecture", "tasks", "decisions", "live", "context"):
                    navigate(tab)
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), tab
                    page.screenshot(path=str(captures / f"{tab}-narrow.png"), full_page=True)
                for section in ("architecture", "decisions", "live", "context"):
                    container = page.locator("#section-" + section)
                    if container.get_attribute("open") == "":
                        container.locator(":scope > summary").click()
                page.get_by_test_id("product-edit").click()
                page.get_by_test_id("product-markdown-input").fill("# Narrow saved product\n\nEditable on a phone.\n")
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                page.screenshot(path=str(captures / "product-editor-narrow.png"), full_page=True)
                page.get_by_test_id("product-save").click()
                expect(page.get_by_test_id("product-rendered")).to_contain_text("Narrow saved product")
                page.reload(wait_until="domcontentloaded")
                expect(page.get_by_test_id("product-rendered")).to_contain_text("Editable on a phone")
                assert state()["communication"]["quiet"] is True
                page.screenshot(path=str(captures / "one-page-narrow.png"), full_page=True)
                assert not errors, errors
                browser.close()
                print(
                    (
                        "Browser passed: exact-file Markdown render/edit/save/reload, retained draft and "
                        "external-file conflict/review/recovery, inert content, agent-file stream, desktop/narrow; "
                        "real Kanban create/move/drop/reload, CLI "
                        "refresh/draft/conflict/reapply, prose preservation, "
                        "options/custom/new decision, XYFlow layout/feedback, incremental "
                        "reports, durable composer/submit/CLI ack, narrow views; no page "
                        "errors."
                    )
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
