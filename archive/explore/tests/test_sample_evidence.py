"""Behavior checks for bounded public evidence and independent list mapping."""
import json
import tempfile
import unittest
from pathlib import Path

from czlake.build.review_profile_sample import review
from czlake.build.stage_profile_reviews import post_attribution, unique_posts
from czlake.build.ten_city_examples import list_priority
from czlake.paths import PROJECT


class SampleEvidenceChecks(unittest.TestCase):
    def test_local_window_deduplication_and_private_payload_withheld(self):
        with tempfile.TemporaryDirectory(dir=PROJECT / "tmp") as directory:
            root = Path(directory)
            batch = {"targets": [{"handle": "public_fixture", "name": "Synthetic person", "city": "Praha", "key": "person-key"},
                                 {"handle": "private_fixture", "name": "Synthetic list", "city": "Praha", "key": "list-key", "eligibility_kind": "local_list"}]}
            post = {"id": "inside", "timestamp": "2026-04-08T23:00:00Z"}
            raw = {"run_id": "fixture", "fetched_at": "2026-10-09T00:00:00+02:00", "items": [
                {"username": "public_fixture", "fullName": "Synthetic person", "biography": "Praha", "private": False, "followersCount": 10,
                 "latestPosts": [post, post, {"id": "old", "timestamp": "2026-04-08T21:59:59Z"}, {"id": "next_day", "timestamp": "2026-10-08T22:00:00Z"}]},
                {"username": "private_fixture", "fullName": "Synthetic list", "private": True, "followersCount": 10000, "latestPosts": [post]}]}
            rp, bp, op = root / "raw.json", root / "batch.json", root / "review.json"
            rp.write_text(json.dumps(raw))
            bp.write_text(json.dumps(batch))
            result = review(rp, bp, op)
            retained = json.loads(op.read_text())
            self.assertEqual(result["unique_in_window_posts"], 1)
            self.assertIsNone(retained["posts"][0]["entity_key"])
            self.assertIsNone(retained["profiles"][0]["followers_attributed_to_entity"])
            private = retained["profiles"][1]
            self.assertIsNone(private["followers"])
            self.assertEqual(private["in_window_posts"], 0)
            self.assertIsNone(private["candidate_key"])
            self.assertEqual(private["list_key"], "list-key")
            self.assertFalse(retained["complete_six_month_history"])

    def test_list_discovery_preserves_unknowns_and_weak_context_never_adds(self):
        evidence = {"source_url": "https://example.org/official-list", "local22_share": None,
                    "national_alliance_share": None, "city_alliance_share": None}
        unknown = list_priority({"evidence": evidence})
        self.assertEqual(unknown["score"], 1)
        self.assertTrue(unknown["protected_discovery"])
        self.assertIsNone(unknown["components"]["local_list_result"])
        weak = list_priority({"evidence": evidence | {"local22_share": .04, "national_alliance_share": .03, "city_alliance_share": .02}})
        self.assertEqual(weak["score"], 1)
        self.assertEqual(weak["winner"], "current_valid_list_discovery")
        spike = list_priority({"evidence": evidence | {"national_alliance_share": .11}})
        self.assertEqual(spike["score"], 2)
        self.assertIsNone(spike["components"]["local_list_result"])

    def test_other_owner_withholds_direct_attribution_and_shared_posts_keep_observations(self):
        profile = {"handle": "fixture", "followers_attributed_to_entity": 10,
                   "requested_entity_key": "list", "list_key": "list", "candidate_key": None}
        own = {"post_id": "instagram:shared", "handle": "fixture", "owner_handle": "fixture"}
        other = own | {"owner_handle": "external"}
        self.assertEqual(post_attribution(own, profile, {})["entity_key"], "list")
        association = post_attribution(other, profile, {})
        self.assertIsNone(association["entity_key"])
        self.assertEqual(association["observed_profile_entity_key"], "list")
        self.assertIsNone(post_attribution(own, profile | {"followers_attributed_to_entity": None}, {})["entity_key"])
        with tempfile.TemporaryDirectory(dir=PROJECT / "tmp") as directory:
            root = Path(directory)
            paths = [root / "one.json", root / "two.json"]
            for i, path in enumerate(paths):
                path.write_text(json.dumps({"profiles": [profile], "posts": [own | {"apify_run_id": str(i)}]}))
            result = unique_posts(paths, root / "unique.json")
            self.assertEqual(result["unique_posts"], 1)
            self.assertEqual(result["retained_observations"], 2)
            self.assertEqual(result["shared_post_ids"], 1)
            self.assertEqual(result["independently_anchored_owned_unique_posts"], 1)


if __name__ == "__main__":
    unittest.main()
