"""Offline checks for money conservation and the explicit paid-launch hold."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from czlake import apify_run as budget
from czlake.paths import PROJECT


class BudgetChecks(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "tmp"
        scratch.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="budget-check-", dir=scratch)
        self.root = Path(self.directory.name)
        self.paths = patch.multiple(budget, DATA=self.root, LEDGER=self.root / "ledger.csv",
            STATE=self.root / "state.json", LOCK=self.root / "lock", RAW=self.root / "raw", _h=dict)
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.addCleanup(self.directory.cleanup)

    def seed(self, usd, maximum=0.61):
        row: dict = {field: "" for field in budget.FIELDS}
        row.update(time=datetime.now(UTC).isoformat(), actor="fixture/actor", purpose="offline fixture",
                   run_id="fixture", status="SUCCEEDED", max_total_charge_usd=maximum, usage_total_usd=usd)
        budget._rewrite_ledger([row])

    def response(self, record):
        response = Mock(status_code=201)
        response.json.return_value = {"data": record}
        return response

    def test_hold_prevents_every_http_request(self):
        (self.root / "paid_launch_hold.json").write_text(json.dumps({"reason": "explicit hold"}))
        with patch.object(budget, "reconcile") as reconcile, patch.object(httpx, "post") as post:
            with self.assertRaisesRegex(RuntimeError, "explicit hold"):
                budget.run_actor("fixture/actor", {}, 0.5, "held")
            reconcile.assert_not_called()
            post.assert_not_called()

    def test_active_remaining_cap_is_not_released(self):
        self.seed(0.1)
        record = {"id": "fixture", "status": "RUNNING", "usageTotalUsd": 0.2, "finishedAt": None}
        with patch.object(httpx, "Client") as client:
            client.return_value.__enter__.return_value.get.return_value = self.response(record)
            result = budget.reconcile()
        self.assertAlmostEqual(result["spent_usd"], 0.2)
        self.assertAlmostEqual(result["committed_usd"], 0.61)
        self.assertEqual(result["active_runs"], ["fixture"])

    def test_final_bill_correction_and_settlement_release(self):
        self.seed(0.49755)
        record = {"id": "fixture", "status": "SUCCEEDED", "usageTotalUsd": 0.50005,
                  "finishedAt": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
        with patch.object(httpx, "Client") as client:
            client.return_value.__enter__.return_value.get.return_value = self.response(record)
            first = budget.reconcile()
            self.assertAlmostEqual(first["spent_usd"], 0.50005)
            self.assertAlmostEqual(first["committed_usd"], 0.61)
            record["finishedAt"] = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
            second = budget.reconcile()
        self.assertEqual(second["reserved_usd"], 0)
        self.assertAlmostEqual(second["committed_usd"], 0.50005)
        self.assertAlmostEqual(float(budget.ledger_rows()[0]["running_total_usd"]), 0.50005)

    def test_ambiguous_start_keeps_reservation(self):
        with patch.object(budget, "reconcile"), patch.object(httpx, "post", side_effect=httpx.ReadTimeout("fixture")), \
             self.assertRaises(httpx.ReadTimeout):
            budget.run_actor("fixture/actor", {}, 0.5, "ambiguous")
        self.assertAlmostEqual(budget.committed_usd(), 0.5)

    def test_explicit_start_rejection_releases_reservation(self):
        response = Mock(status_code=400, text="fixture invalid input")
        with patch.object(budget, "reconcile"), patch.object(httpx, "post", return_value=response), \
             self.assertRaisesRegex(RuntimeError, "start failed 400"):
            budget.run_actor("fixture/actor", {}, 0.5, "rejected")
        self.assertEqual(budget.committed_usd(), 0)

    def test_server_error_keeps_ambiguous_reservation(self):
        response = Mock(status_code=500)
        with patch.object(budget, "reconcile"), patch.object(httpx, "post", return_value=response), \
             self.assertRaisesRegex(RuntimeError, "start failed 500"):
            budget.run_actor("fixture/actor", {}, 0.5, "server error")
        self.assertAlmostEqual(budget.committed_usd(), 0.5)

    def test_hold_arriving_during_reconciliation_prevents_start(self):
        def hold():
            (self.root / "paid_launch_hold.json").write_text(json.dumps({"reason": "new hold"}))
        with patch.object(budget, "reconcile", side_effect=hold), patch.object(httpx, "post") as post, \
             self.assertRaisesRegex(RuntimeError, "new hold"):
            budget.run_actor("fixture/actor", {}, 0.5, "held during reconciliation")
        post.assert_not_called()
        self.assertEqual(budget.committed_usd(), 0)

    def test_unknown_remote_status_retains_cap(self):
        self.seed(0.1)
        record = {"id": "fixture", "status": "UNKNOWN", "usageTotalUsd": 0.2, "finishedAt": None}
        with patch.object(httpx, "Client") as client:
            client.return_value.__enter__.return_value.get.return_value = self.response(record)
            result = budget.reconcile()
        self.assertAlmostEqual(result["committed_usd"], 0.61)
        self.assertEqual(result["active_runs"], ["fixture"])

    def test_lost_polling_retains_unknown_run_cap(self):
        record = {"id": "fixture", "status": "RUNNING"}
        with patch.object(budget, "reconcile"), patch.object(httpx, "post", return_value=self.response(record)), \
             patch.object(httpx, "get", side_effect=httpx.ReadError("fixture")), patch.object(budget.time, "sleep"), \
             self.assertRaises(httpx.ReadError):
            budget.run_actor("fixture/actor", {}, 0.5, "lost poll")
        self.assertAlmostEqual(budget.committed_usd(), 0.5)
        self.assertEqual(budget.ledger_rows()[0]["status"], "UNKNOWN")

    def test_cap_refusal_prevents_actor_start(self):
        self.seed(19.9, maximum=19.9)
        with patch.object(budget, "reconcile"), patch.object(httpx, "post") as post:
            with self.assertRaises(budget.CapExceeded):
                budget.run_actor("fixture/actor", {}, 0.2, "over cap")
            post.assert_not_called()
        self.assertAlmostEqual(budget.committed_usd(), 19.9)

    def authorize(self):
        path = self.root / "authorizations/exact.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"authorization_id": "exact", "status": "authorized_prepared",
            "authorized_by": "Daniel", "actor": "fixture/actor", "input_sha256": budget.input_digest({}),
            "authorized_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            "max_total_charge_usd": .07, "purpose": "exact", "supersedes_hold_for_exact_input_only": True}))
        (self.root / "paid_launch_hold.json").write_text(json.dumps({"reason": "broad hold"}))
        return path

    def test_authorized_ambiguous_launch_is_reserved_and_never_replayed(self):
        path = self.authorize()
        with patch.object(budget, "reconcile"), patch.object(httpx, "post", side_effect=httpx.ReadTimeout("fixture")) as post:
            with self.assertRaises(httpx.ReadTimeout):
                budget.run_actor("fixture/actor", {}, .07, "exact", authorization_path=path)
            with self.assertRaisesRegex(RuntimeError, "already attempted"):
                budget.run_actor("fixture/actor", {}, .07, "exact", authorization_path=path)
            self.assertEqual(post.call_count, 1)
        self.assertAlmostEqual(budget.committed_usd(), .07)
        self.assertTrue((self.root / "paid_launch_hold.json").exists())

    def test_authorization_cannot_expand_input_cap_or_purpose(self):
        path = self.authorize()
        with patch.object(budget, "reconcile") as reconcile, patch.object(httpx, "post") as post:
            for inp, maximum, purpose in [({"more": 1}, .07, "exact"), ({}, .08, "exact"), ({}, .07, "broad")]:
                with self.assertRaises(ValueError):
                    budget.run_actor("fixture/actor", inp, maximum, purpose, authorization_path=path)
            reconcile.assert_not_called()
            post.assert_not_called()

    def test_new_hold_revokes_prepared_authorization_before_http(self):
        path = self.authorize()
        (self.root / "paid_launch_hold.json").write_text(json.dumps({"reason": "new pause", "updated_at": datetime.now(UTC).isoformat()}))
        with patch.object(budget, "reconcile") as reconcile, patch.object(httpx, "post") as post:
            with self.assertRaisesRegex(RuntimeError, "newer paid-launch hold"):
                budget.run_actor("fixture/actor", {}, .07, "exact", authorization_path=path)
            reconcile.assert_not_called()
            post.assert_not_called()

    def test_ambiguous_authorized_start_recovers_exact_remote_input_without_post(self):
        path = self.authorize()
        inp = self.root / "input.json"
        inp.write_text("{}")
        auth = json.loads(path.read_text())
        auth["input_path"] = str(inp)
        path.write_text(json.dumps(auth))
        with patch.object(budget, "reconcile"), patch.object(httpx, "post", side_effect=httpx.ReadTimeout("fixture")), \
             self.assertRaises(httpx.ReadTimeout):
            budget.run_actor("fixture/actor", {}, .07, "exact", authorization_path=path)
        listed = self.response({"items": [{"id": "found", "startedAt": datetime.now(UTC).isoformat(), "defaultKeyValueStoreId": "store"}]})
        input_response = Mock()
        input_response.json.return_value = {}
        from czlake.build import recover_runs
        with patch.object(httpx, "Client") as client, patch.object(httpx, "post") as post, \
             patch.object(budget, "reconcile", return_value={}), patch.object(recover_runs, "recover", return_value={"run_id": "found"}):
            client.return_value.__enter__.return_value.get.side_effect = [listed, input_response]
            result = budget.recover_authorized_start(path)
            post.assert_not_called()
        self.assertEqual(result["recovered"]["run_id"], "found")
        self.assertEqual(budget._state()["authorizations"]["exact"]["run_id"], "found")
        self.assertAlmostEqual(budget.committed_usd(), .07)


if __name__ == "__main__":
    unittest.main()
