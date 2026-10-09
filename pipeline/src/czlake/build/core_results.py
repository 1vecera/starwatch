"""Party/list results per municipality (city level; Prague and statutory-city districts rolled up).

Sources: precinct files of volby.cz (PS 2021/2025 pst4/pst4p, KZ 2020/2024 kzt6/kzt6p, EP 2019/2024 ept2/ept2p),
council files for municipal elections (kvros). Corrected precinct forms (OPRAVA) replace the originals.
"""
from __future__ import annotations

from .. import lakehouse as lh

PRECINCT = {
    # election: (turnout table, party table, party col, list table, list name col, list abbr col)
    "ps2025": ("pst4", "pst4p", "KSTRANA", "reg_psrkl", "NAZEVCELK", "ZKRATKAK8"),
    "ps2021": ("pst4", "pst4p", "KSTRANA", "reg_psrkl", "NAZEVCELK", "ZKRATKAK8"),
    "kz2024": ("kzt6", "kzt6p", "KSTRANA", "reg_kzrkl_s", "NAZEVCELK", "ZKRATKAK8"),
    "ep2024": ("ept2", "ept2p", "ESTRANA", "reg_eprkl", "NAZEVCELK", "ZKRATKAE8"),
}


def exists(con, name: str) -> bool:
    return bool(con.sql(f"select count(*) from information_schema.tables where table_schema='staging' and table_name='{name}'").fetchone()[0])


def build() -> dict:
    con = lh.duck()
    con.sql("""
      create temp table parent as
      select distinct KODZASTUP as code, NADRZASTUP as city_code from staging.volby_kv2026_cis_kvcoco where TYPZASTUP='2'
      union select distinct KODZASTUP, NADRZASTUP from staging.volby_kv2022_cis_kvcoco where TYPZASTUP='2'
    """)
    parts_r, parts_t = [], []
    for e, (tt, tp, pcol, lt, ln, la) in PRECINCT.items():
        if not exists(con, f"volby_{e}_data_{tp}"):
            continue
        lt_full = f"staging.volby_{e}_{lt}"
        if not exists(con, f"volby_{e}_{lt}"):
            lt_full = None
        lsel = f"l.{ln} as list_name, l.{la} as list_abbr" if lt_full else "null as list_name, null as list_abbr"
        ljoin = f"left join (select {pcol}, any_value({ln}) {ln}, any_value({la}) {la} from {lt_full} group by 1) l on l.{pcol}=v.list_no" if lt_full else ""
        parts_r.append(f"""
          select '{e}' as election_id, coalesce(p.city_code, v.OBEC) as municipality_code, v.list_no, {lsel},
                 sum(v.votes) as votes
          from (select OBEC, {pcol} as list_no, try_cast(POC_HLASU as bigint) as votes,
                       row_number() over (partition by ID_OKRSKY, {pcol} order by try_cast(OPRAVA as int) desc) rn
                from staging.volby_{e}_data_{tp}) v
          left join parent p on p.code=v.OBEC
          {ljoin}
          where v.rn=1 group by all""")
        parts_t.append(f"""
          select '{e}' as election_id, coalesce(p.city_code, t.OBEC) as municipality_code,
                 sum(try_cast(VOL_SEZNAM as bigint)) as registered, sum(try_cast(ODEVZ_OBAL as bigint)) as envelopes,
                 sum(try_cast(PL_HL_CELK as bigint)) as valid_votes
          from (select *, row_number() over (partition by ID_OKRSKY order by try_cast(OPRAVA as int) desc) rn
                from staging.volby_{e}_data_{tt}) t
          left join parent p on p.code=t.OBEC
          where t.rn=1 group by all""")
    res = lh.tbl(con.sql(" union all ".join(parts_r)))
    turn = lh.tbl(con.sql(" union all ".join(parts_t)))
    con.register("res_t", res)
    con.register("turn_t", turn)
    # municipal councils: city-council list results straight from the registry of lists
    kv = lh.tbl(con.sql("""
      select election_id, unit_code as municipality_code, list_no, any_value(list_name) as list_name, any_value(list_abbr) as list_abbr,
             any_value(list_votes) as votes, any_value(list_pct) as pct_reported, any_value(list_mandates) as mandates,
             any_value(unit_seats) as seats
      from core.candidacy where election_type='municipal' and election_id<>'kv2026' and unit_type in ('city_council','municipal_council')
      group by election_id, unit_code, unit_subdistrict, list_no
    """))
    out = lh.tbl(con.sql("""
      select r.election_id, r.municipality_code, r.list_no, r.list_name, r.list_abbr, r.votes,
             r.votes::double / nullif(t.valid_votes,0) as share, null::int as mandates, null::int as seats,
             t.registered, t.valid_votes, t.envelopes::double / nullif(t.registered,0) as turnout
      from res_t r left join turn_t t using (election_id, municipality_code)
    """))
    con.register("out_t", out)
    con.register("kv_t", kv)
    allr = lh.tbl(con.sql("""
      select * from out_t
      union all by name
      select election_id, municipality_code, list_no, list_name, list_abbr, votes,
             votes::double / nullif(sum(votes) over (partition by election_id, municipality_code),0) as share,
             mandates, seats, null::bigint as registered, null::bigint as valid_votes, null::double as turnout
      from kv_t
    """))
    lh.write("core", "result_municipality", allr)
    return {"rows": allr.num_rows}


if __name__ == "__main__":
    print(build())
    con = lh.duck()
    print(con.sql("""select election_id, list_abbr, round(100*share,1), votes from core.result_municipality
                     where municipality_code='554782' and election_id='ps2025' order by votes desc limit 6""").fetchall())
    print(con.sql("""select election_id, list_name, round(100*share,1), mandates from core.result_municipality
                     where municipality_code='582786' and election_id='kv2022' order by votes desc limit 6""").fetchall())
