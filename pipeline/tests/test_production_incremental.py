"""Incremental metadata and real-shaped native session/packet binding checks."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import duckdb
from test_production_graph import AS_OF, PRIVATE_MARKER, SCRATCH, fixture, graph, save

from czlake.production_labels import VERSION, digest, text_digest


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class IncrementalTests(unittest.TestCase):
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
        self.production = self.root / "production"

    def tearDown(self):
        self.temp.cleanup()

    def raw(self, items, actor="apify/instagram-scraper", name="new"):
        epoch = datetime.fromisoformat(AS_OF).timestamp()
        envelope = {
            "schema_version": 1,
            "policy_version": "public-metadata-v1",
            "actor": actor,
            "batch_id": name,
            "run_id": name + "-run",
            "fetched_at_epoch": epoch,
            "input_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "items": items,
        }
        path = self.production / "raw/apify" / (name + ".json")
        save(path, envelope)
        return path

    def post(self, ident=4, owner="alice", text="A new publication"):
        return {
            "id": str(ident),
            "ownerUsername": owner,
            "url": f"https://www.instagram.com/p/NEW{ident}/",
            "caption": text,
            "type": "Video",
            "timestamp": "2026-10-08T12:00:00Z",
            "likesCount": -1,
            "commentsCount": 2,
            "videoViewCount": 14,
            "displayUrl": "https://cdn.example/preview.jpg",
            "latestComments": [{"username": PRIVATE_MARKER}],
            "identity_confirmed": True,
            "entity_id": "bob-candidacy",
        }

    def build(self, **extra):
        rows, inputs, date = graph.build_cached_graph(self.root, **self.kwargs)
        return graph.extend_graph(
            rows,
            inputs,
            date,
            production_root=self.production,
            helpers={
                "handle": graph.handle,
                "confirmed_owner": graph.confirmed_owner,
                "normalize_metric": graph.normalize_metric,
            },
            **extra,
        )

    def export(self, name, **extra):
        return graph.export_checkpoint(
            self.root,
            output=self.base / "export",
            checkpoint_id=name,
            production_root=self.production,
            **self.kwargs,
            **extra,
        )

    def bundle(
        self,
        *,
        topics=None,
        claim_limit=3,
        claims=None,
        reject=False,
        use_strings=False,
    ):
        text = self.build()["asset"][0]["text"]
        # The cached canonical first asset is instagram:1.
        first = next(a for a in self.build()["asset"] if a["asset_id"] == "instagram:1")
        text = first["text"]
        folder_a, folder_b = self.root / "classifier", self.root / "reviewer"
        folder_a.mkdir(exist_ok=True)
        folder_b.mkdir(exist_ok=True)
        card = {
            "asset_id": "instagram:1",
            "entity_id": "alice-candidacy",
            "text": text,
            "content_sha256": text_digest(text),
            "owner_status": "independently_confirmed",
            "source_url": first["url"],
            "platform": "instagram",
            "speaker_entity_id": None,
            "speaker_status": "unknown",
            "claim_limit": claim_limit,
        }
        cards = [card]
        claim_rows = (
            claims
            if claims is not None
            else [
                {
                    "text": text,
                    "start": 0,
                    "end": len(text),
                    "topics": ["housing"],
                    "claim_type": "source_statement",
                    "speaker_entity_id": None,
                    "speaker_status": "unknown",
                }
            ]
        )
        label = {
            "asset_id": "instagram:1",
            "content_sha256": text_digest(text),
            "topics": ["housing"] if topics is None else topics,
            "claims": claim_rows,
            "abstain_reason": "No substantive topic in supplied caption"
            if topics == []
            else None,
            "coverage": {
                "claim_limit": claim_limit,
                "basis": "supplied_caption_only",
                "claims_truncated": claim_limit == 5,
                "omitted_claims_count": None if claim_limit == 5 else 0,
                "note": "Pilot packet; supplied caption only, media not reviewed.",
            },
        }
        labels = {
            "schema_version": VERSION,
            "assignment_id": "classify-native",
            "session_id": "native-session-a",
            "items": [label],
        }
        review = {
            "schema_version": VERSION,
            "assignment_id": "review-native",
            "session_id": "native-session-b",
            "submission_sha256": digest(labels),
            "items": [
                {
                    "asset_id": "instagram:1",
                    "decision": "reject" if reject else "accept",
                    "critical_errors": [],
                    "topic_errors": [],
                    "reviewed_claim_indexes": list(range(len(claim_rows))),
                    "reason": "Exact source offsets and context reviewed.",
                }
            ],
        }
        files = {
            "cards": folder_a / "cards.json",
            "labels": folder_a / "labels.json",
            "review": folder_b / "review.json",
            "registry": self.root / "registry-frozen.json",
        }
        save(files["cards"], cards)
        save(files["labels"], labels)
        save(files["review"], review)
        registry = {"assignments": []}
        for key, session, kind, pane, folder in [
            (
                "classify-native",
                "native-session-a",
                "classification",
                "w1:p1",
                folder_a,
            ),
            (
                "review-native",
                "native-session-b",
                "independent_review",
                "w1:p2",
                folder_b,
            ),
        ]:
            brief = folder / "brief.md"
            brief.write_text("Bounded original assignment fixture.\n")
            agent = {
                "pane_id": pane,
                "agent_session": {
                    "source": "herdr:codex",
                    "kind": "id",
                    "value": session,
                },
            }
            registry["assignments"].append(
                {
                    "assignment_id": key,
                    "session_id": session,
                    "task_kind": kind,
                    "pane": pane,
                    "brief": str(brief),
                    "brief_sha256": file_sha(brief),
                    "cards_sha256": file_sha(files["cards"]),
                    "prompt_receipt": {
                        "type": "agent_prompted",
                        "agent": deepcopy(agent),
                    },
                    "session_binding": {
                        "source": "herdr:codex",
                        "pane": pane,
                        "session_id": session,
                        "agent_receipt": deepcopy(agent),
                    },
                }
            )
        save(files["registry"], registry)
        ref = lambda label: (
            str(files[label])
            if use_strings
            else {"path": str(files[label]), "sha256": file_sha(files[label])}
        )
        path = self.root / "bundle.json"
        save(
            path,
            {
                "schema_version": 1 if use_strings else "production-label-bundle-v1",
                "packets": [
                    {
                        "packet_id": "pilot",
                        "cards": ref("cards"),
                        "labels": ref("labels"),
                        "review": ref("review"),
                        "registry": ref("registry"),
                    }
                ],
            },
        )
        return path, files

    def refresh_reference(self, bundle, files, label):
        value = json.loads(bundle.read_text())
        value["packets"][0][label] = {
            "path": str(files[label]),
            "sha256": file_sha(files[label]),
        }
        save(bundle, value)

    def test_standalone_owner_lane_never_invents_profile_context_or_identity(self):
        self.raw([self.post()])
        rows = self.build()
        record = next(a for a in rows["asset"] if a["asset_id"] == "instagram:4")
        self.assertEqual(record["verification_status"], "verified_publication_owner")
        self.assertEqual(
            record["verification_reason"],
            "independent_anchor_and_standalone_reported_owner",
        )
        self.assertIsNone(rows["production_observation"][0]["observed_account_id"])
        self.assertEqual(
            rows["production_observation"][0]["source_sha256"],
            file_sha(self.production / "raw/apify/new.json"),
        )
        self.assertEqual(
            next(r for r in rows["asset_relation"] if r["asset_id"] == "instagram:4")[
                "entity_id"
            ],
            "alice-candidacy",
        )
        self.assertNotIn(PRIVATE_MARKER, graph.packed(rows))
        sentinel = next(
            m
            for m in rows["metric"]
            if m["asset_id"] == "instagram:4" and m["name"] == "likes"
        )
        self.assertIsNone(sentinel["value"])
        self.assertEqual(sentinel["null_reason"], "provider_unavailable_sentinel")

    def test_mixed_old_new_duplicate_preserves_observations(self):
        original = json.loads(self.paths["review"].read_text())["posts"][0]
        post = self.post(1, text=original["text"])
        post["url"] = original["url"]
        post["likesCount"] = 8
        self.raw([post, self.post(4)])
        rows = self.build()
        self.assertEqual(len(rows["asset"]), 4)
        self.assertEqual(len(rows["asset_observation"]), 4)
        self.assertEqual(len(rows["production_observation"]), 2)
        self.assertEqual(
            len([a for a in rows["asset"] if a["asset_id"] == "instagram:1"]), 1
        )

    def test_content_or_owner_contradictions_quarantine_cached_asset(self):
        for post in [
            self.post(1, text="Changed caption"),
            self.post(1, owner="someone_else"),
        ]:
            self.raw([post])
            rows = self.build()
            asset = next(a for a in rows["asset"] if a["asset_id"] == "instagram:1")
            self.assertEqual(asset["verification_status"], "quarantined")
            self.assertFalse(
                any(r["asset_id"] == "instagram:1" for r in rows["asset_relation"])
            )

    def test_profile_bundle_does_not_promote_another_accounts_post(self):
        self.raw(
            [{"username": "bob", "private": False, "latestPosts": [self.post(4)]}],
            actor="apify/instagram-profile-scraper",
        )
        asset = next(a for a in self.build()["asset"] if a["asset_id"] == "instagram:4")
        self.assertEqual(
            asset["verification_reason"], "other_owner_in_profile_bundle_not_owned"
        )

    def test_facebook_page_author_mismatch_and_unknown_page_are_held(self):
        def fb(ident, author):
            return {
                "postId": str(ident),
                "text": "Public post",
                "url": f"https://www.facebook.com/org/posts/{ident}",
                "topLevelUrl": f"https://www.facebook.com/61599/posts/{ident}",
                "inputUrl": "https://www.facebook.com/org",
                "pageName": "org",
                "user": {"id": author},
                "likes": 1,
                "comments": 2,
                "time": AS_OF,
            }

        self.raw([fb(5, "10001"), fb(6, "61599")], actor="apify/facebook-posts-scraper")
        assets = {a["asset_id"]: a for a in self.build()["asset"]}
        self.assertEqual(
            assets["facebook:5"]["verification_reason"], "facebook_author_page_mismatch"
        )
        self.assertEqual(
            assets["facebook:6"]["verification_reason"],
            "independent_owner_anchor_missing",
        )

    def test_repeated_same_timestamp_metrics_are_not_summed_and_conflicts_surface(self):
        a = self.post()
        a["likesCount"] = 2
        b = self.post()
        b["likesCount"] = 3
        self.raw([a], name="a")
        self.raw([b], name="b")
        result = self.export("metrics")
        con = duckdb.connect(
            str(self.base / "export" / result["database"]), read_only=True
        )
        row = con.execute(
            "SELECT value,null_reason,observation_count FROM metric_snapshots WHERE asset_id='instagram:4' AND name='likes'"
        ).fetchall()[0]
        con.close()
        self.assertEqual(row, (None, "conflicting_values_same_time", 2))

    def test_label_unicode_offsets_and_real_shaped_session_bindings(self):
        path, _ = self.bundle()
        rows = self.build(label_bundle=path)
        self.assertEqual(len(rows["claim"]), 1)
        self.assertEqual(rows["claim"][0]["speaker_status"], "unknown")
        self.assertIsNone(rows["claim"][0]["speaker_entity_id"])
        self.assertEqual(
            rows["claim_evidence"][0]["context_text"], rows["claim"][0]["text"]
        )
        self.export("labels", label_bundle=path)

    def test_topic_only_abstention_and_review_rejection_coverage_survive(self):
        for topics, reject, status in [
            (["housing"], False, "reviewed_topics_only"),
            ([], False, "reviewed_abstention"),
            (["housing"], True, "reviewed_rejected"),
        ]:
            path, _ = self.bundle(topics=topics, claims=[], reject=reject)
            rows = self.build(label_bundle=path)
            self.assertEqual(
                rows["classification_coverage"][0]["review_status"], status
            )
            self.assertEqual(rows["claim"], [])
            self.assertEqual(
                len(rows["asset_topic"]), 1 if topics and not reject else 0
            )

    def test_five_claim_packet_is_supported_and_truncation_preserved(self):
        text = "🏠 První věta. Druhá věta. Třetí věta. Čtvrtá věta. Pátá věta."
        review = json.loads(self.paths["review"].read_text())
        for post in review["posts"]:
            if post["post_id"] == "instagram:1":
                post["text"] = text
        save(self.paths["review"], review)
        claims = []
        for phrase in [
            "První věta.",
            "Druhá věta.",
            "Třetí věta.",
            "Čtvrtá věta.",
            "Pátá věta.",
        ]:
            start = text.index(phrase)
            claims.append(
                {
                    "text": phrase,
                    "start": start,
                    "end": start + len(phrase),
                    "topics": ["housing"],
                    "claim_type": "source_statement",
                    "speaker_entity_id": None,
                    "speaker_status": "unknown",
                }
            )
        path, _ = self.bundle(claim_limit=5, claims=claims)
        rows = self.build(label_bundle=path)
        self.assertEqual(len(rows["claim"]), 5)
        self.assertTrue(rows["classification_coverage"][0]["claims_truncated"])
        result = self.export("five", label_bundle=path)
        self.assertEqual(result["quality"]["claims_admitted"], 5)

    def test_forged_session_pane_or_missing_receipt_cannot_promote(self):
        for mutation in [
            lambda r: r["assignments"][0]["session_binding"]["agent_receipt"].update(
                pane_id="unowned"
            ),
            lambda r: r["assignments"][1].update(session_id="forged"),
            lambda r: r["assignments"][0].pop("session_binding"),
        ]:
            path, files = self.bundle()
            value = json.loads(files["registry"].read_text())
            mutation(value)
            save(files["registry"], value)
            self.refresh_reference(path, files, "registry")
            with self.assertRaises(ValueError):
                self.build(label_bundle=path)

    def test_artifact_hash_and_frozen_brief_change_rejected(self):
        path, files = self.bundle()
        labels = json.loads(files["labels"].read_text())
        labels["items"][0]["claims"][0]["text"] = "Forged"
        save(files["labels"], labels)
        with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
            self.build(label_bundle=path)
        path, files = self.bundle()
        (files["labels"].parent / "brief.md").write_text("Changed brief")
        with self.assertRaisesRegex(ValueError, "brief changed"):
            self.build(label_bundle=path)

    def test_complete_verdict_and_exact_graph_hash_required(self):
        path, files = self.bundle()
        review = json.loads(files["review"].read_text())
        review["items"] = []
        save(files["review"], review)
        self.refresh_reference(path, files, "review")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.build(label_bundle=path)
        path, _ = self.bundle()
        self.raw([self.post(1, text="changed graph caption")])
        with self.assertRaisesRegex(ValueError, "owner is not verified"):
            self.build(label_bundle=path)

    def test_original_registered_path_required_not_a_reviewed_copy(self):
        path, files = self.bundle()
        copy = self.root / "labels-copy.json"
        copy.write_bytes(files["labels"].read_bytes())
        files["labels"] = copy
        self.refresh_reference(path, files, "labels")
        with self.assertRaisesRegex(ValueError, "outside its registered worker"):
            self.build(label_bundle=path)

    def test_actual_coordinator_bundle_shape_supported(self):
        path, _ = self.bundle(use_strings=True)
        self.assertEqual(len(self.build(label_bundle=path)["claim"]), 1)

    def test_stale_bundle_rolls_back_atomically(self):
        self.export("before")
        pointer = (self.base / "export/current.json").read_bytes()
        path, files = self.bundle()
        labels = json.loads(files["labels"].read_text())
        labels["session_id"] = "forged"
        save(files["labels"], labels)
        with self.assertRaises(ValueError):
            self.export("bad", label_bundle=path)
        self.assertEqual((self.base / "export/current.json").read_bytes(), pointer)
        self.assertFalse((self.base / "export/checkpoints/bad").exists())

    def media(self, status="downloaded"):
        post = self.post()
        post["displayUrl"] = "https://cdn.example.fbcdn.net/preview.jpg"
        source = self.raw([post])
        local = self.root / "media/preview.jpg"
        local.parent.mkdir(exist_ok=True)
        local.write_bytes(b"\xff\xd8\xff" + b"image fixture payload")
        record = {
            "asset_id": "instagram:4",
            "media_id": "media:one",
            "kind": "image",
            "source_url": post["displayUrl"],
            "source_envelope": str(source),
            "source_envelope_sha256": file_sha(source),
            "source_item_index": 0,
            "status": status,
            "fetched_at": AS_OF,
        }
        if status == "downloaded":
            record.update(
                path=str(local),
                sha256=file_sha(local),
                bytes=local.stat().st_size,
                content_type="image/jpeg",
                final_url=post["displayUrl"],
            )
        else:
            record["reason"] = "bounded download did not complete"
        index = local.parent / "index.json"
        save(index, {"schema_version": "production-media-v1", "records": [record]})
        return index, local

    def test_media_local_hash_size_source_and_magic_verified(self):
        index, local = self.media()
        rows = self.build(media_index=index)
        self.assertEqual(rows["media_resource"][0]["local_path"], str(local))
        result = self.export("media", media_index=index)
        self.assertEqual(result["counts"]["media_resource"], 1)
        local.write_bytes(b"changed bytes")
        with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
            self.build(media_index=index)

    def test_media_failed_and_skipped_have_no_retained_byte_claim(self):
        for status in ("failed", "skipped"):
            index, _ = self.media(status)
            row = self.build(media_index=index)["media_resource"][0]
            self.assertEqual(row["status"], status)
            self.assertIsNone(row["local_path"])
            self.assertIsNone(row["sha256"])
            self.assertIsNone(row["bytes"])

    def test_media_foreign_url_or_wrong_byte_size_rejected(self):
        for field, value in (
            ("source_url", "https://cdn.example.fbcdn.net/foreign.jpg"),
            ("bytes", 99999),
        ):
            index, _ = self.media()
            document = json.loads(index.read_text())
            document["records"][0][field] = value
            save(index, document)
            with self.assertRaises(ValueError):
                self.build(media_index=index)


if __name__ == "__main__":
    unittest.main()
