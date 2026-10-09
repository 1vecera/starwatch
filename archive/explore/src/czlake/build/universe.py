"""M1: the 100 most populous municipalities at 1 Jan 2026 (ČSÚ OBY02A / table OBY02AT02)."""
from __future__ import annotations

import json

from .. import lakehouse as lh
from ..paths import RAW

CSU_URL = "https://data.csu.gov.cz/opendata/sady/OBY02A/distribuce/csv"
CSU_TABLE_URL = "https://data.csu.gov.cz/datastat/data/VYBER/OBY02AT02"


def manifest_row(path_suffix: str) -> dict:
    rows = [json.loads(l) for l in (RAW / "_manifest.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["path"].endswith(path_suffix)]
    return rows[-1]


def build() -> None:
    m = manifest_row("csu_oby02a/csv")
    con = lh.duck()
    p = RAW / "csu_oby02a" / "csv"
    # staging: municipality population, all years with 1 Jan state, total sex
    st = con.sql(f"""
        select UZ01234596C as municipality_code,
               "Všechna území" as municipality_label,
               cast(Roky as int) as year,
               make_date(cast(Roky as int),1,1) as reference_date,
               cast(Hodnota as bigint) as population,
               '{CSU_URL}' as source_url, '{CSU_TABLE_URL}' as source_table_url,
               '{m['fetched_at']}' as fetched_at
        from read_csv('{p}', all_varchar=true)
        where IndicatorType='2406P' and "Pohlaví"='Celkem'
          and regexp_matches(UZ01234596C, '^[0-9]{{6}}$')
    """).arrow()
    lh.write("staging", "csu_population_1jan", st)
    con = lh.duck()
    top = con.sql("""
        with y as (select * from staging.csu_population_1jan where year=2026),
        r as (select *, row_number() over (order by population desc, municipality_code asc) as population_rank,
                     regexp_replace(municipality_label, ' \\(okr\\. [^)]*\\)$', '') as name
              from y),
        prev as (select municipality_code, population as population_2025 from staging.csu_population_1jan where year=2025)
        select r.municipality_code, r.name, r.municipality_label, r.population, r.population_rank,
               prev.population_2025, r.reference_date, r.source_url, r.source_table_url, r.fetched_at,
               r.population_rank <= 100 as in_top100
        from r left join prev using (municipality_code)
        where r.population_rank <= 110
        order by population_rank
    """).arrow()
    lh.write("core", "municipality_top", top)


if __name__ == "__main__":
    build()
    con = lh.duck()
    print(con.sql("select population_rank, municipality_code, name, population from core.municipality_top where population_rank<=3 or population_rank between 98 and 102 order by 1").fetchall())
