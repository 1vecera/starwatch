"""Export official 2026 council results for the snapshot's ten cities to web/data/results2026.js.

Source: the Czech Statistical Office open data, the council results XML that volby.gov.cz publishes while the
votes are counted (https://volby.gov.cz/opendata/kv2026/kv2026_opendata.htm). Partial counts carry the share of
precincts processed, and the app labels them as partial.

Matching:
  - lists by the official list code (VSTRANA in the results XML, the number in the snapshot's list id
    `kv2026:<municipality>:<code>`), never by ballot position, which differs from the code;
  - elected members by list and candidate position (PORADOVE_CISLO), confirmed by the exact name when the XML has one.
Anything that does not match stays in the file as `unmatched:<ballot number>` with its official name.

    uv run --offline python tools/export_results2026.py --snapshot web/data/real.js --out web/data/results2026.js
    uv run --offline python tools/export_results2026.py --snapshot ... --out ... --source-dir <folder with vysledky_obec_<code>.xml>
"""

from __future__ import annotations

import argparse
import json
import os
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

URL = "https://volby.gov.cz/appdata/kv2026/20261009/odata/zastup/vysledky_obec_{code}.xml"
NS = {"kv": "http://www.volby.cz/kv/"}
SOURCE = "Czech Statistical Office, volby.gov.cz open data (KV2026 council results XML)"


def num(value: str | None) -> float | None:
    """Czech decimals ('44,10') to float; empty or malformed values become None."""
    try:
        return float(value.replace(",", ".")) if value not in (None, "") else None
    except ValueError:
        return None


def count(value: str | None) -> int:
    return int(num(value) or 0)


def fold(text: str | None) -> str:
    """Compare names without case, accents or repeated spaces."""
    text = unicodedata.normalize("NFD", text or "")
    return " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).lower().split())


def load_snapshot(path: Path) -> dict:
    """Read `window.SW_RAW = {...};` without executing it."""
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text[text.index("{"): text.rstrip().rstrip(";").rindex("}") + 1])


def city_index(snap: dict, city_id: str) -> tuple[dict, dict]:
    """List ids by official list code, and (list id, position) -> candidate, for one city."""
    lists = {l["id"].rsplit(":", 1)[1]: l["id"] for l in snap["lists"] if l["city_id"] == city_id}
    cands = {(c["list_id"], str(c["position"])): c for c in snap["cands"] if c["city_id"] == city_id}
    return lists, cands


def parse(xml_bytes: bytes, city_id: str, lists_by_code: dict, cands_by_list_pos: dict, url: str | None = None) -> tuple[dict | None, dict]:
    """One city's results file to (city record, elected members by candidate id)."""
    root = ET.fromstring(xml_bytes)
    obec = root.find("kv:OBEC", NS)
    if obec is None:
        return None, {}
    result = obec.find("kv:VYSLEDEK", NS)
    turnout = result.find("kv:UCAST", NS) if result is not None else None
    t = turnout.attrib if turnout is not None else {}
    out = {
        "counted": obec.get("JE_SPOCTENO") == "true",
        "observed_at": root.get("DATUM_CAS_GENEROVANI"),
        "precincts_pct": num(t.get("OKRSKY_ZPRAC_PROC")),
        "turnout_pct": num(t.get("UCAST_PROC")),
        "valid_votes": count(t.get("PLATNE_HLASY")),
        "seats_total": count(obec.get("VOLENO_ZASTUP")),
        "source_url": url or URL.format(code=city_id),
        "lists": {},
    }
    elected: dict = {}
    for party in (result.findall("kv:VOLEBNI_STRANA", NS) if result is not None else []):
        ballot = party.get("POR_STR_HLAS_LIST")
        list_id = lists_by_code.get(party.get("VSTRANA") or party.get("OSTRANA") or "")
        row = {"name": party.get("NAZEV_STRANY"), "votes": count(party.get("HLASY")), "pct": num(party.get("HLASY_PROC")),
               "seats": count(party.get("ZASTUPITELE_POCET")), "matched": bool(list_id)}
        out["lists"][list_id or f"unmatched:{ballot}"] = row
        if not list_id:
            continue
        for member in party.findall("kv:ZASTUPITEL", NS):
            cand = cands_by_list_pos.get((list_id, member.get("PORADOVE_CISLO")))
            xml_name = " ".join(x for x in (member.get("JMENO"), member.get("PRIJMENI")) if x)
            # the position decides; a name in the XML must agree, so a renumbered list never credits the wrong person
            if cand and (not xml_name or fold(xml_name) == fold(cand["name"])):
                elected[cand["id"]] = {"votes": count(member.get("HLASY")), "pct": num(member.get("HLASY_PROC"))}
    return out, elected


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Starwatch (+https://github.com/1vecera/starwatch)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def build(snap: dict, source_dir: Path | None = None, url_template: str = URL, log=print) -> dict:
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": SOURCE, "cities": {}, "elected": {}}
    for city in snap["cities"]:
        cid = city["id"]
        url = url_template.format(code=cid)
        try:
            data = (source_dir / f"vysledky_obec_{cid}.xml").read_bytes() if source_dir else fetch(url)
        except Exception as exc:  # keep the other cities when one file is not published yet
            log(f"{city['name']}: not available ({type(exc).__name__})")
            continue
        lists, cands = city_index(snap, cid)
        parsed, elected = parse(data, cid, lists, cands, url)
        if parsed:
            payload["cities"][cid] = parsed
            payload["elected"].update(elected)
            unmatched = sum(1 for k in parsed["lists"] if k.startswith("unmatched:"))
            log(f"{city['name']}: {parsed['precincts_pct']}% precincts, {len(parsed['lists'])} lists ({unmatched} unmatched), {len(elected)} elected matched")
    return payload


def write(payload: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text("window.SW_RESULTS2026 = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    os.replace(tmp, out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--source-dir", type=Path, help="read vysledky_obec_<code>.xml from this folder instead of downloading")
    ap.add_argument("--url", default=URL, help="URL template with {code} for the municipality code")
    args = ap.parse_args()
    write(build(load_snapshot(args.snapshot), args.source_dir, args.url), args.out)


if __name__ == "__main__":
    main()
