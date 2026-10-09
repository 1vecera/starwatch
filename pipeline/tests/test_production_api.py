"""Adversarial read API checks using private local immutable DuckDB fixtures."""
from __future__ import annotations

import os
import ast
import base64
import hashlib
import http.client
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("CZLAKE_PROJECT") or Path(__file__).resolve().parents[2])
PRODUCTION = HERE.parent if (HERE.parent / 'src/czlake/production_graph.py').is_file() else ROOT / '.claude/worktrees/production'
MODULE = HERE / 'production_api.py' if (HERE / 'production_api.py').is_file() else PRODUCTION / 'src/czlake/production_api.py'
WEB = PRODUCTION / 'src/czlake/production_web.py' if (PRODUCTION / 'src/czlake/production_web.py').is_file() else ROOT / 'tmp/production/native/graph_finish/implementation/src/czlake/production_web.py'
IMAGES = PRODUCTION / 'src/czlake/production_images.py' if (PRODUCTION / 'src/czlake/production_images.py').is_file() else ROOT / 'tmp/production/native/graph_finish/portrait_extension/src/czlake/production_images.py'
INGEST = PRODUCTION / 'src/czlake/production_ingest.py' if (PRODUCTION / 'src/czlake/production_ingest.py').is_file() else ROOT / 'tmp/production/native/graph_finish/implementation/src/czlake/production_ingest.py'
spec = importlib.util.spec_from_file_location('production_api', MODULE)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
SCRATCH = HERE.parent / 'tmp/tests/production-api'
SCRATCH.mkdir(parents=True, exist_ok=True)
# Fixture source files live under SCRATCH; confine retained-source reads there, whatever the checkout path.
api.PROJECT_ROOT = SCRATCH
AT = '2026-10-09T02:00:00+00:00'
TEXT = 'Bydlení 🏘️ potřebuje opravy.'


def constant(path, name):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(name)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True))


def seal(root, checkpoint_id='fixture-v1', schema='1.1.0'):
    directory = root / 'checkpoints' / checkpoint_id
    directory.mkdir(parents=True, exist_ok=True)
    files = {path.name: {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in directory.iterdir() if path.name not in {'manifest.json'}}
    with duckdb.connect(str(directory / 'graph.duckdb'), read_only=True) as connection:
        counts = {name: connection.execute('SELECT count(*) FROM ' + name).fetchone()[0] for name in ['area', 'entity', 'account', 'asset', 'claim', 'topic']}
    manifest = {'checkpoint_id': checkpoint_id, 'created_at': AT, 'schema_version': 'starwatch-production-graph/' + schema, 'status': 'validated_test_checkpoint', 'quality': {'status': 'passed', 'checks': {}}, 'files': files, 'counts': counts, 'coverage': {'collection': 'fixture_incomplete'}}
    write_json(directory / 'manifest.json', manifest)
    pointer = {key: manifest[key] for key in ['checkpoint_id', 'created_at', 'schema_version']}
    pointer.update(manifest=f'checkpoints/{checkpoint_id}/manifest.json', database=f'checkpoints/{checkpoint_id}/graph.duckdb', manifest_sha256=hashlib.sha256((directory / 'manifest.json').read_bytes()).hexdigest())
    write_json(root / 'current.json', pointer)
    return pointer


def fixture(root, extensions=True, checkpoint_id='fixture-v1', web=False, photos=False):
    directory = root / 'checkpoints' / checkpoint_id
    directory.mkdir(parents=True)
    with duckdb.connect(str(directory / 'graph.duckdb')) as db:
        db.execute(constant(PRODUCTION / 'src/czlake/production_graph.py', 'DDL'))
        if extensions:
            db.execute(constant(INGEST, 'EXTENSION_DDL'))
        if web:
            db.execute(constant(WEB, 'WEB_DDL'))
        if photos:
            db.execute(constant(IMAGES, 'IMAGE_DDL'))
        def insert(table, **values):
            if table == 'classification_coverage' and 'current' in {row[1] for row in db.execute("PRAGMA table_info('classification_coverage')").fetchall()}:
                values.setdefault('current', True)
            db.execute(f'INSERT INTO {table} ({",".join(values)}) VALUES ({",".join("?" for _ in values)})', list(values.values()))
        insert('source', source_id='s1', path='/local/secret/raw.json', sha256='0'*64, bytes=10)
        for area_id, name in [('a', 'Brno'), ('b', 'Namesake city')]:
            insert('area', area_id=area_id, name=name, city_rank=1 if area_id == 'a' else 2)
        for entity_id, kind, area_id, qualified in [('e1', 'current_candidacy', 'a', True), ('e2', 'current_candidacy', 'b', False), ('l1', 'local_list', 'a', False)]:
            insert('entity', entity_id=entity_id, kind=kind, area_id=area_id, name='Same Name' if kind != 'local_list' else 'List', qualified=qualified, protected=False, selection_status='selected_proposal' if qualified else 'not_selected', local_role_status='unknown', validity='A')
        for account_id, status in [('acc1','confirmed'), ('acc2','unknown')]:
            insert('account', account_id=account_id, platform='instagram', handle=account_id, url='https://example.test/' + account_id, public=True, identity_status=status)
            insert('account_observation', observation_id=account_id+'-obs', account_id=account_id, observed_at=AT, source_id='s1', source_pointer='/profile', coverage='incomplete', avatar_url='https://cdn.example.test/avatar.jpg')
            insert('account_relation', relation_id=account_id+'-rel', entity_id='e1' if account_id=='acc1' else 'e2', account_id=account_id, relation='owns_account', status=status, reason='fixture', source_id='s1', source_pointer='/proof')
        for asset_id, owner, verified in [('post1','acc1',True), ('post2','acc2',False)]:
            insert('asset', asset_id=asset_id, platform='instagram', asset_type='Video', url='https://example.test/'+asset_id, published_at=AT, text=TEXT, owner_account_id=owner, verification_status='verified_publication_owner' if verified else 'quarantined', verification_reason='fixture', claim_status='reviewed')
            insert('asset_observation', observation_id=asset_id+'-obs', asset_id=asset_id, observed_account_id=owner, observed_at=AT, source_id='s1', source_pointer='/post', coverage='incomplete', preview_url='https://cdn.example.test/preview.jpg')
            insert('asset_relation', relation_id=asset_id+'-rel', asset_id=asset_id, entity_id='e1' if verified else 'e2', relation='published_by', status='confirmed' if verified else 'unknown', reason='fixture', source_id='s1', source_pointer='/post')
        insert('asset_relation', relation_id='mention', asset_id='post1', entity_id='e2', relation='about', status='confirmed', reason='fixture', source_id='s1', source_pointer='/post')
        for i, value in enumerate([10,10,11]):
            insert('metric', metric_id='f'+str(i), account_id='acc1', observation_id='acc1-obs', platform='instagram', name='followers', value=value, unit='count', observed_at=AT, source_url='https://example.test/acc1', source_id='s1', source_pointer='/followers', coverage='snapshot')
        for metric_id, asset_id, value, null_reason in [('like1','post1',5,None), ('like2','post2',100,None), ('views','post1',None,'provider_unavailable_sentinel')]:
            insert('metric', metric_id=metric_id, asset_id=asset_id, observation_id=asset_id+'-obs', platform='instagram', name='views' if metric_id=='views' else 'likes', value=value, null_reason=null_reason, raw_value='-1' if null_reason else str(value), unit='count', observed_at=AT, source_id='s1', source_pointer='/metrics', coverage='snapshot')
        for topic_id in ['housing','pending','hidden']:
            insert('topic', topic_id=topic_id, label=topic_id, taxonomy_version='v1')
        for claim_id, asset_id, status, topic in [('c1','post1','independently_reviewed','housing'), ('c2','post1','pending','pending'), ('c3','post2','independently_reviewed','hidden')]:
            insert('claim', claim_id=claim_id, asset_id=asset_id, text=TEXT, evidence_quote=TEXT, span_start=0, span_end=len(TEXT), speaker_status='unknown', review_status=status, source_id='s1', source_pointer='/text')
            insert('claim_topic', claim_id=claim_id, topic_id=topic, review_status=status)
        if extensions:
            insert('classification_coverage', classification_id='cc1', asset_id='post1', content_sha256=hashlib.sha256(TEXT.encode()).hexdigest(), review_status='independently_reviewed', review_decision='accept', review_reason='fixture', review_topic_errors='[]', claim_limit=3, claims_truncated=False, omitted_claims_count=0, basis='supplied_caption_only', note='Caption only', packet_assets=1, packet_id='p1', classification_assignment='class1', classification_session='class-session', review_assignment='review1', review_session='review-session', label_sha256='1'*64, cards_source_id='s1', labels_source_id='s1', review_source_id='s1', registry_source_id='s1')
            insert('claim_evidence', claim_id='c1', classification_id='cc1', claim_type='source_statement', content_sha256=hashlib.sha256(TEXT.encode()).hexdigest(), source_url='https://example.test/post1', context_text=TEXT, offset_unit='unicode_codepoint')
            insert('asset_topic', asset_id='post1', topic_id='housing', classification_id='cc1', review_status='independently_reviewed')
            insert('media_resource', media_id='m1', asset_id='post1', kind='image', status='retained', local_path='/private/blob.jpg', sha256='2'*64, bytes=100, content_type='image/jpeg', source_envelope='/private/raw.json', source_envelope_sha256='3'*64, source_item_index=0, source_id='s1', source_pointer='/items/0/displayUrl')
        if web:
            insert('publisher', publisher_id='publisher:context1', name='Public municipality context', url='https://public.example.test', kind='municipality', identity_status='unknown', source_id='s1', source_pointer='/publishers/0')
            for asset_id, asset_type, title, text in [('web:source1','official_record','Council statement',TEXT),('web:source2','article','Different source','No attribution')]:
                insert('web_asset', asset_id=asset_id, url='https://public.example.test/'+asset_id, asset_type=asset_type, public=True, published_at=None, observed_at=AT, title=title, text=text, content_sha256=hashlib.sha256(text.encode()).hexdigest(), retained_text_path='/private/extraction.json', retained_text_sha256='4'*64, text_source_pointer='/main_text', reported_publisher_id='publisher:context1' if asset_id=='web:source1' else None, publisher_status='unknown', subject_status='unknown', speaker_status='unknown', text_truncated=False, coverage='retained_extracted_public_text_only_no_identity_or_speaker_promotion', source_id='s1', text_source_id='s1', source_pointer='/assets/0')
            for relation_id, relation, status, publisher_id, entity_id in [('web:publisher','published_by','unknown','publisher:context1',None),('web:subject','about','unknown',None,'e1'),('web:reject','about','rejected',None,'e2')]:
                insert('web_relation', relation_id=relation_id, asset_id='web:source1', relation=relation, publisher_id=publisher_id, entity_id=entity_id, status=status, reason='Unproven exact attribution', evidence_quote=TEXT, span_start=0, span_end=len(TEXT), content_sha256=hashlib.sha256(TEXT.encode()).hexdigest(), source_id='s1', source_pointer='/relations/0')
        if photos:
            source=root/'source-page.json'
            source.write_text(json.dumps({'images':[{'url':'https://public.example.test/portrait.png'}],'name': 'Same Name'}))
            image_root=root/'approved-images';image_root.mkdir()
            image=image_root/'portrait.png'
            image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aGm0AAAAASUVORK5CYII='))
            insert('source', source_id='photo-page', path=str(source), sha256=hashlib.sha256(source.read_bytes()).hexdigest(), bytes=source.stat().st_size)
            insert('source', source_id='photo-blob', path=str(image), sha256=hashlib.sha256(image.read_bytes()).hexdigest(), bytes=image.stat().st_size)
            for image_id,kind,relation,status in [('photo1','source_bound_portrait','source_identified','downloaded'),('avatar1','owned_account_avatar','source_identified','downloaded'),('unknown-photo','source_bound_portrait','unknown','downloaded'),('failed-photo','source_bound_portrait','source_identified','failed')]:
                insert('source_image', image_id=image_id, entity_id='e1', target_id='target1', kind=kind, relation_status=relation, depicted_person_status='unknown', download_status=status, local_path=str(image) if status=='downloaded' else None, sha256=hashlib.sha256(image.read_bytes()).hexdigest() if status=='downloaded' else None, bytes=image.stat().st_size if status=='downloaded' else None, content_type='image/png' if status=='downloaded' else None, width=1 if status=='downloaded' else None, height=1 if status=='downloaded' else None, original_image_url='https://public.example.test/portrait.png', observed_at=AT, source_page_url='https://public.example.test/person', source_page_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), source_image_pointer='/images/0/url', source_text_pointer='/name', identity_evidence=json.dumps({'exact_name':'Same Name','internal_path':'/private/do-not-export'}), account_id='acc1' if kind=='owned_account_avatar' else None, failure_reason='not_retained' if status=='failed' else None, source_id='s1', source_page_id='photo-page', blob_source_id='photo-blob' if status=='downloaded' else None, source_pointer='/images/0')
            for entity_id, target_id, status, counts in [('e1','target1','downloaded',4),('e2','target2','unknown',0)]:
                insert('entity_photo_coverage',entity_id=entity_id,target_id=target_id,name='Same Name',city='Brno' if entity_id=='e1' else 'Namesake city',status=status,portrait_status='source_bound' if entity_id=='e1' else 'unknown',image_count=counts,downloaded_count=3 if counts else 0,source_portrait_count=1 if counts else 0,unknown_reason=None if counts else 'No exact source image found',source_id='s1',source_pointer='/targets/0')
        db.execute('CHECKPOINT')
    write_json(directory / 'coverage.json', [{'area_id':'a','name':'Brno','owned_publications':1}, {'area_id':'b','name':'Namesake city','owned_publications':0}])
    return seal(root, checkpoint_id, '1.1.0' if extensions else '1.0.0')


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.root = Path(self.tmp.name)
        self.pointer = fixture(self.root)
        self.api = api.ProductionAPI(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def error(self, path, status, code=None):
        with self.assertRaises(api.APIError) as raised:
            self.api.handle(path)
        self.assertEqual(raised.exception.status, status)
        if code:
            self.assertEqual(raised.exception.code, code)
        self.assertNotIn(str(self.root), raised.exception.message)

    def test_admission_and_related_entity_grains(self):
        self.assertEqual(self.api.handle('/api/entities')['page']['total'], 2)
        self.assertEqual(self.api.handle('/api/entities?scope=registered')['page']['total'], 3)
        self.assertEqual(self.api.handle('/api/accounts')['page']['total'], 1)
        self.assertEqual(self.api.handle('/api/assets')['page']['total'], 1)
        self.assertEqual(self.api.handle('/api/assets?entity_id=e2')['page']['total'], 0)
        self.assertEqual(self.api.handle('/api/assets?entity_id=e2&relation=about')['page']['total'], 1)
        self.assertEqual(self.api.handle('/api/claims')['page']['total'], 1)
        self.assertEqual([t['topic_id'] for t in self.api.handle('/api/topics')['items']], ['housing'])
        self.error('/api/assets/post2',404)
        self.assertEqual(self.api.handle('/api/entities/e2')['item']['accounts'], [])

    def test_metric_snapshots_preserve_conflicts_nulls_and_exclude_unverified(self):
        observations = self.api.handle('/api/metrics')['items']
        self.assertEqual(len(observations), 5)
        self.assertFalse(any(m['asset_id']=='post2' for m in observations))
        snapshots = self.api.handle('/api/metrics?mode=snapshots&account_id=acc1')['items']
        self.assertEqual(len(snapshots),1)
        self.assertIsNone(snapshots[0]['value'])
        self.assertEqual(snapshots[0]['null_reason'],'conflicting_values_same_time')
        self.assertEqual(snapshots[0]['observation_count'],3)
        self.assertEqual(self.api.handle('/api/metrics?entity_id=e2')['items'],[])
        null = self.api.handle('/api/metrics?name=views')['items'][0]
        self.assertIsNone(null['value']); self.assertEqual(null['raw_value'],'-1')

    def test_exact_unicode_claim_and_retention_metadata(self):
        claim = self.api.handle('/api/claims')['items'][0]
        self.assertEqual(claim['evidence']['offset_unit'],'unicode_codepoint')
        self.assertEqual(claim['evidence']['context_text'][claim['span_start']:claim['span_end']],TEXT)
        item = self.api.handle('/api/assets/post1')['item']
        self.assertEqual(item['classification_coverage'][0]['basis'],'supplied_caption_only')
        self.assertEqual(item['media_resources'][0]['sha256'],'2'*64)
        self.assertNotIn('local_path',item['media_resources'][0])
        self.assertNotIn('/private/', json.dumps(item))

    def test_bounded_pagination_query_injection_and_timestamp_validation(self):
        first = self.api.handle('/api/entities?scope=registered&limit=1')
        second = self.api.handle('/api/entities?scope=registered&limit=1&offset=1')
        self.assertTrue(first['page']['has_more'])
        self.assertNotEqual(first['items'][0]['entity_id'], second['items'][0]['entity_id'])
        self.assertEqual(self.api.handle('/api/entities?q=%27%20OR%201%3D1--')['items'],[])
        for query in ['limit=201','limit=0','limit=-1','offset=100001','offset=1.2','limit=1&limit=2','sql=SELECT+1','q=','scope=all','q=x&unknown=y','q=%FF']:
            self.error('/api/entities?'+query,400)
        self.error('/api/assets?since=2026-10-09',400)
        self.error('/api/assets?since=2026-10-10T00:00:00Z&until=2026-10-09T00:00:00Z',400)
        self.assertEqual(self.api.handle('/api/assets?since=2026-10-09T00:00:00Z')['page']['total'],1)

    def test_checkpoint_identity_no_paths_and_version_compatibility(self):
        result = self.api.handle('/api/checkpoint')
        self.assertEqual(result['checkpoint']['checkpoint_id'],'fixture-v1')
        self.assertTrue(result['capabilities']['claim_evidence'])
        self.assertNotIn(str(self.root),json.dumps(result))
        self.error('/api/cities?checkpoint_id=old',409,'checkpoint_changed')
        seal(self.root,schema='2.0.0')
        self.error('/api/health',503)

    def test_pin_once_and_keep_same_checkpoint_during_pointer_replacement(self):
        original = api.json_bytes
        pointer_reads = []
        def wrapped(path, maximum):
            result = original(path,maximum)
            if path.name == 'current.json':
                pointer_reads.append(path)
                path.write_text('corrupt')
            return result
        with patch.object(api,'json_bytes',side_effect=wrapped):
            result = self.api.handle('/api/entities/e1')
        self.assertEqual(len(pointer_reads),1)
        self.assertEqual(result['checkpoint']['checkpoint_id'],'fixture-v1')
        self.assertEqual(result['item']['asset_page']['total'],1)
        self.error('/api/health',503)

    def test_corrupt_hash_and_unpassed_quality_fail_closed(self):
        manifest_path = self.root / self.pointer['manifest']
        manifest_path.write_text(manifest_path.read_text()+' ')
        self.error('/api/health',503)
        seal(self.root)
        directory = manifest_path.parent
        with (directory / 'graph.duckdb').open('ab') as stream:
            stream.write(b'bad')
        self.error('/api/cities',503)

    def test_path_traversal_absolute_building_and_symlink_rejected(self):
        for field, value in [('database','../graph.duckdb'), ('manifest',str(self.root/'outside.json')), ('database','checkpoints/.building-hidden/graph.duckdb')]:
            pointer = dict(self.pointer); pointer[field] = value
            write_json(self.root/'current.json',pointer)
            self.error('/api/health',503)
        write_json(self.root/'current.json',self.pointer)
        db = self.root / self.pointer['database']
        outside = self.root / 'outside.duckdb'; db.rename(outside); db.symlink_to(outside)
        self.error('/api/health',503)

    def test_missing_and_unpassed_checkpoint(self):
        manifest_path = self.root / self.pointer['manifest']
        manifest = json.loads(manifest_path.read_text())
        manifest['quality']['status']='failed'; write_json(manifest_path,manifest)
        pointer=dict(self.pointer); pointer['manifest_sha256']=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        write_json(self.root/'current.json',pointer)
        self.error('/api/health',503)
        (self.root/'current.json').unlink()
        self.error('/api/health',503)

    def test_legacy_checkpoint_exposes_explicit_additive_gaps(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            root=Path(directory); fixture(root,extensions=False)
            legacy=api.ProductionAPI(root)
            result=legacy.handle('/api/assets/post1')
            self.assertIsNone(result['item']['classification_coverage'])
            self.assertIn('media_retention_not_reported',{g['code'] for g in result['gaps']})
            self.assertEqual(legacy.handle('/api/metrics?mode=snapshots&name=followers')['items'][0]['null_reason'],'conflicting_values_same_time')

    def test_duplicate_identity_proofs_do_not_duplicate_accounts(self):
        with duckdb.connect(str(self.root / self.pointer['database'])) as db:
            db.execute("INSERT INTO account_relation SELECT 'second-proof',entity_id,account_id,relation,status,reason,'https://independent.example/proof',evidence_span,'2026-10-09T03:00:00+00:00',source_id,source_pointer FROM account_relation WHERE relation_id='acc1-rel'")
        seal(self.root)
        self.assertEqual(self.api.handle('/api/accounts')['page']['total'],1)
        self.assertEqual(len(self.api.handle('/api/entities/e1')['item']['accounts']),1)
        self.assertEqual(self.api.handle('/api/accounts')['items'][0]['evidence_url'],'https://independent.example/proof')

    def test_classification_current_coverage_distinct_from_history(self):
        with duckdb.connect(str(self.root / self.pointer['database'])) as db:
            cursor = db.execute("SELECT * FROM classification_coverage WHERE classification_id='cc1'")
            columns = [column[0] for column in cursor.description]
            record = dict(zip(columns,cursor.fetchone(),strict=True))
            record.update(classification_id='cc-old',current=False,review_decision='reject',review_status='reviewed_rejected')
            db.execute('INSERT INTO classification_coverage ('+','.join('"'+column+'"' for column in record)+') VALUES ('+','.join('?' for _ in record)+')',list(record.values()))
        seal(self.root)
        coverage=self.api.handle('/api/coverage')['classification']
        self.assertEqual(coverage['packet_history_rows'],2)
        self.assertEqual(coverage['current_assets'],1)
        self.assertEqual(coverage['current_decisions'][0]['review_decision'],'accept')
        detail=self.api.handle('/api/assets/post1')['item']
        self.assertEqual(detail['classification_history_count'],2)
        self.assertEqual([row['classification_id'] for row in detail['classification_coverage']],['cc1'])

    def test_same_time_identical_metrics_deduplicate_without_sum(self):
        with duckdb.connect(str(self.root / self.pointer['database'])) as db:
            db.execute("DELETE FROM metric WHERE metric_id='f2'")
        seal(self.root)
        snapshot=self.api.handle('/api/metrics?mode=snapshots&account_id=acc1')['items'][0]
        self.assertEqual(snapshot['value'],10)
        self.assertFalse(snapshot['conflict'])
        self.assertEqual(snapshot['observation_count'],2)
        self.assertEqual(self.api.handle('/api/assets')['items'][0]['latest_observation']['preview_url'],'https://cdn.example.test/preview.jpg')

    def test_optional_web_routes_are_separate_unknown_and_path_free(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            root=Path(directory); fixture(root,web=True)
            client=api.ProductionAPI(root)
            sources=client.handle('/api/web-assets')
            self.assertEqual(sources['page']['total'],2)
            self.assertEqual(sources['admission_status'],'source_only_unattributed')
            self.assertIn('web_attribution_unknown',{gap['code'] for gap in sources['gaps']})
            self.assertTrue(all(source['publisher_status']==source['subject_status']==source['speaker_status']=='unknown' for source in sources['items']))
            self.assertTrue(all('text' not in source and 'retained_text_path' not in source for source in sources['items']))
            detail=client.handle('/api/web-assets/web%3Asource1')
            item=detail['item']
            self.assertEqual(item['text'],TEXT)
            self.assertEqual(item['offset_unit'],'unicode_codepoint')
            self.assertEqual({relation['status'] for relation in item['relation_proposals']},{'unknown','rejected'})
            self.assertEqual(item['relation_proposals_total'],3)
            for relation in item['relation_proposals']:
                self.assertEqual(item['text'][relation['span_start']:relation['span_end']],relation['evidence_quote'])
            self.assertEqual(item['reported_publisher_context']['identity_status'],'unknown')
            self.assertNotIn('/private/',json.dumps(detail))
            self.assertEqual(client.handle('/api/publishers')['admission_status'],'unreviewed_publisher_context')
            self.assertEqual(client.handle('/api/assets')['page']['total'],1)
            self.assertEqual(client.handle('/api/entities/e1')['item']['asset_page']['total'],1)
            self.assertEqual(client.handle('/api/entities/e2')['item']['asset_page']['total'],0)
            self.assertEqual(client.handle('/api/coverage')['items'][0]['owned_publications'],1)
            self.assertEqual(client.handle('/api/claims')['page']['total'],1)
            self.assertEqual(client.handle('/api/metrics')['page']['total'],5)
            self.assertTrue(client.handle('/api/checkpoint')['capabilities']['web_asset'])
            self.assertEqual(client.handle('/api/web-assets?reported_publisher_id=publisher%3Acontext1')['page']['total'],1)
            self.assertEqual(client.handle('/api/web-assets?asset_type=article')['page']['total'],1)
            self.assertEqual(client.handle('/api/web-assets?q=Bydl')['page']['total'],1)
            self.assertEqual(client.handle('/api/publishers?kind=municipality')['page']['total'],1)
            self.assertEqual(client.handle('/api/web-assets?limit=1')['page']['total'],2)
            first=client.handle('/api/web-assets?limit=1')['items'][0]['asset_id']
            second=client.handle('/api/web-assets?limit=1&offset=1')['items'][0]['asset_id']
            self.assertNotEqual(first,second)
            self.assertEqual(client.handle('/api/web-assets?q=%27%20OR%201%3D1--')['items'],[])
            for path in ['/api/web-assets?entity_id=e1','/api/web-assets?area_id=a','/api/publishers?entity_id=e1','/api/web-assets?sql=SELECT+1']:
                with self.assertRaises(api.APIError) as error: client.handle(path)
                self.assertEqual(error.exception.status,400)
            with self.assertRaises(api.APIError) as error: client.handle('/api/assets/web%3Asource1')
            self.assertEqual(error.exception.status,404)

    def test_web_routes_absent_on_legacy_checkpoint_are_explicit(self):
        for route in ['/api/web-assets','/api/publishers']:
            result=self.api.handle(route)
            self.assertEqual(result['items'],[])
            self.assertEqual(result['page']['total'],0)
            self.assertIn('web_sources_not_retained',{gap['code'] for gap in result['gaps']})
        self.error('/api/web-assets/unknown',404)
        self.assertFalse(self.api.handle('/api/checkpoint')['capabilities']['web_asset'])

    def photo_fixture(self):
        temporary=tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);fixture(root,photos=True)
        client=api.ProductionAPI(root,photo_roots=[root/'approved-images'])
        return root,client

    def test_source_photo_metadata_coverage_and_blob_binding(self):
        root,client=self.photo_fixture()
        photos=client.handle('/api/photos')['items']
        self.assertEqual(len(photos),4)
        self.assertTrue(all(photo['depicted_person_status']=='unknown' for photo in photos))
        self.assertNotIn('/private/',json.dumps(photos))
        self.assertNotIn(str(root),json.dumps(photos))
        self.assertTrue(all('local_path' not in photo and 'identity_evidence' not in photo for photo in photos))
        self.assertEqual(client.handle('/api/photos?kind=owned_account_avatar')['page']['total'],1)
        self.assertEqual(client.handle('/api/photos?entity_id=e2')['page']['total'],0)
        self.assertEqual(client.handle('/api/photos?area_id=a&download_status=downloaded')['page']['total'],3)
        coverage=client.handle('/api/photo-coverage?entity_id=e2')['items'][0]
        self.assertEqual(coverage['status'],'unknown');self.assertEqual(coverage['image_count'],0)
        self.assertEqual(client.handle('/api/photo-coverage?status=downloaded')['page']['total'],1)
        detail=client.handle('/api/entities/e1')['item']
        self.assertEqual(detail['photo_page']['total'],4)
        self.assertEqual(detail['photo_coverage']['downloaded_count'],3)
        self.assertEqual(client.handle('/api/assets')['page']['total'],1)
        metadata=client.handle('/api/photos/photo1')['item']
        response=client.handle(metadata['blob_url'])
        self.assertIsInstance(response,api.ImageResponse)
        self.assertEqual(response.data,(root/'approved-images/portrait.png').read_bytes())
        self.assertEqual(response.content_type,'image/png')
        self.assertEqual(response.sha256,metadata['sha256'])
        for image_id in ['unknown-photo','failed-photo']:
            with self.assertRaises(api.APIError) as error:client.handle('/api/photos/'+image_id+'/blob')
            self.assertEqual(error.exception.status,404)
        with self.assertRaises(api.APIError) as error:client.handle('/api/photos/photo1/blob?path=/etc/passwd')
        self.assertEqual(error.exception.status,400)

    def test_photo_corruption_source_pointer_type_and_unapproved_path_fail_closed(self):
        for mutation in ['blob_bytes','source_bytes','source_pointer','content_type','outside_root','symlink','blob_source_binding','mismatched_raster_type','svg_payload']:
            root,client=self.photo_fixture()
            database=root/'checkpoints/fixture-v1/graph.duckdb'
            if mutation=='blob_bytes':
                with (root/'approved-images/portrait.png').open('ab') as stream:stream.write(b'bad')
            elif mutation=='source_bytes':
                with (root/'source-page.json').open('ab') as stream:stream.write(b' ')
            else:
                with duckdb.connect(str(database)) as db:
                    if mutation=='source_pointer':db.execute("UPDATE source_image SET source_image_pointer='/name' WHERE image_id='photo1'")
                    if mutation=='content_type':db.execute("UPDATE source_image SET content_type='text/html' WHERE image_id='photo1'")
                    if mutation=='mismatched_raster_type':db.execute("UPDATE source_image SET content_type='image/jpeg' WHERE image_id='photo1'")
                    if mutation=='svg_payload':
                        image=root/'approved-images/portrait.png';image.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>')
                        sha=hashlib.sha256(image.read_bytes()).hexdigest();size=image.stat().st_size
                        db.execute("UPDATE source_image SET sha256=?,bytes=? WHERE image_id='photo1'",[sha,size])
                        db.execute("UPDATE source SET sha256=?,bytes=? WHERE source_id='photo-blob'",[sha,size])
                    if mutation=='blob_source_binding':db.execute("UPDATE source_image SET blob_source_id='photo-page' WHERE image_id='photo1'")
                    if mutation in {'outside_root','symlink'}:
                        outside=root/'outside.png';outside.write_bytes((root/'approved-images/portrait.png').read_bytes())
                        target=root/'approved-images/link.png' if mutation=='symlink' else outside
                        if mutation=='symlink':target.symlink_to(outside)
                        db.execute("UPDATE source_image SET local_path=? WHERE image_id='photo1'",[str(target)])
                        db.execute("INSERT INTO source VALUES ('other-blob',?,?,?)",[str(target),hashlib.sha256(outside.read_bytes()).hexdigest(),outside.stat().st_size])
                        db.execute("UPDATE source_image SET blob_source_id='other-blob' WHERE image_id='photo1'")
                seal(root)
            with self.assertRaises(api.APIError) as error:client.handle('/api/photos/photo1/blob')
            self.assertEqual(error.exception.status,503,mutation)
            self.assertEqual(error.exception.code,'image_unavailable')
            self.assertNotIn(str(root),error.exception.message)

    def test_avif_compatible_brand_original_bytes_and_mismatched_type(self):
        # A bounded major mif1/compatible avif container exercises brands, not suffix guesses.
        avif=(28).to_bytes(4,'big')+b'ftyp'+b'mif1'+bytes(4)+b'avif'+b'mif1'+b'miaf'+(20).to_bytes(4,'big')+b'ispe'+bytes(4)+(1).to_bytes(4,'big')*2
        self.assertEqual(api.image_type(avif),'image/avif')
        animated=(20).to_bytes(4,'big')+b'ftyp'+b'mif1'+bytes(4)+b'avis'
        self.assertEqual(api.image_type(animated),'image/avif')
        # avif in minor-version bytes or outside declared ftyp never proves the brand.
        for invalid in [(20).to_bytes(4,'big')+b'ftyp'+b'mif1'+b'avif'+b'miaf', (16).to_bytes(4,'big')+b'ftyp'+b'mif1'+bytes(4)+b'avif', (9000).to_bytes(4,'big')+b'ftyp'+b'avif'+bytes(4), bytes(4)+b'ftyp'+b'avif'+bytes(4)]:
            with self.assertRaises(ValueError):api.image_type(invalid)
        root,client=self.photo_fixture()
        image=root/'approved-images/portrait.png'  # Deliberately keep the misleading extension.
        image.write_bytes(avif);sha=hashlib.sha256(avif).hexdigest()
        with duckdb.connect(str(root/'checkpoints/fixture-v1/graph.duckdb')) as db:
            db.execute("UPDATE source_image SET sha256=?,bytes=?,content_type='image/avif' WHERE image_id='photo1'",[sha,len(avif)])
            db.execute("UPDATE source SET sha256=?,bytes=? WHERE source_id='photo-blob'",[sha,len(avif)])
        seal(root)
        response=client.handle('/api/photos/photo1/blob')
        self.assertEqual(response.data,avif)
        self.assertEqual(response.content_type,'image/avif')
        with duckdb.connect(str(root/'checkpoints/fixture-v1/graph.duckdb')) as db:
            db.execute("UPDATE source_image SET content_type='image/jpeg' WHERE image_id='photo1'")
        seal(root)
        with self.assertRaises(api.APIError) as error:client.handle('/api/photos/photo1/blob')
        self.assertEqual(error.exception.status,503)
        self.assertEqual(error.exception.code,'image_unavailable')

    def test_photo_http_raster_get_head_and_host_guard(self):
        root,client=self.photo_fixture()
        server=api.make_server(root,port=0,photo_roots=[root/'approved-images'])
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        port=server.server_address[1];base='http://127.0.0.1:'+str(port)
        try:
            with urlopen(base+'/api/photos/photo1/blob',timeout=5) as response:
                data=response.read()
                self.assertEqual(response.headers['Content-Type'],'image/png')
                self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
                self.assertEqual(response.headers['X-Starwatch-Checkpoint'],'fixture-v1')
                self.assertEqual(hashlib.sha256(data).hexdigest(),response.headers['ETag'].strip('"'))
            with urlopen(Request(base+'/api/photos/photo1/blob',method='HEAD'),timeout=5) as response:
                self.assertEqual(response.read(),b'')
                self.assertGreater(int(response.headers['Content-Length']),0)
            for headers in [{'Host':'hostile.example:'+str(port)},{'Origin':'http://hostile.example:'+str(port)}]:
                with self.assertRaises(HTTPError) as error:urlopen(Request(base+'/api/photos/photo1/blob',headers=headers),timeout=5)
                self.assertEqual(error.exception.code,403)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_absent_photo_tables_are_explicit_on_older_checkpoint(self):
        for route in ['/api/photos','/api/photo-coverage']:
            result=self.api.handle(route)
            self.assertEqual(result['items'],[])
            self.assertIn('photo_data_not_retained',{gap['code'] for gap in result['gaps']})
        self.error('/api/photos/unknown/blob',404)

    def test_http_loopback_authority_and_origin_boundary(self):
        server=api.make_server(self.root,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        port=server.server_address[1]
        def request(headers):
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            try:
                connection.putrequest('GET','/api/checkpoint',skip_host=True)
                for name,value in headers:
                    connection.putheader(name,value)
                connection.endheaders()
                response=connection.getresponse()
                return response.status,json.loads(response.read())
            finally:
                connection.close()
        try:
            for host in [f'127.0.0.1:{port}',f'localhost:{port}',f'[::1]:{port}',f'LOCALHOST:{port}']:
                status,body=request([('Host',host)])
                self.assertEqual(status,200)
                status,body=request([('Host',host),('Origin','http://'+host)])
                self.assertEqual(status,200)
            bad_hosts=[f'attacker.example:{port}',f'localhost.attacker.example:{port}',f'localhost:{port+1}',f'localhost:{port}/path',f'localhost@attacker.example:{port}',f'localhost:{port},attacker.example',f'localhost%2e:{port}',f'::1:{port}',f'[::1]:nonnumeric','localhost']
            for host in bad_hosts:
                status,body=request([('Host',host)])
                self.assertEqual(status,403,host)
                self.assertEqual(body['error']['code'],'forbidden_host')
                self.assertNotIn('checkpoint',body)
            for headers in [[],[('Host',f'localhost:{port}'),('Host',f'127.0.0.1:{port}')]]:
                status,body=request(headers)
                self.assertEqual(status,403)
                self.assertEqual(body['error']['code'],'forbidden_host')
            bad_origins=['null','https://localhost:'+str(port),'http://attacker.example:'+str(port),'http://localhost:'+str(port+1),'http://localhost:'+str(port)+'/path','http://localhost:'+str(port)+',http://attacker.example',f'http://user@localhost:{port}',f'http://localhost:{port}/']
            for origin in bad_origins:
                status,body=request([('Host',f'localhost:{port}'),('Origin',origin)])
                self.assertEqual(status,403,origin)
                self.assertEqual(body['error']['code'],'forbidden_origin')
                self.assertNotIn('checkpoint',body)
            status,body=request([('Host',f'localhost:{port}'),('Origin',f'http://localhost:{port}'),('Origin',f'http://localhost:{port}')])
            self.assertEqual(status,403)
            status,body=request([('Host',f'localhost:{port}'),('Origin',f'http://127.0.0.1:{port}')])
            self.assertEqual(status,403)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_read_only_database_and_http_methods_local_only(self):
        with api.PinnedCheckpoint(self.root) as cp:
            with self.assertRaises(duckdb.Error):
                cp.connection.execute('DELETE FROM entity')
            with self.assertRaises(duckdb.Error):
                cp.connection.execute("SELECT * FROM read_csv('/etc/passwd')")
        server=api.make_server(self.root,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        base='http://127.0.0.1:'+str(server.server_address[1])
        try:
            with urlopen(base+'/api/health',timeout=5) as response:
                self.assertEqual(response.status,200)
                self.assertEqual(response.headers['Cache-Control'],'no-store')
                self.assertIsNone(response.headers['Access-Control-Allow-Origin'])
                self.assertEqual(json.load(response)['status'],'ready')
            for method in ['POST','PUT','PATCH','DELETE','OPTIONS','TRACE','CONNECT']:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/api/entities',method=method),timeout=5)
                self.assertEqual(error.exception.code,405)
            with urlopen(Request(base+'/api/cities',method='HEAD'),timeout=5) as response:
                self.assertEqual(response.read(),b'')
            with self.assertRaises(HTTPError) as error:
                urlopen(base+'/api/cities?sql=evil',timeout=5)
            self.assertEqual(error.exception.code,400)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__=='__main__':
    unittest.main()
