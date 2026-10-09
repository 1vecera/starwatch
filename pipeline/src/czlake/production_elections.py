"""Official municipal results with replayed CSV provenance and bounded registry links.

Historical candidate votes include whole-list allocation; they are not a separately
measured preference-only count. Registry links do not prove personal identity or
continuity of electoral coalitions.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

VERSION = 'production-election-supplement-v1'
ELECTION_TABLES = ('election_list_result', 'election_candidate_result', 'entity_election_link')
ELECTION_DDL = """
CREATE TABLE election_list_result(result_id VARCHAR PRIMARY KEY,election_id VARCHAR NOT NULL,election_date VARCHAR NOT NULL,area_id VARCHAR NOT NULL REFERENCES area(area_id),district_code VARCHAR NOT NULL,list_number VARCHAR NOT NULL,list_party_code VARCHAR NOT NULL,list_name VARCHAR NOT NULL,list_abbreviation VARCHAR,composition VARCHAR NOT NULL,votes BIGINT NOT NULL CHECK(votes>=0),vote_share_pct DOUBLE NOT NULL CHECK(vote_share_pct BETWEEN 0 AND 100),vote_share_denominator BIGINT NOT NULL CHECK(vote_share_denominator>0),reported_adjusted_pct DOUBLE NOT NULL CHECK(reported_adjusted_pct>=0),seats INTEGER NOT NULL CHECK(seats>=0),council_seats INTEGER NOT NULL CHECK(council_seats>0),source_url VARCHAR NOT NULL,observed_at VARCHAR NOT NULL,source_id VARCHAR NOT NULL REFERENCES source(source_id),source_pointer VARCHAR NOT NULL,source_row_key VARCHAR NOT NULL);
CREATE TABLE election_candidate_result(result_id VARCHAR PRIMARY KEY,historical_candidacy_id VARCHAR NOT NULL,election_id VARCHAR NOT NULL,election_date VARCHAR NOT NULL,area_id VARCHAR NOT NULL REFERENCES area(area_id),district_code VARCHAR NOT NULL,list_result_id VARCHAR NOT NULL REFERENCES election_list_result(result_id),list_position INTEGER NOT NULL,name VARCHAR NOT NULL,first_name VARCHAR NOT NULL,last_name VARCHAR NOT NULL,age INTEGER,occupation VARCHAR,residence VARCHAR,member_party_code VARCHAR,nominating_party_code VARCHAR,validity VARCHAR NOT NULL CHECK(validity IN ('A','N')),candidate_votes BIGINT NOT NULL CHECK(candidate_votes>=0),reported_vote_pct DOUBLE NOT NULL CHECK(reported_vote_pct>=0),elected BOOLEAN NOT NULL,mandate_order INTEGER,substitute_order INTEGER,source_url VARCHAR NOT NULL,observed_at VARCHAR NOT NULL,source_id VARCHAR NOT NULL REFERENCES source(source_id),source_pointer VARCHAR NOT NULL,source_row_key VARCHAR NOT NULL);
CREATE TABLE entity_election_link(entity_id VARCHAR NOT NULL REFERENCES entity(entity_id),election_id VARCHAR NOT NULL,result_kind VARCHAR NOT NULL CHECK(result_kind IN ('candidate','list')),result_id VARCHAR,match_status VARCHAR NOT NULL CHECK(match_status IN ('registry_supported','context_only','unknown','ambiguous')),identity_status VARCHAR NOT NULL CHECK(identity_status='not_independently_resolved'),match_basis VARCHAR NOT NULL,possible_result_ids VARCHAR NOT NULL,evidence VARCHAR NOT NULL,unknown_reason VARCHAR,current_registry_source_id VARCHAR NOT NULL REFERENCES source(source_id),current_source_pointer VARCHAR NOT NULL,current_source_row_key VARCHAR NOT NULL,source_id VARCHAR NOT NULL REFERENCES source(source_id),PRIMARY KEY(entity_id,election_id));
"""
GENERIC_PARTIES = {'', '0', '80', '90', '99'}
FILES = {
    'lists_2022': ('registry_2022', 'csv_od/kvros.csv'),
    'candidates_2022': ('registry_2022', 'csv_od/kvrk.csv'),
    'councils_2022': ('codes_2022', 'csv_od/kvcoco.csv'),
    'lists_2026': ('registry_2026', 'csv_od/kvros.csv'),
    'candidates_2026': ('registry_2026', 'csv_od/kvrk.csv'),
}
ARCHIVE_URLS = {
    'registry_2022': 'https://volby.gov.cz/opendata/kv2022/KV2022reg20260328_csv.zip',
    'codes_2022': 'https://volby.gov.cz/opendata/kv2022/KV2022ciselniky20260328_csv.zip',
    'registry_2026': 'https://volby.gov.cz/opendata/kv2026/KV2026reg20261007_csv.zip',
}
ELECTION_GATES = {
    'election_list_candidate_votes': "SELECT count(*) FROM election_list_result l WHERE l.votes<>(SELECT coalesce(sum(c.candidate_votes),0) FROM election_candidate_result c WHERE c.list_result_id=l.result_id)",
    'election_list_elected_seats': "SELECT count(*) FROM election_list_result l WHERE l.seats<>(SELECT count(*) FROM election_candidate_result c WHERE c.list_result_id=l.result_id AND c.elected)",
    'election_city_seats': "SELECT count(*) FROM (SELECT area_id,district_code FROM election_list_result GROUP BY area_id,district_code HAVING sum(seats)<>max(council_seats) OR min(council_seats)<>max(council_seats))",
    'election_raw_vote_share': "SELECT count(*) FROM election_list_result WHERE abs(vote_share_pct-votes::DOUBLE/vote_share_denominator*100)>0.0000001",
    'election_candidate_link_scope': "SELECT count(*) FROM entity_election_link l JOIN entity e USING(entity_id) LEFT JOIN election_candidate_result c ON c.result_id=l.result_id WHERE l.result_kind='candidate' AND l.result_id IS NOT NULL AND (l.match_status<>'registry_supported' OR c.result_id IS NULL OR c.area_id<>e.area_id OR c.validity<>'A' OR e.kind<>'current_candidacy')",
    'election_list_link_scope': "SELECT count(*) FROM entity_election_link l JOIN entity e USING(entity_id) LEFT JOIN election_list_result r ON r.result_id=l.result_id WHERE l.result_kind='list' AND l.result_id IS NOT NULL AND (l.match_status<>'context_only' OR r.result_id IS NULL OR r.area_id<>e.area_id OR e.kind<>'local_list')",
    'election_unknown_links': "SELECT count(*) FROM entity_election_link WHERE ((match_status IN ('unknown','ambiguous'))<>(result_id IS NULL)) OR (result_id IS NULL AND unknown_reason IS NULL)",
}


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalized(value):
    # Preserve accents; only canonical Unicode, casing and whitespace vary.
    return ' '.join(unicodedata.normalize('NFC', value or '').casefold().split())


def integer(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+', value):
        raise ValueError('Official nonnegative integer required')
    return int(value)


def percent(value):
    number = Decimal(value.replace(',', '.'))
    if not number.is_finite() or number < 0:
        raise ValueError('Official finite nonnegative percentage required')
    return float(number)


def stamp(value):
    observed = datetime.fromisoformat(value)
    if observed.tzinfo is None:
        raise ValueError('Official acquisition time requires timezone')
    return value


def candidacy_id(election, row):
    fields = [election, row['KODZASTUP'], row['COBVODU'], row['OSTRANA'], str(integer(row['PORCISLO'])), row['JMENO'], row['PRIJMENI']]
    return hashlib.md5('|'.join(fields).encode()).hexdigest()


def row_key(row, candidate=False):
    keys = ['DATUMVOLEB', 'KODZASTUP', 'COBVODU', 'OSTRANA']
    if candidate:
        keys.append('PORCISLO')
    return packed({key: row.get(key, '20261009') for key in keys})


def list_id(row):
    return 'kv2022-list:' + ':'.join(row[key] for key in ('KODZASTUP', 'COBVODU', 'OSTRANA'))


def read_sources(document, pin_file=None, inputs=None):
    """Revalidate exact original archive bytes, CSV bytes and acquisition receipts."""
    if document.get('schema_version') != VERSION or set(document.get('archives', {})) != set(ARCHIVE_URLS) or set(document.get('files', {})) != set(FILES):
        raise ValueError('Complete pinned official election source set required')
    archives, source_ids = {}, {}
    for key, expected_url in ARCHIVE_URLS.items():
        reference = document['archives'][key]
        if reference.get('source_url') != expected_url or reference.get('final_url') != expected_url:
            raise ValueError('Archive provenance is not the exact authorized official release')
        stamp(reference['fetched_at'])
        path = Path(reference['path']).resolve()
        raw = path.read_bytes()
        if sha(raw) != reference.get('sha256') or len(raw) != reference.get('bytes'):
            raise ValueError('Official archive hash or length changed')
        if pin_file:
            pin_file(inputs, path, reference['sha256'])
        archives[key] = zipfile.ZipFile(io.BytesIO(raw))
    result = {}
    for key, (archive_key, entry) in FILES.items():
        reference = document['files'][key]
        if reference.get('archive') != archive_key or reference.get('entry') != entry:
            raise ValueError('Unexpected official CSV component')
        path = Path(reference['path']).resolve()
        raw = path.read_bytes()
        if sha(raw) != reference.get('sha256') or raw != archives[archive_key].read(entry):
            raise ValueError('CSV bytes differ from pinned official archive component')
        source_ids[key] = pin_file(inputs, path, reference['sha256']) if pin_file else None
        # Retain source record indices before filtering; they address the original CSV.
        result[key] = [(index, row) for index, row in enumerate(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))]
        metadata = json.loads(archives[archive_key].read(entry[:-4] + '.json'))
        columns = {row['name']: row.get('dc:description') for row in metadata['tableSchema']['columns']}
        if key == 'lists_2022' and columns.get('PROCHLSTR') != 'Přepočtené procento získaných hlasů (bez zaokrouhlení)':
            raise ValueError('Official adjusted percentage semantics changed')
        if key == 'candidates_2022' and columns.get('POCHLASU') != 'Počet hlasů, které kandidát získal':
            raise ValueError('Official candidate vote semantics changed')
    for archive in archives.values():
        archive.close()
    return result, source_ids


def source_fields(document, key, index, source_id, row, candidate=False):
    reference = document['files'][key]
    archive = document['archives'][reference['archive']]
    return {'source_url': archive['source_url'], 'observed_at': archive['fetched_at'], 'source_id': source_id,
            'source_pointer': '/' + reference['entry'] + '/records/' + str(index), 'source_row_key': row_key(row, candidate)}


def derive_rows(document, entities, raw, source_ids, supplement_source=None):
    """Derive from exact original rows, independently of proposed supplement values."""
    area_ids = set(document['area_ids'])
    if not area_ids or area_ids != {e['area_id'] for e in entities if e['kind'] in {'current_candidacy', 'local_list'}}:
        raise ValueError('Election scope differs from active graph cities')
    output = {table: [] for table in ELECTION_TABLES}
    old_lists = [(index, row) for index, row in raw['lists_2022'] if row['KODZASTUP'] in area_ids and row['DATUMVOLEB'] == '20220923']
    old_candidates = [(index, row) for index, row in raw['candidates_2022'] if row['KODZASTUP'] in area_ids and row['DATUMVOLEB'] == '20220923']
    councils = {(row['KODZASTUP'], row['COBVODU']): row for _, row in raw['councils_2022'] if row['KODZASTUP'] in area_ids and row['DATUMVOLEB'] == '20220923' and row['TYPZASTUP'] == '1'}
    totals = Counter()
    for _, row in old_lists:
        totals[(row['KODZASTUP'], row['COBVODU'])] += integer(row['HLASY_STR'])
    historical_lists = {}
    for index, row in old_lists:
        key = (row['KODZASTUP'], row['COBVODU'], row['OSTRANA'])
        if key in historical_lists or key[:2] not in councils or totals[key[:2]] <= 0:
            raise ValueError('Duplicate or incomplete council result grain')
        historical_lists[key] = row
        result = {'result_id': list_id(row), 'election_id': 'kv2022', 'election_date': '2022-09-23', 'area_id': key[0],
                  'district_code': key[1], 'list_number': key[2], 'list_party_code': row['VSTRANA'], 'list_name': row['NAZEVCELK'],
                  'list_abbreviation': row['ZKRATKAO8'], 'composition': packed(sorted(row['SLOZENI'].split(','))),
                  'votes': integer(row['HLASY_STR']), 'vote_share_pct': float(Decimal(row['HLASY_STR']) / totals[key[:2]] * 100),
                  'vote_share_denominator': totals[key[:2]], 'reported_adjusted_pct': percent(row['PROCHLSTR']),
                  'seats': integer(row['MAND_STR']), 'council_seats': integer(councils[key[:2]]['MANDATY'])}
        result.update(source_fields(document, 'lists_2022', index, source_ids['lists_2022'], row))
        output['election_list_result'].append(result)
    by_name, historic_by_id = defaultdict(list), {}
    for index, row in old_candidates:
        if (row['KODZASTUP'], row['COBVODU'], row['OSTRANA']) not in historical_lists:
            raise ValueError('Historical candidate has no exact council list result')
        identifier = candidacy_id('kv2022', row)
        result_id = 'kv2022-candidate:' + identifier
        if result_id in historic_by_id or row['PLATNOST'] not in {'A', 'N'} or row['MANDAT'] not in {'A', 'N'}:
            raise ValueError('Historical candidacy is duplicated or has unknown validity')
        historic_by_id[result_id] = row
        result = {'result_id': result_id, 'historical_candidacy_id': identifier, 'election_id': 'kv2022', 'election_date': '2022-09-23',
                  'area_id': row['KODZASTUP'], 'district_code': row['COBVODU'], 'list_result_id': list_id(row), 'list_position': integer(row['PORCISLO']),
                  'name': row['JMENO'] + ' ' + row['PRIJMENI'], 'first_name': row['JMENO'], 'last_name': row['PRIJMENI'], 'age': integer(row['VEK']) if row['VEK'] else None,
                  'occupation': row['POVOLANI'], 'residence': row['BYDLISTEN'], 'member_party_code': row['PSTRANA'], 'nominating_party_code': row['NSTRANA'],
                  'validity': row['PLATNOST'], 'candidate_votes': integer(row['POCHLASU']), 'reported_vote_pct': percent(row['POCPROCVSE']),
                  'elected': row['MANDAT'] == 'A', 'mandate_order': integer(row['PORADIMAND']), 'substitute_order': integer(row['PORADINAHR'])}
        result.update(source_fields(document, 'candidates_2022', index, source_ids['candidates_2022'], row, True))
        output['election_candidate_result'].append(result)
        if row['PLATNOST'] == 'A':
            by_name[(row['KODZASTUP'], normalized(row['JMENO']), normalized(row['PRIJMENI']))].append(result_id)
    current_candidates, matches = {}, {}
    for index, row in raw['candidates_2026']:
        if row['KODZASTUP'] not in area_ids or row['PLATNOST'] != 'A':
            continue
        identifier = candidacy_id('kv2026', row)
        if identifier in current_candidates:
            raise ValueError('Duplicate current official candidacy grain')
        current_candidates[identifier] = (index, row)
        options = by_name[(row['KODZASTUP'], normalized(row['JMENO']), normalized(row['PRIJMENI']))]
        birth = 2026 - integer(row['VEK'])
        parties = {row['PSTRANA'], row['NSTRANA']} - GENERIC_PARTIES
        matches[identifier] = [option for option in options if (abs(birth - (2022 - integer(historic_by_id[option]['VEK']))) <= 1
            and bool(normalized(row['BYDLISTEN'])) and normalized(row['BYDLISTEN']) == normalized(historic_by_id[option]['BYDLISTEN'])
            and parties & ({historic_by_id[option]['PSTRANA'], historic_by_id[option]['NSTRANA']} - GENERIC_PARTIES))]
    reverse = Counter(option for options in matches.values() for option in options)
    current_lists = {}
    for index, row in raw['lists_2026']:
        if row['KODZASTUP'] in area_ids:
            identifier = 'kv2026:' + row['KODZASTUP'] + ':' + row['OSTRANA']
            if identifier in current_lists:
                raise ValueError('Current list entity cannot collapse electoral districts')
            current_lists[identifier] = (index, row)
    for entity in sorted(entities, key=lambda row: row['entity_id']):
        if entity['kind'] not in {'current_candidacy', 'local_list'}:
            continue
        identifier = entity['entity_id']
        candidate = entity['kind'] == 'current_candidacy'
        key = 'candidates_2026' if candidate else 'lists_2026'
        current = current_candidates if candidate else current_lists
        if identifier not in current:
            raise ValueError('Active graph entity lacks exact current official registry ID')
        index, row = current[identifier]
        expected_name = row['JMENO'] + ' ' + row['PRIJMENI'] if candidate else row['NAZEVCELK']
        if entity['area_id'] != row['KODZASTUP'] or normalized(entity['name']) != normalized(expected_name):
            raise ValueError('Active entity name or city differs from its official registry ID')
        if candidate and (entity.get('position') != integer(row['PORCISLO']) or entity.get('list_id') != 'kv2026:' + row['KODZASTUP'] + ':' + row['OSTRANA']):
            raise ValueError('Active entity list or position differs from exact official row')
        if candidate:
            options = matches[identifier]
            unique = len(options) == 1 and reverse[options[0]] == 1
            status = 'registry_supported' if unique else 'ambiguous' if options else 'unknown'
            basis = 'exact_name_city_overlapping_birth_window_exact_residence_specific_party_unique_both_directions'
            evidence = {'current_name': expected_name, 'current_age': integer(row['VEK']), 'current_residence': row['BYDLISTEN'],
                        'current_party_codes': sorted({row['PSTRANA'], row['NSTRANA']} - GENERIC_PARTIES), 'same_name_historical_count': len(by_name[(row['KODZASTUP'], normalized(row['JMENO']), normalized(row['PRIJMENI']))])}
            if unique:
                old = historic_by_id[options[0]]
                evidence.update(historical_name=old['JMENO'] + ' ' + old['PRIJMENI'], historical_age=integer(old['VEK']), historical_residence=old['BYDLISTEN'], historical_party_codes=sorted({old['PSTRANA'], old['NSTRANA']} - GENERIC_PARTIES))
        else:
            options = [list_id(old) for _, old in old_lists if old['KODZASTUP'] == row['KODZASTUP'] and old['VSTRANA'] == row['VSTRANA'] and row['VSTRANA'] not in GENERIC_PARTIES and sorted(old['SLOZENI'].split(',')) == sorted(row['SLOZENI'].split(','))]
            unique = len(options) == 1
            status = 'context_only' if unique else 'ambiguous' if options else 'unknown'
            basis = 'same_city_exact_nongeneric_registered_list_code_and_composition_not_slate_continuity'
            evidence = {'current_name': expected_name, 'current_registered_list_code': row['VSTRANA'], 'current_composition': sorted(row['SLOZENI'].split(',')), 'continuity_status': 'not_established'}
        output['entity_election_link'].append({'entity_id': identifier, 'election_id': 'kv2022', 'result_kind': 'candidate' if candidate else 'list',
            'result_id': options[0] if unique else None, 'match_status': status, 'identity_status': 'not_independently_resolved', 'match_basis': basis,
            'possible_result_ids': packed(sorted(options)), 'evidence': packed(evidence), 'unknown_reason': None if unique else 'multiple_consistent_registry_records' if options else 'no_match_under_explicit_registry_evidence_rule',
            'current_registry_source_id': source_ids[key], 'current_source_pointer': '/' + FILES[key][1] + '/records/' + str(index), 'current_source_row_key': row_key(row, candidate), 'source_id': supplement_source})
    for table in ELECTION_TABLES:
        output[table].sort(key=lambda row: row.get('result_id') or row['entity_id'])
    # Mechanical conservation checks prevent partial or duplicate result imports.
    candidate_totals, seat_totals = Counter(), Counter()
    for result in output['election_candidate_result']:
        candidate_totals[result['list_result_id']] += result['candidate_votes']
        seat_totals[result['list_result_id']] += result['elected']
    for result in output['election_list_result']:
        if candidate_totals[result['result_id']] != result['votes'] or seat_totals[result['result_id']] != result['seats']:
            raise ValueError('Official candidate totals disagree with list votes or seats')
    if set(row['area_id'] for row in output['election_list_result']) != area_ids:
        raise ValueError('An expected city has no historical result')
    return output


def import_election_supplement(rows, inputs, path, pin_file):
    document, supplement_source = inputs.read(path)
    raw, source_ids = read_sources(document, pin_file, inputs)
    derived = derive_rows(document, rows['entity'], raw, source_ids, supplement_source)
    expected = document.get('expected_counts')
    actual = {key: len(value) for key, value in derived.items()}
    if expected != actual:
        raise ValueError('Election supplement expected coverage changed')
    for table, values in derived.items():
        if rows.get(table):
            raise ValueError('Election results were already imported')
        rows[table] = values
    return derived


def election_listing(cp, resource, p):
    table = {'election-lists': 'election_list_result', 'election-candidates': 'election_candidate_result', 'election-links': 'entity_election_link'}[resource]
    if table not in cp.tables:
        from czlake.production_api import fail
        fail(503, 'election_results_unavailable', 'This checkpoint does not contain official historical election results.')
    values, where = [], []
    allowed = {'election-lists': {'area_id', 'election_id'}, 'election-candidates': {'area_id', 'election_id', 'list_result_id', 'elected'}, 'election-links': {'entity_id', 'election_id', 'result_kind', 'match_status'}}[resource]
    for field in sorted(allowed):
        if field in p:
            where.append('r.' + field + '=?')
            values.append(p[field] == 'true' if field == 'elected' else p[field])
    if resource == 'election-links' and 'area_id' in p:
        where.append('EXISTS(SELECT 1 FROM entity e WHERE e.entity_id=r.entity_id AND e.area_id=?)')
        values.append(p['area_id'])
    if 'q' in p:
        if resource == 'election-links':
            where.append('EXISTS(SELECT 1 FROM entity e WHERE e.entity_id=r.entity_id AND strpos(lower(e.name),lower(?))>0)')
        else:
            where.append('strpos(lower(r.' + ('list_name' if resource == 'election-lists' else 'name') + '),lower(?))>0')
        values.append(p['q'])
    clause = ' WHERE ' + ' AND '.join(where) if where else ''
    order = 'r.area_id,r.votes DESC,r.result_id' if resource == 'election-lists' else 'r.area_id,r.candidate_votes DESC,r.result_id' if resource == 'election-candidates' else 'r.entity_id'
    total = cp.rows('SELECT count(*) total FROM ' + table + ' r' + clause, values)[0]['total']
    items = cp.rows('SELECT r.* FROM ' + table + ' r' + clause + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?', [*values, p['limit'], p['offset']])
    for item in items:
        for key in ('composition', 'possible_result_ids', 'evidence', 'source_row_key', 'current_source_row_key'):
            if key in item:
                item[key] = json.loads(item[key])
        if resource == 'election-links':
            result_table = 'election_candidate_result' if item['result_kind'] == 'candidate' else 'election_list_result'
            result = cp.rows('SELECT * FROM ' + result_table + ' WHERE result_id=?', [item['result_id']]) if item['result_id'] else []
            item['result'] = result[0] if result else None
    return {'checkpoint': cp.identity(), 'items': items, 'page': {'limit': p['limit'], 'offset': p['offset'], 'total': total, 'has_more': p['offset'] + len(items) < total},
            'semantics': {'candidate_votes': 'Official POCHLASU totals include whole-list allocation and are not separately measured preference-only votes.',
                          'vote_share_pct': 'HLASY_STR divided by the total list votes in the same council and electoral district, multiplied by 100.',
                          'reported_adjusted_pct': 'Official PROCHLSTR adjusted percentage, retained separately; this is not the unadjusted vote share.',
                          'links': 'Candidate links are direct registry evidence matches, not independently resolved identity; list links are historical code/composition context, not established coalition continuity.'}}
