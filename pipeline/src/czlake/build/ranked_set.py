"""Ranked set v1: people who matter for the top-100 municipalities, from official data.

Tiers: national office holders from election results (MPs 2025, senators, MEPs 2024), and local
figures in the top-100 city councils (2026 list leaders, 2022 top-3 personal votes, 2022 elected
councillors of the top 30 cities). Each row says why the person is in the set.
"""
from __future__ import annotations

from .. import lakehouse as lh


def build() -> dict:
    con = lh.duck()
    t = lh.tbl(con.sql("""
      with top as (select municipality_code, name as city, population_rank from core.municipality_top where in_top100),
      cand as (select c.*, cp.person_id from core.candidacy c join core.candidacy_person cp using (candidacy_id)),
      reasons as (
        select person_id, 'MP 2025 (' || unit_name || ', ' || coalesce(list_abbr, list_name) || ')' as reason, 1 as tier, null as city, null::int as city_rank from cand where election_id='ps2025' and elected
        union all select person_id, 'Senator (' || unit_name || ')', 1, null, null from cand where election_id in ('se2022','se2024','se2025leden','se2020') and elected
        union all select person_id, 'MEP 2024 (' || coalesce(list_abbr, list_name) || ')', 1, null, null from cand where election_id='ep2024' and elected
        union all select c.person_id, '2026 list leader: ' || c.list_name || ' (' || t.city || ')', 2, t.city, t.population_rank
               from cand c join top t on c.unit_code=t.municipality_code where c.election_id='kv2026' and c.list_position=1
        union all select person_id, '2022 top-3 personal votes (' || city || ')', 2, city, population_rank from (
               select c.person_id, t.city, t.population_rank, row_number() over (partition by c.unit_code order by c.pref_votes desc) rn
               from cand c join top t on c.unit_code=t.municipality_code where c.election_id='kv2022') where rn<=3
        union all select c.person_id, '2022 city councillor (' || t.city || ')', 3, t.city, t.population_rank
               from cand c join top t on c.unit_code=t.municipality_code where c.election_id='kv2022' and c.elected and t.population_rank<=30
      )
      select r.person_id, p.display_name, p.first_name, p.last_name, p.birth_year_lo, p.birth_year_hi, p.latest_residence,
             min(r.tier) as tier, string_agg(distinct r.reason, '; ') as reasons,
             min(r.city_rank) as best_city_rank, any_value(r.city) as a_city,
             o.score_official
      from reasons r join core.person p using (person_id)
      left join marts.rank_official_composite o using (person_id)
      group by all
    """))
    lh.write("marts", "ranked_set_v1", t)
    return {"persons": t.num_rows}


if __name__ == "__main__":
    print(build())
    con = lh.duck()
    print(con.sql("select tier, count(*) from marts.ranked_set_v1 group by 1 order by 1").fetchall())
    print(con.sql("select count(*) from marts.ranked_set_v1 where tier<=2 and (tier=1 or best_city_rank<=30)").fetchall())
