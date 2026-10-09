"""core.party: ČSÚ party/movement codes (stable across elections) with names, abbreviations and IČO.

IČO comes from Wikidata (P4156, CC0) matched on accent-free full name, then on abbreviation; the MV ČR
register (from the offices sweep) overrides when present. core.list_party maps each electoral list
(VSTRANA, a party, coalition or independents' association) to its member parties.
"""
from __future__ import annotations

from .. import lakehouse as lh
from ..textnorm import register

CODE_TABLES = ["kv2026", "kv2022", "kv2018", "ps2025", "ps2021", "kz2024", "kz2020", "se2026", "se2024", "se2022", "ep2024", "ep2019"]


def exists(con, name: str) -> bool:
    return bool(con.sql(f"select count(*) from information_schema.tables where table_schema='staging' and table_name='{name}'").fetchone()[0])


def build() -> dict:
    con = lh.duck()
    register(con)
    parts = []
    for i, e in enumerate(CODE_TABLES):
        if exists(con, f"volby_{e}_cis_cpp"):
            parts.append(f"select PSTRANA as party_code, NAZEV_STRP as name, ZKRATKAP8 as abbr, {i} as recency, '{e}' as seen_in, source_url from staging.volby_{e}_cis_cpp")
    con.sql(f"create temp table codes as {' union all '.join(parts)}")
    con.sql("""
      create temp table wd as
      select partyLabel as wd_name, shortname as wd_abbr, ico, web as wd_web, party as wd_qid, inception, dissolved,
             normkey(partyLabel) as nk, normkey(shortname) as ak
      from staging.wikidata_cz_parties where ico is not null
    """)
    party = lh.tbl(con.sql("""
      with latest as (
        select party_code, arg_min(name, recency) as name, arg_min(abbr, recency) as abbr,
               string_agg(distinct seen_in, ',') as seen_in, arg_min(source_url, recency) as source_url
        from codes group by party_code),
      m1 as (select l.party_code, any_value(w.ico) ico, any_value(w.wd_qid) qid, any_value(w.wd_web) web, 'name' as basis
             from latest l join wd w on w.nk = normkey(l.name) group by 1),
      m2 as (select l.party_code, any_value(w.ico) ico, any_value(w.wd_qid) qid, any_value(w.wd_web) web, 'abbreviation' as basis
             from latest l join wd w on w.ak = normkey(l.abbr) and w.dissolved is null
             where l.party_code not in (select party_code from m1) group by 1 having count(distinct w.ico)=1)
      select l.*, coalesce(m1.ico, m2.ico) as ico, coalesce(m1.qid, m2.qid) as wikidata, coalesce(m1.web, m2.web) as website,
             coalesce(m1.basis, m2.basis) as ico_match_basis
      from latest l left join m1 using (party_code) left join m2 using (party_code)
    """))
    lh.write("core", "party", party)
    parts = []
    for e in CODE_TABLES:
        if exists(con, f"volby_{e}_cis_cvs_slozeni"):
            parts.append(f"select '{e}' as election_id, VSTRANA as list_party_code, NSTRANA as party_code from staging.volby_{e}_cis_cvs_slozeni")
    lp = lh.tbl(con.sql(" union all ".join(parts)))
    lh.write("core", "list_party", lp)
    return {"parties": party.num_rows, "with_ico": sum(1 for x in party.column("ico").to_pylist() if x), "list_party": lp.num_rows}


if __name__ == "__main__":
    print(build())
    con = lh.duck()
    print(con.sql("select party_code, abbr, name, ico, ico_match_basis from core.party where party_code in ('768','53','166','720','1114','1','721','1178','7','47','1265','1298','714') order by 1").fetchall())
