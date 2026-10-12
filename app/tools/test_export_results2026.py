"""The 2026 results importer reads the CSU council XML and candidate registry, matches lists by official code (never by
ballot position alone) and candidates by list code, position and name, and reports whatever does not match."""

from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import export_results2026
from export_results2026 import ballot_codes, build, parse, read_registry, registry_files, write

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# A synthetic snapshot shaped like real.js: list ids end in the official list code (OSTRANA), not the ballot number.
SNAP = {
    "cities": [{"id": "554782", "name": "Praha"}, {"id": "582786", "name": "Brno"}],
    "lists": [
        {"id": "kv2026:554782:1", "city_id": "554782", "name": "Test"},
        {"id": "kv2026:554782:9", "city_id": "554782", "name": "Ballot nine, a different list"},
        {"id": "kv2026:554782:903", "city_id": "554782", "name": "Local list, VSTRANA 80"},
    ],
    "cands": [
        {"id": "c-a-b", "name": "A B", "list_id": "kv2026:554782:1", "city_id": "554782", "position": 1},
        {"id": "c-c-d", "name": "C D", "list_id": "kv2026:554782:1", "city_id": "554782", "position": 2},
        {"id": "c-e-f", "name": "E F", "list_id": "kv2026:554782:1", "city_id": "554782", "position": 3},
        {"id": "c-renamed", "name": "Not I J", "list_id": "kv2026:554782:1", "city_id": "554782", "position": 5},
        {"id": "c-missing", "name": "Nobody", "list_id": "kv2026:554782:1", "city_id": "554782", "position": 6},
        {"id": "c-other", "name": "Somebody Else", "list_id": "kv2026:554782:9", "city_id": "554782", "position": 1},
        {"id": "c-local", "name": "Katerina La", "list_id": "kv2026:554782:903", "city_id": "554782", "position": 1},
    ],
}
LISTS = {"1": "kv2026:554782:1", "9": "kv2026:554782:9", "903": "kv2026:554782:903"}


def registry(**edit) -> dict:
    files = registry_files(FIXTURES / "registry")
    if edit.get("no_results"):  # the registry as published before the count: no votes, nobody elected
        rows = list(csv.DictReader(io.StringIO(files["kvrk"])))
        for r in rows:
            r.update(POCHLASU="0", MANDAT="N", PORADIMAND="0", PORADINAHR="0", PRESKOCENI="N")
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
        files["kvrk"] = buf.getvalue()
    return read_registry(files, {"554782", "582786"})


class ResultsImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.xml = (FIXTURES / "vysledky_obec_554782.xml").read_bytes()

    def test_city_totals_and_partial_count(self) -> None:
        city, _ = parse(self.xml, "554782", LISTS, {})
        self.assertFalse(city["counted"])
        self.assertEqual(city["observed_at"], "2026-10-10T18:00:00")
        self.assertEqual((city["precincts_pct"], city["turnout_pct"], city["valid_votes"], city["seats_total"]), (50.0, 44.1, 123456, 65))
        self.assertIn("vysledky_obec_554782.xml", city["source_url"])

    def test_counted_flag_reads_xml_boolean(self) -> None:
        for raw, expected in (("1", True), ("true", True), ("0", False), ("false", False)):
            xml = self.xml.replace(b'JE_SPOCTENO="false"', f'JE_SPOCTENO="{raw}"'.encode())
            city, _ = parse(xml, "554782", {}, {})
            self.assertIs(city["counted"], expected, raw)

    def test_lists_match_by_official_code_not_ballot_position(self) -> None:
        city, _ = parse(self.xml, "554782", LISTS, {})
        self.assertEqual(city["lists"]["kv2026:554782:1"], {"name": "Test", "votes": 1000, "pct": 25.5, "seats": 17, "matched": True, "ballot": 1})
        # "Other" is ballot 9 with code 2: it must not be credited to the list whose code is 9
        self.assertNotIn("kv2026:554782:9", city["lists"])
        self.assertEqual(city["lists"]["unmatched:9"]["name"], "Other")
        # without the registry a local list (VSTRANA 80, OSTRANA 903) cannot be placed, so it stays unmatched
        self.assertNotIn("kv2026:554782:903", city["lists"])
        self.assertIn("unmatched:3", city["lists"])

    def test_registry_translates_ballot_position_to_official_code(self) -> None:
        codes = ballot_codes(registry(), "554782")
        self.assertEqual(codes, {"1": ("1", "1"), "3": ("903", "80"), "9": ("2", "2")})
        city, _ = parse(self.xml, "554782", LISTS, {}, codes=codes)
        self.assertEqual(city["lists"]["kv2026:554782:903"]["votes"], 400)
        self.assertIn("unmatched:9", city["lists"])  # code 2 is not a snapshot list; still never credited to code 9
        # the XML and the registry must agree on VSTRANA, otherwise the list stays unmatched
        city, _ = parse(self.xml, "554782", LISTS, {}, codes={**codes, "3": ("903", "81")})
        self.assertIn("unmatched:3", city["lists"])

    def test_elected_by_position_with_name_check(self) -> None:
        cands = {("kv2026:554782:1", "1"): {"id": "c-a-b", "name": "A B"}}
        _, elected = parse(self.xml, "554782", LISTS, cands)
        self.assertEqual(elected, {"c-a-b": {"votes": 999, "pct": 1.2}})
        _, elected = parse(self.xml, "554782", LISTS, {("kv2026:554782:1", "1"): {"id": "x", "name": "Not The Same"}})
        self.assertEqual(elected, {})

    def test_every_candidate_gets_votes_rank_and_outcome_from_the_registry(self) -> None:
        logs: list[str] = []
        payload = build(SNAP, FIXTURES, log=logs.append, registry=registry())
        people = payload["candidates"]
        self.assertEqual(payload["cities"]["554782"]["people"], "all")
        # elected from position 2 on a list whose registry seats are 1: moved up on votes
        self.assertEqual(people["c-c-d"], {"votes": 1500, "pct": 15.0, "rank": 1, "elected": True, "seat": 1, "pref": True, "moved_up": True})
        # not elected, still with votes; equal votes share a rank; the withdrawn candidacy (#4) takes no rank
        self.assertEqual(people["c-a-b"], {"votes": 999, "pct": 9.99, "rank": 2, "elected": False, "sub": 1})
        self.assertEqual(people["c-e-f"]["rank"], 2)
        self.assertEqual(people["c-local"], {"votes": 350, "pct": 87.5, "rank": 1, "elected": True, "seat": 2})  # name folded
        unmatched = {u["id"]: u["reason"] for u in payload["match"]["554782"]["unmatched"]}
        self.assertEqual(set(unmatched), {"c-renamed", "c-missing", "c-other"})
        self.assertTrue(unmatched["c-renamed"].startswith("name differs"))
        self.assertNotIn("c-renamed", people)
        self.assertEqual(payload["match"]["554782"]["matched"], 4)
        # the XML elects A B while the registry elects C D: both are official, so the difference is reported
        self.assertTrue(any("elected differ" in i for i in payload["match"]["554782"]["issues"]))
        self.assertTrue(any("cross-check" in line for line in logs))
        self.assertEqual(payload["cities"]["554782"]["page_url"], "https://volby.gov.cz/app/kv2026/cs/20261009/results/!___1100_1100_554782")

    def test_before_the_registry_has_results_only_xml_elected_members_count(self) -> None:
        payload = build(SNAP, FIXTURES, log=lambda _: None, registry=registry(no_results=True))
        self.assertEqual(payload["cities"]["554782"]["people"], "elected")
        self.assertEqual(payload["candidates"], {"c-a-b": {"votes": 999, "pct": 1.2, "elected": True},
                                                 "c-local": {"votes": 350, "pct": 87.5, "elected": True}})

    def test_registry_download_reads_the_csv_od_files_from_the_zip(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name in ("kvrk", "kvros"):
                zf.write(FIXTURES / "registry" / f"{name}.csv", f"csv_od/{name}.csv")
                zf.writestr(f"csv/{name}.csv", "semicolon variant, not read")
        with mock.patch.object(export_results2026, "fetch", return_value=buf.getvalue()) as fetch:
            files = registry_files(None, log=lambda _: None)
        fetch.assert_called_once_with(export_results2026.REGISTRY_URL)
        self.assertEqual(files, registry_files(FIXTURES / "registry"))

    def test_build_skips_unpublished_cities_and_writes_the_window_global(self) -> None:
        logs: list[str] = []
        payload = build(SNAP, FIXTURES, log=logs.append)
        self.assertEqual(list(payload["cities"]), ["554782"])
        self.assertTrue(any(line.startswith("Brno: not available") for line in logs))
        self.assertEqual(payload["candidates"], {"c-a-b": {"votes": 999, "pct": 1.2, "elected": True}})
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "results2026.js"
            write(payload, out)
            text = out.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("window.SW_RESULTS2026 = "))
            self.assertEqual(json.loads(text[text.index("{"): text.rindex("}") + 1])["cities"]["554782"]["seats_total"], 65)


if __name__ == "__main__":
    unittest.main()
