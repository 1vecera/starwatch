"""Integration defects that affect identity, supersession and retained media."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import duckdb
import test_production_incremental as incremental
from test_production_graph import AS_OF, save


class FinishTests(unittest.TestCase):
    setUp = incremental.IncrementalTests.setUp
    tearDown = incremental.IncrementalTests.tearDown
    raw = incremental.IncrementalTests.raw
    post = incremental.IncrementalTests.post
    build = incremental.IncrementalTests.build
    export = incremental.IncrementalTests.export
    bundle = incremental.IncrementalTests.bundle
    media = incremental.IncrementalTests.media

    def query(self, result, sql):
        with duckdb.connect(
            str(self.base / "export" / result["database"]), read_only=True
        ) as connection:
            return connection.execute(sql).fetchall()

    def revised_bundle(
        self, *, original_rejected=False, revised_rejected=False, same=False
    ):
        old_path, old_files = self.bundle(reject=original_rejected, use_strings=True)
        original_root = self.root
        self.root = original_root / "revision"
        self.root.mkdir(exist_ok=True)
        try:
            new_path, new_files = self.bundle(
                reject=revised_rejected,
                use_strings=True,
                topics=None if same else ["transport"],
            )
        finally:
            self.root = original_root
        old_packet = json.loads(old_path.read_text())["packets"][0]
        new_packet = json.loads(new_path.read_text())["packets"][0]
        old_packet["packet_id"], new_packet["packet_id"] = "original", "revision"
        old_item = json.loads(old_files["labels"].read_text())["items"][0]
        new_packet["supersedes"] = {"instagram:1": incremental.digest(old_item)}
        path = original_root / "combined.json"
        save(
            path,
            {
                "schema_version": "production-label-bundle-v1",
                "packets": [old_packet, new_packet],
            },
        )
        return path, old_files, new_files

    def test_revision_removes_stale_active_quarantine_but_preserves_history(self):
        bundle, _, _ = self.revised_bundle(original_rejected=True)
        result = self.export("revision", label_bundle=bundle)
        self.assertEqual(result["counts"]["classification_coverage"], 2)
        self.assertEqual(result["counts"]["claim"], 1)
        self.assertEqual(
            self.query(
                result,
                "SELECT count(*) FROM active_quarantine WHERE grain='classification'",
            ),
            [(0,)],
        )
        self.assertEqual(
            self.query(
                result, "SELECT count(*) FROM quarantine WHERE grain='classification'"
            ),
            [(1,)],
        )
        self.assertEqual(
            self.query(
                result,
                "SELECT current,review_status FROM classification_coverage ORDER BY current",
            ),
            [(False, "reviewed_rejected"), (True, "reviewed_claims")],
        )

    def test_latest_rejected_revision_removes_earlier_claims(self):
        bundle, _, _ = self.revised_bundle(revised_rejected=True)
        result = self.export("rejected-revision", label_bundle=bundle)
        self.assertEqual(result["counts"]["claim"], 0)
        self.assertEqual(result["counts"]["asset_topic"], 0)
        self.assertEqual(
            self.query(
                result, "SELECT claim_status FROM asset WHERE asset_id='instagram:1'"
            ),
            [("reviewed_rejected",)],
        )
        self.assertEqual(
            self.query(
                result,
                "SELECT count(*) FROM active_quarantine WHERE grain='classification'",
            ),
            [(1,)],
        )

    def test_identical_overlap_deduplicates_and_changed_overlap_needs_hash(self):
        bundle, _, _ = self.revised_bundle(same=True)
        document = json.loads(bundle.read_text())
        del document["packets"][1]["supersedes"]
        save(bundle, document)
        result = self.export("identical", label_bundle=bundle)
        self.assertEqual(result["counts"]["claim"], 1)
        document["packets"][1]["supersedes"] = {"instagram:1": "0" * 64}
        # Changing the verdict requires binding even when the caption labels match.
        _, _, _new_files = self.revised_bundle(revised_rejected=True)
        document = json.loads(bundle.read_text())
        document["packets"][1]["supersedes"] = {"instagram:1": "0" * 64}
        save(bundle, document)
        with self.assertRaisesRegex(ValueError, "supersedes"):
            self.build(label_bundle=bundle)

    def test_packet_raw_hash_binding_is_checked(self):
        bundle, _ = self.bundle(use_strings=True)
        document = json.loads(bundle.read_text())
        document["packets"][0]["cards_sha256"] = "0" * 64
        save(bundle, document)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.build(label_bundle=bundle)

    def test_historical_owner_and_text_conflicts_survive_new_matching_observation(self):
        original = json.loads(self.paths["review"].read_text())
        for field, value, reason in (
            ("owner_handle", "bob", "reported_publication_owner_conflict"),
            ("text", "Contradictory historical caption", "content_contradiction"),
        ):
            with self.subTest(field=field):
                review = deepcopy(original)
                review["posts"][3][field] = value
                save(self.paths["review"], review)
                self.production.mkdir(parents=True, exist_ok=True)
                raw_dir = self.production / "raw/apify"
                if raw_dir.exists():
                    for path in raw_dir.glob("*.json"):
                        path.unlink()
                old = next(
                    a for a in self.build()["asset"] if a["asset_id"] == "instagram:1"
                )
                self.assertEqual(old["verification_status"], "quarantined")
                new = self.post(1, text=old["text"])
                new["url"] = old["url"]
                self.raw([new])
                result = self.export("historical-" + field)
                self.assertEqual(
                    self.query(
                        result,
                        "SELECT verification_status,verification_reason FROM asset WHERE asset_id='instagram:1'",
                    ),
                    [("quarantined", reason)],
                )
                self.assertEqual(
                    self.query(
                        result,
                        "SELECT count(*) FROM active_quarantine WHERE grain='asset' AND record_id='instagram:1'",
                    ),
                    [(2,)],
                )
                self.assertEqual(
                    self.query(
                        result,
                        "SELECT count(*) FROM asset_relation WHERE asset_id='instagram:1' AND status='confirmed'",
                    ),
                    [(0,)],
                )
                connection = duckdb.connect(":memory:")
                try:
                    connection.execute(incremental.graph.DDL)
                    rows = self.build()
                    broken = next(
                        a for a in rows["asset"] if a["asset_id"] == "instagram:1"
                    )
                    broken.update(
                        verification_status="verified_publication_owner",
                        owner_account_id="instagram:alice",
                    )
                    for table in incremental.graph.TABLES:
                        incremental.graph.insert_rows(connection, table, rows[table])
                    with self.assertRaisesRegex(ValueError, "accumulated_.*conflict"):
                        incremental.graph.validate(connection)
                finally:
                    connection.close()

    def test_multiple_same_owner_proofs_preserve_evidence_but_one_account_row(self):
        review = self.root / "additional-alice-review.json"
        save(review, json.loads(self.paths["identity"].read_text()))
        result = self.export("same-owner", identity_reviews=[review])
        self.assertEqual(
            self.query(
                result,
                "SELECT count(*) FROM account_relation WHERE account_id='instagram:alice' AND status='confirmed'",
            ),
            [(2,)],
        )
        self.assertEqual(
            self.query(
                result,
                "SELECT count(*) FROM verified_accounts WHERE account_id='instagram:alice'",
            ),
            [(1,)],
        )
        accounts = json.loads(
            (self.base / "export/checkpoints/same-owner/accounts.json").read_text()
        )
        self.assertEqual(len(accounts), 1)

    def test_scalar_numeric_coercion_and_large_counts_keep_database_contract(self):
        rows = self.build()
        rows["entity"][0]["relevance_score"] = "1.5"
        measured = next(m for m in rows["metric"] if m["value"] is not None)
        measured["value"] = 10**20
        with duckdb.connect(":memory:") as connection:
            connection.execute(incremental.graph.DDL)
            for table in incremental.graph.TABLES:
                incremental.graph.insert_rows(connection, table, rows[table])
            incremental.graph.validate(connection)
            self.assertEqual(
                connection.execute(
                    "SELECT relevance_score FROM entity WHERE entity_id=?",
                    [rows["entity"][0]["entity_id"]],
                ).fetchall(),
                [(1.5,)],
            )
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM metric WHERE metric_id=?",
                    [measured["metric_id"]],
                ).fetchall(),
                [(1e20,)],
            )

    def test_instagram_actor_cannot_admit_mobile_facebook_permalink(self):
        post = self.post()
        post["url"] = "https://m.facebook.com/123/posts/456/"
        self.raw([post])
        rows = self.build()
        self.assertNotIn("instagram:4", {row["asset_id"] for row in rows["asset"]})
        self.assertTrue(
            any(
                row["record_id"] == "4"
                and row["reason"] == "missing_public_asset_id_url_or_scalar_text"
                for row in rows["quarantine"]
            )
        )

    def test_new_identity_rechecks_cached_direct_assets_without_new_collection(self):
        proof = deepcopy(
            json.loads(self.paths["identity"].read_text())["candidates"][
                "alice-candidacy"
            ]
        )
        proof.update(
            handle="bob",
            profile_url="https://www.instagram.com/bob/",
            source_url="https://campaign.example/bob",
        )
        review = self.root / "bob-review.json"
        save(review, {"candidates": {"bob-candidacy": proof}, "lists": {}})
        bundle = self.root / "identity-bundle.json"
        save(
            bundle,
            {
                "schema_version": "production-identity-bundle-v1",
                "reviews": [
                    {"path": str(review), "sha256": incremental.file_sha(review)}
                ],
            },
        )
        result = self.export("identity", identity_reviews=[bundle])
        self.assertEqual(
            self.query(
                result,
                "SELECT verification_status FROM asset WHERE asset_id='instagram:3'",
            ),
            [("verified_publication_owner",)],
        )
        proof["handle"] = "forged"
        save(review, {"candidates": {"bob-candidacy": proof}})
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.build(identity_reviews=[bundle])

    def test_numeric_facebook_profile_and_exact_href_must_agree(self):
        record = {
            "postId": "7",
            "text": "Public source",
            "url": "https://www.facebook.com/61599/posts/7",
            "topLevelUrl": "https://www.facebook.com/61599/posts/7",
            "user": {"id": "61599"},
            "time": AS_OF,
        }
        self.raw([record], actor="apify/facebook-posts-scraper")
        proof = {
            "platform": "facebook",
            "page_id": "61599",
            "page_id_link_confirmed": True,
            "profile_url": "https://www.facebook.com/61599/",
            "exact_href": "https://www.facebook.com/profile.php?id=61599",
            "adjudication": "confirmed",
            "identity_confirmed": True,
            "anchor_links_account": True,
            "public": True,
            "source_url": "https://campaign.example/alice",
            "observed_at": AS_OF,
        }
        review = self.root / "facebook-review.json"
        save(review, {"candidates": {"alice-candidacy": proof}})
        rows = self.build(identity_reviews=[review])
        self.assertEqual(
            next(a for a in rows["asset"] if a["asset_id"] == "facebook:7")[
                "verification_status"
            ],
            "verified_publication_owner",
        )
        for change in (
            {"profile_url": "https://www.facebook.com/different/"},
            {"exact_href": "https://www.facebook.com/profile.php?id=999"},
        ):
            save(review, {"candidates": {"alice-candidacy": {**proof, **change}}})
            self.assertEqual(
                next(
                    a
                    for a in self.build(identity_reviews=[review])["asset"]
                    if a["asset_id"] == "facebook:7"
                )["verification_status"],
                "quarantined",
            )

    def test_private_profile_contradiction_blocks_independent_public_anchor(self):
        self.raw(
            [{"username": "alice", "private": True, "latestPosts": []}],
            actor="apify/instagram-profile-scraper",
        )
        result = self.export("private")
        self.assertEqual(
            self.query(
                result,
                "SELECT count(*) FROM verified_accounts WHERE account_id='instagram:alice'",
            ),
            [(0,)],
        )
        self.assertEqual(
            self.query(
                result,
                "SELECT count(*) FROM verified_assets WHERE owner_account_id='instagram:alice'",
            ),
            [(0,)],
        )

    def test_public_anchor_confirms_owner_without_inventing_account_visibility(self):
        proof = deepcopy(
            json.loads(self.paths["identity"].read_text())["candidates"][
                "alice-candidacy"
            ]
        )
        proof.update(
            handle="charlie",
            profile_url="https://www.instagram.com/charlie/",
            source_url="https://campaign.example/bob",
        )
        review = self.root / "charlie-review.json"
        save(review, {"candidates": {"bob-candidacy": proof}})
        rows = self.build(identity_reviews=[review])
        account = next(
            a for a in rows["account"] if a["account_id"] == "instagram:charlie"
        )
        self.assertEqual(account["identity_status"], "confirmed")
        self.assertIsNone(account["public"])
        self.raw(
            [
                {
                    "username": "charlie",
                    "private": False,
                    "followersCount": 17,
                    "fullName": "Public source name",
                    "latestPosts": [self.post(4, owner="charlie")],
                }
            ],
            actor="apify/instagram-profile-scraper",
        )
        result = self.export("public-profile", identity_reviews=[review])
        self.assertEqual(
            self.query(
                result,
                "SELECT public FROM account WHERE account_id='instagram:charlie'",
            ),
            [(True,)],
        )
        self.assertEqual(
            self.query(
                result,
                "SELECT value,observed_at FROM metric WHERE account_id='instagram:charlie' AND name='followers'",
            ),
            [(17.0, AS_OF)],
        )
        self.assertEqual(
            self.query(
                result,
                "SELECT verification_status FROM asset WHERE asset_id='instagram:4'",
            ),
            [("verified_publication_owner",)],
        )

    def test_media_invalid_magic_cannot_match_missing_content_type(self):
        index, local = self.media()
        local.write_bytes(b"invalid image bytes")
        document = json.loads(index.read_text())
        document["records"][0].update(
            sha256=incremental.file_sha(local),
            bytes=local.stat().st_size,
            content_type=None,
        )
        save(index, document)
        with self.assertRaises(ValueError):
            self.build(media_index=index)

    def test_profile_media_original_projection_lineage_is_exact(self):
        from czlake.production_collect import public_metadata

        index, _ = self.media()
        document = json.loads(index.read_text())
        record = document["records"][0]
        post = json.loads(Path(record["source_envelope"]).read_text())["items"][0]
        legacy = self.root / "legacy-profiles.json"
        profile = {"username": "alice", "private": False, "latestPosts": [post]}
        save(legacy, {"actor": "apify/instagram-profile-scraper", "items": [profile]})
        source = self.raw(
            [public_metadata("apify/instagram-profile-scraper", profile)],
            actor="apify/instagram-profile-scraper",
            name="projected",
        )
        envelope = json.loads(source.read_text())
        envelope["original_source"] = {
            "path": str(legacy),
            "sha256": incremental.file_sha(legacy),
        }
        save(source, envelope)
        record.update(
            source_envelope=str(source),
            source_envelope_sha256=incremental.file_sha(source),
            source_post_index=0,
        )
        save(index, document)
        rows = self.build(media_index=index)
        self.assertEqual(
            rows["media_resource"][0]["source_pointer"],
            "/items/0/latestPosts/0/displayUrl",
        )
        envelope["items"][0]["username"] = "bob"
        save(source, envelope)
        record["source_envelope_sha256"] = incremental.file_sha(source)
        save(index, document)
        with self.assertRaisesRegex(ValueError, "original projection"):
            self.build(media_index=index)

    def test_carousel_media_binds_parent_asset_and_rejects_engager_pointer(self):
        index, _ = self.media()
        document = json.loads(index.read_text())
        record = document["records"][0]
        source = Path(record["source_envelope"])
        envelope = json.loads(source.read_text())
        child_url = "https://cdn.example.fbcdn.net/child.jpg"
        envelope["items"][0]["childPosts"] = [{"id": "child", "displayUrl": child_url}]
        save(source, envelope)
        record.update(
            source_envelope_sha256=incremental.file_sha(source),
            source_url=child_url,
            final_url=child_url,
            source_media_pointer="/items/0/childPosts/0/displayUrl",
        )
        save(index, document)
        rows = self.build(media_index=index)
        self.assertEqual(rows["media_resource"][0]["asset_id"], "instagram:4")
        record["source_media_pointer"] = "/items/0/latestComments/0/username"
        save(index, document)
        with self.assertRaisesRegex(ValueError, "public asset media"):
            self.build(media_index=index)

    def test_native_classifier_and_reviewer_use_registered_original_packet(self):
        adapter = (
            Path(__file__).parents[3]
            / "native_provenance/implementation/src/czlake/production_labels.py"
        )
        if adapter.exists():
            spec = importlib.util.spec_from_file_location(
                "czlake.production_labels", adapter
            )
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            import czlake.production_labels as module
        bundle, files = self.bundle(use_strings=True)
        labels, review = (
            json.loads(files[name].read_text()) for name in ("labels", "review")
        )
        registry = {
            "native_parent_session_id": "native-parent",
            "native_parent_task_path": "/root",
            "assignments": [],
        }
        for kind, document, task, name in (
            ("classification", labels, "classifier", "labels"),
            ("independent_review", review, "reviewer", "review"),
        ):
            path = files[name]
            task_path = "/root/" + task
            document["session_id"] = "native:" + task_path
            row = {
                "assignment_id": document["assignment_id"],
                "session_id": document["session_id"],
                "task_kind": kind,
                "task_path": task_path,
                "parent_session_id": "native-parent",
                "brief": str(path.parent / "brief.md"),
                "brief_sha256": incremental.file_sha(path.parent / "brief.md"),
                "cards_path": str(files["cards"]),
                "cards_sha256": incremental.file_sha(files["cards"]),
                "output_directory": str(path.parent),
                "output_path": str(path),
                "output_kind": name,
                "registered_at": (
                    datetime.now(UTC) - timedelta(seconds=30)
                ).isoformat(),
                "spawn_receipt": {"task_name": task_path},
                "session_binding": {
                    "source": "native:collaboration",
                    "task_path": task_path,
                    "parent_session_id": "native-parent",
                },
            }
            if kind == "independent_review":
                document["submission_sha256"] = incremental.digest(labels)
                row["submission_sha256"] = document["submission_sha256"]
            save(path, document)
            registry["assignments"].append(row)
        save(files["registry"], registry)
        with patch.dict(sys.modules, {"czlake.production_labels": module}):
            result = self.export("native", label_bundle=bundle)
            self.assertEqual(result["counts"]["claim"], 1)
            registry["assignments"][1]["spawn_receipt"] = {"task_name": "/root/forged"}
            save(files["registry"], registry)
            with self.assertRaises(ValueError):
                self.build(label_bundle=bundle)


if __name__ == "__main__":
    unittest.main()
