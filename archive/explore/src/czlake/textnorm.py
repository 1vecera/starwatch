"""Name normalisation shared by Python and DuckDB (unaccented, lower-case, single-spaced)."""
from __future__ import annotations

import functools
import re

from unidecode import unidecode


def normkey(s: str | None) -> str | None:
    if s is None:
        return None
    s = unidecode(s).lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@functools.lru_cache(maxsize=1)
def municipality_names() -> frozenset:
    from . import lakehouse as lh
    con = lh.duck()
    rows = con.sql("""select distinct regexp_replace(municipality_label, ' \\(okr\\. [^)]*\\)$', '') from staging.csu_population_1jan where year=2026""").fetchall()
    return frozenset(normkey(r[0]) for r in rows)


_STRIP = [re.compile(r"^(.+?)\s+[IVXLC]+\b.*$"), re.compile(r"^(.+?)\s+\d+.*$"), re.compile(r"^(.+?)\s*-\s*.+$"),
          re.compile(r"^(.+?)\s+-.*$")]


def reskey(s: str | None) -> str | None:
    """Residence -> municipality-level key: 'Praha 5' -> praha, 'Děčín XXVIII-Folknáře' -> decin, keeps 'Frýdek-Místek'."""
    if not s:
        return None
    k = normkey(s)
    names = municipality_names()
    if k in names:
        return k
    for rx in _STRIP:
        m = rx.match(s.strip())
        if m:
            k2 = normkey(m.group(1))
            if k2 in names:
                return k2
    return k


def register(con) -> None:
    con.create_function("normkey", normkey, ["VARCHAR"], "VARCHAR", null_handling="special")
    con.create_function("reskey", reskey, ["VARCHAR"], "VARCHAR", null_handling="special")
