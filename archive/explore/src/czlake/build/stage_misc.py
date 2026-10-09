"""Stage Wikidata (CC0) politicians/parties and psp.cz MP open data into Iceberg staging."""
from __future__ import annotations

import json

import pyarrow as pa

from .. import lakehouse as lh
from ..paths import RAW


def _manifest(path_suffix: str) -> dict:
    rows = [json.loads(l) for l in (RAW / "_manifest.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["path"].endswith(path_suffix)]
    return rows[-1] if rows else {}


def wikidata() -> dict:
    out = {}
    for name in ("cz_politicians", "cz_parties"):
        p = RAW / "wikidata" / f"{name}.json"
        if not p.exists():
            continue
        m = _manifest(f"wikidata/{name}.json")
        d = json.loads(p.read_text())
        rows = []
        for b in d["results"]["bindings"]:
            rows.append({k: v.get("value") for k, v in b.items()} | {"source_url": "https://query.wikidata.org/sparql",
                                                                      "fetched_at": m.get("fetched_at")})
        cols = sorted({k for r in rows for k in r})
        t = pa.table({c: [r.get(c) for r in rows] for c in cols})
        lh.write("staging", f"wikidata_{name}", t)
        out[name] = len(rows)
    return out


def psp() -> dict:
    """psp.cz poslanci.zip: pipe-separated, cp1250, trailing pipe. Columns per the psp.cz open-data docs."""
    base = RAW / "psp_opendata" / "poslanci_unz"
    m = _manifest("psp_opendata/poslanci.zip")
    specs = {
        "osoby": ["id_osoba", "pred", "prijmeni", "jmeno", "za", "narozeni", "pohlavi", "zmena", "umrti"],
        "poslanec": ["id_poslanec", "id_osoba", "id_kraj", "id_kandidatka", "id_obdobi", "web", "ulice", "obec", "psc",
                     "email", "telefon", "fax", "psp_telefon", "facebook", "foto"],
        "organy": ["id_organ", "organ_id_organ", "id_typ_organu", "zkratka", "nazev_organu_cz", "nazev_organu_en",
                   "od_organ", "do_organ", "priorita", "cl_organ_base"],
        "zarazeni": ["id_osoba", "id_of", "cl_funkce", "od_o", "do_o", "od_f", "do_f"],
        "osoba_extra": ["id_osoba", "id_org", "typ", "obvod", "strana", "id_external"],
    }
    out = {}
    for name, cols in specs.items():
        f = base / f"{name}.unl"
        if not f.exists():
            continue
        rows = []
        for line in f.read_bytes().decode("cp1250", "replace").splitlines():
            vals = line.split("|")
            if vals and vals[-1] == "":
                vals = vals[:-1]
            vals = (vals + [None] * len(cols))[:len(cols)]
            rows.append(dict(zip(cols, vals)))
        t = pa.table({c: [r[c] for r in rows] for c in cols} | {
            "source_url": ["https://www.psp.cz/eknih/cdrom/opendata/poslanci.zip"] * len(rows),
            "fetched_at": [m.get("fetched_at")] * len(rows)})
        lh.write("staging", f"psp_{name}", t)
        out[name] = len(rows)
    return out


if __name__ == "__main__":
    print(wikidata())
    print(psp())
