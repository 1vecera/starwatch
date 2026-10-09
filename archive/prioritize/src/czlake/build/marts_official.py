"""M2 marts from official data: relevant persons for the top-100 municipalities and several rankings.

Rankings (each a separate mart, all transparent):
  rank_offices        current public mandates from election results (MP 2025, MEP 2024, senator, regional 2024, city 2022)
  rank_pref_ps2025    preferential votes in the 2025 Chamber election (absolute and share of the party's regional vote)
  rank_pref_city2022  personal votes in the 2022 city-council elections of the top-100 cities, normalised by the council's votes per seat
  rank_lead2026       leading a 2026 list in a top-100 city (list position 1-3), weighted by city size
  rank_official_composite  published weights over percentile ranks of the components above plus career breadth
Scores measure electoral strength and public office, never character or credibility.
"""
from __future__ import annotations

import json

from .. import lakehouse as lh
from ..textnorm import register

WEIGHTS = {"offices": 0.35, "pull": 0.30, "lead2026": 0.20, "career": 0.15}
OFFICE_POINTS = {"MP 2025": 5, "MEP 2024": 5, "Senator": 4, "Regional councillor 2024": 3,
                 "City councillor 2022": 2, "District councillor 2022": 1}


def build() -> dict:
    con = lh.duck()
    register(con)
    con.sql("""
      create temp table top as select municipality_code, name, population, population_rank, normkey(name) as name_key_city
      from core.municipality_top where in_top100;
      create temp table cand as select c.*, cp.person_id from core.candidacy c join core.candidacy_person cp using (candidacy_id);
      -- council-level vote totals for municipal elections (sum of list votes per council)
      create temp table council_votes as
        select election_id, unit_code, sum(list_votes) as council_votes, any_value(unit_seats) as seats
        from (select distinct election_id, unit_code, unit_subdistrict, list_no, list_votes, unit_seats from cand where election_type='municipal' and election_id<>'kv2026')
        group by all;
      -- relevance: local candidacy in a top-100 city (city or district council), or residence in a top-100 city
      create temp table relevant as
        select distinct c.person_id, t.municipality_code
        from cand c join top t on c.municipality_code = t.municipality_code
        union
        select distinct c.person_id, t.municipality_code
        from cand c join top t on c.residence_key = t.name_key_city
        where c.election_type in ('chamber','regional','senate','european');
    """)
    # offices from election results (current terms)
    con.sql("""
      create temp table offices as
      select person_id, office, unit_name, election_id from (
        select person_id, 'MP 2025' as office, unit_name, election_id from cand where election_id='ps2025' and elected
        union all select person_id, 'MEP 2024', unit_name, election_id from cand where election_id='ep2024' and elected
        union all select person_id, 'Senator', unit_name, election_id from cand where election_id in ('se2022','se2024','se2025leden','se2020') and elected
        union all select person_id, 'Regional councillor 2024', unit_name, election_id from cand where election_id='kz2024' and elected
        union all select c.person_id, 'City councillor 2022', c.unit_name, c.election_id from cand c join top t on c.unit_code=t.municipality_code where c.election_id='kv2022' and c.elected
        union all select c.person_id, 'District councillor 2022', c.unit_name, c.election_id from cand c join top t on c.municipality_code=t.municipality_code
               where c.election_id='kv2022' and c.elected and c.unit_type='district_council'
      )
    """)
    pts = " ".join(f"when '{k}' then {v}" for k, v in OFFICE_POINTS.items())
    rank_offices = lh.tbl(con.sql(f"""
      select person_id, string_agg(office || ' (' || unit_name || ')', '; ' order by office) as offices,
             max(case office {pts} end) + 0.5 * (count(*) - 1) as office_points, count(*) as n_offices,
             max(case office {pts} end) as top_office_points
      from offices group by person_id
    """))
    lh.write("marts", "rank_offices", rank_offices)
    con.register("rank_offices_t", rank_offices)

    rank_ps = lh.tbl(con.sql("""
      select person_id, first_name || ' ' || last_name as name, list_name, unit_name as region, list_position, pref_votes, pref_pct, elected,
             rank() over (order by pref_votes desc) as rank_abs, rank() over (order by pref_pct desc nulls last) as rank_share
      from cand where election_id='ps2025' and pref_votes > 0
    """))
    lh.write("marts", "rank_pref_ps2025", rank_ps)

    rank_city = lh.tbl(con.sql("""
      select c.person_id, c.first_name || ' ' || c.last_name as name, t.name as city, t.population_rank, c.list_name, c.list_position,
             c.pref_votes, c.elected, v.council_votes, v.seats,
             c.pref_votes / nullif(v.council_votes / nullif(v.seats,0), 0) as votes_per_seat_quota,
             rank() over (partition by t.municipality_code order by c.pref_votes desc) as rank_in_city
      from cand c join top t on c.unit_code = t.municipality_code
      join council_votes v on v.election_id=c.election_id and v.unit_code=c.unit_code
      where c.election_id='kv2022' and c.pref_votes > 0
    """))
    lh.write("marts", "rank_pref_city2022", rank_city)

    lead = lh.tbl(con.sql("""
      select c.person_id, c.first_name || ' ' || c.last_name as name, t.name as city, t.population, t.population_rank,
             c.list_name, c.list_position, c.occupation,
             (4 - c.list_position) * ln(t.population) as lead_points
      from cand c join top t on c.unit_code = t.municipality_code
      where c.election_id='kv2026' and c.list_position <= 3
    """))
    lh.write("marts", "rank_lead2026", lead)
    con.register("lead_t", lead)
    con.register("rank_city_t", rank_city)
    con.register("rank_ps_t", rank_ps)

    comp = lh.tbl(con.sql(f"""
      with persons as (select distinct person_id from relevant
                       union select person_id from rank_offices_t),
      pull as (
        select person_id, max(p) as pull_pct from (
          select person_id, percent_rank() over (order by votes_per_seat_quota) as p from rank_city_t
          union all select person_id, percent_rank() over (order by pref_votes) from rank_ps_t
          union all select person_id, percent_rank() over (order by pref_votes)
            from cand where election_id in ('kz2024','ep2024') and pref_votes > 0
          union all select person_id, percent_rank() over (order by pref_pct)
            from cand where election_type='senate' and election_id <> 'se2026' and pref_pct > 0
        ) group by person_id),
      career as (select person_id, count(distinct election_id) filter (where election_id <> 'kv2026') as n_contested,
                        count(*) filter (where elected) as n_won from cand group by person_id),
      l26 as (select person_id, max(lead_points) as lead_points from lead_t group by person_id),
      base as (
        select p.person_id, coalesce(o.office_points,0) as office_points, o.offices,
               coalesce(pull.pull_pct,0) as pull_pct, coalesce(l26.lead_points,0) as lead_points,
               coalesce(cr.n_contested,0) as n_contested, coalesce(cr.n_won,0) as n_won
        from persons p left join rank_offices_t o using (person_id) left join pull using (person_id)
        left join l26 using (person_id) left join career cr using (person_id)),
      pct as (
        select *, percent_rank() over (order by office_points) as offices_pct,
                  percent_rank() over (order by lead_points) as lead_pct,
                  percent_rank() over (order by n_won * 2 + n_contested) as career_pct
        from base)
      select pct.*, pe.display_name, pe.birth_year_lo, pe.birth_year_hi, pe.latest_residence, pe.latest_occupation, pe.elections,
             pe.possible_duplicates,
             round(100 * ({WEIGHTS['offices']} * offices_pct + {WEIGHTS['pull']} * pull_pct + {WEIGHTS['lead2026']} * lead_pct + {WEIGHTS['career']} * career_pct), 2) as score_official,
             '{json.dumps(WEIGHTS)}' as weights
      from pct join core.person pe using (person_id)
      order by score_official desc
    """))
    lh.write("marts", "rank_official_composite", comp)
    rel = lh.tbl(con.sql("select * from relevant"))
    lh.write("core", "person_municipality_relevance", rel)
    return {"offices": rank_offices.num_rows, "ps2025": rank_ps.num_rows, "city2022": rank_city.num_rows,
            "lead2026": lead.num_rows, "composite": comp.num_rows, "relevance_pairs": rel.num_rows}


if __name__ == "__main__":
    print(build())
