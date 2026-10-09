"""core.ballot_2026: every person on the 9-10 Oct 2026 municipal (KV) or Senate (SE) candidate registry."""
from __future__ import annotations

import sys

from .. import lakehouse as lh
from ..textnorm import register


def build() -> None:
    con = lh.duck()
    register(con)
    t = con.sql("""
        select 'kv2026' as election_id, 'municipal' as election_type,
               k.KODZASTUP as council_code, z.NAZEVZAST as council_name, z.OBEC as municipality_code,
               z.TYPZASTUP as council_type, z.MANDATY as council_seats,
               k.OSTRANA as list_no, r.NAZEVCELK as list_name, k.PORCISLO as list_position,
               k.JMENO as first_name, k.PRIJMENI as last_name, k.TITULPRED as title_before, k.TITULZA as title_after,
               try_cast(k.VEK as int) as age, k.POVOLANI as occupation, k.BYDLISTEN as residence,
               k.PSTRANA as member_party_code, pm.ZKRATKAP8 as member_party_abbr, pm.NAZEV_STRP as member_party,
               k.NSTRANA as nominating_party_code, pn.ZKRATKAP8 as nominating_party_abbr,
               k.PLATNOST as validity, k.source_url, k.fetched_at,
               normkey(k.JMENO || ' ' || k.PRIJMENI) as name_key
        from staging.volby_kv2026_kvrk k
        left join (select KODZASTUP, COBVODU, any_value(NAZEVZAST) as NAZEVZAST, any_value(TYPZASTUP) as TYPZASTUP,
                          any_value(DRUHZASTUP) as DRUHZASTUP, min(OBEC) as OBEC, any_value(MANDATY) as MANDATY
                   from staging.volby_kv2026_kvrzcoco group by all) z on z.KODZASTUP=k.KODZASTUP and z.COBVODU=k.COBVODU
        left join (select KODZASTUP, COBVODU, OSTRANA, any_value(NAZEVCELK) as NAZEVCELK, any_value(VSTRANA) as VSTRANA
                   from staging.volby_kv2026_kvros group by all) r on r.KODZASTUP=k.KODZASTUP and r.COBVODU=k.COBVODU and r.OSTRANA=k.OSTRANA
        left join staging.volby_kv2026_cis_cpp pm on pm.PSTRANA=k.PSTRANA
        left join staging.volby_kv2026_cis_cpp pn on pn.PSTRANA=k.NSTRANA
        union all by name
        select 'se2026' as election_id, 'senate' as election_type,
               s.OBVOD as council_code, o.NAZEV_OBV as council_name, null as municipality_code,
               s.CKAND as list_no, s.NAZEV_VS as list_name, null as list_position,
               s.JMENO as first_name, s.PRIJMENI as last_name, s.TITULPRED as title_before, s.TITULZA as title_after,
               try_cast(s.VEK as int) as age, s.POVOLANI as occupation, s.BYDLISTEN as residence,
               s.PSTRANA as member_party_code, pm.ZKRATKAP8 as member_party_abbr, pm.NAZEV_STRP as member_party,
               s.NSTRANA as nominating_party_code, pn.ZKRATKAP8 as nominating_party_abbr,
               s.PLATNOST as validity, s.source_url, s.fetched_at,
               normkey(s.JMENO || ' ' || s.PRIJMENI) as name_key
        from staging.volby_se2026_serk s
        left join staging.volby_se2026_cis_secobv o on o.OBVOD=s.OBVOD
        left join staging.volby_se2026_cis_cpp pm on pm.PSTRANA=s.PSTRANA
        left join staging.volby_se2026_cis_cpp pn on pn.PSTRANA=s.NSTRANA
    """).arrow()
    lh.write("core", "ballot_2026", t)


def check(names: list[str]) -> list[tuple]:
    con = lh.duck()
    register(con)
    out = []
    for n in names:
        rows = con.sql("""select election_id, council_name, list_name, list_position, first_name, last_name, age, occupation, residence
                          from core.ballot_2026 where name_key = normkey(?)""", params=[n]).fetchall()
        out.append((n, rows))
    return out


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        build()
    else:
        for n, rows in check(sys.argv[1:]):
            print(f"{n}: {'ABSENT' if not rows else 'ON BALLOT'}")
            for r in rows:
                print("   ", r)
