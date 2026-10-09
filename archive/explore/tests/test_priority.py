"""Behavioral checks for qualification, source review and held scheduling."""

from __future__ import annotations

import math
import random
import unittest
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from czlake.build.prioritize import (
    local_role_extensions,
    reviewed_following,
    reviewed_signals,
)
from czlake.priority import Candidate, qualify, schedule

AS_OF = datetime.fromisoformat("2026-10-09T00:45:00+02:00")


def candidate(**changes) -> Candidate:
    base = Candidate(
        "synthetic_base",
        "city",
        1,
        "10",
        10,
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
    return replace(base, **changes)


def founder_review(**changes) -> dict:
    # Explicitly synthetic; these URLs are never fetched or represented as retained evidence.
    record = {
        "candidacy_id": None,
        "entity_id": "synthetic_founder",
        "entity_name": "Synthetic entrepreneur",
        "municipality_code": "city",
        "kind": "local_political_role",
        "identity_confirmed": True,
        "public": True,
        "adjudication": "confirmed",
        "source_url": "https://synthetic.example/local-party/founder",
        "identity_source_url": "https://synthetic.example/public-professional/identity",
        "excerpt": "Identified founder leads this local political organization in this city.",
        "observed_at": AS_OF.isoformat(),
        "official_role_source": True,
        "role_type": "founder",
        "organization_kind": "local_political_organization",
        "organization_name": "Synthetic new local list",
        "valid_from": "2026-10-01T00:00:00+02:00",
        "valid_until": "2026-10-20T00:00:00+02:00",
        "independent_origin": "organization",
    }
    return {**record, **changes}


class QualificationTests(unittest.TestCase):
    def test_main_party_leader_and_lower_local_performer_have_separate_paths(self):
        leader = qualify(candidate(position=1, party_strength=1.4))
        lower = qualify(candidate(position=40, local_vote_lift=1.5))
        self.assertEqual(leader.winner, "party_contender")
        self.assertEqual(lower.reasons, ("local_votes",))
        self.assertTrue(lower.qualified)

    def test_current_office_works_without_histories(self):
        decision = qualify(candidate(current_office_verified=True, historical_identity_clear=False))
        self.assertTrue(decision.qualified)
        self.assertEqual(decision.components["office"], 1.5)

    def test_large_following_alone_survives_missing_history(self):
        decision = qualify(candidate(followers=20_000))
        self.assertEqual(decision.score, 2)
        self.assertEqual(decision.reasons, ("public_reach",))
        self.assertTrue(decision.protected)

    def test_unknown_list_leader_qualifies_without_finance_or_metrics(self):
        decision = qualify(candidate(position=1))
        self.assertEqual(decision.reasons, ("list_leader",))
        self.assertIsNone(decision.components["public_reach"])
        self.assertIsNone(decision.components["public_activity"])
        self.assertTrue(decision.protected)

    def test_many_mediocre_signals_cannot_qualify(self):
        weak = qualify(
            candidate(
                position=2,
                party_strength=0.9,
                local_vote_rank=4,
                local_vote_lift=1.1,
                followers=8_000,
            )
        )
        spike = qualify(candidate(followers=10_000))
        self.assertLess(weak.score, 1)
        self.assertFalse(weak.qualified)
        self.assertTrue(spike.qualified)

    def test_national_fame_without_local_eligibility_never_qualifies(self):
        self.assertFalse(qualify(candidate(eligible=False, followers=5_000_000)).qualified)

    def test_ambiguous_namesake_cannot_inherit_history_or_followers(self):
        ambiguous = qualify(
            candidate(
                mandate_evidence=True,
                local_vote_rank=1,
                prior_leader=True,
                historical_identity_clear=False,
            )
        )
        self.assertFalse(ambiguous.qualified)
        self.assertIsNone(ambiguous.components["local_votes"])
        # Account attribution is gated in the adapter. Current ballot leadership still qualifies.
        self.assertTrue(qualify(replace(ambiguous.candidate, position=1)).qualified)

    def test_invalid_candidacy_does_not_disqualify_another_role_or_candidacy(self):
        invalid = qualify(candidate(key="invalid", eligible=False, position=1))
        other = qualify(candidate(key="other", position=1))
        role = qualify(
            candidate(
                key="role",
                position=0,
                local_role_verified=True,
                eligibility_kind="reviewed_local_role",
            )
        )
        self.assertFalse(invalid.qualified)
        self.assertTrue(other.qualified)
        self.assertTrue(role.qualified)

    def test_monotonicity_and_spike_preservation_across_generated_inputs(self):
        rng = random.Random(83)
        for index in range(500):
            c = candidate(
                key=str(index),
                position=rng.randint(1, 50),
                party_strength=rng.random() * 3,
                local_vote_lift=rng.random() * 3,
                local_vote_rank=rng.randint(1, 500),
                followers=rng.randint(0, 100_000),
                prior_leader=bool(rng.randrange(2)),
            )
            assert c.party_strength is not None and c.local_vote_lift is not None
            assert c.local_vote_rank is not None and c.followers is not None
            baseline = qualify(c)
            for stronger in (
                replace(c, party_strength=c.party_strength + 0.5),
                replace(c, local_vote_lift=c.local_vote_lift + 0.5),
                replace(c, local_vote_rank=max(1, c.local_vote_rank - 1)),
                replace(c, followers=c.followers + 1_000),
                replace(c, mandate_evidence=True),
            ):
                result = qualify(stronger)
                self.assertGreaterEqual(result.score, baseline.score)
                self.assertTrue(not baseline.qualified or result.qualified)
            if baseline.qualified:
                # Removing irrelevant unknown/weak channels cannot remove the winning strong signal.
                self.assertGreaterEqual(max(v for v in baseline.components.values() if v is not None), 1)

    def test_threshold_boundaries_and_invalid_measurements(self):
        for followers, expected in ((9999, False), (10000, True)):
            self.assertEqual(qualify(candidate(followers=followers)).qualified, expected)
        self.assertTrue(qualify(candidate(local_vote_rank=3)).qualified)
        self.assertFalse(qualify(candidate(local_vote_rank=4)).qualified)
        self.assertTrue(qualify(candidate(local_vote_lift=1.25)).qualified)
        for bad in (math.inf, math.nan, -1):
            with self.assertRaises(ValueError):
                qualify(candidate(party_strength=bad))


class SchedulingTests(unittest.TestCase):
    def test_newcomer_and_unknown_exploration_survive_main_party_crowding(self):
        decisions = [qualify(candidate(key=f"main_{i}", position=2, party_strength=2)) for i in range(30)]
        decisions += [
            qualify(candidate(key="new", position=1)),
            qualify(candidate(key="unknown", position=2)),
        ]
        costs = {d.candidate.key: Decimal("0.10") for d in decisions}
        result = schedule(decisions, 5, Decimal("0.50"), costs)
        keys = {d.candidate.key for d in result.selected}
        self.assertIn("new", keys)
        self.assertIn("unknown", keys)
        self.assertEqual(len(result.selected), 5)
        self.assertEqual(len(result.deferred), 27)
        self.assertEqual(len(result.exploratory), 1)
        self.assertEqual(result.cost, Decimal("0.50"))

    def test_high_reach_main_contender_cannot_take_newcomer_reserve(self):
        self.assertFalse(qualify(candidate(position=1, party_strength=2, followers=100_000)).protected)

    def test_stable_ties_and_determinism_under_input_permutations(self):
        decisions = [qualify(candidate(key=key, position=1)) for key in ("c", "a", "b", "d", "e", "f")]
        costs = {d.candidate.key: Decimal(0) for d in decisions}
        first = schedule(decisions, 3, Decimal(0), costs)
        second = schedule(list(reversed(decisions)), 3, Decimal(0), costs)
        self.assertEqual(first, second)
        self.assertEqual([d.candidate.key for d in first.selected], ["a", "b", "c"])

    def test_budget_overflow_keeps_qualification_and_skips_unaffordable_work(self):
        decisions = [qualify(candidate(key=k, position=1)) for k in ("a", "b", "c")]
        result = schedule(
            decisions,
            3,
            Decimal("0.20"),
            {"a": Decimal(1), "b": Decimal("0.10"), "c": Decimal("0.10")},
        )
        self.assertEqual([d.candidate.key for d in result.selected], ["b", "c"])
        self.assertEqual([d.candidate.key for d in result.deferred], ["a"])
        self.assertTrue(result.deferred[0].qualified)
        self.assertLessEqual(result.cost, Decimal("0.20"))
        empty = schedule(decisions, 0, Decimal(0), {d.candidate.key: Decimal(0) for d in decisions})
        self.assertEqual(len(empty.deferred), 3)

    def test_city_round_robin_and_no_budget_breach(self):
        decisions = [
            qualify(candidate(key=f"{rank}_{i}", position=1, city_rank=rank, city_code=str(rank)))
            for rank in (1, 2)
            for i in range(5)
        ]
        costs = {d.candidate.key: Decimal("0.03") for d in decisions}
        result = schedule(decisions, 3, Decimal("0.10"), costs)
        self.assertEqual([d.candidate.city_rank for d in result.selected], [1, 2, 1])
        self.assertEqual(result.cost, Decimal("0.09"))


class SourceReviewTests(unittest.TestCase):
    def test_reach_requires_explicit_fresh_account_review_and_rejects_namesake_ownership(self):
        account = {
            "status": "accepted",
            "platform": "instagram",
            "handle": "same_name",
            "person_id": "p1",
            "sources": "serp",
        }
        metric = {
            "platform": "instagram",
            "handle": "same_name",
            "followers": 100_000,
            "observed_at": AS_OF.isoformat(),
            "source_path": "synthetic_cached_profile.json",
        }
        review = {"kind": "account_identity", "platform": "instagram", "handle": "same_name"}
        owners = {("instagram", "same_name"): {"p1"}}
        self.assertEqual(reviewed_following([account], owners, [metric], [], AS_OF)[1], [])
        self.assertEqual(len(reviewed_following([account], owners, [metric], [review], AS_OF)[1]), 1)
        self.assertEqual(
            reviewed_following([account], {("instagram", "same_name"): {"p1", "p2"}}, [metric], [review], AS_OF)[1], []
        )
        self.assertEqual(
            reviewed_following([account | {"status": "unconfirmed"}],
                               {("instagram", "same_name"): {"p2"}}, [metric], [review], AS_OF)[1], []
        )
        stale = {**metric, "observed_at": "2026-08-01T00:00:00+02:00"}
        self.assertEqual(reviewed_following([account], owners, [stale], [review], AS_OF)[1], [])

    def test_metric_ties_use_lower_count_and_latest_observation_uses_absolute_time(self):
        account = {"status": "unconfirmed", "platform": "instagram", "handle": "person", "person_id": "p1"}
        reviews = [{"kind": "account_identity", "platform": "instagram", "handle": "person"}]
        counts = [
            {
                "platform": "instagram",
                "handle": "person",
                "followers": followers,
                "observed_at": timestamp,
                "source_path": "synthetic",
            }
            for followers, timestamp in (
                (100_000, "2026-10-09T00:00:00+02:00"),
                (12_000, "2026-10-08T22:30:00+00:00"),
                (9_000, "2026-10-09T00:30:00+02:00"),
            )
        ]
        _, measurements = reviewed_following([account], {}, counts, reviews, AS_OF)
        self.assertEqual(measurements[0]["followers"], 9_000)
        self.assertTrue(measurements[0]["conflicting_counts"])
        self.assertFalse(qualify(candidate(followers=measurements[0]["followers"])).qualified)

    def test_duplicate_review_order_does_not_change_noncandidate_result(self):
        cities = [{"municipality_code": "city", "population_rank": 1, "population": 100_000, "name": "Synthetic city"}]
        reviews = [founder_review(), founder_review(source_url="https://synthetic.example/other-anchor")]
        self.assertEqual(
            local_role_extensions(reviews, cities, AS_OF, set()),
            local_role_extensions(list(reversed(reviews)), cities, AS_OF, set()),
        )

    def test_exact_noncandidate_founder_without_followers_or_finance_triggers_discovery(
        self,
    ):
        cities = [
            {
                "municipality_code": "city",
                "population_rank": 1,
                "population": 100_000,
                "name": "Synthetic city",
            }
        ]
        extensions = local_role_extensions([founder_review()], cities, AS_OF, set())
        self.assertEqual(len(extensions), 1)
        c = Candidate(**extensions[0]["candidate"])
        self.assertEqual(c.eligibility_kind, "reviewed_local_role")
        self.assertTrue(qualify(c).qualified)
        self.assertTrue(qualify(c).protected)
        self.assertIsNone(c.followers)
        self.assertEqual(
            extensions[0]["evidence"]["source"]["identity_source_url"],
            "https://synthetic.example/public-professional/identity",
        )

    def test_occupation_donor_fame_stale_unsupported_role_and_conflict_do_not_trigger_extension(
        self,
    ):
        cities = [
            {
                "municipality_code": "city",
                "population_rank": 1,
                "population": 100_000,
                "name": "Synthetic city",
            }
        ]
        for bad in (
            founder_review(role_type="business_owner"),
            founder_review(role_type="private_donor"),
            founder_review(municipality_code="unrelated"),
            founder_review(identity_confirmed=False),
            founder_review(observed_at="2025-10-09T00:00:00+02:00"),
            founder_review(valid_until="2026-10-01T00:00:00+02:00"),
        ):
            self.assertEqual(local_role_extensions([bad], cities, AS_OF, set()), [])
        conflict = founder_review(adjudication="conflicting")
        self.assertEqual(
            local_role_extensions([founder_review(), conflict], cities, AS_OF, set()),
            [],
        )
        self.assertEqual(
            local_role_extensions([founder_review()], cities, AS_OF, {("synthetic_founder", "city")}),
            [],
        )

    def test_independently_documented_activity_and_current_office(self):
        role = founder_review(candidacy_id="candidate")
        action = {
            **role,
            "kind": "local_public_action",
            "source_url": "https://synthetic.example/news/local-action",
            "independent_origin": "independent_editorial_owner",
            "substantive_action_confirmed": True,
            "event_at": "2026-09-20T00:00:00+02:00",
        }
        office = {**role, "kind": "current_office"}
        activity, current, _, _ = reviewed_signals([role, action, office], "candidate", "city", AS_OF)
        self.assertTrue(activity)
        self.assertTrue(current)
        repeated = {**action, "independent_origin": "organization"}
        self.assertFalse(reviewed_signals([role, repeated], "candidate", "city", AS_OF)[0])
        conflict = {**action, "adjudication": "conflicting"}
        self.assertFalse(reviewed_signals([role, action, conflict], "candidate", "city", AS_OF)[0])
        stale = {**action, "event_at": "2024-01-01T00:00:00+02:00"}
        self.assertFalse(reviewed_signals([role, stale], "candidate", "city", AS_OF)[0])

        expired_role = {**role, "valid_until": "2026-09-01T00:00:00+02:00"}
        self.assertFalse(reviewed_signals([expired_role, action], "candidate", "city", AS_OF)[0])
        account = {
            **role,
            "kind": "account_identity",
            "platform": "instagram",
            "handle": "person",
            "anchor_links_account": False,
        }
        self.assertEqual(reviewed_signals([account], "candidate", "city", AS_OF)[2], [])

    def test_account_only_review_leaves_public_activity_unknown(self):
        review = founder_review(candidacy_id="candidate", kind="account_identity", anchor_links_account=True)
        self.assertIsNone(reviewed_signals([review], "candidate", "city", AS_OF)[0])


if __name__ == "__main__":
    unittest.main()
