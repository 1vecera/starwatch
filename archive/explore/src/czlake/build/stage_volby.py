"""Stage every landed volby.cz CSV table into Iceberg: staging.volby_<election>_<kind>_<table>.

kind is reg (candidate registries), cis (code lists) or data (results). When an election
has several zips of one kind (e.g. a post-scrutiny re-issue), the latest one wins.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .. import lakehouse as lh
from ..paths import RAW


def kind_of(zip_stem: str) -> str:
    s = zip_stem.lower()
    if "cisel" in s:
        return "cis"
    if "reg" in s:
        return "reg"
    return "data"


def plan() -> dict[tuple[str, str], Path]:
    best: dict[tuple[str, str], tuple[str, Path]] = {}
    for d in sorted(RAW.glob("volby_*/*_unz")):
        election = d.parent.name.removeprefix("volby_")
        stem = d.name.removesuffix("_unz")
        k = kind_of(stem)
        date = (re.findall(r"(20\d{6})", stem) or ["0"])[-1]
        src = d / "csv_od" if (d / "csv_od").exists() else d / "csv" if (d / "csv").exists() else d
        cur = best.get((election, k))
        if cur is None or date > cur[0]:
            best[(election, k)] = (date, src)
    return {key: v[1] for key, v in best.items()}


def manifest_for(zip_stem: str) -> dict:
    rows = [json.loads(l) for l in (RAW / "_manifest.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if Path(r["path"]).stem == zip_stem]
    return rows[-1] if rows else {"source_url": None, "fetched_at": None}


def stage(only: list[str] | None = None) -> list[str]:
    done = []
    con = lh.duck()
    for (election, k), src in sorted(plan().items()):
        if only and election not in only:
            continue
        zip_stem = (src.parent if src.name in ("csv_od", "csv") else src).name.removesuffix("_unz")
        m = manifest_for(zip_stem)
        utf8 = src.name == "csv_od"
        for csv in sorted(src.glob("*.csv")):
            t = csv.stem.lower()
            name = f"volby_{election}_{k}_{t}"
            path = csv
            if not utf8:
                raw = csv.read_bytes()
                try:
                    raw.decode("utf-8")
                except UnicodeDecodeError:
                    tmp = RAW / "_transcoded" / election / csv.name
                    tmp.parent.mkdir(parents=True, exist_ok=True)
                    tmp.write_text(raw.decode("cp1250", "replace"), encoding="utf-8")
                    path = tmp
            first = path.open(encoding="utf-8", errors="replace").readline()
            sep = ";" if first.count(";") > first.count(",") else ","
            try:
                rel = con.sql(f"""select *, '{m['source_url']}' as source_url, '{m['fetched_at']}' as fetched_at,
                                  '{csv.name}' as source_file
                                  from read_csv('{path}', all_varchar=true, header=true, delim='{sep}', quote='"', strict_mode=false)""").arrow()
                lh.write("staging", name, rel)
                done.append(name)
            except Exception as ex:  # noqa: BLE001
                print("FAIL", name, str(ex)[:200], flush=True)
    return done


if __name__ == "__main__":
    out = stage(sys.argv[1:] or None)
    print(len(out), "tables")
