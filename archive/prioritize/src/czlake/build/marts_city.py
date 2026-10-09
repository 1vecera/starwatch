"""City marts for the top-100 municipalities.

marts.city_lists_2026       every list standing for the 2026 city council, its leader, notable names on it,
                            member parties and the 2022 / 2025 performance of the same party or list in that city
marts.city_party_strength   party/list shares per city across elections (PS 2021/2025, KZ 2024, EP 2024, KV 2018/2022)
marts.city_profile          one row per city: population, council size, number of lists and candidates in 2026,
                            2022 winner, 2025 Chamber winner, turnout
"""
from __future__ import annotations

from .. import lakehouse as lh


def build() -> dict:
    con = lh.duck()
    con.sql("""
      create temp table top as select municipality_code, name as city, population, population_rank from core.municipality_top where in_top100;
      create temp table cand as select c.*, cp.person_id from core.candidacy c join core.candidacy_person cp using (candidacy_id);
      create temp table lists26 as
        select c.municipality_code, c.list_no, any_value(c.list_name) list_name, any_value(c.list_abbr) list_abbr,
               any_value(c.list_party_code) list_party_code, count(*) n_candidates, any_value(c.unit_seats) seats
        from cand c join top t on c.unit_code=t.municipality_code
        where c.election_id='kv2026' group by 1,2;
      create temp table members as
        select l.municipality_code, l.list_no, string_agg(distinct p.abbr, ' + ') as member_parties,
               list(distinct lp.party_code) as member_codes
        from lists26 l left join core.list_party lp on lp.election_id='kv2026' and lp.list_party_code=l.list_party_code
        left join core.party p on p.party_code=lp.party_code group by 1,2;
      create temp table prev22 as
        select r.municipality_code, r.list_no, r.list_name, r.share, r.mandates, lp.party_code
        from core.result_municipality r
        join (select distinct unit_code, list_no, list_party_code from core.candidacy where election_id='kv2022') k
          on k.unit_code=r.municipality_code and k.list_no=r.list_no
        left join core.list_party lp on lp.election_id='kv2022' and lp.list_party_code=k.list_party_code
        where r.election_id='kv2022';
      create temp table ps25 as
        select r.municipality_code, r.share, lp.party_code
        from core.result_municipality r
        join (select distinct list_no, list_party_code from core.candidacy where election_id='ps2025') k on k.list_no=r.list_no
        left join core.list_party lp on lp.election_id='ps2025' and lp.list_party_code=k.list_party_code
        where r.election_id='ps2025';
    """)
    lists = lh.tbl(con.sql("""
      with leader as (
        select c.unit_code as municipality_code, c.list_no, c.person_id as leader_person_id,
               c.first_name || ' ' || c.last_name as leader_name, c.title_before as leader_title, c.age as leader_age,
               c.occupation as leader_occupation, c.residence as leader_residence
        from cand c join top t on c.unit_code=t.municipality_code where c.election_id='kv2026' and c.list_position=1),
      notable as (
        select c.unit_code as municipality_code, c.list_no,
               string_agg(c.first_name || ' ' || c.last_name || ' (#' || c.list_position || ': ' || o.offices || ')', '; ' order by o.top_office_points desc, c.list_position) as notable_candidates,
               count(*) as n_office_holders
        from cand c join top t on c.unit_code=t.municipality_code join marts.rank_offices o using (person_id)
        where c.election_id='kv2026' group by 1,2),
      same22 as (  -- same list party code in 2022, else any member party overlap; best match by share
        select l.municipality_code, l.list_no, max(p.share) as share_2022_same_party, arg_max(p.list_name, p.share) as list_2022,
               arg_max(p.mandates, p.share) as mandates_2022
        from lists26 l join members m using (municipality_code, list_no)
        join prev22 p on p.municipality_code=l.municipality_code and list_contains(m.member_codes, p.party_code) and p.party_code not in ('80','90','99')
        group by 1,2),
      ps as (
        select l.municipality_code, l.list_no, max(p.share) as ps2025_share_member_party
        from lists26 l join members m using (municipality_code, list_no)
        join ps25 p on p.municipality_code=l.municipality_code and list_contains(m.member_codes, p.party_code) and p.party_code not in ('80','90','99')
        group by 1,2)
      select t.population_rank, t.city, l.municipality_code, l.list_no, l.list_name, l.list_abbr, m.member_parties,
             l.n_candidates, l.seats, ld.leader_person_id, ld.leader_title, ld.leader_name, ld.leader_age, ld.leader_occupation,
             ld.leader_residence, o.offices as leader_offices, rc.score_official as leader_score_official,
             n.notable_candidates, coalesce(n.n_office_holders,0) as n_office_holders,
             s.list_2022, s.share_2022_same_party, s.mandates_2022, ps.ps2025_share_member_party,
             'https://volby.gov.cz/opendata/kv2026/KV2026reg20261007_csv.zip' as source_url
      from lists26 l join top t using (municipality_code)
      left join members m using (municipality_code, list_no)
      left join leader ld using (municipality_code, list_no)
      left join marts.rank_offices o on o.person_id=ld.leader_person_id
      left join marts.rank_official_composite rc on rc.person_id=ld.leader_person_id
      left join notable n using (municipality_code, list_no)
      left join same22 s using (municipality_code, list_no)
      left join ps using (municipality_code, list_no)
      order by t.population_rank, coalesce(s.share_2022_same_party, 0) desc, l.list_no
    """))
    lh.write("marts", "city_lists_2026", lists)
    strength = lh.tbl(con.sql("""
      select t.population_rank, t.city, r.election_id, r.list_no, r.list_name, r.list_abbr, r.votes, r.share, r.mandates, r.turnout
      from core.result_municipality r join top t using (municipality_code)
    """))
    lh.write("marts", "city_party_strength", strength)
    profile = lh.tbl(con.sql("""
      with l as (select municipality_code, count(*) n_lists_2026, sum(n_candidates) n_candidates_2026, any_value(seats) seats from lists26 group by 1),
      w22 as (select municipality_code, arg_max(list_name, share) winner_2022, max(share) winner_2022_share from core.result_municipality where election_id='kv2022' group by 1),
      w25 as (select municipality_code, arg_max(list_abbr, share) winner_ps2025, max(share) winner_ps2025_share, any_value(turnout) turnout_ps2025 from core.result_municipality where election_id='ps2025' group by 1)
      select t.*, l.n_lists_2026, l.n_candidates_2026, l.seats as council_seats, w22.winner_2022, w22.winner_2022_share,
             w25.winner_ps2025, w25.winner_ps2025_share, w25.turnout_ps2025
      from top t left join l using (municipality_code) left join w22 using (municipality_code) left join w25 using (municipality_code)
      order by population_rank
    """))
    lh.write("marts", "city_profile", profile)
    return {"lists": lists.num_rows, "strength": strength.num_rows, "profile": profile.num_rows}


if __name__ == "__main__":
    print(build())
    con = lh.duck()
    for r in con.sql("select city, list_abbr, leader_name, leader_offices, round(100*share_2022_same_party,1), round(100*ps2025_share_member_party,1), n_office_holders from marts.city_lists_2026 where city in ('Brno') order by share_2022_same_party desc nulls last limit 12").fetchall(): print(r)
    print(con.sql("select city, n_lists_2026, n_candidates_2026, council_seats, winner_2022, round(100*winner_2022_share,1), winner_ps2025, round(100*turnout_ps2025,1) from marts.city_profile limit 5").fetchall())
