"""Topic navigation checks for admitted provenance, counting and attribution."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = Path('/home/vecera/code/agents007-hackathon')
PRODUCTION = HERE.parent if (HERE.parent / 'src/czlake/production_graph.py').is_file() else ROOT / '.claude/worktrees/production'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


topics = load('czlake.production_topic_graph', HERE / 'production_topic_graph.py' if (HERE / 'production_topic_graph.py').is_file() else PRODUCTION / 'src/czlake/production_topic_graph.py')
api = load('topic_navigation_api', HERE / 'production_api.py' if (HERE / 'production_api.py').is_file() else PRODUCTION / 'src/czlake/production_api.py')
AT = '2026-10-09T02:00:00+00:00'
TEXT = 'Bydlení 🏘️ potřebuje opravy.'
NAME = 'Same Name'
WEB_TEXT = NAME + ' writes about repairs. 🏡'
SCRATCH = HERE.parent / 'tmp/tests/topic-graph'


def constant(path, name):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(name)


def fixture(root, modern=True, web=True):
    directory = root / 'checkpoints' / 'topic-fixture'
    directory.mkdir(parents=True)
    with duckdb.connect(str(directory / 'graph.duckdb')) as db:
        db.execute(constant(PRODUCTION / 'src/czlake/production_graph.py', 'DDL'))
        if modern:
            db.execute(constant(PRODUCTION / 'src/czlake/production_ingest.py', 'EXTENSION_DDL'))
        if web:
            db.execute(constant(PRODUCTION / 'src/czlake/production_web.py', 'WEB_DDL'))

        def insert(table, **values):
            db.execute('INSERT INTO ' + table + ' (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', list(values.values()))

        insert('source', source_id='s1', path='/private/no-export.json', sha256='0'*64, bytes=12)
        for area_id, name in [('brno', 'Brno'), ('other', 'Namesake city')]:
            insert('area', area_id=area_id, name=name)
        for entity_id, area_id in [('owner','brno'),('mentioned','other')]:
            insert('entity', entity_id=entity_id, kind='current_candidacy', area_id=area_id, name=NAME, qualified=True, protected=False, selection_status='selected', local_role_status='unknown')
        for account_id, entity_id, status in [('owned','owner','confirmed'),('unproven','mentioned','unknown')]:
            insert('account', account_id=account_id, platform='instagram', handle=account_id, url='https://example.test/'+account_id, public=True, identity_status=status)
            insert('account_relation', relation_id=account_id, entity_id=entity_id, account_id=account_id, relation='owns_account', status=status, reason='fixture', source_id='s1', source_pointer='/owner')
        for asset_id, published_at, verified in [('post1','2026-10-01T10:00:00+02:00',True),('post2','2026-10-02T08:00:00+00:00',True),('post3',None,True),('unknown',AT,False)]:
            owner = 'owned' if verified else 'unproven'
            insert('asset', asset_id=asset_id, platform='instagram', asset_type='Image', url='https://example.test/'+asset_id, published_at=published_at, text=TEXT, owner_account_id=owner, verification_status='verified_publication_owner' if verified else 'quarantined', verification_reason='fixture', claim_status='reviewed')
            insert('asset_relation', relation_id=asset_id, asset_id=asset_id, entity_id='owner' if verified else 'mentioned', relation='published_by', status='confirmed' if verified else 'unknown', reason='fixture', evidence_url='https://example.test/'+asset_id, source_id='s1', source_pointer='/published')
            insert('asset_observation', observation_id=asset_id, asset_id=asset_id, observed_account_id=owner, observed_at=AT, source_id='s1', source_pointer='/observation', coverage='incomplete', preview_url='https://cdn.example.test/'+asset_id+'.jpg')
        insert('asset_relation', relation_id='about-only', asset_id='post1', entity_id='mentioned', relation='about', status='confirmed', reason='fixture', source_id='s1', source_pointer='/about')
        for topic in ['housing','governance','pending','stale','rejected','unverified']:
            insert('topic', topic_id=topic, label=topic, taxonomy_version='fixture-v1')

        def coverage(identifier, asset, current=True, decision='accept', errors='[]'):
            insert('classification_coverage', classification_id=identifier, asset_id=asset, content_sha256=hashlib.sha256(TEXT.encode()).hexdigest(), review_status='reviewed_claims', review_decision=decision, review_reason='fixture', review_topic_errors=errors, claim_limit=3, claims_truncated=False, omitted_claims_count=0, basis='supplied_caption_only', note='Caption only', packet_assets=1, packet_id=identifier, classification_assignment='classifier', classification_session='classifier-session', review_assignment='reviewer', review_session='reviewer-session', label_sha256='1'*64, cards_source_id='s1', labels_source_id='s1', review_source_id='s1', registry_source_id='s1', current=current)

        if modern:
            for identifier, asset, current, decision, errors in [('cc1','post1',True,'accept','[]'),('cc2','post2',True,'accept','[]'),('cc3','post3',True,'accept','[]'),('ccold','post1',False,'accept','[]'),('ccreject','post1',True,'reject','[]'),('ccerror','post1',True,'accept','["housing"]'),('ccunknown','unknown',True,'accept','[]')]:
                coverage(identifier,asset,current,decision,errors)
            for asset,topic,classification,status in [('post1','housing','cc1','independently_reviewed'),('post1','governance','cc1','independently_reviewed'),('post2','housing','cc2','independently_reviewed'),('post2','governance','cc2','independently_reviewed'),('post3','housing','cc3','independently_reviewed'),('post1','stale','ccold','independently_reviewed'),('post1','rejected','ccreject','independently_reviewed'),('post1','rejected','ccerror','independently_reviewed'),('post1','pending','cc1','pending'),('unknown','unverified','ccunknown','independently_reviewed')]:
                insert('asset_topic', asset_id=asset, topic_id=topic, classification_id=classification, review_status=status)
        for identifier,asset,topic,status,classification in [('claim1','post1','housing','independently_reviewed','cc1'),('claim2','post2','housing','independently_reviewed','cc2'),('claim3','post2','governance','independently_reviewed','cc2'),('claimpending','post1','pending','pending','cc1'),('claimstale','post1','stale','independently_reviewed','ccold'),('claimreject','post1','rejected','independently_reviewed','ccreject'),('claimunknown','unknown','unverified','independently_reviewed','ccunknown')]:
            insert('claim', claim_id=identifier, asset_id=asset, text=TEXT, evidence_quote=TEXT, span_start=0, span_end=len(TEXT), speaker_status='unknown', review_status=status, source_id='s1', source_pointer='/text')
            insert('claim_topic', claim_id=identifier, topic_id=topic, review_status=status)
            if modern:
                insert('claim_evidence', claim_id=identifier, classification_id=classification, claim_type='source_statement', content_sha256=hashlib.sha256(TEXT.encode()).hexdigest(), source_url='https://example.test/'+asset, context_text=TEXT, offset_unit='unicode_codepoint')
        for identifier,asset,value,time,null_reason in [('m1','post1',5,AT,None),('mduplicate','post1',5,AT,None),('mearlier','post1',999,'2026-10-08T02:00:00Z',None),('mconflict1','post2',4,AT,None),('mconflict2','post2',6,AT,None),('mnull','post3',None,AT,'provider_unavailable')]:
            insert('metric', metric_id=identifier, asset_id=asset, observation_id=asset, platform='instagram', name='likes', value=value, unit='count', null_reason=null_reason, observed_at=time, source_url='https://example.test/'+asset, source_id='s1', source_pointer='/likes', coverage='snapshot')
        insert('metric', metric_id='followers', account_id='owned', observation_id='owned', platform='instagram', name='followers', value=5000, unit='count', observed_at=AT, source_id='s1', source_pointer='/followers', coverage='snapshot')
        if web:
            insert('publisher',publisher_id='pub',name='Reported source context',url='https://news.example.test',kind='news',identity_status='unknown',source_id='s1',source_pointer='/publisher')
            insert('web_asset',asset_id='web1',url='https://news.example.test/story',asset_type='article',public=True,observed_at=AT,title='Retained article',text=WEB_TEXT,content_sha256=hashlib.sha256(WEB_TEXT.encode()).hexdigest(),retained_text_path='/private/article.json',retained_text_sha256='2'*64,text_source_pointer='/main_text',reported_publisher_id='pub',publisher_status='unknown',subject_status='unknown',speaker_status='unknown',text_truncated=False,coverage='retained_source_only',source_id='s1',text_source_id='s1',source_pointer='/article')
            for identifier,entity,status,quote,start,end,content_hash in [('webmention','owner','unknown',NAME,0,len(NAME),hashlib.sha256(WEB_TEXT.encode()).hexdigest()),('webrejected','owner','rejected',NAME,0,len(NAME),hashlib.sha256(WEB_TEXT.encode()).hexdigest()),('webaboutentity','mentioned','unknown',NAME,0,len(NAME),hashlib.sha256(WEB_TEXT.encode()).hexdigest()),('webwrongspan','owner','unknown',NAME,1,len(NAME)+1,hashlib.sha256(WEB_TEXT.encode()).hexdigest()),('webwronghash','owner','unknown',NAME,0,len(NAME),'3'*64)]:
                insert('web_relation',relation_id=identifier,asset_id='web1',relation='about',entity_id=entity,status=status,reason='exact name is insufficient identity proof',evidence_quote=quote,span_start=start,span_end=end,content_sha256=content_hash,source_id='s1',source_pointer='/mention')
        db.execute('CHECKPOINT')
    (directory/'coverage.json').write_text(json.dumps([{'area_id':'brno','owned_publications':3},{'area_id':'other','owned_publications':0}]))
    files={path.name:{'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in directory.iterdir()}
    manifest={'checkpoint_id':'topic-fixture','created_at':AT,'schema_version':'starwatch-production-graph/1.1.0' if modern else 'starwatch-production-graph/1.0.0','status':'validated_fixture','quality':{'status':'passed'},'files':files,'counts':{},'coverage':{}}
    (directory/'manifest.json').write_text(json.dumps(manifest))
    pointer={key:manifest[key] for key in ('checkpoint_id','created_at','schema_version')}
    pointer.update(manifest='checkpoints/topic-fixture/manifest.json',database='checkpoints/topic-fixture/graph.duckdb',manifest_sha256=hashlib.sha256((directory/'manifest.json').read_bytes()).hexdigest())
    (root/'current.json').write_text(json.dumps(pointer))


class TopicGraphTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=SCRATCH)
        self.root=Path(self.temp.name)
        fixture(self.root)
        self.api=api.ProductionAPI(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_only_active_accepted_topics_and_distinct_parent_counts(self):
        result=self.api.handle('/api/topics')
        self.assertEqual({x['topic_id'] for x in result['items']},{'housing','governance'})
        housing=next(x for x in result['items'] if x['topic_id']=='housing')
        self.assertEqual((housing['verified_parent_asset_count'],housing['source_claim_count'],housing['owner_entity_count'],housing['owner_account_count']),(3,2,1,1))
        self.assertEqual((housing['known_publication_asset_count'],housing['unknown_publication_asset_count']),(2,1))
        self.assertEqual(housing['first_published_at'],'2026-10-01T08:00:00.000000Z')
        self.assertEqual(housing['last_published_at'],'2026-10-02T08:00:00.000000Z')

    def test_owner_projection_never_promotes_about_entity(self):
        result=self.api.handle('/api/topics/housing/entities')
        self.assertEqual([x['entity_id'] for x in result['items']],['owner'])
        self.assertEqual(result['items'][0]['relation'],'published_by')
        assets=self.api.handle('/api/topics/housing/assets')['items']
        self.assertEqual({x['entity_id'] for a in assets for x in a['publication_owners']},{'owner'})
        self.assertEqual(self.api.handle('/api/topics?entity_id=mentioned')['page']['total'],0)

    def test_source_claim_evidence_exact_unicode_span_and_unknown_speaker(self):
        claims=self.api.handle('/api/topics/housing/claims')['items']
        self.assertEqual({x['claim_id'] for x in claims},{'claim1','claim2'})
        for claim in claims:
            self.assertEqual(claim['context_text'][claim['span_start']:claim['span_end']],claim['evidence_quote'])
            self.assertEqual(claim['offset_unit'],'unicode_codepoint')
            self.assertIsNone(claim['speaker_entity_id'])
            self.assertEqual(claim['speaker_status'],'unknown')
            self.assertEqual(claim['truth_status'],'source_statement_not_verified_truth')

    def test_cooccurrence_is_distinct_shared_parent_publications(self):
        related=self.api.handle('/api/topics/housing/related')['items']
        self.assertEqual(len(related),1)
        row=related[0]
        self.assertEqual((row['topic_id'],row['shared_parent_asset_count'],row['topic_parent_asset_count'],row['related_topic_parent_asset_count'],row['union_parent_asset_count']),('governance',2,3,2,3))
        self.assertAlmostEqual(row['jaccard_cooccurrence'],2/3)
        self.assertEqual(row['causal_status'],'not_established')

    def test_metrics_are_latest_snapshots_with_duplicate_and_conflict_provenance(self):
        rows={x['asset_id']:x for x in self.api.handle('/api/topics/housing/metrics')['items']}
        self.assertEqual(set(rows),{'post1','post2','post3'})
        self.assertEqual(rows['post1']['value'],5)
        self.assertEqual((rows['post1']['observation_count'],rows['post1']['source_observation_count']),(2,1))
        self.assertTrue(rows['post2']['conflict'])
        self.assertIsNone(rows['post2']['value'])
        self.assertEqual(rows['post2']['null_reason'],'conflicting_values_same_time')
        self.assertIsNone(rows['post3']['value'])
        self.assertNotIn('sum',rows['post1'])
        self.assertEqual(rows['post1']['source_urls'],['https://example.test/post1'])

    def test_web_mentions_keep_exact_span_no_inherited_topic_or_identity(self):
        result=self.api.handle('/api/topics/housing/web-sources')
        self.assertEqual(result['page']['total'],1)
        row=result['items'][0]
        self.assertEqual(row['relation_id'],'webmention')
        self.assertEqual(WEB_TEXT[row['span_start']:row['span_end']],row['evidence_quote'])
        self.assertEqual(row['topic_status'],'not_classified')
        self.assertEqual(row['entity_identity_status'],'unknown')
        self.assertEqual(row['publisher_status'],'unknown')
        self.assertEqual(row['url'],'https://news.example.test/story')
        self.assertTrue(row['detail_url'].startswith('/api/web-assets/web1?checkpoint_id='))
        self.assertNotIn('/private/',json.dumps(result))

    def test_filters_preserve_date_scope_and_navigation_checkpoint(self):
        result=self.api.handle('/api/topics?area_id=brno&since=2026-10-02T00%3A00%3A00Z')
        housing=next(x for x in result['items'] if x['topic_id']=='housing')
        self.assertEqual(housing['verified_parent_asset_count'],1)
        self.assertIn('area_id=brno',housing['detail_url'])
        detail=self.api.handle(housing['detail_url'])
        self.assertEqual(detail['item']['verified_parent_asset_count'],1)
        self.assertIn('since=',detail['item']['navigation']['related'])
        related=self.api.handle(detail['item']['navigation']['related'])['items'][0]
        self.assertEqual(related['shared_parent_asset_count'],1)

    def test_detail_and_subroute_pagination_are_bounded(self):
        detail=self.api.handle('/api/topics/housing?limit=1')['item']
        self.assertEqual((len(detail['assets_preview']),detail['assets_page']['total']),(1,3))
        result=self.api.handle('/api/topics/housing/assets?limit=1&offset=1')
        self.assertEqual(result['items'][0]['asset_id'],'post1')
        self.assertTrue(result['page']['has_more'])
        for path,status in [('/api/topics/housing/assets?limit=201',400),('/api/topics/housing/blob',404),('/api/topics/pending',404),('/api/topics/housing?entity_id=mentioned',404),('/api/topics/housing?checkpoint_id=other',409),('/api/topics/housing?since=2026-10-09',400),('/api/topics/housing?entity_id=owner&entity_id=owner',400)]:
            with self.subTest(path=path),self.assertRaises(api.APIError) as error:
                self.api.handle(path)
            self.assertEqual(error.exception.status,status)

    def test_summary_exports_each_undirected_edge_once(self):
        with api.PinnedCheckpoint(self.root) as cp:
            result=topics.export_summary(cp)
        self.assertEqual(result['export_schema'],'starwatch-topic-summary/1.0.0')
        self.assertEqual(len(result['relations']),1)
        self.assertEqual(result['relations'][0]['shared_parent_asset_count'],2)
        json.dumps(result,allow_nan=False)

    def test_legacy_source_topics_work_without_optional_layers(self):
        legacy=Path(self.temp.name)/'legacy'
        fixture(legacy,modern=False,web=False)
        api_legacy=api.ProductionAPI(legacy)
        result=api_legacy.handle('/api/topics/housing')
        self.assertEqual(result['item']['verified_parent_asset_count'],2)
        self.assertEqual(result['item']['web_sources_page']['total'],0)
        self.assertTrue(all(x['evidence_gap']=='source_context_not_retained' for x in result['item']['claims_preview']))


if __name__=='__main__':
    unittest.main()
