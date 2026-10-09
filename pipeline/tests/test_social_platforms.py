"""Offline policies using provider-shaped fixtures, not real collected posts."""
import json
import tempfile
import time
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from test_production_graph import GraphTests, SCRATCH, save
from czlake.production_budget import digest, file_hash
from czlake.production_collect import public_metadata, validate_input, validate_manifest
from czlake.production_media import validate_plan
from czlake.production_new_platforms import (
    DISABLED_TIKTOK, TIKTOK, X, allowed_new_media_url, normalize_new_asset, source_input,
)

PRICE_FIXTURES = tempfile.TemporaryDirectory(dir=SCRATCH)


def manifest(actor):
    if actor == X:
        run_input = {'searchTerms': [f'from:alice{i} filter:media -filter:replies -filter:retweets' for i in range(5)], 'sort': 'Latest', 'maxItems': 6000, 'includeSearchTerms': True}
        items, unit, rate, extra, extra_rate, estimate, cap = 6000, 'Dataset Item Tier 1', '0.0004', 'Search/Profile/List etc Query', '0.016', '2.48', '2.8'
    else:
        run_input = {'profiles': ['alice1','alice2','alice3','alice4'], 'resultsPerPage': 200, 'profileScrapeSections':['videos'], 'profileSorting':'latest', **DISABLED_TIKTOK}
        items, unit, rate, extra, extra_rate, estimate, cap = 800, 'Result', '0.003', 'Actor start', '0.001', '2.401', '2.65'
    observed = datetime.now(UTC).isoformat()
    price = Path(PRICE_FIXTURES.name)/(actor.replace('/','--')+'.json')
    price.write_text(json.dumps({'observed_at': observed, 'data': {'actorInfo': {'id':'fixture-'+actor.rsplit('/',1)[1], 'fullName':actor, 'pricing':{'model':'PAY_PER_EVENT','userTier':'BRONZE','events':[{'title':name,'tieredPricing':[{'tier':'BRONZE','priceUsd':value}]} for name,value in [(unit,rate),(extra,extra_rate)]]}},'inputSchema':{'properties':{key:{} for key in run_input}}}}))
    return {'schema_version':1,'scope_id':'starwatch-ten-city-production-20261009','batch_id':'synthetic-'+actor.rsplit('/',1)[1], 'cities':['Praha'], 'actor':actor,'input':run_input,'input_sha256':digest(run_input),'max_items':items,'max_total_charge_usd':cap,'timeout_s':60,'memory_mb':1024,'purpose':'Offline public platform contract fixture','price_basis':{'snapshot_path':str(price),'snapshot_sha256':file_hash(price),'observed_at':observed,'pricing_model':'PAY_PER_EVENT','tier':'BRONZE','unit':unit,'expected_upper_usd':estimate,'rationale':'Offline bounded query/start fee fixture'}}


def fixture(actor):
    if actor == X:
        return {
            'id': '1234567890', 'url': 'https://x.com/alice/status/1234567890',
            'text': 'Council transport project', 'createdAt': '2026-10-09T01:00:00Z',
            'isReply': False, 'isRetweet': False, 'isQuote': False,
            'author': {'id': '1', 'userName': 'Alice', 'name': 'Alice',
                       'twitterUrl': 'https://x.com/alice', 'protected': False,
                       'location': 'DO_NOT_RETAIN', 'canDm': True},
            'media': ['https://pbs.twimg.com/media/exact.jpg'],
            'entities': {'user_mentions': [{'name': 'DO_NOT_RETAIN'}], 'media': [
                {'media_url_https': 'https://pbs.twimg.com/media/exact.jpg',
                 'type': 'photo', 'features': {'faces': 'DO_NOT_RETAIN'},
                 'additional_media_info': {'source_user': 'DO_NOT_RETAIN'}}]},
            'quote': {'author': 'DO_NOT_RETAIN'}, 'likeCount': 0, 'viewCount': 12,
            'replyCount': 2, 'retweetCount': 3,
        }
    return {
        'id': '9876543210', 'webVideoUrl': 'https://www.tiktok.com/@alice/video/9876543210',
        'text': 'Council transport project', 'createTimeISO': '2026-10-09T01:00:00Z',
        'authorMeta': {'id': '2', 'name': 'alice', 'privateAccount': False,
                       'profileUrl': 'https://www.tiktok.com/@alice', 'signature': 'DO_NOT_RETAIN'},
        'videoMeta': {'coverUrl': 'https://p16.tiktokcdn.com/exact.jpg',
                      'downloadAddr': 'https://v16.tiktokcdn.com/exact.mp4',
                      'subtitleLinks': ['DO_NOT_RETAIN']},
        'commentCount': 0, 'diggCount': 4, 'playCount': 17, 'shareCount': 1,
        'detailedMentions': [{'name': 'DO_NOT_RETAIN'}],
        'locationMeta': {'address': 'DO_NOT_RETAIN'},
    }


def fixture_input(actor):
    value = manifest(actor)['input']
    if actor == X:
        value['searchTerms'] = ['from:alice filter:media -filter:replies -filter:retweets']
    else:
        value['profiles'] = ['alice']
    return value


class SocialPolicyTests(unittest.TestCase):
    def test_sealed_manifests_have_full_query_and_start_price(self):
        for actor in (X, TIKTOK):
            value = manifest(actor)
            self.assertTrue(validate_manifest(value, time.time())['actor_id'])
            value['price_basis']['expected_upper_usd'] = '0.001'
            with self.assertRaisesRegex(ValueError, 'understates'):
                validate_manifest(value, time.time())

    def test_x_queries_stay_in_exact_tier_one(self):
        original = manifest(X)
        for change in (
            {'searchTerms': ['from:alice']}, {'sort': 'Top'}, {'includeSearchTerms': False},
            {'searchTerms': [f'from:alice{i} filter:media -filter:replies -filter:retweets' for i in range(6)]},
            {'searchTerms': ['from:Alice filter:media -filter:replies -filter:retweets', 'from:alice filter:media -filter:replies -filter:retweets']},
            {'maxItems': True}, {'twitterHandles': ['alice']}, {'startUrls': ['https://x.com/alice']},
        ):
            value = deepcopy(original['input']); value.update(change)
            with self.assertRaises((ValueError, TypeError)):
                validate_input(X, value, original['max_items'])

    def test_tiktok_no_metered_extras_or_unbounded_profiles(self):
        original = manifest(TIKTOK)
        for change in (
            {'shouldDownloadVideos': True}, {'maxFollowersPerProfile': 1},
            {'commentsPerPost': False}, {'proxyCountryCode': 'CZ'}, {'resultsPerPage': 201},
            {'profiles': ['https://www.tiktok.com/@alice']}, {'profiles': ['alice', 'Alice']},
            {'profileScrapeSections': ['videos', 'reposts']}, {'oldestPostDate': '2020-01-01'},
            {'downloadSubtitlesOptions': 'ALWAYS_DOWNLOAD_SUBTITLES'},
        ):
            value = deepcopy(original['input']); value.update(change)
            with self.assertRaises((ValueError, TypeError)):
                validate_input(TIKTOK, value, original['max_items'])

    def test_nested_projection_drops_unrelated_identities(self):
        for actor in (X, TIKTOK):
            row = public_metadata(actor, fixture(actor))
            self.assertNotIn('DO_NOT_RETAIN', json.dumps(row))
            self.assertEqual(public_metadata(actor, row), row)
            self.assertEqual(normalize_new_asset(actor, row, fixture_input(actor))['owner'], 'alice')

    def test_public_owner_flags_and_exact_input_are_mandatory(self):
        for actor, section, flag in ((X, 'author', 'protected'), (TIKTOK, 'authorMeta', 'privateAccount')):
            row = public_metadata(actor, fixture(actor)); run_input = fixture_input(actor)
            for value in (None, True, 0, 'false'):
                bad = deepcopy(row); bad[section][flag] = value
                with self.assertRaises(ValueError): normalize_new_asset(actor, bad, run_input)
            with self.assertRaises(ValueError): normalize_new_asset(actor, row, None)
            bad = deepcopy(row); bad[section]['userName' if actor == X else 'name'] = 'bob'
            with self.assertRaises(ValueError): normalize_new_asset(actor, bad, run_input)
            bad = deepcopy(row); bad['id'] = 'not-numeric'
            with self.assertRaises(ValueError): normalize_new_asset(actor, bad, run_input)
            bad = deepcopy(row); bad['url' if actor == X else 'webVideoUrl'] += '?login=true'
            with self.assertRaises(ValueError): normalize_new_asset(actor, bad, run_input)
        for key in ('isReply', 'isRetweet'):
            for value in (None, True, 0):
                row = public_metadata(X, fixture(X)); row[key] = value
                with self.assertRaises(ValueError): normalize_new_asset(X, row, fixture_input(X))

    def test_input_provenance_and_platform_cdn_are_exact(self):
        for actor in (X, TIKTOK):
            value = fixture_input(actor)
            envelope = {'actor': actor, 'collection_input': value, 'input_sha256': digest(value)}
            self.assertEqual(source_input(envelope), value)
            envelope['input_sha256'] = '0' * 64
            with self.assertRaises(ValueError): source_input(envelope)
        for url in ('http://pbs.twimg.com/a', 'https://pbs.twimg.com.evil.test/a', 'https://user:pass@pbs.twimg.com/a', 'https://pbs.twimg.com:123/a'):
            self.assertFalse(allowed_new_media_url(url, 'x'))
        self.assertFalse(allowed_new_media_url('https://pbs.twimg.com/a', 'tiktok'))
        self.assertFalse(allowed_new_media_url('https://i.ytimg.com/a', 'x'))


class SocialGraphTests(GraphTests):
    def test_public_x_and_tiktok_survive_graph_with_literal_source_pointers(self):
        production = self.root / 'production'
        proof = json.loads(self.paths['identity'].read_text())['candidates']['alice-candidacy']
        reviews = []
        for actor, platform in ((X, 'x'), (TIKTOK, 'tiktok')):
            item = public_metadata(actor, fixture(actor)); run_input = fixture_input(actor)
            source = production / f'raw/apify/{platform}.json'
            save(source, dict(schema_version=1, policy_version='public-metadata-v1', actor=actor,
                             items=[item], fetched_at_epoch=1791510300, run_id='offline-fixture',
                             batch_id='offline-' + platform, collection_input=run_input, input_sha256=digest(run_input)))
            identity = self.root / (platform + '-proof.json')
            owner = deepcopy(proof); owner.update(platform=platform, handle='alice',
                profile_url='https://x.com/alice' if platform == 'x' else 'https://www.tiktok.com/@alice')
            save(identity, {'candidates': {'alice-candidacy': owner}, 'lists': {}}); reviews.append(identity)
            entry = dict(asset_id=platform + ':' + item['id'], kind='image',
                         url=item['media'][0] if platform == 'x' else item['videoMeta']['coverUrl'],
                         source_envelope=str(source), source_envelope_sha256=file_hash(source), source_item_index=0,
                         source_media_pointer='/items/0/media/0' if platform == 'x' else '/items/0/videoMeta/coverUrl')
            self.assertEqual(len(validate_plan({'schema_version': 'production-media-plan-v1', 'entries': [entry]})), 1)
            entry['source_media_pointer'] = '/items/1/wrong'
            with self.assertRaises(ValueError): validate_plan({'schema_version': 'production-media-plan-v1', 'entries': [entry]})
        self.kwargs.update(production_root=production, identity_reviews=reviews); self.export('social')
        db = duckdb.connect(str(self.base / 'output/checkpoints/social/graph.duckdb'), read_only=True)
        found = db.execute("select platform,verification_status from asset where platform in ('x','tiktok') order by platform").fetchall()
        self.assertEqual(found, [('tiktok', 'verified_publication_owner'), ('x', 'verified_publication_owner')])
        self.assertEqual(db.execute("select count(*) from production_observation where platform in ('x','tiktok') and source_pointer='/items/0'").fetchone()[0], 2)
        self.assertEqual(db.execute("select count(*) from claim where asset_id like 'x:%' or asset_id like 'tiktok:%'").fetchone()[0], 0)
        db.close()


if __name__ == '__main__': unittest.main()
