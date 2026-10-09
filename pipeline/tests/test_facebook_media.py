import copy
import json
import tempfile
import unittest
from pathlib import Path

from czlake.production_budget import file_hash

OUT = Path(__file__).resolve().parents[1] / 'tmp/tests/facebook-media'
OUT.mkdir(parents=True, exist_ok=True)
from czlake.production_media import validate_plan, retain, validate_checkpoint_rows
from czlake.production_ingest import import_media_index
from czlake.production_facebook_media import facebook_parent_identity, pinned_media_json
from czlake.production_graph import Inputs


class FacebookMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=OUT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.post = {'postId': '10215518625235712', 'topLevelUrl': 'https://www.facebook.com/1741631496/posts/10215518625235712',
                     'url': 'https://www.facebook.com/kocumova.zuzana/posts/10215518625235712:2484589785382144',
                     'inputUrl': 'https://www.facebook.com/kocumova.zuzana', 'facebookUrl': 'https://www.facebook.com/kocumova.zuzana',
                     'pageName': 'kocumova.zuzana', 'user': {'id': '1741631496', 'profileUrl': 'https://www.facebook.com/1741631496',
                     'profilePic': 'https://scontent-mia3-2.xx.fbcdn.net/avatar.jpg'},
                     'media': [{'__typename': 'Photo', 'id': '10215518625235712', 'thumbnail': 'https://scontent-mia5-1.xx.fbcdn.net/actual.png',
                     'url': 'https://www.facebook.com/photo/?fbid=10215518625235712'}]}
        self.asset = {'asset_id': 'facebook:10215518625235712', 'owner_account_id': 'facebook:1741631496', 'platform': 'facebook',
                      'verification_status': 'verified_publication_owner'}
        self.snapshot = self.root/'assets.json'; self.snapshot.write_text(json.dumps([self.asset]))
        self.source = self.root/'source.json'
        self.entry = {**{k:self.asset[k] for k in ('asset_id','owner_account_id')}, 'kind':'image', 'url':self.post['media'][0]['thumbnail'],
                      'source_envelope':str(self.source), 'source_item_index':0, 'source_media_pointer':'/items/0/media/0/thumbnail',
                      'verified_asset_evidence': {'path':str(self.snapshot), 'sha256':file_hash(self.snapshot)}}
        self.write_source()
        self.plan = {'schema_version':'production-media-plan-v1','entries':[self.entry]}

    def write_source(self, actor='apify/facebook-posts-scraper'):
        self.source.write_text(json.dumps({'schema_version':1,'policy_version':'public-metadata-v1','actor':actor,'items':[self.post]}))
        self.entry['source_envelope_sha256'] = file_hash(self.source)

    def record(self):
        return {**self.entry, 'source_url': self.entry['url'], 'media_id': 'media:test', 'status':'skipped', 'fetched_at':'2026-10-09T03:00:00Z'}

    def ingest(self, record=None, asset=None):
        index = self.root/'index.json'; index.write_text(json.dumps({'schema_version':'production-media-v1','records':[record or self.record()]}))
        rows={'asset':[asset or self.asset], 'quarantine':[], 'media_resource':[]}
        import_media_index(rows, Inputs(self.root), index)
        return rows

    def test_actual_shape_canonical_parent_and_ingest(self):
        self.assertEqual(facebook_parent_identity(self.post), ('facebook:10215518625235712','facebook:1741631496'))
        validate_plan(self.plan)
        self.assertEqual(self.ingest()['media_resource'][0]['source_pointer'], '/items/0/media/0/thumbnail')

    def test_retained_bytes_keep_owner_and_snapshot_and_reject_cross_cdn_redirect(self):
        import io
        class Response(io.BytesIO):
            headers = {}
            def geturl(response):
                return final_url
        class Opener:
            def open(self, *args, **kwargs):
                return Response(b"\xff\xd8\xffactual image fixture")
        path = self.root/'plan.json'; path.write_text(json.dumps(self.plan))
        final_url = self.entry['url']
        result = retain(path, self.root/'retained', opener=Opener())
        row = result['records'][0]
        self.assertEqual(row['status'], 'downloaded')
        self.assertEqual(row['owner_account_id'], self.asset['owner_account_id'])
        self.assertEqual(row['verified_asset_evidence'], self.entry['verified_asset_evidence'])
        self.assertEqual(self.ingest(row)['media_resource'][0]['status'], 'downloaded')
        final_url = 'https://s.cdninstagram.com/foreign.jpg'
        result = retain(path, self.root/'cross-cdn', opener=Opener())
        self.assertEqual(result['records'][0]['status'], 'failed')
        self.assertFalse(list((self.root/'cross-cdn').glob('*.jpg')))

    def test_wrong_author_container_or_graph_owner(self):
        self.post['user']['id'] = '999'; self.write_source()
        with self.assertRaises(ValueError): validate_plan(self.plan)
        self.post['user']['id'] = '1741631496'; self.write_source()
        with self.assertRaisesRegex(ValueError,'graph admitted owner'):
            self.ingest(asset={**self.asset,'owner_account_id':'facebook:999'})

    def test_avatar_inputecho_wrong_pointer_and_video_rejected(self):
        for pointer in ('/items/0/user/profilePic','/items/0/inputUrl','/items/1/media/0/thumbnail','/items/0/media/0/url'):
            with self.subTest(pointer=pointer):
                self.entry['source_media_pointer']=pointer
                with self.assertRaises(ValueError): validate_plan(self.plan)
        self.entry['source_media_pointer']='/items/0/media/0/thumbnail'; self.entry['kind']='video'
        with self.assertRaises(ValueError): validate_plan(self.plan)
        self.entry['kind']='image'; self.post={'inputUrl':'https://www.facebook.com/1741631496','media':[{'thumbnail':self.entry['url']}]};self.write_source()
        with self.assertRaises(ValueError): validate_plan(self.plan)

    def test_actor_hash_and_unverified_snapshot_rejected(self):
        self.write_source('not-facebook')
        with self.assertRaises(ValueError):validate_plan(self.plan)
        self.write_source();self.entry['source_envelope_sha256']='0'*64
        with self.assertRaises(ValueError):validate_plan(self.plan)
        self.write_source();self.snapshot.write_text(json.dumps([{**self.asset,'verification_status':'quarantined'}]));self.entry['verified_asset_evidence']['sha256']=file_hash(self.snapshot)
        with self.assertRaises(ValueError):validate_plan(self.plan)

    def test_cache_reuses_exact_bytes_and_invalidates_on_change(self):
        from unittest.mock import patch
        first_sha, first = pinned_media_json(self.source)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('cache miss')):
            self.assertEqual(pinned_media_json(self.source), (first_sha, first))
        self.source.write_text('{"new":true}')
        new_sha, new = pinned_media_json(self.source)
        self.assertNotEqual(first_sha, new_sha)
        self.assertEqual(new, {'new': True})

    def test_checkpoint_owner_tamper_rejected(self):
        row=self.record();row['media_id']='media:'+__import__('czlake.production_budget',fromlist=['digest']).digest([row['asset_id'],row['kind'],row['url']])[:24]
        validate_checkpoint_rows([row],[self.entry],complete=True)
        row['owner_account_id']='facebook:999'
        with self.assertRaises(ValueError):validate_checkpoint_rows([row],[self.entry],complete=True)

if __name__=='__main__':unittest.main()
