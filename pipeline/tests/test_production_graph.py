"""Adversarial cached graph/immutable checkpoint tests; no collection/provider calls."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import duckdb

MODULE = Path(__file__).parents[1] / "src/czlake/production_graph.py"
sys.path.insert(0, str(MODULE.parent))
spec = importlib.util.spec_from_file_location("worker_production_graph", MODULE)
assert spec is not None and spec.loader is not None
graph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graph)
SCRATCH = Path(__file__).parents[1] / "tmp/production-graph-tests"
SCRATCH.mkdir(parents=True, exist_ok=True)
AS_OF = "2026-10-09T01:50:00+00:00"
PRIVATE_MARKER = "DO_NOT_PERSIST_ENGAGER_90731"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(root):
    """One exact local list, two distinct candidacies and one invalid N row."""

    def person(entity_id, position, validity="A"):
        return {
            "candidate": {
                "key": entity_id,
                "city_code": "123456",
                "city_rank": 1,
                "list_no": "7",
                "position": position,
                "eligible": validity == "A",
                "eligibility_kind": "current_candidacy",
                "population": 10000,
                "historical_identity_clear": False,
            },
            "city": "Fixture city",
            "name": "Same Name",
            "person_id": "unresolved_namesake_cluster",
            "qualified": validity == "A",
            "protected": False,
            "score": 1.5,
            "components": {"party_contender": 1.5},
            "reasons": ["party_contender"],
            "rule_version": "relevance-v2",
            "evidence": {
                "validity": validity,
                "source_url": "https://official.example/registry.zip",
                "fetched_at": AS_OF,
            },
        }

    universe = [
        person("alice-candidacy", 1),
        person("bob-candidacy", 2),
        person("invalid-candidacy", 3, "N"),
    ]
    lists = [
        {
            "key": "kv2026:123456:7",
            "city": "Fixture city",
            "city_rank": 1,
            "municipality_code": "123456",
            "name": "Local list",
            "list_no": "7",
            "qualified": False,
            "protected": False,
            "priority": {
                "score": 0.5,
                "components": {"local_list_result": 0.5},
                "sources": {"current_list": "https://official.example/registry.zip"},
            },
            "rule_version": "relevance-v2",
            "observed_at": AS_OF,
        }
    ]
    select = {
        "qualified_keys": ["alice-candidacy"],
        "qualifying_overflow": ["bob-candidacy"],
        "additional_discovery_keys": [],
    }
    proof = {
        "adjudication": "confirmed",
        "identity_confirmed": True,
        "anchor_links_account": True,
        "public": True,
        "handle": "alice",
        "profile_url": "https://www.instagram.com/alice/",
        "source_url": "https://campaign.example/alice",
        "observed_at": AS_OF,
        "excerpt": "Public political page links this exact account.",
    }
    identity = {"candidates": {"alice-candidacy": proof}, "lists": {}}
    raw_path = root / "raw-profiles.json"
    profiles = []
    for who in ("alice", "bob"):
        profiles.append(
            {
                "handle": who,
                "requested_entity_key": f"{who}-candidacy",
                "public": True,
                "profile_url": f"https://www.instagram.com/{who}/",
                "display_name": "Public profile",
                "biography": "Public bio",
                "followers": 10,
                "followers_attributed_to_entity": 10,
                "observed_at": AS_OF,
                "source_path": str(raw_path),
                "commenters": [{"name": PRIVATE_MARKER}],
                "relatedProfiles": [{"username": PRIVATE_MARKER}],
            }
        )

    def post(post_id, observed, owner, likes=5):
        return {
            "post_id": f"instagram:{post_id}",
            "handle": observed,
            "observed_profile_handle": observed,
            "owner_handle": owner,
            "url": f"https://www.instagram.com/p/ABC{post_id}/",
            "published_at": "2026-10-08T12:00:00Z",
            "fetched_at": AS_OF,
            "kind": "Video",
            "text": "Quoted words are unreviewed even if the account is owned.",
            "likes": likes,
            "comments_count": 3,
            "views": 20,
            "latestComments": [
                {"ownerUsername": PRIVATE_MARKER, "text": PRIVATE_MARKER}
            ],
            "taggedUsers": [{"username": PRIVATE_MARKER}],
        }

    posts = [
        post(1, "alice", "alice"),
        post(2, "alice", "external"),
        post(3, "bob", "bob", -1),
        post(1, "bob", "alice"),
    ]
    raw_posts = [
        {
            "id": str(i),
            "ownerUsername": who,
            "displayUrl": f"https://cdn.example/{i}.jpg",
            "videoUrl": f"https://cdn.example/{i}.mp4",
            "comments": [{"username": PRIVATE_MARKER}],
            "taggedUsers": [{"username": PRIVATE_MARKER}],
        }
        for i, who in ((1, "alice"), (2, "external"), (3, "bob"))
    ]
    raw = {
        "items": [
            {
                "username": "alice",
                "private": False,
                "profilePicUrl": "https://cdn.example/alice.jpg",
                "latestPosts": raw_posts,
                "relatedProfiles": [{"username": PRIVATE_MARKER}],
            }
        ]
    }
    review = {
        "profiles": profiles,
        "posts": posts,
        "observed_at": AS_OF,
        "window": ["2026-04-09T00:00:00+02:00", "2026-10-09T00:00:00+02:00"],
    }
    paths = {
        "universe": root / "relevance/universe.json",
        "lists": root / "relevance/lists.json",
        "selection": root / "relevance/selection.json",
        "identity": root / "identity.json",
        "review": root / "review.json",
        "raw": raw_path,
    }
    for label, payload in (
        ("universe", universe),
        ("lists", lists),
        ("selection", select),
        ("identity", identity),
        ("review", review),
        ("raw", raw),
    ):
        save(paths[label], payload)
    return paths


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.base = Path(self.temp.name)
        self.root = self.base / "sources"
        self.paths = fixture(self.root)
        self.kwargs = {
            "relevance_dir": self.root / "relevance",
            "reviews": [self.paths["review"]],
            "identity_path": self.paths["identity"],
            "as_of": AS_OF,
        }

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        return graph.build_cached_graph(self.root, **self.kwargs)[0]

    def change(self, label, apply):
        content = json.loads(self.paths[label].read_text())
        apply(content)
        save(self.paths[label], content)

    def export(self, name):
        return graph.export_checkpoint(
            self.root, output=self.base / "output", checkpoint_id=name, **self.kwargs
        )

    def test_meaningful_overflow_invalid_and_namesake_grains(self):
        data = self.build()
        people = [row for row in data["entity"] if row["kind"] == "current_candidacy"]
        self.assertEqual(
            [row["entity_id"] for row in people], ["alice-candidacy", "bob-candidacy"]
        )
        self.assertEqual(
            {row["selection_status"] for row in people},
            {"selected_proposal", "qualifying_overflow"},
        )
        self.assertEqual(len({row["person_cluster_id"] for row in people}), 1)
        self.assertTrue(
            any(row["record_id"] == "invalid-candidacy" for row in data["quarantine"])
        )
        self.assertEqual(
            len([row for row in data["entity"] if row["kind"] == "local_list"]), 1
        )

    def test_unknown_owner_repost_and_shared_post_are_separate(self):
        data = self.build()
        assets = {row["asset_id"]: row for row in data["asset"]}
        self.assertEqual(
            assets["instagram:1"]["verification_status"], "verified_publication_owner"
        )
        self.assertEqual(
            assets["instagram:2"]["verification_reason"],
            "other_owner_in_profile_bundle_not_owned",
        )
        self.assertEqual(
            assets["instagram:3"]["verification_reason"],
            "independent_owner_anchor_missing",
        )
        self.assertEqual(len(data["asset_observation"]), 4)
        self.assertEqual(
            [(row["entity_id"], row["relation"]) for row in data["asset_relation"]],
            [("alice-candidacy", "published_by")],
        )
        self.assertEqual(data["claim"], [])
        self.assertEqual(data["topic"], [])

    def test_a_follower_attribution_number_never_confirms_owner(self):
        self.change("identity", lambda value: value["candidates"].clear())
        self.assertEqual(self.build()["asset_relation"], [])

    def test_exact_link_mismatch_social_self_anchor_and_stale_proof(self):
        original = json.loads(self.paths["identity"].read_text())
        for update in (
            {"handle": "another"},
            {"profile_url": "https://www.instagram.com/another"},
            {"source_url": "https://www.instagram.com/alice/"},
            {"observed_at": "2026-08-01T12:00:00Z"},
            {"observed_at": "2027-01-01T12:00:00Z"},
        ):
            with self.subTest(update=update):
                changed = deepcopy(original)
                changed["candidates"]["alice-candidacy"].update(update)
                save(self.paths["identity"], changed)
                self.assertEqual(self.build()["asset_relation"], [])

    def test_reported_owner_conflict_prevents_promotion(self):
        self.change(
            "review", lambda value: value["posts"][3].update(owner_handle="bob")
        )
        first = next(
            row for row in self.build()["asset"] if row["asset_id"] == "instagram:1"
        )
        self.assertEqual(
            first["verification_reason"], "reported_publication_owner_conflict"
        )
        self.assertEqual(self.build()["asset_relation"], [])

    def test_raw_owner_contradiction_prevents_promotion(self):
        self.change(
            "raw",
            lambda value: value["items"][0]["latestPosts"][0].update(
                ownerUsername="external"
            ),
        )
        first = next(
            row for row in self.build()["asset"] if row["asset_id"] == "instagram:1"
        )
        self.assertEqual(first["verification_status"], "quarantined")
        self.assertEqual(
            first["verification_reason"], "reported_publication_owner_conflict"
        )

    def test_multiple_entity_owner_proofs_are_conflicted(self):
        self.change(
            "review",
            lambda value: value["profiles"][1].update(
                handle="alice", profile_url="https://www.instagram.com/alice/"
            ),
        )
        self.change(
            "identity",
            lambda value: value["candidates"].update(
                {"bob-candidacy": deepcopy(value["candidates"]["alice-candidacy"])}
            ),
        )
        data = self.build()
        self.assertEqual(data["asset_relation"], [])
        self.assertTrue(
            all(row["status"] == "conflicted" for row in data["account_relation"])
        )

    def test_private_raw_account_prevents_public_owner_promotion(self):
        self.change("raw", lambda value: value["items"][0].update(private=True))
        self.assertEqual(self.build()["asset_relation"], [])

    def test_sentinel_missing_and_undated_metrics(self):
        data = self.build()
        row = next(
            row
            for row in data["metric"]
            if row["asset_id"] == "instagram:3" and row["name"] == "likes"
        )
        self.assertIsNone(row["value"])
        self.assertEqual(row["null_reason"], "provider_unavailable_sentinel")
        self.assertEqual(row["raw_value"], "-1")
        for value in (-2, True, float("nan"), "12", None):
            self.assertIsNone(graph.normalize_metric(value, AS_OF)[0])
        self.assertEqual(graph.normalize_metric(0, AS_OF), (0, None))
        self.assertEqual(
            graph.normalize_metric(12, None),
            (None, "observation_time_missing_or_invalid"),
        )

    def test_missing_overflow_is_a_blocking_coverage_error(self):
        self.change("selection", lambda value: value.update(qualifying_overflow=[]))
        with self.assertRaisesRegex(ValueError, "every meaningful qualifier"):
            self.build()

    def test_reviewed_noncandidate_role_is_separate_from_candidacy(self):
        def noncandidate(value):
            value[1]["candidate"].update(
                eligibility_kind="reviewed_local_role",
                local_role_verified=True,
                position=0,
            )
            value[1]["reviewed_sources"] = [
                {
                    "source_url": "https://campaign.example/role",
                    "adjudication": "confirmed",
                }
            ]

        self.change("universe", noncandidate)
        role = next(
            row for row in self.build()["entity"] if row["entity_id"] == "bob-candidacy"
        )
        self.assertEqual(role["kind"], "noncandidate_person")
        self.assertIsNone(role["list_id"])
        self.assertIsNone(role["validity"])
        self.assertEqual(role["local_role_status"], "reviewed_local_role")
        self.change(
            "universe",
            lambda value: value[1]["candidate"].update(
                eligibility_kind="invented_kind"
            ),
        )
        with self.assertRaisesRegex(ValueError, "unknown/ineligible"):
            self.build()

    def test_quality_gates_reject_wrong_publisher_and_missing_metric_observation(self):
        data = self.build()
        con = duckdb.connect(":memory:")
        try:
            con.execute(graph.DDL)
            for table in graph.TABLES:
                graph.insert_rows(con, table, data[table])
            con.execute("UPDATE asset_relation SET entity_id='bob-candidacy'")
            with self.assertRaisesRegex(ValueError, "false_publisher_relation.*1"):
                graph.validate(con)
            con.execute("UPDATE asset_relation SET entity_id='alice-candidacy'")
            con.execute("UPDATE metric SET observation_id='missing' WHERE name='likes'")
            with self.assertRaisesRegex(ValueError, "orphan_metric_observation.*[1-9]"):
                graph.validate(con)
        finally:
            con.close()

    def test_schema_foreign_keys_and_polymorphic_metrics(self):
        result = self.export("one")
        con = duckdb.connect(
            str(self.base / "output" / result["database"]), read_only=True
        )
        try:
            self.assertEqual(
                con.execute("SELECT count(*) FROM verified_assets").fetchall()[0][0], 1
            )
            self.assertEqual(
                con.execute("SELECT count(*) FROM entity").fetchall()[0][0], 3
            )
            self.assertEqual(graph.validate(con)["status"], "passed")
        finally:
            con.close()
        con = duckdb.connect(":memory:")
        con.execute(graph.DDL)
        with self.assertRaises(duckdb.ConstraintException):
            con.execute(
                "INSERT INTO asset(asset_id,platform,owner_account_id,verification_status,verification_reason,claim_status) VALUES ('invalid','instagram','nonexistent','quarantined','missing','unreviewed')"
            )
        con.close()

    def test_nested_engager_fields_never_persisted(self):
        result = self.export("privacy")
        directory = (self.base / "output" / result["manifest"]).parent
        for path in directory.iterdir():
            self.assertNotIn(PRIVATE_MARKER.encode(), path.read_bytes(), path.name)
        self.assertNotIn(PRIVATE_MARKER, graph.packed(self.build()))

    def test_sources_read_only_and_manifest_hashes(self):
        before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.paths.values()
        }
        result = self.export("source-integrity")
        after = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.paths.values()
        }
        self.assertEqual(before, after)
        directory = (self.base / "output" / result["manifest"]).parent
        manifest = json.loads((directory / "manifest.json").read_text())
        for name, record in manifest["files"].items():
            self.assertEqual(
                hashlib.sha256((directory / name).read_bytes()).hexdigest(),
                record["sha256"],
            )
        self.assertEqual(
            hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest(),
            result["manifest_sha256"],
        )

    def test_existing_id_is_immutable_and_new_pointer_preserves_previous(self):
        first = self.export("first")
        database = self.base / "output" / first["database"]
        original = database.read_bytes()
        with self.assertRaises(FileExistsError):
            self.export("first")
        second = self.export("second")
        self.assertEqual(database.read_bytes(), original)
        self.assertEqual(
            json.loads((self.base / "output/current.json").read_text())[
                "checkpoint_id"
            ],
            second["checkpoint_id"],
        )

    def test_changed_source_failure_keeps_previous_pointer(self):
        self.export("before")
        pointer = (self.base / "output/current.json").read_bytes()
        with (
            patch.object(graph.Inputs, "unchanged", return_value=False),
            self.assertRaisesRegex(RuntimeError, "Inputs changed"),
        ):
            self.export("changed-source")
        self.assertEqual((self.base / "output/current.json").read_bytes(), pointer)
        self.assertFalse((self.base / "output/checkpoints/changed-source").exists())
        self.assertFalse(list((self.base / "output/checkpoints").glob(".building-*")))

    def test_interrupted_pointer_publication_keeps_previous_version_readable(self):
        self.export("before")
        pointer = (self.base / "output/current.json").read_bytes()
        original = graph.write_json

        def fail_pointer(path, value):
            if Path(path).name.startswith(".current-"):
                raise OSError("simulated interruption")
            original(path, value)

        with (
            patch.object(graph, "write_json", side_effect=fail_pointer),
            self.assertRaisesRegex(OSError, "simulated interruption"),
        ):
            self.export("complete-orphan")
        self.assertEqual((self.base / "output/current.json").read_bytes(), pointer)
        self.assertTrue(
            (self.base / "output/checkpoints/complete-orphan/manifest.json").exists()
        )


if __name__ == "__main__":
    unittest.main()
