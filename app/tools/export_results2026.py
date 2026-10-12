"""Export official 2026 council results for the snapshot's cities to web/data/results2026.js.

Sources, both from the Czech Statistical Office open data (https://volby.gov.cz/opendata/kv2026/kv2026_opendata.htm):
  - the council results XML per municipality (vysledky_obec_<code>.xml): count status, turnout, valid votes, seats and
    each list's votes, share and seats. While counting runs it carries the share of precincts processed, and the app
    labels it as partial;
  - the candidate registry after processing (KV2026reg<date>_csv.zip, csv_od/kvrk.csv and kvros.csv), filled once the
    whole country is counted: every candidate's votes, share of the list's votes, elected flag, seat order, substitute
    order and the preference-vote flag. Column meanings: https://volby.gov.cz/opendata/kv2026/KV2026regPopis.htm.

A vote for a whole list counts for each of its candidates, so a candidate's votes are not preference votes only.

Matching (anything that does not match is logged and listed under `match`, never credited):
  - lists: the snapshot list id `kv2026:<municipality>:<code>` ends in the official list code OSTRANA. The XML names a
    list by ballot position and VSTRANA; the registry list file translates the ballot position to OSTRANA and must agree
    on VSTRANA. Without the registry the XML's VSTRANA is used, which equals OSTRANA for party lists but not for every
    local list. The ballot position alone never decides;
  - candidates: municipality + OSTRANA + list position (PORCISLO), confirmed by the name without case or accents.
    Withdrawn candidacies (PLATNOST=N) are skipped and do not take a rank;
  - while the registry has no results yet (a partial count), elected members come from the XML by list and position,
    confirmed by name, and everyone else stays without a result.

    uv run --offline python tools/export_results2026.py --snapshot web/data/real.js --out web/data/results2026.js
    uv run --offline python tools/export_results2026.py --snapshot ... --out ... --source-dir <xml folder> --registry-dir <csv folder>
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

URL = "https://volby.gov.cz/appdata/kv2026/20261009/odata/zastup/vysledky_obec_{code}.xml"
REGISTRY_URL = "https://volby.gov.cz/opendata/kv2026/KV2026reg20261011_csv.zip"
# the CSU results page for one council; a list's page appends ____<ballot position>
PAGE_URL = "https://volby.gov.cz/app/kv2026/cs/20261009/results/!___{region}_{district}_{code}"
NS = {"kv": "http://www.volby.cz/kv/"}
SOURCE = "Czech Statistical Office, volby.gov.cz open data (KV2026 council results XML and candidate registry)"


def num(value: str | None) -> float | None:
    """Czech or plain decimals ('44,10', '.42') to float; empty or malformed values become None."""
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


# ---------- candidate registry (kvrk.csv candidates, kvros.csv lists) ----------

def read_registry(files: dict[str, str], city_ids: set[str]) -> dict:
    """Registry rows for the given councils: lists by ballot position, candidates by (OSTRANA, PORCISLO).

    `files` maps 'kvrk' and 'kvros' to CSV text (comma-separated with a header, the csv_od variant)."""
    reg = {"lists": defaultdict(dict), "cands": defaultdict(lambda: defaultdict(list)), "district": {}, "has_results": defaultdict(bool)}
    for row in csv.DictReader(io.StringIO(files["kvros"])):
        cid = row["KODZASTUP"]
        if cid in city_ids:
            # several districts (COBVODU) would repeat ballot positions; keep them apart so they never match silently
            reg["lists"][cid].setdefault(row["POR_STR_HL"], []).append(row)
            reg["district"][cid] = row["OKRES"]
    for row in csv.DictReader(io.StringIO(files["kvrk"])):
        cid = row["KODZASTUP"]
        if cid in city_ids:
            reg["cands"][cid][(row["OSTRANA"], row["PORCISLO"])].append(row)
            if row["MANDAT"] == "A":  # filled only after the whole country is processed
                reg["has_results"][cid] = True
    return reg


def registry_files(source: Path | None, log=print) -> dict[str, str]:
    """CSV text from a folder (with kvrk.csv/kvros.csv, or a csv_od/ subfolder) or, when None, the official zip."""
    if source is not None:
        folder = source / "csv_od" if (source / "csv_od").is_dir() else source
        return {name: (folder / f"{name}.csv").read_text(encoding="utf-8") for name in ("kvrk", "kvros")}
    log(f"registry: downloading {REGISTRY_URL}")
    with zipfile.ZipFile(io.BytesIO(fetch(REGISTRY_URL))) as zf:
        return {name: zf.read(f"csv_od/{name}.csv").decode("utf-8") for name in ("kvrk", "kvros")}


def ballot_codes(reg: dict | None, city_id: str) -> dict | None:
    """Ballot position -> (OSTRANA, VSTRANA) for one council, from the registry list file; None without a registry."""
    if not reg or city_id not in reg["lists"]:
        return None
    return {ballot: (rows[0]["OSTRANA"], rows[0]["VSTRANA"]) for ballot, rows in reg["lists"][city_id].items() if len(rows) == 1}


def match_candidates(snap: dict, city_id: str, reg: dict) -> tuple[dict, list]:
    """Every snapshot candidate in one city to its registry result, plus the ones that did not match and why."""
    rows = reg["cands"].get(city_id, {})
    # rank by votes within each list among valid candidacies; equal votes share a rank
    by_list: dict[str, list[int]] = defaultdict(list)
    seats: dict[str, int] = defaultdict(int)
    for (code, _pos), found in rows.items():
        for r in found:
            if r["PLATNOST"] == "A":
                by_list[code].append(count(r["POCHLASU"]))
                seats[code] += r["MANDAT"] == "A"
    ranked = {code: sorted(v, reverse=True) for code, v in by_list.items()}
    out, unmatched = {}, []
    for cand in (c for c in snap["cands"] if c["city_id"] == city_id):
        code, pos = cand["list_id"].rsplit(":", 1)[1], str(cand["position"])
        found = rows.get((code, pos), [])
        reason = None
        if not found:
            reason = "no registry row for this list code and position"
        elif len(found) > 1:
            reason = "several registry rows (electoral districts) for this list code and position"
        elif fold(f"{found[0]['JMENO']} {found[0]['PRIJMENI']}") != fold(cand["name"]):
            reason = f"name differs: registry has {found[0]['JMENO']} {found[0]['PRIJMENI']}"
        elif found[0]["PLATNOST"] != "A":
            reason = "candidacy withdrawn or invalid (PLATNOST=N)"
        if reason:
            unmatched.append({"id": cand["id"], "name": cand["name"], "list_id": cand["list_id"], "position": cand["position"], "reason": reason})
            continue
        r = found[0]
        votes, elected = count(r["POCHLASU"]), r["MANDAT"] == "A"
        rec = {"votes": votes, "pct": num(r["POCPROCVSE"]), "rank": ranked[code].index(votes) + 1, "elected": elected}
        if elected and count(r["PORADIMAND"]):
            rec["seat"] = count(r["PORADIMAND"])  # order in which the list's seats went to its candidates
        if not elected and count(r["PORADINAHR"]):
            rec["sub"] = count(r["PORADINAHR"])  # substitute order on the list
        if r["PRESKOCENI"] == "A":
            rec["pref"] = True  # met the preference-vote condition to move ahead of the list order
        if elected and int(pos) > seats[code]:
            rec["moved_up"] = True  # elected from below the list's seat count, on votes
        out[cand["id"]] = rec
    return out, unmatched


# ---------- council results XML ----------

def parse(xml_bytes: bytes, city_id: str, lists_by_code: dict, cands_by_list_pos: dict, url: str | None = None,
          codes: dict | None = None) -> tuple[dict | None, dict]:
    """One city's results file to (city record, elected members by candidate id).

    `codes` (ballot position -> (OSTRANA, VSTRANA) from the registry) maps lists exactly; without it, VSTRANA is used."""
    root = ET.fromstring(xml_bytes)
    obec = root.find("kv:OBEC", NS)
    if obec is None:
        return None, {}
    result = obec.find("kv:VYSLEDEK", NS)
    turnout = result.find("kv:UCAST", NS) if result is not None else None
    t = turnout.attrib if turnout is not None else {}
    out = {
        "counted": obec.get("JE_SPOCTENO") in ("true", "1"),  # xs:boolean; the live feed sends 0/1
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
        ballot, vstrana = party.get("POR_STR_HLAS_LIST"), party.get("VSTRANA") or ""
        if codes is not None:
            ostrana, reg_vstrana = codes.get(ballot, (None, None))
            code = ostrana if reg_vstrana == vstrana else None  # the registry and the XML must name the same list
        else:
            code = vstrana or party.get("OSTRANA") or ""
        list_id = lists_by_code.get(code or "")
        row = {"name": party.get("NAZEV_STRANY"), "votes": count(party.get("HLASY")), "pct": num(party.get("HLASY_PROC")),
               "seats": count(party.get("ZASTUPITELE_POCET")), "matched": bool(list_id)}
        if ballot:
            row["ballot"] = int(ballot)
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
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def cross_check(city: dict, cid: str, reg: dict, people: dict, xml_elected: dict, lists_by_code: dict) -> list[str]:
    """Disagreements between the registry and the XML for one city (both are official; any difference is reported)."""
    issues = []
    for rows in reg["lists"].get(cid, {}).values():
        r = rows[0]
        x = city["lists"].get(lists_by_code.get(r["OSTRANA"], ""))
        if x and (x["votes"] != count(r["HLASY_STR"]) or x["seats"] != count(r["MAND_STR"])):
            issues.append(f"list {r['OSTRANA']}: XML {x['votes']} votes/{x['seats']} seats, registry {r['HLASY_STR']}/{r['MAND_STR']}")
    reg_elected = {k for k, v in people.items() if v["elected"]}
    if set(xml_elected) != reg_elected:
        issues.append(f"elected differ: {len(set(xml_elected) - reg_elected)} only in XML, {len(reg_elected - set(xml_elected))} only in registry")
    for k, v in xml_elected.items():
        if k in people and people[k]["votes"] != v["votes"]:
            issues.append(f"{k}: XML {v['votes']} votes, registry {people[k]['votes']}")
    seats = sum(x["seats"] for x in city["lists"].values())
    if city["counted"] and seats != city["seats_total"]:
        issues.append(f"list seats add up to {seats}, council has {city['seats_total']}")
    return issues


def build(snap: dict, source_dir: Path | None = None, url_template: str = URL, log=print, registry: dict | None = None) -> dict:
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": SOURCE,
               "registry_url": REGISTRY_URL if registry else None, "cities": {}, "candidates": {}, "match": {}}
    for city in snap["cities"]:
        cid = city["id"]
        url = url_template.format(code=cid)
        try:
            data = (source_dir / f"vysledky_obec_{cid}.xml").read_bytes() if source_dir else fetch(url)
        except Exception as exc:  # keep the other cities when one file is not published yet
            log(f"{city['name']}: not available ({type(exc).__name__})")
            continue
        lists, cands = city_index(snap, cid)
        parsed, xml_elected = parse(data, cid, lists, cands, url, ballot_codes(registry, cid))
        if not parsed:
            log(f"{city['name']}: no council in the results file")
            continue
        district = registry and registry["district"].get(cid)
        if district:
            parsed["page_url"] = PAGE_URL.format(region=district[:2] + "00", district=district, code=cid)
        n_snap = sum(1 for c in snap["cands"] if c["city_id"] == cid)
        unmatched_lists = sorted(k for k in parsed["lists"] if k.startswith("unmatched:"))
        missing_lists = sorted(set(lists.values()) - set(parsed["lists"]))
        if registry and registry["has_results"].get(cid):
            people, unmatched = match_candidates(snap, cid, registry)
            parsed["people"] = "all"  # every matched candidate has a result
            issues = cross_check(parsed, cid, registry, people, xml_elected, lists)
        else:
            people = {k: dict(v, elected=True) for k, v in xml_elected.items()}
            unmatched, issues = [], []
            parsed["people"] = "elected"  # only elected members are known; the rest have no result yet
        payload["cities"][cid] = parsed
        payload["candidates"].update(people)
        n_el = sum(1 for v in people.values() if v["elected"])
        payload["match"][cid] = {"snapshot_candidates": n_snap, "matched": len(people), "elected": n_el,
                                 "unmatched": unmatched, "lists_unmatched": unmatched_lists, "lists_missing": missing_lists, "issues": issues}
        log(f"{city['name']}: {'final' if parsed['counted'] else str(parsed['precincts_pct']) + '% precincts'}, "
            f"{len(parsed['lists'])} lists ({len(unmatched_lists)} unmatched, {len(missing_lists)} snapshot lists missing), "
            f"{len(people)}/{n_snap} candidates matched ({parsed['people']}), {n_el} elected of {parsed['seats_total']} seats"
            + (f", {len(unmatched)} unmatched" if unmatched else "") + (f", {len(issues)} cross-check issues" if issues else ""))
        for u in unmatched:
            log(f"  unmatched {u['name']} ({u['list_id']} #{u['position']}): {u['reason']}")
        for i in issues:
            log(f"  cross-check: {i}")
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
    ap.add_argument("--registry-dir", type=Path, help="folder with the registry's kvrk.csv and kvros.csv (or csv_od/); default: download the official zip")
    ap.add_argument("--no-registry", action="store_true", help="results XML only (elected members, while the registry has no results)")
    args = ap.parse_args()
    snap = load_snapshot(args.snapshot)
    registry = None
    if not args.no_registry:
        registry = read_registry(registry_files(args.registry_dir), {c["id"] for c in snap["cities"]})
    payload = build(snap, args.source_dir, args.url, registry=registry)
    total = sum(m["snapshot_candidates"] for m in payload["match"].values())
    print(f"total: {sum(m['matched'] for m in payload['match'].values())}/{total} candidates matched, "
          f"{sum(m['elected'] for m in payload['match'].values())} elected, {len(payload['cities'])}/{len(snap['cities'])} cities")
    write(payload, args.out)


if __name__ == "__main__":
    main()
