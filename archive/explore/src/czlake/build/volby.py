"""Stage volby.cz open-data CSV registries (csv_od = UTF-8) into Iceberg staging tables."""
from __future__ import annotations

import json
from pathlib import Path

from .. import lakehouse as lh
from ..paths import RAW

BASE = "https://volby.gov.cz/opendata"


def _manifest() -> list[dict]:
    return [json.loads(l) for l in (RAW / "_manifest.jsonl").read_text().splitlines() if l.strip()]


def stage_zip_dir(election: str, zip_name: str, tables: list[str] | None = None, prefix: str = "") -> list[str]:
    """Stage every csv in <raw>/volby_<election>/<zip>_unz/csv_od as staging.volby_<election>_<prefix><table>."""
    src_dir = RAW / f"volby_{election}" / (Path(zip_name).stem + "_unz") / "csv_od"
    m = [r for r in _manifest() if r["path"].endswith(zip_name)][-1]
    con = lh.duck()
    done = []
    for csv in sorted(src_dir.glob("*.csv")):
        t = csv.stem.lower()
        if tables and t not in tables:
            continue
        rel = con.sql(f"""select *, '{m['source_url']}' as source_url, '{m['fetched_at']}' as fetched_at,
                          '{csv.name}' as source_file
                          from read_csv('{csv}', all_varchar=true, header=true)""").arrow()
        name = f"volby_{election}_{prefix}{t}"
        lh.write("staging", name, rel)
        done.append(name)
    return done


if __name__ == "__main__":
    import sys
    print(stage_zip_dir(sys.argv[1], sys.argv[2], prefix=(sys.argv[3] if len(sys.argv) > 3 else "")))
