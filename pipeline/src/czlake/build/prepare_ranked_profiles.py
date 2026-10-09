"""Intersect a draft ranking snapshot with cached profiles; never schedule a run."""
from __future__ import annotations

import hashlib
import json

from .. import lakehouse as lh
from ..land import now_iso
from ..paths import DATA, DOCS, PROJECT
from ..priority import Candidate, qualify
from ..scope import TOP_CITY_RANK


def prepare() -> dict:
    path = PROJECT / "tmp" / "prioritization" / "universe.json"
    snapshot = path.read_bytes()
    retained = json.loads(snapshot)
    con = lh.duck()
    official = {row[0] for row in con.sql("select candidacy_id from marts.active_city_2026_candidates where eligible_current_ballot").fetchall()}
    qualified = [row for row in retained if row["qualified"] and row["candidate"]["eligible"]
                 and row["candidate"]["city_rank"] <= TOP_CITY_RANK]
    for row in qualified:
        if not qualify(Candidate(**row["candidate"])).qualified:
            raise ValueError("Saved qualification differs from the integrated reference")
    candidacies = [row for row in qualified if row["candidate"]["eligibility_kind"] == "current_candidacy"]
    roles = [row for row in qualified if row["candidate"]["eligibility_kind"] == "reviewed_local_role"]
    if not all(row["candidate"]["key"] in official for row in candidacies):
        raise ValueError("Ranking keys do not match the current eligible top-ten official snapshot")
    by_person = {}
    for row in qualified:
        by_person.setdefault(row["person_id"], []).append(row)
    profiles = con.sql("select * from marts.active_profile_candidates where entity_kind='person'").to_arrow_table().to_pylist()
    matched = [row for row in profiles if row["entity_id"] in by_person]
    handles = sorted({row["handle"] for row in matched})
    associations = [{"handle": row["handle"], "person_id": row["entity_id"], "name": row["entity_name"],
                     "city": row["city"], "identity_status": row["identity_status"], "inherited_status": row["inherited_status"],
                     "ranking_reasons": sorted({reason for target in by_person[row["entity_id"]] for reason in target["reasons"]}),
                     "protected": any(target["protected"] for target in by_person[row["entity_id"]]),
                     "profile_url": row["profile_url"], "discovery_url": row["discovery_url"], "match_basis": row["match_basis"]}
                    for row in matched]
    batches = []
    for start in range(0, len(handles), 50):
        chunk = handles[start:start + 50]
        batches.append({"actor": "apify/instagram-profile-scraper", "input": {"usernames": chunk, "includeAboutSection": False},
                        "profile_count": len(chunk), "estimated_usd": round(len(chunk) * 0.0023, 5),
                        "max_total_charge_usd_proposal": round(len(chunk) * 0.0023 * 1.2 + 0.01, 3),
                        "status": "held_draft_requires_rank_review_identity_check_and_spend_authorization"})
    output = {"observed_at": now_iso(), "scope": "top_ten_city_councils", "status": "unapproved_draft_intersection",
              "ranking_source": str(path), "ranking_sha256": hashlib.sha256(snapshot).hexdigest(),
              "qualified_candidacies": len(candidacies), "qualified_local_roles": len(roles),
              "qualified_total": len(qualified), "qualified_persons": len(by_person),
              "profile_handles": len(handles), "estimated_total_usd": round(len(handles) * 0.0023, 5),
              "inherited_accepted_handles": len({row["handle"] for row in matched if row["inherited_status"] == "accepted"}),
              "protected_handles": len({row["handle"] for row in associations if row["protected"]}),
              "qualification_without_profile": len(set(by_person) - {row["entity_id"] for row in matched}),
              "associations": associations, "batches": batches}
    target = DATA / "inputs" / "top10_ranked_profile_review_proposal.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    note = (f"\n## Draft ranking intersection — {output['observed_at']}\n\n"
            f"The reviewed rule qualifies {len(candidacies)} current candidacies and {len(roles)} separately reviewed local-role discoveries. "
            "Ballot keys match current eligible top-ten official keys; public-role keys remain separate. "
            f"Cached person-account intersection contains {len(handles)} distinct Instagram handles "
            f"({output['inherited_accepted_handles']} inherited accepted, the remainder unconfirmed), estimated **${output['estimated_total_usd']:.5f}**. "
            f"{output['protected_handles']} handles are associated with its protected newcomer/reach/activity path. "
            f"{output['qualification_without_profile']} qualifying person clusters have no cached Instagram candidate and stay visible as gaps; "
            "absence does not remove qualification. This is a held snapshot intersection, not a spending instruction, "
            "a final ordering or permission to buy metrics. Exact held inputs and source hash are in "
            "`data/inputs/top10_ranked_profile_review_proposal.json`; identity checks, protected scheduling and authorization remain pending. "
            "Organization profiles remain in the separate local-list review pool. No shared ranking mart was written.\n")
    document = DOCS / "top10-batch-plan.md"
    previous = document.read_text()
    start = previous.find("\n## Draft ranking intersection")
    following = previous.find("\n## ", start + 1) if start >= 0 else -1
    document.write_text((previous[:start] if start >= 0 else previous) + note
                        + (previous[following:] if following >= 0 else ""))
    print(json.dumps({key: value for key, value in output.items() if key not in {"associations", "batches"}}, ensure_ascii=False))
    return output


if __name__ == "__main__":
    prepare()
