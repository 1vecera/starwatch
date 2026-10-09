"""Core election entities: election, candidacy (every candidate row of every staged election), list results.

All candidacies keep their source registry URL and fetch time. Party codes are ČSÚ's (PSTRANA/NSTRANA),
which are stable across elections; list/council numbers stay inside their election's namespace.
"""
from __future__ import annotations

import pyarrow as pa

from .. import lakehouse as lh
from ..textnorm import register

ELECTIONS = [
    # election_id, type, first day, label, open-data page
    ("kv2026", "municipal", "2026-10-09", "Municipal councils 2026 (candidates only; vote 9-10 Oct)", "https://volby.gov.cz/opendata/kv2026/kv2026_opendata.htm"),
    ("kv2022", "municipal", "2022-09-23", "Municipal councils 2022", "https://volby.gov.cz/opendata/kv2022/kv2022_opendata.htm"),
    ("kv2018", "municipal", "2018-10-05", "Municipal councils 2018", "https://volby.gov.cz/opendata/kv2018/kv2018_opendata.htm"),
    ("ps2025", "chamber", "2025-10-03", "Chamber of Deputies 2025", "https://volby.gov.cz/opendata/ps2025/ps2025_opendata.htm"),
    ("ps2021", "chamber", "2021-10-08", "Chamber of Deputies 2021", "https://volby.gov.cz/opendata/ps2021/ps2021_opendata.htm"),
    ("kz2024", "regional", "2024-09-20", "Regional councils 2024", "https://volby.gov.cz/opendata/kz2024/kz2024_opendata.htm"),
    ("kz2020", "regional", "2020-10-02", "Regional councils 2020", "https://volby.gov.cz/opendata/kz2020/kz2020_opendata.htm"),
    ("se2026", "senate", "2026-10-09", "Senate 2026 (candidates only)", "https://volby.gov.cz/opendata/se2026/se2026_opendata.htm"),
    ("se2025leden", "senate", "2025-01-17", "Senate by-election January 2025", "https://volby.gov.cz/opendata/se2025leden/se2025leden_opendata.htm"),
    ("se2024", "senate", "2024-09-20", "Senate 2024", "https://volby.gov.cz/opendata/se2024/se2024_opendata.htm"),
    ("se2022", "senate", "2022-09-23", "Senate 2022", "https://volby.gov.cz/opendata/se2022/se2022_opendata.htm"),
    ("se2020", "senate", "2020-10-02", "Senate 2020", "https://volby.gov.cz/opendata/se2020/se2020_opendata.htm"),
    ("ep2024", "european", "2024-06-07", "European Parliament 2024", "https://volby.gov.cz/opendata/ep2024/ep2024_opendata.htm"),
    ("ep2019", "european", "2019-05-24", "European Parliament 2019", "https://volby.gov.cz/opendata/ep2019/ep2019_opendata.htm"),
]


def exists(con, name: str) -> bool:
    return bool(con.sql(f"select count(*) from information_schema.tables where table_schema='staging' and table_name='{name}'").fetchone()[0])


def kv_sql(e: str, date: str) -> str:
    return f"""
    select '{e}' as election_id, 'municipal' as election_type, date '{date}' as election_date,
      case when z.TYPZASTUP='2' then 'district_council' when z.DRUHZASTUP in ('3','4') then 'city_council' else 'municipal_council' end as unit_type,
      k.KODZASTUP as unit_code, z.NAZEVZAST as unit_name,
      case when z.TYPZASTUP='2' then z.NADRZASTUP else k.KODZASTUP end as municipality_code,
      k.COBVODU as unit_subdistrict,
      k.OSTRANA as list_no, r.NAZEVCELK as list_name, r.ZKRATKAO8 as list_abbr, r.VSTRANA as list_party_code,
      try_cast(k.PORCISLO as int) as list_position,
      k.JMENO as first_name, k.PRIJMENI as last_name, k.TITULPRED as title_before, k.TITULZA as title_after,
      try_cast(k.VEK as int) as age, k.POVOLANI as occupation, k.BYDLISTEN as residence,
      k.PSTRANA as member_party_code, k.NSTRANA as nominating_party_code, k.PLATNOST as validity,
      try_cast(k.POCHLASU as bigint) as pref_votes, try_cast(replace(k.POCPROCVSE, ',', '.') as double) as pref_pct,
      (k.MANDAT='A') as elected, try_cast(k.PORADIMAND as int) as mandate_order, try_cast(k.PORADINAHR as int) as substitute_order,
      try_cast(r.HLASY_STR as bigint) as list_votes, try_cast(replace(r.PROCHLSTR, ',', '.') as double) as list_pct,
      try_cast(r.MAND_STR as int) as list_mandates, try_cast(z.MANDATY as int) as unit_seats,
      k.source_url, k.fetched_at
    from staging.volby_{e}_reg_kvrk k
    left join (select KODZASTUP, COBVODU, OSTRANA, any_value(NAZEVCELK) NAZEVCELK, any_value(ZKRATKAO8) ZKRATKAO8,
                      any_value(VSTRANA) VSTRANA, any_value(HLASY_STR) HLASY_STR, any_value(PROCHLSTR) PROCHLSTR, any_value(MAND_STR) MAND_STR
               from staging.volby_{e}_reg_kvros group by all) r
      on r.KODZASTUP=k.KODZASTUP and r.COBVODU=k.COBVODU and r.OSTRANA=k.OSTRANA
    left join (select KODZASTUP, any_value(NAZEVZAST) NAZEVZAST, any_value(TYPZASTUP) TYPZASTUP, any_value(DRUHZASTUP) DRUHZASTUP,
                      any_value(NADRZASTUP) NADRZASTUP, any_value(MANDATY) MANDATY
               from staging.volby_{e}_cis_kvcoco group by all) z on z.KODZASTUP=k.KODZASTUP
    """


def ps_sql(e: str, date: str) -> str:
    return f"""
    select '{e}' as election_id, 'chamber' as election_type, date '{date}' as election_date,
      'electoral_region' as unit_type, k.VOLKRAJ as unit_code, v.NAZVOLKRAJ as unit_name, null as municipality_code, null as unit_subdistrict,
      k.KSTRANA as list_no, l.NAZEVCELK as list_name, l.ZKRATKAK8 as list_abbr, l.VSTRANA as list_party_code,
      try_cast(k.PORCISLO as int) as list_position,
      k.JMENO as first_name, k.PRIJMENI as last_name, k.TITULPRED as title_before, k.TITULZA as title_after,
      try_cast(k.VEK as int) as age, k.POVOLANI as occupation, k.BYDLISTEN as residence,
      k.PSTRANA as member_party_code, k.NSTRANA as nominating_party_code, k.PLATNOST as validity,
      try_cast(k.POCHLASU as bigint) as pref_votes, try_cast(replace(k.POCPROC, ',', '.') as double) as pref_pct,
      (k.MANDAT='A') as elected, try_cast(k.PORADIMAND as int) as mandate_order, try_cast(k.PORADINAHR as int) as substitute_order,
      null::bigint as list_votes, null::double as list_pct, null::int as list_mandates, null::int as unit_seats,
      k.source_url, k.fetched_at
    from staging.volby_{e}_reg_psrk k
    left join staging.volby_{e}_reg_psrkl l on l.KSTRANA=k.KSTRANA
    left join staging.volby_{e}_cis_psvolkr v on v.VOLKRAJ=k.VOLKRAJ
    """


def kz_sql(e: str, date: str) -> str:
    return f"""
    select '{e}' as election_id, 'regional' as election_type, date '{date}' as election_date,
      'region' as unit_type, k.KRZAST as unit_code, c.NAZEVKRZ as unit_name, null as municipality_code, null as unit_subdistrict,
      k.KSTRANA as list_no, l.NAZEVCELK as list_name, l.ZKRATKAK8 as list_abbr, l.VSTRANA as list_party_code,
      try_cast(k.PORCISLO as int) as list_position,
      k.JMENO as first_name, k.PRIJMENI as last_name, k.TITULPRED as title_before, k.TITULZA as title_after,
      try_cast(k.VEK as int) as age, k.POVOLANI as occupation, k.BYDLISTEN as residence,
      k.PSTRANA as member_party_code, k.NSTRANA as nominating_party_code, k.PLATNOST as validity,
      try_cast(k.POCHLASU as bigint) as pref_votes, try_cast(replace(k.POCPROC, ',', '.') as double) as pref_pct,
      (k.MANDAT='A') as elected, try_cast(k.PORADIMAND as int) as mandate_order, try_cast(k.PORADINAHR as int) as substitute_order,
      null::bigint as list_votes, null::double as list_pct, null::int as list_mandates, try_cast(c.MANDATYKRZ as int) as unit_seats,
      k.source_url, k.fetched_at
    from staging.volby_{e}_reg_kzrk k
    left join staging.volby_{e}_reg_kzrkl l on l.KRZAST=k.KRZAST and l.KSTRANA=k.KSTRANA
    left join staging.volby_{e}_cis_kzciskr c on c.KRZAST=k.KRZAST
    """


def se_sql(e: str, date: str, con) -> str:
    obv = f"staging.volby_{e}_cis_secobv" if exists(con, f"volby_{e}_cis_secobv") else "staging.volby_se2026_cis_secobv"
    return f"""
    select '{e}' as election_id, 'senate' as election_type, date '{date}' as election_date,
      'senate_district' as unit_type, k.OBVOD as unit_code, o.NAZEV_OBV as unit_name, null as municipality_code, null as unit_subdistrict,
      k.CKAND as list_no, k.NAZEV_VS as list_name, null as list_abbr, k.VSTRANA as list_party_code,
      null::int as list_position,
      k.JMENO as first_name, k.PRIJMENI as last_name, k.TITULPRED as title_before, k.TITULZA as title_after,
      try_cast(k.VEK as int) as age, k.POVOLANI as occupation, k.BYDLISTEN as residence,
      k.PSTRANA as member_party_code, k.NSTRANA as nominating_party_code, k.PLATNOST as validity,
      greatest(coalesce(try_cast(k.HLASY_K1 as bigint),0), coalesce(try_cast(k.HLASY_K2 as bigint),0)) as pref_votes,
      try_cast(replace(coalesce(nullif(k.PROC_K2,'0'), k.PROC_K1), ',', '.') as double) as pref_pct,
      (k.ZVOLEN_K1='1' or k.ZVOLEN_K2='1') as elected, null::int as mandate_order, null::int as substitute_order,
      null::bigint as list_votes, null::double as list_pct, null::int as list_mandates, 1 as unit_seats,
      k.source_url, k.fetched_at
    from staging.volby_{e}_reg_serk k
    left join {obv} o on o.OBVOD=k.OBVOD
    """


def ep_sql(e: str, date: str) -> str:
    return f"""
    select '{e}' as election_id, 'european' as election_type, date '{date}' as election_date,
      'country' as unit_type, 'CZ' as unit_code, 'Česko' as unit_name, null as municipality_code, null as unit_subdistrict,
      k.ESTRANA as list_no, l.NAZEVCELK as list_name, l.ZKRATKAE8 as list_abbr, l.VSTRANA as list_party_code,
      try_cast(k.PORCISLO as int) as list_position,
      k.JMENO as first_name, k.PRIJMENI as last_name, k.TITULPRED as title_before, k.TITULZA as title_after,
      try_cast(k.VEK as int) as age, k.POVOLANI as occupation, k.BYDLISTEN as residence,
      k.PSTRANA as member_party_code, k.NSTRANA as nominating_party_code, k.PLATNOST as validity,
      try_cast(k.POCHLASU as bigint) as pref_votes, try_cast(replace(k.POCPROC, ',', '.') as double) as pref_pct,
      (k.MANDAT='A') as elected, try_cast(k.PORADIMAND as int) as mandate_order, try_cast(k.PORADINAHR as int) as substitute_order,
      null::bigint as list_votes, null::double as list_pct, try_cast(l.POCMANDCR as int) as list_mandates, 21 as unit_seats,
      k.source_url, k.fetched_at
    from staging.volby_{e}_reg_eprk k
    left join staging.volby_{e}_reg_eprkl l on l.ESTRANA=k.ESTRANA
    """


def build() -> dict:
    con = lh.duck()
    register(con)
    lh.write("core", "election", pa.table({
        "election_id": [e[0] for e in ELECTIONS], "election_type": [e[1] for e in ELECTIONS],
        "election_date": [e[2] for e in ELECTIONS], "label": [e[3] for e in ELECTIONS], "source_url": [e[4] for e in ELECTIONS]}))
    parts, missing = [], []
    for e, typ, date, _, _ in ELECTIONS:
        reg = {"municipal": "kvrk", "chamber": "psrk", "regional": "kzrk", "senate": "serk", "european": "eprk"}[typ]
        if not exists(con, f"volby_{e}_reg_{reg}"):
            missing.append(e)
            continue
        sql = {"municipal": kv_sql, "chamber": ps_sql, "regional": kz_sql, "european": ep_sql}.get(typ)
        parts.append(se_sql(e, date, con) if typ == "senate" else sql(e, date))
    union = "\nunion all by name\n".join(parts)
    t = con.sql(f"""
      with u as ({union})
      select u.*, normkey(first_name || ' ' || last_name) as name_key,
             year(election_date) - age - 1 as birth_year_lo, year(election_date) - age as birth_year_hi,
             reskey(residence) as residence_key,
             md5(election_id || '|' || unit_code || '|' || coalesce(unit_subdistrict,'') || '|' || list_no || '|' || coalesce(cast(list_position as varchar), '') || '|' || first_name || '|' || last_name) as candidacy_id
      from u
    """)
    t = lh.tbl(t)
    lh.write("core", "candidacy", t)
    return {"elections": len(ELECTIONS), "candidacies": t.num_rows, "missing": missing}


if __name__ == "__main__":
    print(build())
