"""Offline attribution checks for the held profile proposal."""
from __future__ import annotations

import unittest

from czlake.build.prepare_small_batch import identity_evidence


class IdentityGateTests(unittest.TestCase):
    def setUp(self):
        self.profile = {"handle": "synthetic_candidate", "entity_id": "synthetic_person",
                        "entity_name": "Synthetic Person", "city": "Brno", "possible_duplicates": 0,
                        "inherited_status": "accepted", "sources": "serp", "match_basis": "fixture",
                        "profile_url": "https://www.instagram.com/synthetic_candidate/"}
        self.owners = {"synthetic_candidate": {"synthetic_person"}}
        self.hit = {"person_id": "synthetic_person", "handle": "synthetic_candidate",
                    "title": "Synthetic Person", "description": "Public local political role in Brno.",
                    "url": self.profile["profile_url"], "apify_run_id": "synthetic_run", "rank": 1}

    def test_query_city_alone_does_not_anchor_a_name_match(self):
        hit = self.hit | {"description": "Profile of Synthetic Person.", "query": '"Synthetic Person" Brno'}
        self.assertIsNone(identity_evidence(self.profile, self.owners, [hit]))

    def test_profile_name_and_local_context_support_fetching_but_not_metrics(self):
        evidence = identity_evidence(self.profile, self.owners, [self.hit])
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(evidence["kind"], "cached_profile_name_and_local_context")
        self.assertIn("unverified", evidence["limitation"])

    def test_shared_owner_or_ambiguous_cluster_is_deferred_even_with_curated_anchor(self):
        profile = self.profile | {"sources": "wikidata", "match_basis": "Wikidata Q1: matching public identity"}
        self.assertIsNotNone(identity_evidence(profile, self.owners, []))
        self.assertIsNone(identity_evidence(profile | {"possible_duplicates": 1}, self.owners, []))
        self.assertIsNone(identity_evidence(profile, {"synthetic_candidate": {"synthetic_person", "other"}}, []))
        self.assertIsNone(identity_evidence(profile, {"synthetic_candidate": {"other"}}, []))

    def test_unconfirmed_link_or_missing_owner_name_stays_a_gap(self):
        self.assertIsNone(identity_evidence(self.profile | {"inherited_status": "unconfirmed"}, self.owners, [self.hit]))
        hit = self.hit | {"title": "A local movement in Brno", "description": "No identified account owner"}
        self.assertIsNone(identity_evidence(self.profile, self.owners, [hit]))


if __name__ == "__main__":
    unittest.main()
