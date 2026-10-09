"""Source-preserving relevance revision and independent organization gates."""

from __future__ import annotations

import copy
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta

from czlake.build.relevance_revision import rank_lists, recompute, select_thirty
from czlake.priority import Candidate, qualify

AS_OF = datetime.fromisoformat("2026-10-09T03:00:00+02:00")


def record(key="synthetic", **changes):
    c = Candidate(
        key,
        "city",
        1,
        "10",
        1,
        True,
        None,
        False,
        None,
        None,
        None,
        None,
        100_000,
        None,
        True,
    )
    data = {**asdict(c), **changes}
    decision = qualify(Candidate(**data))
    return {
        "candidate": data,
        "city": "Synthetic city",
        "name": key,
        "list_name": "Synthetic local list",
        "evidence": {
            "validity": "A",
            "source_url": "https://synthetic.example/registry",
            "election_id": "kv2026",
            "unit_type": "city_council",
            "unit_code": "city",
        },
        **{k: getattr(decision, k) for k in ("components", "winner", "score", "qualified", "protected")},
        "reasons": list(decision.reasons),
        "metrics": [],
        "reviewed_sources": [],
        "verified_accounts": [],
    }


def list_record(strength=None, followers=None):
    anchor = {
        "adjudication": "confirmed",
        "public": True,
        "source_url": "https://synthetic.example/local-organization",
        "excerpt": "Exact public city-political-organization account link.",
        "identity_confirmed": True,
        "anchor_links_account": True,
        "handle": "synthetic_list",
        "observed_at": AS_OF.isoformat(),
    }
    measurement = {
        "public": True,
        "entity_kind": "local_list",
        "list_key": "kv2026:city:10",
        "handle": "synthetic_list",
        "followers": followers,
        "followers_attributed_to_entity": followers,
        "observed_at": AS_OF.isoformat(),
        "identity_evidence": anchor,
    }
    return {
        "key": "kv2026:city:10",
        "city": "Synthetic city",
        "city_rank": 1,
        "municipality_code": "city",
        "list_no": "10",
        "priority": {
            "components": {
                "local_list_result": strength,
                "national_alliance_context": None,
                "city_alliance_context": None,
                "current_valid_list_discovery": 1,
            },
            "score": 1,
            "sources": {"current_list": "https://synthetic.example/registry"},
            "shares": {},
        },
        "social_metrics": measurement,
    }


class RevisionTests(unittest.TestCase):
    def test_leadership_only_removed_without_mutating_evidence_or_original_selection(
        self,
    ):
        old = record()
        old.update(
            qualified=True,
            protected=True,
            score=1,
            winner="list_leader",
            reasons=["list_leader"],
        )
        old["components"]["list_leader"] = 1
        snapshot = copy.deepcopy(old)
        rows, changes = recompute([old])
        self.assertEqual(old, snapshot)
        self.assertEqual(changes["removed"], ["synthetic"])
        self.assertEqual(rows[0]["old"]["reasons"], ["list_leader"])
        self.assertFalse(rows[0]["qualified"])
        self.assertIsNone(rows[0]["components"]["public_reach"])

    def test_invalid_candidacy_and_duplicate_keys_fail_validation(self):
        invalid = record(eligible=False)
        with self.assertRaises(ValueError):
            recompute([invalid])
        with self.assertRaises(ValueError):
            recompute([record(), record()])

    def test_cached_metric_expiry_and_missing_independent_review_withhold_reach(self):
        r = record(followers=20_000)
        r["metrics"] = [
            {
                "platform": "instagram",
                "handle": "synthetic",
                "followers": 20_000,
                "observed_at": AS_OF.isoformat(),
            }
        ]
        anchor = {
            "candidacy_id": "synthetic",
            "municipality_code": "city",
            "kind": "account_identity",
            "identity_confirmed": True,
            "public": True,
            "adjudication": "confirmed",
            "source_url": "https://synthetic.example/political-anchor",
            "excerpt": "Exact public account link.",
            "anchor_links_account": True,
            "observed_at": AS_OF.isoformat(),
            "platform": "instagram",
            "handle": "synthetic",
        }
        r["reviewed_sources"] = [anchor]
        self.assertFalse(recompute([r], AS_OF)[0][0]["qualified"])
        r["verified_accounts"] = [{"platform": "instagram", "handle": "synthetic"}]
        fresh = recompute([r], AS_OF)[0][0]
        self.assertTrue(fresh["qualified"])
        self.assertIsNone(fresh["components"]["public_activity"])
        stale = recompute([r], AS_OF + timedelta(days=31))[0][0]
        self.assertFalse(stale["qualified"])
        self.assertIsNone(stale["candidate"]["followers"])
        self.assertEqual(stale["old_candidate"]["followers"], 20_000)

    def test_thirty_means_qualified_not_exploratory_and_all_overflow_survives(self):
        rows = [record(f"strong_{i}", position=i + 1, mandate_evidence=True) for i in range(35)]
        rows += [record("leader_only"), record("unknown_two", position=2)]
        selection = select_thirty(rows)
        self.assertEqual(len(selection["qualified_keys"]), 30)
        self.assertEqual(len(selection["qualifying_overflow"]), 5)
        self.assertEqual(selection["additional_discovery_keys"], ["unknown_two"])
        self.assertNotIn("leader_only", selection["qualified_keys"])


class OrganizationTests(unittest.TestCase):
    def test_independent_exact_local_organization_action_can_qualify_without_followers(self):
        row = list_record()
        role = {
            "entity_id": row["key"],
            "entity_kind": "local_list",
            "candidacy_id": None,
            "municipality_code": "city",
            "kind": "local_political_role",
            "identity_confirmed": True,
            "public": True,
            "adjudication": "confirmed",
            "official_role_source": True,
            "source_url": "https://synthetic.example/local-organization",
            "excerpt": "This current local organization.",
            "observed_at": AS_OF.isoformat(),
            "valid_from": "2026-10-01T00:00:00+02:00",
            "valid_until": "2026-10-20T00:00:00+02:00",
            "independent_origin": "organization",
        }
        action = {
            **role,
            "kind": "local_public_action",
            "source_url": "https://synthetic.example/local-news",
            "independent_origin": "local_editorial",
            "substantive_action_confirmed": True,
            "event_at": "2026-09-20T00:00:00+02:00",
        }
        row["reviewed_sources"] = [role, action]
        result = rank_lists([row], [record()], AS_OF)[0]
        self.assertTrue(result["qualified"])
        self.assertTrue(result["protected"])
        self.assertEqual(result["priority"]["reasons"], ["organization_activity"])
        row["reviewed_sources"] = [role, {**action, "entity_id": "different_local_list"}]
        self.assertFalse(rank_lists([row], [record()], AS_OF)[0]["qualified"])

    def test_registered_weak_list_is_discovery_only_even_with_strong_person(self):
        person = record(party_strength=2)
        result = rank_lists([list_record()], [person], AS_OF)[0]
        self.assertTrue(result["discovery_eligible"])
        self.assertFalse(result["qualified"])
        self.assertEqual(result["priority"]["score"], 0)

    def test_strong_electoral_list_survives_unknown_social_metrics(self):
        result = rank_lists([list_record(strength=1.3)], [record()], AS_OF)[0]
        self.assertTrue(result["qualified"])
        self.assertEqual(result["priority"]["reasons"], ["local_list_result"])

    def test_independently_confirmed_local_organization_reach_can_qualify(self):
        result = rank_lists([list_record(followers=10_000)], [record()], AS_OF)[0]
        self.assertTrue(result["qualified"])
        self.assertTrue(result["protected"])
        self.assertEqual(result["priority"]["reasons"], ["organization_reach"])

    def test_national_other_list_unattributed_and_stale_accounts_cannot_supply_local_reach(
        self,
    ):
        base = list_record(followers=100_000)
        for modification in (
            "national",
            "other_list",
            "unattributed",
            "stale",
            "unconfirmed",
            "no_source",
            "private_anchor",
        ):
            r = copy.deepcopy(base)
            m = r["social_metrics"]
            if modification == "national":
                m["identity_evidence"]["scope"] = "national_party"
            elif modification == "other_list":
                m["list_key"] = "kv2026:elsewhere:10"
            elif modification == "unattributed":
                m["followers_attributed_to_entity"] = None
            elif modification == "stale":
                m["observed_at"] = (AS_OF - timedelta(days=31)).isoformat()
            elif modification == "no_source":
                m["identity_evidence"]["source_url"] = None
            elif modification == "private_anchor":
                m["identity_evidence"]["public"] = False
            else:
                m["identity_evidence"]["adjudication"] = "unknown"
            result = rank_lists([r], [record()], AS_OF)[0]
            self.assertFalse(result["qualified"], modification)
            self.assertIsNone(result["priority"]["components"]["organization_reach"])


if __name__ == "__main__":
    unittest.main()
