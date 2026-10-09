"""The 2026 results importer reads the CSU council XML and matches lists by official code, never by ballot position."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from export_results2026 import build, parse, write

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# A synthetic snapshot shaped like real.js: list ids end in the official list code (VSTRANA), not the ballot number.
SNAP = {
    "cities": [{"id": "554782", "name": "Praha"}, {"id": "582786", "name": "Brno"}],
    "lists": [
        {"id": "kv2026:554782:1", "city_id": "554782", "name": "Test"},
        {"id": "kv2026:554782:9", "city_id": "554782", "name": "Ballot nine, a different list"},
    ],
    "cands": [
        {"id": "c-a-b", "name": "A B", "list_id": "kv2026:554782:1", "city_id": "554782", "position": 1},
        {"id": "c-other", "name": "Somebody Else", "list_id": "kv2026:554782:9", "city_id": "554782", "position": 1},
    ],
}


class ResultsImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.xml = (FIXTURES / "vysledky_obec_554782.xml").read_bytes()

    def test_city_totals_and_partial_count(self) -> None:
        city, _ = parse(self.xml, "554782", {"1": "kv2026:554782:1", "9": "kv2026:554782:9"}, {})
        self.assertFalse(city["counted"])
        self.assertEqual(city["observed_at"], "2026-10-10T18:00:00")
        self.assertEqual((city["precincts_pct"], city["turnout_pct"], city["valid_votes"], city["seats_total"]), (50.0, 44.1, 123456, 65))
        self.assertIn("vysledky_obec_554782.xml", city["source_url"])

    def test_lists_match_by_official_code_not_ballot_position(self) -> None:
        lists = {"1": "kv2026:554782:1", "9": "kv2026:554782:9"}
        city, _ = parse(self.xml, "554782", lists, {})
        self.assertEqual(city["lists"]["kv2026:554782:1"], {"name": "Test", "votes": 1000, "pct": 25.5, "seats": 17, "matched": True})
        # "Other" is ballot 9 with code 2: it must not be credited to the list whose code is 9
        self.assertNotIn("kv2026:554782:9", city["lists"])
        self.assertEqual(city["lists"]["unmatched:9"], {"name": "Other", "votes": 10, "pct": 0.5, "seats": 0, "matched": False})

    def test_elected_by_position_with_name_check(self) -> None:
        cands = {("kv2026:554782:1", "1"): {"id": "c-a-b", "name": "A B"}}
        _, elected = parse(self.xml, "554782", {"1": "kv2026:554782:1"}, cands)
        self.assertEqual(elected, {"c-a-b": {"votes": 999, "pct": 1.2}})
        _, elected = parse(self.xml, "554782", {"1": "kv2026:554782:1"}, {("kv2026:554782:1", "1"): {"id": "x", "name": "Not The Same"}})
        self.assertEqual(elected, {})

    def test_build_skips_unpublished_cities_and_writes_the_window_global(self) -> None:
        logs: list[str] = []
        payload = build(SNAP, FIXTURES, log=logs.append)
        self.assertEqual(list(payload["cities"]), ["554782"])
        self.assertTrue(any(line.startswith("Brno: not available") for line in logs))
        self.assertEqual(payload["elected"], {"c-a-b": {"votes": 999, "pct": 1.2}})
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "results2026.js"
            write(payload, out)
            text = out.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("window.SW_RESULTS2026 = "))
            self.assertEqual(json.loads(text[text.index("{"): text.rindex("}") + 1])["cities"]["554782"]["seats_total"], 65)


if __name__ == "__main__":
    unittest.main()
