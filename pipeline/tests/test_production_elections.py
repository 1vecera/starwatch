"""Behavior checks for official result semantics, matching ambiguity and provenance."""
from __future__ import annotations
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
if (HERE / 'production_elections.py').exists():
    spec = importlib.util.spec_from_file_location('election_module', HERE / 'production_elections.py')
    elections = importlib.util.module_from_spec(spec); spec.loader.exec_module(elections)
else:
    from czlake import production_elections as elections


def fixture():
    old_list = {'DATUMVOLEB': '20220923', 'KODZASTUP': '123456', 'COBVODU': '1', 'OSTRANA': '53', 'VSTRANA': '53', 'NAZEVCELK': 'Test party', 'ZKRATKAO8': 'TP', 'SLOZENI': '053', 'HLASY_STR': '20', 'PROCHLSTR': '100', 'MAND_STR': '1'}
    old = {'DATUMVOLEB': '20220923', 'KODZASTUP': '123456', 'COBVODU': '1', 'OSTRANA': '53', 'PORCISLO': '1', 'JMENO': 'Jan', 'PRIJMENI': 'Novák', 'VEK': '40', 'POVOLANI': 'učitel', 'BYDLISTEN': 'Test City', 'PSTRANA': '53', 'NSTRANA': '53', 'PLATNOST': 'A', 'POCHLASU': '20', 'POCPROCVSE': '100', 'MANDAT': 'A', 'PORADIMAND': '1', 'PORADINAHR': '0'}
    current = {**old, 'VEK': '44', 'POCHLASU': '0', 'MANDAT': 'N'}; current.pop('DATUMVOLEB')
    new_list = {**old_list}; new_list.pop('DATUMVOLEB')
    raw = {'lists_2022': [(37, old_list)], 'candidates_2022': [(82, old)], 'councils_2022': [(4, {'DATUMVOLEB': '20220923', 'KODZASTUP': '123456', 'COBVODU': '1', 'TYPZASTUP': '1', 'MANDATY': '1'})], 'lists_2026': [(47, new_list)], 'candidates_2026': [(93, current)]}
    entities = [{'entity_id': elections.candidacy_id('kv2026', current), 'kind': 'current_candidacy', 'name': 'Jan Novák', 'area_id': '123456', 'position': 1, 'list_id': 'kv2026:123456:53'}, {'entity_id': 'kv2026:123456:53', 'kind': 'local_list', 'name': 'Test party', 'area_id': '123456'}]
    document = {'schema_version': elections.VERSION, 'area_ids': ['123456'], 'files': {key: {'archive': archive, 'entry': entry} for key, (archive, entry) in elections.FILES.items()}, 'archives': {key: {'source_url': url, 'fetched_at': '2026-10-08T23:50:42+02:00'} for key, url in elections.ARCHIVE_URLS.items()}}
    source_ids = {key: 's1' for key in elections.FILES}
    return document, entities, raw, source_ids


class ElectionResultTests(unittest.TestCase):
    def setUp(self):
        self.doc, self.entities, self.raw, self.sources = fixture()

    def derive(self):
        return elections.derive_rows(self.doc, self.entities, self.raw, self.sources, 's1')

    def candidate_link(self, result):
        return next(x for x in result['entity_election_link'] if x['result_kind'] == 'candidate')

    def test_exact_multiattribute_registry_link_preserves_semantics_and_original_record(self):
        result = self.derive()
        link = self.candidate_link(result)
        self.assertEqual(link['match_status'], 'registry_supported')
        self.assertEqual(link['identity_status'], 'not_independently_resolved')
        candidate = result['election_candidate_result'][0]
        self.assertEqual(candidate['candidate_votes'], 20)
        self.assertTrue(candidate['elected'])
        self.assertEqual(candidate['source_pointer'], '/csv_od/kvrk.csv/records/82')
        self.assertEqual(json.loads(candidate['source_row_key'])['DATUMVOLEB'], '20220923')
        list_link = next(x for x in result['entity_election_link'] if x['result_kind'] == 'list')
        self.assertEqual(list_link['match_status'], 'context_only')
        self.assertEqual(json.loads(list_link['evidence'])['continuity_status'], 'not_established')

    def test_adjusted_percentage_is_not_used_as_raw_vote_share(self):
        self.raw['lists_2022'][0][1]['PROCHLSTR'] = '200'
        result = self.derive()['election_list_result'][0]
        self.assertEqual(result['reported_adjusted_pct'], 200)
        self.assertEqual(result['vote_share_pct'], 100)
        self.assertEqual(result['vote_share_denominator'], 20)

    def test_same_name_with_different_age_residence_or_party_remains_unknown(self):
        for key, value in [('VEK', '20'), ('BYDLISTEN', 'Another City'), ('PSTRANA', '99')]:
            with self.subTest(key=key):
                document, entities, raw, sources = fixture()
                raw['candidates_2022'][0][1][key] = value
                if key == 'PSTRANA': raw['candidates_2022'][0][1]['NSTRANA'] = '80'
                result = elections.derive_rows(document, entities, raw, sources)
                link = self.candidate_link(result)
                self.assertEqual(link['match_status'], 'unknown')
                self.assertIsNone(link['result_id'])
                self.assertIsNotNone(link['unknown_reason'])

    def test_two_consistent_old_records_are_ambiguous_not_arbitrarily_selected(self):
        second = copy.deepcopy(self.raw['candidates_2022'][0][1]); second.update(PORCISLO='2', POCHLASU='0', MANDAT='N')
        self.raw['candidates_2022'].append((83, second))
        link = self.candidate_link(self.derive())
        self.assertEqual(link['match_status'], 'ambiguous')
        self.assertIsNone(link['result_id'])
        self.assertEqual(len(json.loads(link['possible_result_ids'])), 2)

    def test_two_current_records_cannot_claim_one_historical_result(self):
        current = copy.deepcopy(self.raw['candidates_2026'][0][1]); current['PORCISLO'] = '2'
        self.raw['candidates_2026'].append((94, current))
        self.entities.append({**self.entities[0], 'entity_id': elections.candidacy_id('kv2026', current), 'position': 2})
        links = [row for row in self.derive()['entity_election_link'] if row['result_kind'] == 'candidate']
        self.assertEqual({row['match_status'] for row in links}, {'ambiguous'})
        self.assertTrue(all(row['result_id'] is None for row in links))

    def test_changed_coalition_composition_is_not_linked(self):
        self.raw['lists_2026'][0][1]['SLOZENI'] = '053,166'
        link = next(x for x in self.derive()['entity_election_link'] if x['result_kind'] == 'list')
        self.assertEqual(link['match_status'], 'unknown')
        self.assertIsNone(link['result_id'])

    def test_generic_list_code_cannot_establish_continuity(self):
        self.raw['lists_2026'][0][1]['VSTRANA'] = '90'
        self.raw['lists_2022'][0][1]['VSTRANA'] = '90'
        link = next(x for x in self.derive()['entity_election_link'] if x['result_kind'] == 'list')
        self.assertEqual(link['match_status'], 'unknown')

    def test_current_entity_id_cannot_override_name_city_or_ballot_position(self):
        for field, value in [('name', 'A namesake'), ('position', 4), ('list_id', 'kv2026:123456:166')]:
            with self.subTest(field=field):
                document, entities, raw, sources = fixture(); entities[0][field] = value
                with self.assertRaisesRegex(ValueError, 'Active entity'):
                    elections.derive_rows(document, entities, raw, sources)

    def test_candidate_vote_and_elected_count_must_conserve_list_totals(self):
        for field, value in [('POCHLASU', '19'), ('MANDAT', 'N')]:
            with self.subTest(field=field):
                document, entities, raw, sources = fixture(); raw['candidates_2022'][0][1][field] = value
                with self.assertRaisesRegex(ValueError, 'totals disagree'):
                    elections.derive_rows(document, entities, raw, sources)

    def test_other_election_dates_and_other_cities_do_not_leak(self):
        row = copy.deepcopy(self.raw['candidates_2022'][0][1]); row['DATUMVOLEB'] = '20260328'
        self.raw['candidates_2022'].append((99, row))
        row = copy.deepcopy(self.raw['lists_2022'][0][1]); row['KODZASTUP'] = '654321'
        self.raw['lists_2022'].append((100, row))
        result = self.derive()
        self.assertEqual(len(result['election_candidate_result']), 1)
        self.assertEqual(len(result['election_list_result']), 1)

    def test_invalid_official_placeholder_retains_null_age_and_never_matches(self):
        row = copy.deepcopy(self.raw['candidates_2022'][0][1]); row.update(PORCISLO='2', VEK='', PLATNOST='N', POCHLASU='0', MANDAT='N')
        self.raw['candidates_2022'].append((99, row))
        result = self.derive()
        invalid = next(x for x in result['election_candidate_result'] if x['validity'] == 'N')
        self.assertIsNone(invalid['age'])
        self.assertEqual(self.candidate_link(result)['match_status'], 'registry_supported')

    def test_nonofficial_release_or_incomplete_sources_fail_closed(self):
        with self.assertRaises(ValueError): elections.read_sources({'schema_version': elections.VERSION})
        document = copy.deepcopy(self.doc)
        document['archives']['registry_2022']['source_url'] = 'https://example.test/elections.zip'
        with self.assertRaisesRegex(ValueError, 'official release'):
            elections.read_sources(document)

    def test_result_tables_and_all_gates_run_with_nulls_and_explicit_unknowns(self):
        result = self.derive()
        with duckdb.connect() as db:
            db.execute('CREATE TABLE source(source_id VARCHAR PRIMARY KEY); CREATE TABLE area(area_id VARCHAR PRIMARY KEY); CREATE TABLE entity(entity_id VARCHAR PRIMARY KEY,area_id VARCHAR,kind VARCHAR,name VARCHAR);')
            db.execute("INSERT INTO source VALUES ('s1'); INSERT INTO area VALUES ('123456')")
            for entity in self.entities: db.execute('INSERT INTO entity VALUES (?,?,?,?)', [entity['entity_id'], entity['area_id'], entity['kind'], entity['name']])
            db.execute(elections.ELECTION_DDL)
            for table in elections.ELECTION_TABLES:
                for row in result[table]:
                    db.execute('INSERT INTO ' + table + ' (' + ','.join(row) + ') VALUES (' + ','.join('?' for _ in row) + ')', list(row.values()))
            self.assertEqual({name: db.execute(sql).fetchone()[0] for name, sql in elections.ELECTION_GATES.items()}, {name: 0 for name in elections.ELECTION_GATES})
            class Checkpoint:
                tables = set(elections.ELECTION_TABLES)
                def rows(self, sql, values=()):
                    cur = db.execute(sql, values); return [dict(zip([x[0] for x in cur.description], row)) for row in cur.fetchall()]
                def identity(self): return {'checkpoint_id': 'fixture'}
            page = elections.election_listing(Checkpoint(), 'election-links', {'entity_id': self.entities[0]['entity_id'], 'limit': 1, 'offset': 0})
            self.assertEqual(page['page']['total'], 1)
            self.assertEqual(page['items'][0]['result']['candidate_votes'], 20)
            self.assertIn('whole-list', page['semantics']['candidate_votes'])
            db.execute('UPDATE election_list_result SET vote_share_pct=50')
            self.assertEqual(db.execute(elections.ELECTION_GATES['election_raw_vote_share']).fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
