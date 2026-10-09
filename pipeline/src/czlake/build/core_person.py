"""Resolve candidacies into persons across elections and years.

Two candidacies with the same accent-free name are the same person when their birth-year
windows (from age on election day) overlap AND they share a residence or a specific party
(member or nominating; the generic codes for independents/SNK do not count). Links are
transitive (union-find). person_id is derived from the earliest candidacy, so it stays
stable when later elections are added. Ambiguity stays visible: `possible_duplicates`
counts other same-name clusters with overlapping birth years.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict

import pyarrow as pa

from .. import lakehouse as lh

GENERIC_PARTY = {"99", "80", "90", "0", "", None}


class UF:
    def __init__(self, n):
        self.p = list(range(n))

    def f(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def u(self, a, b):
        a, b = self.f(a), self.f(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


def build() -> dict:
    con = lh.duck()
    rows = con.sql("""
        select candidacy_id, election_id, election_date, name_key, birth_year_lo, birth_year_hi, residence_key,
               member_party_code, nominating_party_code, first_name, last_name, title_before, title_after,
               residence, occupation
        from core.candidacy where name_key is not null and age is not null
        order by name_key, election_date
    """).fetchall()
    groups: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        groups[r[3]].append(i)
    # commonness: candidacies with this name in the two latest municipal registries; common names need a residence match
    common = {k: v for k, v in con.sql("""select name_key, count(*) from core.candidacy
                                          where election_id in ('kv2026','kv2022') group by 1 having count(*) > 4""").fetchall()}
    person_of = [None] * len(rows)
    persons = []
    ambiguous = 0
    for name, idx in groups.items():
        uf = UF(len(idx))
        for a in range(len(idx)):
            ra = rows[idx[a]]
            pa_ = {ra[7], ra[8]} - GENERIC_PARTY
            for b in range(a + 1, len(idx)):
                rb = rows[idx[b]]
                if ra[4] > rb[5] or rb[4] > ra[5]:
                    continue  # birth windows do not overlap
                same_res = ra[6] is not None and ra[6] == rb[6]
                pb = {rb[7], rb[8]} - GENERIC_PARTY
                if same_res or ((pa_ & pb) and name not in common):
                    uf.u(a, b)
        clusters: dict[int, list[int]] = defaultdict(list)
        for k in range(len(idx)):
            clusters[uf.f(k)].append(idx[k])
        cl = list(clusters.values())
        windows = []
        for members in cl:
            lo = max(rows[m][4] for m in members)
            hi = min(rows[m][5] for m in members)
            if lo > hi:  # inconsistent windows after transitive merge: keep the widest
                lo, hi = min(rows[m][4] for m in members), max(rows[m][5] for m in members)
            windows.append((lo, hi))
        for ci, members in enumerate(cl):
            members.sort(key=lambda m: (rows[m][2], rows[m][0]))
            first = rows[members[0]]
            pid = "p_" + hashlib.md5(first[0].encode()).hexdigest()[:12]
            lo, hi = windows[ci]
            dup = sum(1 for cj, (l2, h2) in enumerate(windows) if cj != ci and not (lo > h2 or l2 > hi))
            ambiguous += dup > 0
            last = rows[members[-1]]
            for m in members:
                person_of[m] = pid
            persons.append({
                "person_id": pid, "name_key": name,
                "display_name": " ".join(x for x in [last[11], last[9], last[10], last[12]] if x),
                "first_name": last[9], "last_name": last[10], "birth_year_lo": lo, "birth_year_hi": hi,
                "n_candidacies": len(members), "n_elections": len({rows[m][1] for m in members}),
                "elections": ",".join(sorted({rows[m][1] for m in members})),
                "residences": "; ".join(sorted({rows[m][13] for m in members if rows[m][13]})),
                "latest_residence": last[13], "latest_occupation": last[14],
                "possible_duplicates": dup,
            })
    lh.write("core", "person", pa.Table.from_pylist(persons))
    lh.write("core", "candidacy_person", pa.table({"candidacy_id": [r[0] for r in rows], "person_id": person_of}))
    return {"candidacies": len(rows), "persons": len(persons), "ambiguous_clusters": ambiguous}


if __name__ == "__main__":
    print(build())
