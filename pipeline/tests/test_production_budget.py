"""Offline behavior checks; all state, synthetic replies and receipts stay in this worker's scratch."""

from __future__ import annotations

import copy
import io
import json
import multiprocessing
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from czlake.production_budget import (
    SCOPE_ID,
    AmbiguousStart,
    BudgetError,
    CapExceeded,
    ProductionBudget,
    atomic_write,
    canonical,
    digest,
    file_hash,
    money,
    timestamp,
)
from czlake.production_collect import (
    ACTORS,
    GOOGLE_DISABLED,
    ApifyTransport,
    ProductionCollector,
    TransportFailure,
    public_metadata,
    validate_input,
    validate_manifest,
)
from czlake.production_new_platforms import DISABLED_TIKTOK, DISABLED_YOUTUBE, TIKTOK, X, YOUTUBE

WORKER = Path.cwd()


class Crash(BaseException):
    pass


class Clock:
    def __init__(self):
        self.now = timestamp("2026-10-09T01:40:00Z")

    def __call__(self):
        return self.now

    def iso(self, offset=0):
        return datetime.fromtimestamp(self.now + offset, UTC).isoformat()


class FakeTransport:
    def __init__(self, clock, actor_id, run_input):
        self.clock, self.actor_id, self.run_input = clock, actor_id, run_input
        self.starts = 0
        self.calls = []
        self.rows = []
        self.runs = {}
        self.raise_start = None
        self.raise_page = None
        self.status = "RUNNING"
        self.usage = "0.01"

    def start(self, actor, run_input, caps):
        self.starts += 1
        self.calls.append((actor, copy.deepcopy(run_input), caps))
        run = {
            "id": f"run{self.starts}",
            "actId": self.actor_id,
            "status": self.status,
            "startedAt": self.clock.iso(),
            "usageTotalUsd": self.usage,
            "chargedEventCounts": {},
            "defaultDatasetId": "dataset1",
            "defaultKeyValueStoreId": "store1",
        }
        if self.status in {"SUCCEEDED", "FAILED"}:
            run["finishedAt"] = self.clock.iso()
        run["options"] = {
            "maxTotalChargeUsd": caps["maxTotalChargeUsd"],
            "maxItems": caps["maxItems"],
            "timeoutSecs": caps["timeout"],
            "memoryMbytes": caps["memory"],
        }
        self.runs[run["id"]] = run
        if self.raise_start:
            raise self.raise_start
        return copy.deepcopy(run)

    def get_run(self, run_id):
        return copy.deepcopy(self.runs[run_id])

    def get_input(self, store_id):
        return copy.deepcopy(self.run_input)

    def dataset_page(self, dataset_id, offset, limit):
        self.calls.append((dataset_id, offset, limit))
        if self.raise_page:
            raise self.raise_page
        return copy.deepcopy(self.rows[offset : offset + limit])


def process_reserve(root, manifest, now, queue):
    try:
        ProductionBudget(Path(root), clock=lambda: now).reserve(manifest)
        queue.put("accepted")
    except CapExceeded:
        queue.put("capped")


class ProductionChecks(unittest.TestCase):
    def setUp(self):
        (WORKER / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="tests-", dir=WORKER / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.auth = self.root / "auth.json"
        self.auth.write_text(json.dumps({
            "authorization_id": "daniel-production-20261009", "authorized_by": "Daniel",
            "status": "authorized_for_execution", "run_cap_usd": "100.00",
            "overall_night_cap_usd": "120.00", "brief": "docs/tasks/hos-production.md",
            "supersedes_historical_paid_hold_for_this_run_only": True,
            "recorded_at": "2026-10-09T01:29:48+00:00",
        }))
        self.accounting = self.root / "accounting.json"
        self.snapshot = {
            "schema_version": 1,
            "scope": "night",
            "complete": True,
            "period_start": "2026-10-08T14:00:00Z",
            "period_end": "2026-10-09T12:00:00Z",
            "observed_at": self.clock.iso(),
            "entries": [
                {
                    "id": "explore",
                    "provider": "apify",
                    "lane": "historical-explore",
                    "status": "settled",
                    "settled_usd": "2.83650",
                    "reserved_usd": "0",
                    "applies_to_production": False,
                    "evidence": "local settled receipt",
                },
                {
                    "id": "older-lanes",
                    "provider": "external",
                    "lane": "older-collection-scribe-search",
                    "status": "unresolved",
                    "settled_usd": "0",
                    "reserved_usd": "5",
                    "applies_to_production": False,
                    "evidence": "synthetic conservative reserve; not a real reconciliation",
                },
                {
                    "id": "native",
                    "provider": "native-codex",
                    "lane": "subscription",
                    "status": "unpriced_subscription",
                    "settled_usd": "0",
                    "reserved_usd": "0",
                    "applies_to_production": True,
                    "evidence": "native subscription consumption is unpriced",
                },
            ],
        }
        self.save_accounting()
        self.budget = ProductionBudget(self.root / "production", clock=self.clock)
        self.budget.initialize(self.auth, file_hash(self.auth), self.accounting)
        self.manifest = self.make_manifest()
        actor_id = json.loads(Path(self.manifest["price_basis"]["snapshot_path"]).read_text())["data"]["actorInfo"][
            "id"
        ]
        self.transport = FakeTransport(self.clock, actor_id, self.manifest["input"])
        self.collector = ProductionCollector(self.budget, self.transport, page_size=2)

    def save_accounting(self):
        self.accounting.write_text(json.dumps(self.snapshot))

    def make_manifest(self, actor="apify/instagram-profile-scraper", batch_id="batch-one", cap="1.00", items=5):
        inputs = {
            YOUTUBE: {"startUrls": [{"url": "https://www.youtube.com/@public_owner"}],
                      "maxResults": items, "maxResultsShorts": 0, "maxResultStreams": 0,
                      "sortVideosBy": "NEWEST", **DISABLED_YOUTUBE},
            X: {"searchTerms": ["from:public_owner filter:media -filter:replies -filter:retweets"],
                "sort": "Latest", "maxItems": items, "includeSearchTerms": True},
            TIKTOK: {"profiles": ["public_owner"], "resultsPerPage": items,
                     "profileScrapeSections": ["videos"], "profileSorting": "latest", **DISABLED_TIKTOK},
            "apify/instagram-profile-scraper": {"usernames": ["public_owner"], "includeAboutSection": False},
            "apify/instagram-scraper": {
                "directUrls": ["https://www.instagram.com/public_owner/"],
                "resultsType": "posts",
                "resultsLimit": items,
                "addParentData": False,
            },
            "apify/facebook-posts-scraper": {
                "startUrls": [{"url": "https://www.facebook.com/public_owner/"}],
                "resultsLimit": items,
                "captionText": False,
            },
            "apify/google-search-scraper": {
                "queries": "public owner Praha",
                "maxPagesPerQuery": 1,
                "countryCode": "cz",
                "searchLanguage": "cs",
                **copy.deepcopy(GOOGLE_DISABLED),
            },
        }
        price_path = self.root / (actor.replace("/", "--") + ".json")
        # Synthetic contract fixtures keep money/privacy behavior tests independent of private run data.
        units = {"apify/instagram-profile-scraper": ("Profile", "0.0023"),
                 "apify/instagram-scraper": ("Result", "0.0023"),
                 "apify/facebook-posts-scraper": ("Post", "0.004"),
                 "apify/google-search-scraper": ("Scraped search result page", "0.0025"),
                 YOUTUBE: ("Video", "0.003"), X: ("Dataset Item Tier 1", "0.0004"), TIKTOK: ("Result", "0.003")}
        events = [{"title": title, "tieredPricing": [{"tier": "BRONZE", "priceUsd": rate}]}
                  for title, rate in [units[actor], ("Actor start", "0.001"), ("Add-on: Date filter", "0.001")]]
        events.append({"title": "Actor Start", "priceUsd": "0.00005"})
        events.append({"title": "Search/Profile/List etc Query", "tieredPricing": [{"tier": "BRONZE", "priceUsd": "0.016"}]})
        keys = set(inputs[actor]) | {"onlyPostsNewerThan", "onlyPostsOlderThan"}
        price_path.write_text(json.dumps({"observed_at": self.clock.iso(), "data": {
            "actorInfo": {"id": "synthetic-" + actor.rsplit("/", 1)[1], "fullName": actor,
                          "pricing": {"model": "PAY_PER_EVENT", "userTier": "BRONZE", "events": events}},
            "inputSchema": {"properties": {key: {} for key in keys}}}}))
        snapshot = json.loads(price_path.read_text(), parse_float=Decimal)
        pricing = snapshot["data"]["actorInfo"]["pricing"]
        unit, rate = units[actor]
        estimate = Decimal(rate) * items
        if unit == "Post" or actor == TIKTOK:
            estimate += Decimal("0.001")
        if actor == X:
            estimate += Decimal("0.016")
        if unit == "Scraped search result page":
            estimate += Decimal("0.00005")
        return {
            "schema_version": 1,
            "batch_id": batch_id,
            "scope_id": SCOPE_ID,
            "cities": ["Praha"],
            "actor": actor,
            "input": inputs[actor],
            "input_sha256": digest(inputs[actor]),
            "purpose": "Synthetic offline production budget test",
            "max_total_charge_usd": cap,
            "max_items": items,
            "timeout_s": 60,
            "memory_mb": 1024,
            "price_basis": {
                "snapshot_path": str(price_path),
                "snapshot_sha256": file_hash(price_path),
                "observed_at": snapshot["observed_at"],
                "pricing_model": pricing["model"],
                "tier": pricing["userTier"],
                "unit": unit,
                "expected_upper_usd": str(estimate),
                "rationale": "capped items plus start where applicable",
            },
        }

    def terminal(self, usage="0.03"):
        self.transport.runs["run1"].update(status="SUCCEEDED", finishedAt=self.clock.iso(), usageTotalUsd=usage)

    def test_exact_decimal_and_two_caps(self):
        self.assertEqual(money("0.1") + money("0.2"), Decimal("0.3"))
        for value in [0.1, True, "NaN", "Infinity", "-1"]:
            with self.assertRaises((TypeError, ValueError)):
                money(value)
        self.budget.reserve(self.make_manifest(batch_id="sixty", cap="60"))
        with self.assertRaises(CapExceeded):
            self.budget.reserve(self.make_manifest(batch_id="next", cap="40.00001"))
        self.assertEqual(self.budget.status()["run_reserved_usd"], "60")

    def test_night_cap_counts_external_unresolved_and_settled(self):
        self.snapshot["entries"][1]["reserved_usd"] = "30"
        self.save_accounting()
        self.budget.import_accounting(self.accounting)
        with self.assertRaises(CapExceeded):
            self.budget.reserve(self.make_manifest(cap="90"))
        self.assertEqual(self.budget.status()["night_committed_usd"], "32.83650")
        self.assertEqual(self.budget.status()["run_committed_usd"], "0")

    def test_cross_process_reservations_never_exceed_cap(self):
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        children = [
            context.Process(
                target=process_reserve,
                args=(str(self.budget.root), self.make_manifest(batch_id=f"p{i}", cap="30"), self.clock(), queue),
            )
            for i in range(6)
        ]
        for child in children:
            child.start()
        for child in children:
            child.join(10)
            self.assertEqual(child.exitcode, 0)
        results = [queue.get(timeout=2) for _ in children]
        self.assertEqual(results.count("accepted"), 3)
        self.assertEqual(self.budget.status()["run_committed_usd"], "90")
        journal = json.loads(self.budget.state_path.read_text())["journal"]
        self.assertEqual([e["sequence"] for e in journal], [1, 2, 3, 4])

    def test_concurrent_same_batch_launches_once(self):
        entered, release = threading.Event(), threading.Event()
        original = self.transport.start

        def blocked(*args):
            entered.set()
            release.wait(5)
            return original(*args)

        self.transport.start = blocked
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.collector.run_batch, self.manifest)
            self.assertTrue(entered.wait(3))
            second = executor.submit(self.collector.run_batch, self.manifest)
            with self.assertRaises(AmbiguousStart):
                second.result(timeout=3)
            release.set()
            self.assertEqual(first.result(timeout=3)["run_id"], "run1")
        self.assertEqual(self.transport.starts, 1)

    def test_required_caps_and_idempotent_restart(self):
        first = self.collector.run_batch(self.manifest)
        restarted = ProductionCollector(ProductionBudget(self.budget.root, clock=self.clock), self.transport)
        second = restarted.run_batch(self.manifest)
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(self.transport.starts, 1)
        self.assertEqual(
            self.transport.calls[0][2], {"maxTotalChargeUsd": "1.00", "maxItems": 5, "memory": 1024, "timeout": 60}
        )
        changed = copy.deepcopy(self.manifest)
        changed["purpose"] = "different purpose"
        with self.assertRaises(BudgetError):
            restarted.run_batch(changed)
        self.assertEqual(self.transport.starts, 1)

    def test_crash_after_reserve_is_safe_to_resume(self):
        def crash(event):
            if event == "after_reserve":
                raise Crash()

        self.collector.hook = crash
        with self.assertRaises(Crash):
            self.collector.run_batch(self.manifest)
        self.assertEqual(self.budget.batch("batch-one")["phase"], "RESERVED")
        self.assertEqual(self.transport.starts, 0)
        self.collector.hook = lambda event: None
        self.collector.run_batch(self.manifest)
        self.assertEqual(self.transport.starts, 1)

    def test_crash_before_network_is_ambiguous_and_never_released(self):
        def crash(event):
            if event == "before_network":
                raise Crash()

        self.collector.hook = crash
        with self.assertRaises(Crash):
            self.collector.run_batch(self.manifest)
        self.assertEqual(self.transport.starts, 0)
        self.collector.hook = lambda event: None
        with self.assertRaises(AmbiguousStart):
            self.collector.run_batch(self.manifest)
        self.clock.now += 301
        self.collector.reconcile()
        self.assertEqual(self.budget.status()["run_committed_usd"], "1.00")

    def test_crash_after_network_recovers_remote_input_without_start(self):
        def crash(event):
            if event == "after_network":
                raise Crash()

        self.collector.hook = crash
        with self.assertRaises(Crash):
            self.collector.run_batch(self.manifest)
        self.assertIsNone(self.budget.batch("batch-one")["run_id"])
        self.collector.hook = lambda event: None
        self.collector.recover("batch-one", "run1")
        self.collector.run_batch(self.manifest)
        self.assertEqual(self.transport.starts, 1)

    def test_timeout_start_preserves_full_reservation_forever(self):
        self.transport.raise_start = TimeoutError("response disappeared after launch")
        with self.assertRaises(AmbiguousStart):
            self.collector.run_batch(self.manifest)
        self.clock.now += 601
        self.collector.reconcile()
        with self.assertRaises(AmbiguousStart):
            self.collector.run_batch(self.manifest)
        self.assertEqual(self.budget.status()["run_reserved_usd"], "1.00")
        with self.assertRaises(BudgetError):
            self.collector.recover("batch-one", "run1")
        self.assertIsNone(self.budget.batch("batch-one")["run_id"])
        self.assertEqual(self.budget.status()["run_reserved_usd"], "1.00")
        self.assertEqual(self.transport.starts, 1)

    def test_later_identical_run_cannot_release_an_ambiguous_original_reservation(self):
        self.transport.raise_start = TimeoutError()
        with self.assertRaises(AmbiguousStart):
            self.collector.run_batch(self.manifest)
        # Another caller's later run has the exact same actor, input and caps.
        self.clock.now += 3600
        self.transport.raise_start = None
        later = self.transport.start(self.manifest["actor"], self.manifest["input"], self.transport.calls[0][2])
        self.transport.runs[later["id"]].update(status="SUCCEEDED", usageTotalUsd="0", finishedAt=self.clock.iso())
        with self.assertRaises(BudgetError):
            self.collector.recover("batch-one", later["id"])
        self.clock.now += 601
        restarted = ProductionCollector(ProductionBudget(self.budget.root, clock=self.clock), self.transport)
        restarted.reconcile(land=False)
        original = self.budget.batch("batch-one")
        self.assertIsNone(original["run_id"])
        self.assertEqual(original["phase"], "STARTING")
        self.assertEqual(money(original["reserved_usd"]), Decimal(1))
        self.assertEqual(money(self.budget.status()["run_committed_usd"]), Decimal(1))

    def test_exact_start_receipt_rejects_another_identical_run_even_in_same_second(self):
        def crash(event):
            if event == "after_network":
                raise Crash()

        self.collector.hook = crash
        with self.assertRaises(Crash):
            self.collector.run_batch(self.manifest)
        self.assertEqual(self.budget.batch("batch-one")["start_response_receipt"]["run_id"], "run1")
        unrelated = self.transport.start(self.manifest["actor"], self.manifest["input"], self.transport.calls[0][2])
        with self.assertRaises(BudgetError):
            self.collector.recover("batch-one", unrelated["id"])
        restarted = ProductionCollector(ProductionBudget(self.budget.root, clock=self.clock), self.transport)
        restarted.recover("batch-one", "run1")
        self.assertEqual(self.budget.batch("batch-one")["run_id"], "run1")
        self.assertEqual(self.transport.starts, 2)

    def test_malformed_start_response_stays_ambiguous(self):
        self.transport.actor_id = "wrong-actor"
        with self.assertRaises(AmbiguousStart):
            self.collector.run_batch(self.manifest)
        self.assertIsNone(self.budget.batch("batch-one")["run_id"])
        self.assertEqual(self.budget.status()["run_committed_usd"], "1.00")

    def test_recovery_rejects_wrong_actor_input_and_old_run(self):
        def crash(event):
            if event == "after_network":
                raise Crash()

        self.collector.hook = crash
        with self.assertRaises(Crash):
            self.collector.run_batch(self.manifest)
        original = copy.deepcopy(self.transport.runs["run1"])
        self.transport.runs["run1"]["actId"] = "other"
        with self.assertRaises(BudgetError):
            self.collector.recover("batch-one", "run1")
        self.transport.runs["run1"] = copy.deepcopy(original)
        self.transport.run_input = {"usernames": ["namesake"], "includeAboutSection": False}
        with self.assertRaises(BudgetError):
            self.collector.recover("batch-one", "run1")
        self.transport.run_input = self.manifest["input"]
        self.transport.runs["run1"]["startedAt"] = self.clock.iso(-10)
        with self.assertRaises(BudgetError):
            self.collector.recover("batch-one", "run1")
        self.assertIsNone(self.budget.batch("batch-one")["run_id"])
        self.assertEqual(self.transport.starts, 1)

    def test_billing_buffer_observes_delayed_actual_and_overrun(self):
        self.collector.run_batch(self.manifest)
        self.terminal("0.03")
        self.collector.reconcile()
        self.assertEqual(self.budget.status()["run_committed_usd"], "1.00")
        self.clock.now += 301
        self.transport.runs["run1"]["usageTotalUsd"] = "0.65"
        self.collector.reconcile()
        self.assertEqual(self.budget.status()["run_actual_usd"], "0.65")
        self.assertEqual(self.budget.status()["run_committed_usd"], "1.00")
        self.clock.now += 301
        self.collector.reconcile()
        self.assertEqual(self.budget.status()["run_reserved_usd"], "0")
        self.transport.runs["run1"]["usageTotalUsd"] = "105"
        self.collector.reconcile()
        self.assertEqual(self.budget.status()["run_actual_usd"], "105")
        self.assertTrue(self.budget.status()["over_cap"])
        with self.assertRaises(CapExceeded):
            self.collector.run_batch(self.make_manifest(batch_id="next"))
        self.assertEqual(self.transport.starts, 1)

    def test_missing_bill_and_failed_read_do_not_release_cap(self):
        self.collector.run_batch(self.manifest)
        self.terminal()
        self.collector.reconcile()
        self.clock.now += 301
        del self.transport.runs["run1"]["usageTotalUsd"]
        self.collector.reconcile()
        self.assertEqual(self.budget.status()["run_committed_usd"], "1.00")
        with patch.object(self.transport, "get_run", side_effect=TimeoutError()), self.assertRaises(TimeoutError):
            self.collector.run_batch(self.make_manifest(batch_id="next"))
        self.assertEqual(self.transport.starts, 1)
        self.assertEqual(self.budget.status()["run_committed_usd"], "1.00")

    def test_failed_landing_and_orphan_file_recovery_do_not_relaunch(self):
        self.transport.status = "SUCCEEDED"
        self.transport.raise_page = TimeoutError()
        with self.assertRaises(TimeoutError):
            self.collector.run_batch(self.manifest)
        self.assertEqual(self.budget.status()["run_committed_usd"], "1.00")
        self.assertFalse(list((self.budget.root / "raw").rglob("*.json")))
        self.transport.raise_page = None
        self.transport.rows = [{"username": "public_owner"}]

        def crash(event):
            if event == "after_landing_commit":
                raise Crash()

        self.collector.hook = crash
        with self.assertRaises(Crash):
            self.collector.run_batch(self.manifest)
        self.assertIsNone(self.budget.batch("batch-one")["landing"])
        self.collector.hook = lambda event: None
        self.collector.run_batch(self.manifest)
        self.assertEqual(self.budget.batch("batch-one")["landing"]["items"], 1)
        self.assertEqual(self.transport.starts, 1)

    def test_pagination_filters_before_any_write_and_stops_at_cap(self):
        self.transport.status = "SUCCEEDED"
        self.transport.rows = [
            {
                "username": "public_owner",
                "followersCount": 12,
                "followers": [{"username": "FORBIDDEN_FOLLOWER"}],
                "relatedProfiles": [{"fullName": "FORBIDDEN_RELATED"}],
                "latestPosts": [
                    {
                        "id": f"p{i}",
                        "ownerUsername": "public_owner",
                        "likesCount": 3,
                        "firstComment": "FORBIDDEN_COMMENT",
                        "latestComments": [{"ownerUsername": "FORBIDDEN_COMMENTER"}],
                        "likers": [{"username": "FORBIDDEN_LIKER"}],
                        "mentions": ["FORBIDDEN_MENTION"],
                        "childPosts": [{"ownerId": "owner", "comments": [{"user": "FORBIDDEN_NESTED"}]}],
                    }
                ],
            }
            for i in range(8)
        ]
        result = self.collector.run_batch(self.manifest)
        path = Path(result["landing"]["path"])
        self.assertEqual(result["landing"]["items"], 5)
        self.assertNotIn("FORBIDDEN", path.read_text())
        self.assertEqual(
            [(call[1], call[2]) for call in self.transport.calls if call[0] == "dataset1"], [(0, 2), (2, 2), (4, 1)]
        )
        self.assertEqual(json.loads(path.read_text())["items"][0]["latestPosts"][0]["ownerUsername"], "public_owner")
        self.assertFalse(list(path.parent.glob(".filtered-*")))

    def test_malicious_nested_counts_and_unknown_actor_fail_closed(self):
        result = public_metadata(
            "apify/facebook-posts-scraper",
            {
                "comments": "FORBIDDEN_COMMENT",
                "likes": [{"name": "FORBIDDEN_LIKER"}],
                "user": {"name": "public owner", "friends": ["FORBIDDEN"]},
                "media": [{"url": "https://example.org/image.jpg", "comments": ["FORBIDDEN"]}],
                "reactions": {"LIKE": 5, "people": ["FORBIDDEN"]},
            },
        )
        self.assertNotIn("FORBIDDEN", json.dumps(result))
        self.assertEqual(result["reactions"], {"LIKE": 5})
        self.assertEqual(result["user"]["name"], "public owner")
        with self.assertRaises(ValueError):
            public_metadata("unknown/actor", {})

    def test_all_reviewed_actors_validate_synthetic_price_receipts(self):
        for actor in ACTORS:
            with self.subTest(actor=actor):
                validate_manifest(self.make_manifest(actor=actor), self.clock())

    def test_comments_mentions_enrichment_and_unknown_inputs_are_rejected(self):
        for actor in ACTORS:
            manifest = self.make_manifest(actor=actor)
            malicious = copy.deepcopy(manifest["input"])
            malicious["unreviewedOption"] = True
            with self.assertRaises(ValueError):
                validate_input(actor, malicious, 5)
        for mode in ["comments", "mentions", "stories", "details"]:
            source = self.make_manifest(actor="apify/instagram-scraper")["input"]
            source["resultsType"] = mode
            with self.assertRaises(ValueError):
                validate_input("apify/instagram-scraper", source, 5)
        google = self.make_manifest(actor="apify/google-search-scraper")["input"]
        for key in GOOGLE_DISABLED:
            changed = copy.deepcopy(google)
            changed[key] = True
            with self.assertRaises(ValueError):
                validate_input("apify/google-search-scraper", changed, 5)
        profile = self.manifest["input"] | {"includeAboutSection": True}
        with self.assertRaises(ValueError):
            validate_input(self.manifest["actor"], profile, 5)

    def test_manifest_rejects_scope_caps_input_price_and_tier_mismatches(self):
        changes = [
            {"scope_id": "unrelated"},
            {"cities": ["London"]},
            {"max_items": 0},
            {"memory_mb": 5000},
            {"timeout_s": 901},
            {"input_sha256": "bad"},
            {"max_total_charge_usd": "NaN"},
        ]
        for change in changes:
            with self.assertRaises(ValueError):
                validate_manifest(self.manifest | change, self.clock())
        for field, value in [
            ("tier", "FREE"),
            ("unit", "Page"),
            ("expected_upper_usd", "0.0001"),
            ("snapshot_sha256", "bad"),
        ]:
            changed = copy.deepcopy(self.manifest)
            changed["price_basis"][field] = value
            with self.assertRaises(ValueError):
                validate_manifest(changed, self.clock())
        facebook = self.make_manifest(actor="apify/facebook-posts-scraper")
        facebook["input"]["onlyPostsNewerThan"] = "2026-10-01"
        facebook["input_sha256"] = digest(facebook["input"])
        with self.assertRaises(ValueError):
            validate_manifest(facebook, self.clock())

    def test_authorization_and_price_changes_after_reserve_prevent_network(self):
        def change_auth(event):
            if event == "after_reserve":
                self.auth.write_text(self.auth.read_text() + "\n")

        self.collector.hook = change_auth
        with self.assertRaises(BudgetError):
            self.collector.run_batch(self.manifest)
        self.assertEqual(self.transport.starts, 0)
        self.assertEqual(self.budget.batch("batch-one")["phase"], "RESERVED")

    def test_recorded_at_supersedes_only_exact_historical_hold(self):
        hold = self.root / "production-hold.json"
        hold.write_text(json.dumps({"held_at": "2026-10-09T01:29:00Z", "reason": "historical preparation"}))
        separate = ProductionBudget(self.root / "with-hold", clock=self.clock)
        separate.initialize(self.auth, file_hash(self.auth), self.accounting, hold_paths=(hold,))
        self.assertNotIn("authorized_at", json.loads(self.auth.read_text()))
        separate.reserve(self.manifest)
        hold.write_text(json.dumps({"held_at": "2026-10-09T01:41:00Z", "reason": "new hold"}))
        with self.assertRaises(BudgetError):
            separate.begin_start("batch-one")
        newer = ProductionBudget(self.root / "new-hold", clock=self.clock)
        with self.assertRaises(BudgetError):
            newer.initialize(self.auth, file_hash(self.auth), self.accounting, hold_paths=(hold,))

    def test_new_canonical_hold_and_missing_auth_prevent_launch(self):
        hold = self.budget.root.parent / "paid_launch_hold.json"
        hold.write_text(json.dumps({"held_at": self.clock.iso(), "reason": "new hold"}))
        with self.assertRaises(BudgetError):
            self.collector.run_batch(self.manifest)
        self.assertEqual(self.transport.starts, 0)
        hold.unlink()
        self.auth.unlink()
        with self.assertRaises(BudgetError):
            self.collector.run_batch(self.manifest)
        self.assertEqual(self.transport.starts, 0)

    def test_external_accounting_cannot_disappear_understate_or_release_without_evidence(self):
        self.snapshot["entries"][1]["reserved_usd"] = "0"
        self.save_accounting()
        with self.assertRaises(ValueError):
            self.budget.import_accounting(self.accounting)
        self.snapshot["entries"][1].update(status="settled", settled_usd="0.50", reserved_usd="0")
        self.save_accounting()
        with self.assertRaises(BudgetError):
            self.budget.import_accounting(self.accounting)
        self.snapshot["entries"][1]["evidence"] = "new provider settlement receipt"
        self.save_accounting()
        self.budget.import_accounting(self.accounting)
        self.assertEqual(self.budget.status()["night_committed_usd"], "3.33650")
        self.snapshot["entries"].pop(0)
        self.save_accounting()
        with self.assertRaises(BudgetError):
            self.budget.import_accounting(self.accounting)

    def test_expired_accounting_and_failed_atomic_commit_block_start(self):
        self.clock.now += 3601
        with self.assertRaises(BudgetError):
            self.collector.run_batch(self.manifest)
        self.assertEqual(self.transport.starts, 0)
        self.clock.now -= 3601
        previous = self.budget.state_path.read_bytes()
        with (
            patch("czlake.production_budget.os.replace", side_effect=OSError("disk error")),
            self.assertRaises(OSError),
        ):
            self.collector.run_batch(self.manifest)
        self.assertEqual(self.budget.state_path.read_bytes(), previous)
        self.assertEqual(self.transport.starts, 0)
        self.assertFalse(list(self.budget.root.glob(".budget.json-*")))

    def test_negative_metric_sentinels_are_preserved_in_filtered_raw(self):
        self.transport.status = "SUCCEEDED"
        self.transport.rows = [
            {
                "username": "public_owner",
                "followersCount": -1,
                "latestPosts": [
                    {
                        "id": "post",
                        "ownerUsername": "public_owner",
                        "likesCount": -1,
                        "videoViewCount": -1.5,
                        "commentsCount": None,
                    }
                ],
            }
        ]
        result = self.collector.run_batch(self.manifest)
        item = json.loads(Path(result["landing"]["path"]).read_text())["items"][0]
        self.assertEqual(item["followersCount"], -1)
        self.assertEqual(item["latestPosts"][0]["likesCount"], -1)
        self.assertEqual(item["latestPosts"][0]["videoViewCount"], -1.5)
        self.assertIsNone(item["latestPosts"][0]["commentsCount"])
        retained = public_metadata(
            "apify/facebook-posts-scraper",
            {
                "likes": -1,
                "shares": Decimal("-1.2"),
                "comments": "commenter identity",
                "views": float("inf"),
                "videoViews": float("nan"),
            },
        )
        self.assertEqual(retained, {"likes": -1, "shares": -1.2})

    def test_caption_text_accepts_explicit_true_without_inventing_price_event(self):
        manifest = self.make_manifest(actor="apify/facebook-posts-scraper")
        manifest["input"]["captionText"] = True
        manifest["input_sha256"] = digest(manifest["input"])
        validate_manifest(manifest, self.clock())
        manifest["input"]["captionText"] = "yes"
        with self.assertRaises(ValueError):
            validate_input(manifest["actor"], manifest["input"], 5)

    def test_near_cap_decimal_reservation_cannot_round_under_ceiling(self):
        self.budget.reserve(self.make_manifest(batch_id="almost", cap="99.9999999999999999999999999999"))
        with self.assertRaises(CapExceeded):
            self.budget.reserve(self.make_manifest(batch_id="over", cap="0.0000000000000000000000000002"))

    def test_external_production_read_provision_consumes_run_headroom(self):
        actual = self.root / "with-production-overhead.json"
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["entries"].append({"id": "production-read", "provider": "apify", "lane": "reads",
                                    "status": "unresolved", "settled_usd": "0", "reserved_usd": "1.00",
                                    "applies_to_production": True, "evidence": "Synthetic overhead provision"})
        actual.write_text(json.dumps(snapshot))
        isolated = ProductionBudget(self.root / "actual-accounting", clock=self.clock)
        summary = isolated.initialize(self.auth, file_hash(self.auth), actual)
        self.assertEqual(summary["run_reserved_usd"], "1.00")
        self.assertEqual(summary["run_remaining_usd"], "99.00")
        with self.assertRaises(CapExceeded):
            isolated.reserve(self.make_manifest(cap="100"))

    def test_charged_event_floor_blocks_contradictory_zero_usage_settlement(self):
        self.collector.run_batch(self.manifest)
        self.terminal("0")
        run = self.transport.runs["run1"]
        run["chargedEventCounts"] = {"profile": 5}
        run["pricingInfo"] = {"pricingPerEvent": {"actorChargeEvents": {"profile": {"eventPriceUsd": "0.0023"}}}}
        self.collector.reconcile(land=False)
        self.clock.now += 301
        self.collector.reconcile(land=False)
        self.assertEqual(self.budget.status()["run_actual_usd"], "0.0115")
        self.assertEqual(self.budget.status()["run_committed_usd"], "1.0000")
        self.assertFalse(self.budget.batch("batch-one")["billing_settled"])
        run["usageTotalUsd"] = "0.0115"
        self.collector.reconcile(land=False)
        self.assertEqual(self.budget.status()["run_reserved_usd"], "0")

    def test_unknown_positive_event_price_prevents_settlement(self):
        self.collector.run_batch(self.manifest)
        self.terminal("0.03")
        run = self.transport.runs["run1"]
        run["chargedEventCounts"] = {"profile": 5, "unpriced-positive-event": 1, "disabled-event": 0}
        run["pricingInfo"] = {"pricingPerEvent": {"actorChargeEvents": {"profile": {"eventPriceUsd": "0.0023"}}}}
        self.collector.reconcile(land=False)
        self.clock.now += 301
        self.collector.reconcile(land=False)
        self.assertEqual(money(self.budget.status()["run_committed_usd"]), Decimal(1))
        self.assertFalse(self.budget.batch("batch-one")["billing_prices_complete"])

    def test_each_provider_option_mismatch_blocks_normal_start_and_covers_higher_cap(self):
        original = self.transport.start

        def mismatch(*args):
            run = original(*args)
            run["options"]["maxTotalChargeUsd"] = "50"
            self.transport.runs[run["id"]] = run
            return run

        self.transport.start = mismatch
        with self.assertRaises(AmbiguousStart):
            self.collector.run_batch(self.manifest)
        batch = self.budget.batch("batch-one")
        self.assertIsNone(batch["run_id"])
        self.assertTrue(batch["safety_hold"])
        self.assertEqual(batch["reserved_usd"], "50")
        self.assertEqual(batch["last_diagnostic"]["mismatched_options"], ["maxTotalChargeUsd"])
        with self.assertRaises(BudgetError):
            self.budget.reserve(self.make_manifest(batch_id="next"))
        self.assertEqual(self.transport.starts, 1)

    def test_recovery_rejects_each_missing_or_mismatched_limit(self):
        def crash(event):
            if event == "after_network":
                raise Crash()

        self.collector.hook = crash
        with self.assertRaises(Crash):
            self.collector.run_batch(self.manifest)
        original = copy.deepcopy(self.transport.runs["run1"]["options"])
        for key, wrong in [
            ("maxTotalChargeUsd", "50"),
            ("maxItems", 5000),
            ("timeoutSecs", 900),
            ("memoryMbytes", 4096),
        ]:
            for missing in (False, True):
                with self.subTest(field=key, missing=missing):
                    self.transport.runs["run1"]["options"] = copy.deepcopy(original)
                    if missing:
                        del self.transport.runs["run1"]["options"][key]
                    else:
                        self.transport.runs["run1"]["options"][key] = wrong
                    with self.assertRaises(BudgetError):
                        self.collector.recover("batch-one", "run1")
                    self.assertIsNone(self.budget.batch("batch-one")["run_id"])
                    self.assertGreaterEqual(money(self.budget.status()["run_committed_usd"]), Decimal(1))
        self.assertEqual(self.budget.status()["run_reserved_usd"], "50")
        self.assertEqual(self.transport.starts, 1)

    def test_missing_start_options_keep_full_cap_and_safety_hold(self):
        original = self.transport.start

        def missing(*args):
            run = original(*args)
            del run["options"]
            return run

        self.transport.start = missing
        with self.assertRaises(AmbiguousStart):
            self.collector.run_batch(self.manifest)
        self.assertEqual(self.budget.status()["run_committed_usd"], "1.00")
        self.assertTrue(self.budget.batch("batch-one")["safety_hold"])

    def test_reconciliation_cannot_release_on_options_drift(self):
        self.collector.run_batch(self.manifest)
        self.terminal("0.03")
        self.transport.runs["run1"]["options"]["maxTotalChargeUsd"] = "50"
        with self.assertRaises(BudgetError):
            self.collector.reconcile(land=False)
        self.assertEqual(money(self.budget.status()["run_committed_usd"]), Decimal(50))
        self.assertFalse(self.budget.batch("batch-one")["billing_settled"])

    def test_http_status_and_known_error_type_are_recorded_without_body_or_token(self):
        token = "SYNTHETIC_TOKEN_MUST_NOT_PERSIST"
        transport = ApifyTransport(token)
        response = io.BytesIO(
            json.dumps(
                {"error": {"type": "invalid-input", "message": token, "unsafeIdentity": "FORBIDDEN_PERSON"}}
            ).encode()
        )
        error = HTTPError("https://api.apify.com/v2/acts/known/runs", 400, token, {}, response)
        collector = ProductionCollector(self.budget, transport)
        with patch("czlake.production_collect.urlopen", side_effect=error), self.assertRaises(AmbiguousStart):
            collector.run_batch(self.manifest)
        diagnostic = self.budget.batch("batch-one")["last_diagnostic"]
        self.assertEqual(
            diagnostic, {"kind": "http_error", "operation": "start", "http_status": 400, "error_type": "invalid-input"}
        )
        self.assertEqual(self.budget.status()["run_committed_usd"], "1.00")
        self.assertNotIn(token, self.budget.state_path.read_text())
        self.assertNotIn("FORBIDDEN_PERSON", self.budget.state_path.read_text())

    def test_unknown_provider_error_type_is_not_persisted(self):
        transport = ApifyTransport("synthetic-secret")
        response = io.BytesIO(b'{"error":{"type":"TOKEN_ABC123","message":"FORBIDDEN_PERSON"}}')
        error = HTTPError("https://api.apify.com/v2/acts/known/runs", 400, "secret", {}, response)
        with (
            patch("czlake.production_collect.urlopen", side_effect=error),
            self.assertRaises(TransportFailure) as caught,
        ):
            transport.start(self.manifest["actor"], self.manifest["input"], {})
        self.assertNotIn("TOKEN_ABC123", json.dumps(caught.exception.diagnostic))
        self.assertNotIn("FORBIDDEN", json.dumps(caught.exception.diagnostic))
        self.assertEqual(caught.exception.diagnostic["http_status"], 400)

    def test_google_minimum_prevents_paid_boundary_without_replaying_old_id(self):
        manifest = self.make_manifest(actor="apify/google-search-scraper", cap="0.08")
        with self.assertRaises(ValueError):
            validate_manifest(manifest, self.clock())
        validate_manifest(manifest, self.clock(), enforce_freshness=False)
        manifest["max_total_charge_usd"] = "0.50"
        validate_manifest(manifest, self.clock())

    def test_unknown_positive_event_disappearance_keeps_reservation_across_restart(self):
        self.transport.usage = "0"
        self.collector.run_batch(self.manifest)
        self.terminal("0")
        run = self.transport.runs["run1"]
        run["chargedEventCounts"] = {"unknown-extra-event": 3}
        self.collector.reconcile(land=False)
        first = self.budget.batch("batch-one")
        self.assertFalse(first["billing_prices_complete"])
        self.assertEqual(first["billing_events"][digest("unknown-extra-event")]["count"], 3)
        run.pop("chargedEventCounts")
        self.clock.now += 301
        restarted = ProductionCollector(ProductionBudget(self.budget.root, clock=self.clock), self.transport)
        restarted.reconcile(land=False)
        batch = self.budget.batch("batch-one")
        self.assertFalse(batch["billing_settled"])
        self.assertFalse(batch["billing_prices_complete"])
        self.assertEqual(money(batch["reserved_usd"]), Decimal(1))
        self.assertNotIn("unknown-extra-event", self.budget.state_path.read_text())
        # An explicit effective event price now covers the retained count despite the missing count map.
        run["pricingInfo"] = {
            "pricingPerEvent": {"actorChargeEvents": {"unknown-extra-event": {"eventPriceUsd": "0.02"}}}
        }
        run["usageTotalUsd"] = "0.06"
        restarted.reconcile(land=False)
        self.assertEqual(self.budget.batch("batch-one")["billing_floor_usd"], "0.06")
        self.assertTrue(self.budget.batch("batch-one")["billing_prices_complete"])
        self.assertEqual(money(self.budget.status()["run_committed_usd"]), Decimal(1))
        self.clock.now += 301
        restarted.reconcile(land=False)
        self.assertFalse(self.budget.batch("batch-one")["billing_settled"])
        # Retained positive evidence can resolve pricing, but settlement also
        # needs a current explicit terminal count map; omission is not completeness.
        run["chargedEventCounts"] = {"unknown-extra-event": 3}
        restarted.reconcile(land=False)
        self.assertTrue(self.budget.batch("batch-one")["billing_settled"])
        self.assertEqual(self.budget.status()["run_reserved_usd"], "0")

    def test_absent_or_malformed_event_counts_never_settle_unevidenced_zero_usage(self):
        for label, counts in (("missing", "missing"), ("null", None), ("array", []),
                              ("bad-count", {"profile": -1})):
            with self.subTest(counts=label):
                budget = ProductionBudget(self.root / label, clock=self.clock)
                budget.initialize(self.auth, file_hash(self.auth), self.accounting)
                transport = FakeTransport(self.clock, self.transport.actor_id, self.manifest["input"])
                transport.status, transport.usage = "SUCCEEDED", "0"
                start = transport.start

                def without_evidence(*args):
                    run = start(*args)
                    if counts == "missing":
                        run.pop("chargedEventCounts")
                    else:
                        run["chargedEventCounts"] = counts
                    transport.runs[run["id"]] = copy.deepcopy(run)
                    return run

                transport.start = without_evidence
                collector = ProductionCollector(budget, transport)
                collector.run_batch(self.manifest)
                self.clock.now += 301
                restarted = ProductionCollector(ProductionBudget(budget.root, clock=self.clock), transport)
                restarted.reconcile(land=False)
                batch = budget.batch("batch-one")
                self.assertFalse(batch["billing_settled"])
                self.assertFalse(batch["billing_prices_complete"])
                self.assertEqual(money(batch["reserved_usd"]), Decimal(1))
                if label == "missing":
                    # Explicit zero resolves absence, while a later missing map
                    # retains evidence but cannot independently settle exposure.
                    transport.runs["run1"]["chargedEventCounts"] = {}
                    restarted.reconcile(land=False)
                    self.assertTrue(budget.batch("batch-one")["billing_settled"])
                    transport.runs["run1"].pop("chargedEventCounts")
                    restarted.reconcile(land=False)
                    self.assertEqual(money(budget.status()["run_reserved_usd"]), Decimal(1))

    def test_running_zero_counts_do_not_evidence_missing_terminal_bill(self):
        self.transport.usage = "0"
        self.collector.run_batch(self.manifest)
        self.terminal("0")
        self.transport.runs["run1"].pop("chargedEventCounts")
        self.collector.reconcile(land=False)
        self.clock.now += 301
        restarted = ProductionCollector(ProductionBudget(self.budget.root, clock=self.clock), self.transport)
        restarted.reconcile(land=False)
        batch = self.budget.batch("batch-one")
        self.assertFalse(batch["billing_settled"])
        self.assertFalse(batch["billing_counts_complete"])
        self.assertEqual(money(batch["reserved_usd"]), Decimal(1))
        self.transport.runs["run1"]["chargedEventCounts"] = {}
        restarted.reconcile(land=False)
        self.assertTrue(self.budget.batch("batch-one")["billing_settled"])
        self.assertEqual(self.budget.status()["run_reserved_usd"], "0")

    def test_known_event_counts_prices_are_monotonic_and_zero_is_not_erasure(self):
        self.transport.usage = "0"
        self.collector.run_batch(self.manifest)
        self.terminal("0")
        run = self.transport.runs["run1"]
        run["chargedEventCounts"] = {"profile": 5}
        run["pricingInfo"] = {"pricingPerEvent": {"actorChargeEvents": {"profile": {"eventPriceUsd": "0.0023"}}}}
        self.collector.reconcile(land=False)
        run["chargedEventCounts"] = {"profile": 0}
        run["pricingInfo"] = {}
        self.clock.now += 301
        self.collector.reconcile(land=False)
        event = self.budget.batch("batch-one")["billing_events"][digest("profile")]
        self.assertEqual(event, {"count": 5, "unit_price_usd": "0.0023"})
        self.assertEqual(self.budget.batch("batch-one")["billing_floor_usd"], "0.0115")
        self.assertFalse(self.budget.batch("batch-one")["billing_settled"])
        run["chargedEventCounts"] = {"profile": 7}
        self.collector.reconcile(land=False)
        self.assertEqual(self.budget.batch("batch-one")["billing_floor_usd"], "0.0161")

    def test_legacy_unknown_event_flag_cannot_clear_without_retained_evidence(self):
        self.collector.run_batch(self.manifest)
        self.terminal("0")
        with self.budget.locked() as state:
            batch = state["batches"]["batch-one"]
            batch.pop("billing_events", None)
            batch["billing_prices_complete"] = False
            self.budget._commit(state, "synthetic_legacy_unknown_event_fixture", "batch-one")
        self.collector.reconcile(land=False)
        self.clock.now += 301
        self.collector.reconcile(land=False)
        self.assertFalse(self.budget.batch("batch-one")["billing_prices_complete"])
        self.assertFalse(self.budget.batch("batch-one")["billing_settled"])
        self.assertEqual(money(self.budget.status()["run_committed_usd"]), Decimal(1))

    def test_google_start_upper_estimate_scales_with_memory_and_minimum_one_event(self):
        for memory in (128, 512, 1024, 2048, 4096):
            with self.subTest(memory_mb=memory):
                manifest = self.make_manifest(actor="apify/google-search-scraper")
                manifest["memory_mb"] = memory
                expected = Decimal("0.0125") + Decimal("0.00005") * max(1, memory // 1024)
                manifest["price_basis"]["expected_upper_usd"] = str(expected)
                validate_manifest(manifest, self.clock())
                if memory > 1024:
                    manifest["price_basis"]["expected_upper_usd"] = "0.01255"
                    with self.assertRaises(ValueError):
                        validate_manifest(manifest, self.clock())
                    # Read-only recovery of a historical immutable manifest never launches or re-prices it.
                    validate_manifest(manifest, self.clock(), enforce_freshness=False)

    def test_atomic_file_preserves_previous_contents_on_failure(self):
        path = self.root / "durable.json"
        atomic_write(path, canonical({"actual": "1"}))
        with patch("czlake.production_budget.os.replace", side_effect=OSError()), self.assertRaises(OSError):
            atomic_write(path, canonical({"actual": "2"}))
        self.assertEqual(json.loads(path.read_text()), {"actual": "1"})

    def seed_parallel_batches(self):
        for suffix in ("a", "b", "c"):
            self.collector.run_batch(self.make_manifest(batch_id=f"batch-{suffix}"))
        return ["batch-a", "batch-b", "batch-c"]

    def test_parallel_reconcile_reads_every_settled_run_with_serial_observations(self):
        batch_ids = self.seed_parallel_batches()
        for run in self.transport.runs.values():
            run.update(status="SUCCEEDED", finishedAt=self.clock.iso(), usageTotalUsd="0.03")
        self.collector.reconcile(land=False)
        self.clock.now += 301
        self.collector.reconcile(land=False)
        self.assertTrue(all(self.budget.batch(batch_id)["billing_settled"] for batch_id in batch_ids))
        self.transport.runs["run1"]["usageTotalUsd"] = "0.04"
        self.collector.read_workers = 2
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        active = peak = 0
        reads, observations = [], []
        original_read, original_observe = self.transport.get_run, self.budget.observe

        def read(run_id):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                reads.append(run_id)
            try:
                if run_id in {"run1", "run2"}:
                    barrier.wait(timeout=5)
                return original_read(run_id)
            finally:
                with lock:
                    active -= 1

        def observe(batch_id, run):
            observations.append((batch_id, threading.get_ident()))
            return original_observe(batch_id, run)

        with patch.object(self.transport, "get_run", side_effect=read), patch.object(self.budget, "observe", side_effect=observe):
            self.collector.reconcile(land=False)
        self.assertEqual(peak, 2)
        self.assertCountEqual(reads, ["run1", "run2", "run3"])
        self.assertEqual(observations, [(batch_id, threading.get_ident()) for batch_id in batch_ids])
        self.assertEqual(self.budget.batch("batch-a")["actual_usd"], "0.04")
        self.assertEqual(self.transport.starts, 3)

    def test_failed_parallel_read_blocks_paid_start_without_releasing_reservations(self):
        self.seed_parallel_batches()
        before = self.budget.status()
        original_read = self.transport.get_run
        reads = []

        def read(run_id):
            reads.append(run_id)
            if run_id == "run1":
                raise TimeoutError()
            return original_read(run_id)

        with patch.object(self.transport, "get_run", side_effect=read), self.assertRaises(TimeoutError):
            self.collector.run_batch(self.make_manifest(batch_id="batch-d"))
        self.assertCountEqual(reads, ["run1", "run2", "run3"])
        self.assertEqual(self.budget.status(), before)
        self.assertEqual(self.transport.starts, 3)

    def test_parallel_dataset_downloads_keep_receipts_serial_and_filter_before_commit(self):
        batch_ids = self.seed_parallel_batches()
        for number, run in enumerate(self.transport.runs.values(), 1):
            run.update(status="SUCCEEDED", finishedAt=self.clock.iso(), defaultDatasetId=f"dataset{number}")
        self.collector.read_workers = 2
        barrier = threading.Barrier(2)
        calls, receipts = [], []
        original_record = self.budget.record_landing

        def page(dataset_id, offset, limit):
            calls.append((dataset_id, offset))
            if offset == 0:
                if dataset_id in {"dataset1", "dataset2"}:
                    barrier.wait(timeout=5)
                return [{"username": "public_owner", "followers": [{"username": "FORBIDDEN"}]}]
            return []

        def record(batch_id, receipt):
            receipts.append((batch_id, threading.get_ident()))
            return original_record(batch_id, receipt)

        with patch.object(self.transport, "dataset_page", side_effect=page), patch.object(self.budget, "record_landing", side_effect=record):
            self.collector.reconcile()
        self.assertEqual(receipts, [(batch_id, threading.get_ident()) for batch_id in batch_ids])
        for batch_id in batch_ids:
            receipt = self.budget.batch(batch_id)["landing"]
            self.assertEqual(receipt["items"], 1)
            self.assertNotIn("FORBIDDEN", Path(receipt["path"]).read_text())
        self.assertFalse(list((self.budget.root / "raw").rglob(".filtered-*")))

    def test_parallel_dataset_failure_preserves_recoverable_orphans_without_relaunch(self):
        batch_ids = self.seed_parallel_batches()
        for number, run in enumerate(self.transport.runs.values(), 1):
            run.update(status="SUCCEEDED", finishedAt=self.clock.iso(), defaultDatasetId=f"dataset{number}")

        def page(dataset_id, offset, limit):
            if dataset_id == "dataset1":
                raise TimeoutError()
            return [{"username": "public_owner"}] if offset == 0 else []

        with patch.object(self.transport, "dataset_page", side_effect=page), self.assertRaises(TimeoutError):
            self.collector.reconcile()
        self.assertTrue(all(self.budget.batch(batch_id)["landing"] is None for batch_id in batch_ids))
        self.assertFalse((self.budget.root / "raw/apify/batch-a.json").exists())
        self.assertTrue((self.budget.root / "raw/apify/batch-b.json").exists())
        self.assertFalse(list((self.budget.root / "raw").rglob(".filtered-*")))
        self.transport.rows = [{"username": "public_owner"}]
        with patch.object(self.transport, "dataset_page", wraps=self.transport.dataset_page) as download:
            self.collector.reconcile()
        self.assertTrue(all(self.budget.batch(batch_id)["landing"] for batch_id in batch_ids))
        self.assertEqual({call.args[0] for call in download.call_args_list}, {"dataset1"})
        self.assertEqual(self.transport.starts, 3)

    def test_parallel_read_worker_bounds(self):
        for workers in (0, 33, True, 1.5):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                ProductionCollector(self.budget, self.transport, read_workers=workers)

    def test_repeated_landing_does_not_append_another_receipt_commit(self):
        self.transport.status = "SUCCEEDED"
        batch = self.collector.run_batch(self.manifest)
        before = self.budget.status()
        with patch.object(self.transport, "dataset_page", side_effect=AssertionError("unexpected refetch")):
            self.assertEqual(self.collector.land("batch-one"), batch["landing"])
        self.assertEqual(self.budget.status(), before)


    def make_amendment(self):
        amendment = self.root / "extension.json"
        amendment.write_text(json.dumps({"schema_version": 1,
            "authorization_id": "daniel-production-extension-20261009-110",
            "amends_authorization_id": "daniel-production-20261009",
            "parent_authorization_sha256": file_hash(self.auth), "scope_id": SCOPE_ID,
            "authorized_by": "Daniel", "status": "authorized_for_execution",
            "run_cap_usd": "110.00", "overall_night_cap_usd": "120.00",
            "brief": "docs/tasks/hos-production.md", "recorded_at": self.clock.iso(),
            "evidence": "Explicit instruction to continue beyond 90 minutes to at least $110, within $120 night."}))
        return amendment


    def test_pinned_amendment_extends_effective_cap_without_changing_prior_receipts_or_holds(self):
        self.budget.reserve(self.make_manifest(batch_id="original", cap="95"))
        before = json.loads(self.budget.state_path.read_text())
        original_auth_bytes = self.auth.read_bytes()
        with self.assertRaises(CapExceeded):
            self.budget.reserve(self.make_manifest(batch_id="extension", cap="10"))
        amendment = self.make_amendment()
        imported = self.budget.import_authorization_amendment(amendment, file_hash(amendment))
        after = json.loads(self.budget.state_path.read_text())
        for field in ("auth_path", "auth_sha256", "authorization", "accounting", "holds", "batches"):
            self.assertEqual(after[field], before[field])
        self.assertEqual(self.auth.read_bytes(), original_auth_bytes)
        self.assertEqual(money(imported["run_cap_usd"]), Decimal(110))
        self.assertEqual(money(imported["night_cap_usd"]), Decimal(120))
        self.assertEqual(after["journal"][:-1], before["journal"])
        sequence = after["sequence"]
        self.budget.import_authorization_amendment(amendment, file_hash(amendment))
        self.assertEqual(self.budget.status()["sequence"], sequence)
        restarted = ProductionBudget(self.budget.root, clock=self.clock)
        restarted.reserve(self.make_manifest(batch_id="extension", cap="10"))
        restarted.reserve(self.make_manifest(batch_id="exact-limit", cap="5"))
        self.assertEqual(money(restarted.status()["run_remaining_usd"]), Decimal(0))
        with self.assertRaises(CapExceeded):
            restarted.reserve(self.make_manifest(batch_id="over-amendment", cap="0.01"))
        self.assertEqual(restarted.batch("original"), before["batches"]["original"])


    def test_amendment_cannot_raise_night_cap_or_drop_unresolved_external_reserves(self):
        self.snapshot["entries"][1]["reserved_usd"] = "15"
        self.save_accounting()
        self.budget.import_accounting(self.accounting)
        amendment = self.make_amendment()
        self.budget.import_authorization_amendment(amendment, file_hash(amendment))
        self.budget.reserve(self.make_manifest(batch_id="large", cap="100"))
        with self.assertRaises(CapExceeded):
            self.budget.reserve(self.make_manifest(batch_id="night-overrun", cap="3"))
        self.assertEqual(money(self.budget.status()["night_reserved_usd"]), Decimal(115))


    def test_malformed_wrong_parent_or_changed_amendment_fails_closed_without_ledger_edit(self):
        amendment = self.make_amendment()
        valid = json.loads(amendment.read_text())
        before = self.budget.state_path.read_bytes()
        for field, value in (("run_cap_usd", "120"), ("overall_night_cap_usd", "121"),
                             ("scope_id", "other"), ("authorized_by", "other"),
                             ("amends_authorization_id", "other"), ("parent_authorization_sha256", "0" * 64),
                             ("recorded_at", self.clock.iso(120)), ("evidence", "")):
            with self.subTest(field=field):
                amendment.write_text(json.dumps({**valid, field: value}))
                with self.assertRaises((BudgetError, ValueError)):
                    self.budget.import_authorization_amendment(amendment, file_hash(amendment))
                self.assertEqual(self.budget.state_path.read_bytes(), before)
        amendment.write_text(json.dumps(valid))
        with self.assertRaises(ValueError):
            self.budget.import_authorization_amendment(amendment, "0" * 64)
        self.budget.import_authorization_amendment(amendment, file_hash(amendment))
        after = self.budget.state_path.read_bytes()
        amendment.write_text(json.dumps({**valid, "evidence": "Changed authorization bytes."}))
        with self.assertRaises(BudgetError):
            self.budget.reserve(self.make_manifest(batch_id="tampered-pin"))
        self.assertEqual(self.budget.state_path.read_bytes(), after)



if __name__ == "__main__":
    unittest.main()
