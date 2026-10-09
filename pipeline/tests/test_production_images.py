"""Source/byte integrity and honest target-image coverage, no network calls."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import duckdb
from test_production_graph import AS_OF, SCRATCH, fixture, graph, save


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.base = Path(self.temp.name)
        self.root = self.base / "sources"
        self.paths = fixture(self.root)
        self.options = {
            "relevance_dir": self.root / "relevance",
            "reviews": [self.paths["review"]],
            "identity_path": self.paths["identity"],
            "as_of": AS_OF,
        }
        self.blob = self.root / "images/photo.png"
        self.blob.parent.mkdir()
        self.blob.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jFk0AAAAASUVORK5CYII="
            )
        )
        self.raw = self.root / "photo-source.html"
        self.raw.write_text(
            '<html><head><title>Fixture city</title></head><body><main><h1>Candidate council</h1><figure><p>Same Name local candidate</p><img src="/photo.png" alt="Same Name"/></figure></main></body></html>'
        )
        self.extraction = self.root / "photo-source.json"
        self.source = {
            "source_page_url": "https://official.example/alice",
            "original_image_url": "https://official.example/photo.png",
            "target_id": "alice-candidacy",
            "exact_name_evidence": "Same Name, local candidate",
            "identity_evidence": {
                "exact_name": "Same Name",
                "role_match": "candidate",
                "locality_match": "Fixture city",
            },
            "raw_dom_pointer": "/html/body/main/figure/img",
            "original_source": {"path": str(self.raw), "sha256": self.sha(self.raw)},
        }
        save(self.extraction, self.source)
        self.image = {
            "image_id": "source-image-1",
            "target_id": "alice-candidacy",
            "entity_id": "alice-candidacy",
            "kind": "source_bound_portrait",
            "relation_status": "source_identified",
            "depicted_person_status": "unknown",
            "source_page": {
                "path": str(self.extraction),
                "sha256": self.sha(self.extraction),
                "url": self.source["source_page_url"],
                "text_pointer": "/exact_name_evidence",
            },
            "source_image_pointer": "/original_image_url",
            "original_image_url": self.source["original_image_url"],
            "observed_at": AS_OF,
            "identity_evidence": {
                "exact_name": "Same Name",
                "role_match": "candidate",
                "locality_match": "Fixture city",
            },
            "download_status": "downloaded",
            "download": {
                "local_path": str(self.blob),
                "sha256": self.sha(self.blob),
                "bytes": self.blob.stat().st_size,
                "content_type": "image/png",
                "width": 1,
                "height": 1,
            },
        }
        self.document = {
            "schema": "production-source-images-v1",
            "schema_version": 1,
            "target_count": 2,
            "targets": [
                {
                    "target_id": "alice-candidacy",
                    "name": "Same Name",
                    "city": "Fixture city",
                    "status": "downloaded",
                    "portrait_status": "source_bound_available",
                    "image_ids": ["source-image-1"],
                    "unknown_reason": None,
                },
                {
                    "target_id": "bob-candidacy",
                    "name": "Same Name",
                    "city": "Fixture city",
                    "status": "unknown",
                    "portrait_status": "unknown",
                    "image_ids": [],
                    "unknown_reason": "No source-labelled image found.",
                },
            ],
            "images": [self.image],
        }
        self.index = self.root / "images-index.json"
        proposal = self.root / "tmp/production/native/collector/index.json"
        save(proposal, deepcopy(self.document))
        review_path = (
            self.root / "tmp/production/native/identity_review_fixture/review.json"
        )
        review = {
            "reviewer": "native:/root/identity_review_fixture",
            "index_path": str(proposal),
            "index_sha256": self.sha(proposal),
            "reviews": {
                "source-image-1": {
                    "decision": "accept",
                    "target_id": "alice-candidacy",
                    "original_image_url": self.image["original_image_url"],
                    "source_page_sha256": self.sha(self.raw),
                    "binding_scope": "bounded_person_card",
                    "target_specific_proof": {
                        "sources": [
                            {
                                "path": str(self.raw),
                                "sha256": self.sha(self.raw),
                                "name_pointer": "/html/body/main/figure",
                                "role_pointer": "/html/body/main/h1",
                                "locality_pointer": "/html/head/title",
                                "exact_name": "Same Name",
                                "exact_role": "Candidate council",
                                "exact_locality": "Fixture city",
                            }
                        ],
                        "image_page_binding": {
                            "path": str(self.raw),
                            "sha256": self.sha(self.raw),
                            "dom_pointer": "/html/body/main/figure/img",
                        },
                    },
                }
            },
        }
        save(review_path, review)
        self.source["identity_evidence"].update(
            binding_scope="bounded_person_card",
            binding_review={
                "path": str(review_path),
                "sha256": self.sha(review_path),
                "pointer": "/reviews/source-image-1",
            },
        )
        save(self.extraction, self.source)
        self.image["source_page"].update(
            sha256=self.sha(self.extraction), raw_page_sha256=self.sha(self.raw)
        )

    def tearDown(self):
        self.temp.cleanup()

    def sha(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def export(self, name="photos", document=None):
        save(self.index, self.document if document is None else document)
        return graph.export_checkpoint(
            self.root,
            output=self.base / "export",
            checkpoint_id=name,
            image_index=self.index,
            **self.options,
        )

    def test_source_images_and_explicit_missing_target_coverage(self):
        result = self.export()
        with duckdb.connect(
            str(self.base / "export" / result["database"]), read_only=True
        ) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT entity_id,status,downloaded_count FROM entity_photo_coverage ORDER BY entity_id"
                ).fetchall(),
                [("alice-candidacy", "downloaded", 1), ("bob-candidacy", "unknown", 0)],
            )
            self.assertEqual(
                connection.execute(
                    "SELECT depicted_person_status FROM source_image"
                ).fetchall(),
                [("unknown",)],
            )
        self.assertEqual(result["counts"]["verified_assets"], 1)
        self.assertEqual(result["quality"]["checks"]["image_coverage_binding"], 0)
        self.assertEqual(result["quality"]["checks"]["image_download_binding"], 0)

    def test_exact_image_pointer_and_original_dom_cannot_change(self):
        for field, value in (
            ("source_image_pointer", "/missing"),
            ("original_image_url", "https://official.example/other.png"),
        ):
            with self.subTest(field=field):
                document = deepcopy(self.document)
                document["images"][0][field] = value
                with self.assertRaises(ValueError):
                    self.export(field, document)
        self.raw.write_text('<img src="/other.png"/>')
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.export("raw-changed")

    def test_changed_download_bytes_or_declared_dimensions_reject(self):
        document = deepcopy(self.document)
        document["images"][0]["download"]["width"] = 2
        with self.assertRaisesRegex(ValueError, "dimensions"):
            self.export("bad-dimensions", document)
        self.blob.write_bytes(self.blob.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.export("bad-bytes")

    def test_unknown_depiction_is_mandatory(self):
        document = deepcopy(self.document)
        document["images"][0]["depicted_person_status"] = "confirmed"
        with self.assertRaisesRegex(ValueError, "depicted identity"):
            self.export("depiction", document)

    def update_review(self, review):
        path = Path(self.source["identity_evidence"]["binding_review"]["path"])
        save(path, review)
        self.source["identity_evidence"]["binding_review"]["sha256"] = self.sha(path)
        save(self.extraction, self.source)
        self.image["source_page"]["sha256"] = self.sha(self.extraction)

    def test_reviewer_identity_rejects_empty_traversal_and_same_proposer(self):
        path = Path(self.source["identity_evidence"]["binding_review"]["path"])
        original = json.loads(path.read_text())
        for reviewer in (
            "native:/root/",
            "native:/root/identity_review_fixture/../collector",
            "native:/root/collector",
        ):
            with self.subTest(reviewer=reviewer):
                review = deepcopy(original)
                review["reviewer"] = reviewer
                self.update_review(review)
                with self.assertRaises(ValueError):
                    self.export("invalid-reviewer")

    def test_roster_uses_actual_dom_heading_city_and_same_original_hash(self):
        path = Path(self.source["identity_evidence"]["binding_review"]["path"])
        review = json.loads(path.read_text())
        verdict = review["reviews"]["source-image-1"]
        verdict.pop("target_specific_proof")
        capture_path = self.root / "roster-capture.json"
        packet = {
            "raw_sha256": self.sha(self.raw),
            "original_source": {"path": str(self.raw), "sha256": self.sha(self.raw)},
            "scope": {
                "dom_pointer": "/html/body/main",
                "heading": {
                    "dom_pointer": "/html/body/main/h1",
                    "text": "Candidate council",
                },
                "city_title": {
                    "dom_pointer": "/html/head/title",
                    "text": "Fixture city",
                },
                "cards": [
                    {
                        "dom_pointer": "/html/body/main/figure",
                        "text": "Same Name local candidate",
                        "images": [
                            {
                                "dom_pointer": "/html/body/main/figure/img",
                                "url": self.image["original_image_url"],
                            }
                        ],
                    }
                ],
            },
        }

        def bind(packet):
            save(capture_path, packet)
            verdict["roster_scope"] = {
                "scope_source": {
                    "path": str(capture_path),
                    "sha256": self.sha(capture_path),
                    "pointer": "/scope",
                }
            }
            self.update_review(review)

        bind(packet)
        self.export("actual-roster")
        for part, text in (
            ("heading", "Candidate mayor"),
            ("city_title", "Fixture city official"),
        ):
            with self.subTest(part=part):
                changed = deepcopy(packet)
                changed["scope"][part]["text"] = text
                bind(changed)
                with self.assertRaisesRegex(ValueError, "physically bind"):
                    self.export("copied-roster")
        changed = deepcopy(packet)
        another = self.root / "unrelated-source.html"
        another.write_text(
            self.raw.read_text() + "<!-- unrelated retained document -->"
        )
        changed["original_source"] = {"path": str(another), "sha256": self.sha(another)}
        bind(changed)
        with self.assertRaisesRegex(ValueError, "hash must match"):
            self.export("unrelated-roster-source")

    def test_json_anchor_requires_exact_already_admitted_target_proof(self):
        identity_path = self.paths["identity"]
        identity = json.loads(identity_path.read_text())
        identity["candidates"]["alice-candidacy"].update(
            name="Same Name",
            public_role_evidence=["Local candidate"],
            locality_evidence=["Fixture city"],
        )
        save(identity_path, identity)
        review_path = Path(self.source["identity_evidence"]["binding_review"]["path"])
        review = json.loads(review_path.read_text())
        proof = review["reviews"]["source-image-1"]["target_specific_proof"]
        proof["image_page_binding"]["named_context_pointer"] = "/html/body/main/figure"
        proof["sources"] = [
            {
                "path": str(identity_path),
                "sha256": self.sha(identity_path),
                "name_pointer": "/candidates/alice-candidacy/name",
                "role_pointer": "/candidates/alice-candidacy/public_role_evidence/0",
                "locality_pointer": "/candidates/alice-candidacy/locality_evidence/0",
                "exact_name": "Same Name",
                "exact_role": "Local candidate",
                "exact_locality": "Fixture city",
                "original_source_path": str(self.raw),
                "original_source_sha256": self.sha(self.raw),
            }
        ]
        self.update_review(review)
        self.export("admitted-json-anchor")
        unrelated = self.root / "unadmitted-copy.json"
        save(unrelated, identity)
        proof["sources"][0].update(path=str(unrelated), sha256=self.sha(unrelated))
        self.update_review(review)
        with self.assertRaisesRegex(ValueError, "Target-specific source role/city"):
            self.export("unadmitted-json-anchor")

    def test_direct_retained_html_proof_uses_actual_bounded_card(self):
        self.raw.write_text(
            self.raw.read_text().replace(
                "local candidate", "local candidate Fixture city"
            )
        )
        raw_hash = self.sha(self.raw)
        self.source["original_source"]["sha256"] = raw_hash
        self.image["source_page"]["raw_page_sha256"] = raw_hash
        review_path = Path(self.source["identity_evidence"]["binding_review"]["path"])
        review = json.loads(review_path.read_text())
        verdict = review["reviews"]["source-image-1"]
        verdict.pop("target_specific_proof")
        verdict["source_page_sha256"] = raw_hash
        verdict["exact_proof"] = [
            {
                "source_path": str(self.raw),
                "source_packet_sha256": raw_hash,
                "dom_pointer": "/html/body/main/figure",
            }
        ]
        self.update_review(review)
        self.export("direct-html-proof")
        self.raw.write_text(
            self.raw.read_text().replace(
                "local candidate Fixture city", "unrelated biography"
            )
        )
        raw_hash = self.sha(self.raw)
        self.source["original_source"]["sha256"] = raw_hash
        self.image["source_page"]["raw_page_sha256"] = raw_hash
        verdict["source_page_sha256"] = raw_hash
        verdict["exact_proof"][0]["source_packet_sha256"] = raw_hash
        self.update_review(review)
        with self.assertRaisesRegex(ValueError, "physically bind"):
            self.export("global-heading-cannot-fill-card")

    def test_unknown_source_candidate_bytes_do_not_claim_available_photo(self):
        document = deepcopy(self.document)
        document["images"][0]["relation_status"] = "unknown"
        document["targets"][0].update(
            status="unknown",
            portrait_status="unknown",
            image_ids=[],
            unknown_reason="Source relation remains unreviewed.",
        )
        result = self.export("candidate", document)
        with duckdb.connect(
            str(self.base / "export" / result["database"]), read_only=True
        ) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT status,downloaded_count FROM entity_photo_coverage WHERE entity_id='alice-candidacy'"
                ).fetchall(),
                [("unknown", 0)],
            )
            self.assertEqual(
                connection.execute(
                    "SELECT download_status,relation_status FROM source_image"
                ).fetchall(),
                [("downloaded", "unknown")],
            )

    def test_original_avif_type_uses_brands_and_dimensions_not_extension(self):
        raw = (24).to_bytes(4, "big") + b"ftypavif" + bytes(4) + b"mif1miaf"
        raw += (
            (20).to_bytes(4, "big")
            + b"ispe"
            + bytes(4)
            + (218).to_bytes(4, "big")
            + (270).to_bytes(4, "big")
        )
        self.blob.write_bytes(raw)
        document = deepcopy(self.document)
        document["images"][0]["download"].update(
            sha256=self.sha(self.blob),
            bytes=len(raw),
            content_type="image/avif",
            width=218,
            height=270,
        )
        self.export("avif", document)
        self.blob.write_bytes(raw.replace(b"avif", b"mp42"))
        document["images"][0]["download"]["sha256"] = self.sha(self.blob)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            self.export("fake-avif", document)

    def test_avatar_requires_exact_reviewed_owner_public_profile(self):
        profile = {
            "schema_version": 1,
            "policy_version": "public-metadata-v1",
            "actor": "apify/instagram-profile-scraper",
            "items": [
                {
                    "username": "alice",
                    "private": False,
                    "fullName": "Same Name",
                    "profilePicUrlHD": self.source["original_image_url"],
                }
            ],
        }
        save(self.extraction, profile)
        document = deepcopy(self.document)
        item = document["images"][0]
        item.update(
            kind="owned_account_avatar",
            account_id="instagram:alice",
            source_image_pointer="/items/0/profilePicUrlHD",
        )
        item["source_page"].update(
            sha256=self.sha(self.extraction), text_pointer="/items/0/fullName"
        )
        item["source_page"]["url"] = "https://www.instagram.com/alice/"
        self.export("avatar", document)
        item["account_id"] = "instagram:bob"
        with self.assertRaisesRegex(ValueError, "independently owned"):
            self.export("unowned-avatar", document)

    def test_failed_image_retains_source_only_coverage_without_bytes(self):
        document = deepcopy(self.document)
        document["images"][0].update(
            download_status="failed", download=None, failure_reason="Timeout"
        )
        document["targets"][0]["status"] = "source_only"
        result = self.export("failed", document)
        self.assertEqual(result["counts"]["source_image"], 1)
        document["images"][0]["download"] = self.image["download"]
        with self.assertRaisesRegex(ValueError, "cannot claim"):
            self.export("false-bytes", document)

    def test_namesake_city_and_gap_counts_cannot_be_changed(self):
        for field, value in (
            ("city", "Other city"),
            ("status", "unknown"),
            ("image_ids", ["missing-image"]),
        ):
            with self.subTest(field=field):
                document = deepcopy(self.document)
                document["targets"][0][field] = value
                with self.assertRaises(ValueError):
                    self.export(field, document)

    def test_invalid_image_export_preserves_previous_pointer(self):
        self.export("first")
        pointer = (self.base / "export/current.json").read_bytes()
        self.blob.write_bytes(b"not an image")
        with self.assertRaises(ValueError):
            self.export("second")
        self.assertEqual((self.base / "export/current.json").read_bytes(), pointer)


if __name__ == "__main__":
    unittest.main()
