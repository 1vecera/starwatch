import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from czlake.production_accounting_refresh import prepare_accounting_refresh


class AccountingRefreshTests(unittest.TestCase):
    def setUp(self):
        scratch = Path.cwd() / "tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.baseline = self.root / "baseline.json"
        self.observation = self.root / "observation.json"
        self.ledger = self.root / "budget.json"
        self.snapshot = self.root / "accounting.json"
        self.old = {"observed_at": "2026-10-09T03:39:10Z", "source_url": "provider-billing-control",
                    "daily_control": [{"date": "2026-10-09T00:00:00Z", "serviceUsage": {
                        "PAID_ACTORS_PER_EVENT": {"baseAmountUsd": "80"},
                        "DATASET_READS": {"baseAmountUsd": "0.02"}}}]}
        self.baseline.write_text(json.dumps(self.old))
        self.entries = [
            {"id": "legacy.provision.exa", "provider": "exa", "lane": "search", "status": "unresolved",
             "settled_usd": "0", "reserved_usd": "5", "applies_to_production": False, "evidence": "unknown bill"},
            {"id": "production.storage_http_provision", "provider": "apify", "lane": "storage",
             "status": "unresolved", "settled_usd": "0.73387689604487189968", "reserved_usd": "1",
             "applies_to_production": True, "evidence": {"refresh_path": str(self.baseline),
                "refresh_sha256": hashlib.sha256(self.baseline.read_bytes()).hexdigest()}}]
        self.accounting = {"schema_version": 1, "scope": "night", "complete": True,
            "observed_at": self.old["observed_at"], "period_start": "2026-10-08T15:00:00Z",
            "period_end": "2026-10-09T21:59:59Z", "entries": self.entries}
        self._save_ledger()

    def _save_ledger(self):
        self.snapshot.write_text(json.dumps(self.accounting))
        self.ledger.write_text(json.dumps({"accounting": {**self.accounting,
            "snapshot_path": str(self.snapshot), "snapshot_sha256": hashlib.sha256(self.snapshot.read_bytes()).hexdigest()},
            "batches": {"p1": {"run_id": "exact-run", "manifest": {"actor": "apify/example"}, "actual_usd": "79"}}}))

    def _prepare(self, value, name):
        self.observation.write_text(json.dumps(value))
        return prepare_accounting_refresh(self.ledger, self.baseline, self.observation, self.root / name)

    def test_only_positive_nonactor_increments_raise_existing_floor_without_releasing_reserves(self):
        new = copy.deepcopy(self.old)
        new["observed_at"] = "2026-10-09T03:40:00Z"
        services = new["daily_control"][0]["serviceUsage"]
        services["PAID_ACTORS_PER_EVENT"]["baseAmountUsd"] = "100"
        services["DATASET_READS"]["baseAmountUsd"] = "0.03"
        before = self.ledger.read_bytes()
        result = self._prepare(new, "prepared")
        accounting = json.loads(Path(result["accounting"]).read_text())
        evidence = json.loads(Path(result["evidence"]).read_text())
        self.assertEqual(result["nonactor_increment_usd"], "0.01")
        self.assertEqual(accounting["entries"][1]["settled_usd"], "0.74387689604487189968")
        self.assertEqual(accounting["entries"][1]["reserved_usd"], "1")
        self.assertEqual(accounting["entries"][0], self.entries[0])
        self.assertEqual(evidence["actor_observation"]["provider_minus_known_actor_run_usd"], "21")
        self.assertEqual(evidence["actor_observation"]["ledger_addition_usd"], "0")
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_missing_then_reappearing_category_does_not_double_count_or_erase_floor(self):
        missing = copy.deepcopy(self.old)
        missing["observed_at"] = "2026-10-09T03:40:00Z"
        missing["daily_control"][0]["serviceUsage"].pop("DATASET_READS")
        first = self._prepare(missing, "missing")
        self.assertEqual(first["nonactor_increment_usd"], "0")
        self.baseline = Path(first["evidence"])
        self.accounting = json.loads(Path(first["accounting"]).read_text())
        self._save_ledger()
        returning = copy.deepcopy(self.old)
        returning["observed_at"] = "2026-10-09T03:41:00Z"
        second = self._prepare(returning, "returning")
        self.assertEqual(second["nonactor_increment_usd"], "0")
        self.assertEqual(json.loads(Path(second["accounting"]).read_text())["entries"][1]["settled_usd"],
                         "0.73387689604487189968")

    def test_third_party_actor_bill_is_in_diagnostic_without_extra_charge(self):
        ledger = json.loads(self.ledger.read_text())
        ledger["batches"]["p2"] = {"run_id": "third-party-run", "manifest": {"actor": "streamers/youtube-scraper"}, "actual_usd": "1"}
        self.ledger.write_text(json.dumps(ledger))
        newer = {**self.old, "observed_at": "2026-10-09T03:40:00Z"}
        result = self._prepare(newer, "third-party")
        diagnostic = json.loads(Path(result["evidence"]).read_text())["actor_observation"]
        self.assertEqual(diagnostic["known_production_bound_actor_usd"], "80")
        self.assertEqual(diagnostic["provider_minus_known_actor_run_usd"], "0")
        self.assertEqual(result["nonactor_increment_usd"], "0")

    def test_wrong_baseline_pin_or_backwards_scope_refuses_before_output(self):
        self.baseline.write_text(json.dumps({**self.old, "source_url": "changed"}))
        with self.assertRaises(ValueError):
            self._prepare(self.old, "rejected-pin")
        self.assertFalse((self.root / "rejected-pin").exists())
        self.baseline.write_text(json.dumps(self.old))
        older = {**self.old, "observed_at": "2026-10-09T03:38:00Z"}
        with self.assertRaises(ValueError):
            self._prepare(older, "rejected-date")
        self.assertFalse((self.root / "rejected-date").exists())


if __name__ == "__main__":
    unittest.main()
