import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from czlake.production_budget import file_hash
from czlake.production_collect import public_metadata
from czlake.production_media import media_pointer_value, retain, retain_many, validate_plan


class Response(io.BytesIO):
    headers = {}
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url
    def geturl(self):
        return self.url


class Opener:
    def __init__(self, data=b'\xff\xd8\xfftest'):
        self.data, self.calls = data, 0
    def open(self, request, **kwargs):
        self.calls += 1
        return Response(self.data, request.full_url)


class ExtendedMediaTests(unittest.TestCase):
    def setUp(self):
        Path('tmp').mkdir(exist_ok=True)
        folder = tempfile.TemporaryDirectory(dir='tmp')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()

    def plan(self, identifier):
        source = self.root / f'source-{identifier}.json'
        url = f'https://s.cdninstagram.com/{identifier}.jpg'
        source.write_text(json.dumps({'schema_version': 1, 'actor': 'apify/instagram-scraper',
            'policy_version': 'public-metadata-v1', 'items': [{'id': identifier, 'displayUrl': url}]}))
        plan = {'schema_version': 'production-media-plan-v1', 'entries': [{'asset_id': 'instagram:' + identifier,
                'kind': 'image', 'url': url, 'source_envelope': str(source), 'source_envelope_sha256': file_hash(source),
                'source_item_index': 0}]}
        path = self.root / f'plan-{identifier}.json'; path.write_text(json.dumps(plan))
        return path

    def test_parent_pointer_escape_and_nonmedia_fields_rejected(self):
        post = {'displayUrl': 'parent', 'childPosts': [{'displayUrl': 'child', 'images': ['image']}], 'ownerUsername': 'person'}
        self.assertEqual(media_pointer_value(post, '/items/2', '/items/2/childPosts/0/displayUrl', 'image'), 'child')
        self.assertEqual(media_pointer_value(post, '/items/2', '/items/2/childPosts/0/images/0', 'image'), 'image')
        for pointer in ['/items/3/displayUrl', '/items/2/ownerUsername', '/items/2/childPosts/-1/displayUrl']:
            with self.assertRaises(ValueError):
                media_pointer_value(post, '/items/2', pointer, 'image')

    def test_cached_profile_lineage_and_exact_nested_parent(self):
        url = 'https://s.cdninstagram.com/child.jpg'
        profile = {'username': 'person', 'private': False,
                   'latestPosts': [{'id': '1', 'childPosts': [{'id': 'child', 'displayUrl': url}]}],
                   'unknownCommenter': {'identity': 'must_drop'}}
        original = self.root / 'original.json'
        original.write_text(json.dumps({'actor': 'apify/instagram-profile-scraper', 'items': [profile]}))
        source = self.root / 'sanitized.json'
        source.write_text(json.dumps({'schema_version': 1, 'policy_version': 'public-metadata-v1',
                'actor': 'apify/instagram-profile-scraper', 'original_source': {'path': str(original), 'sha256': file_hash(original)},
                'items': [public_metadata('apify/instagram-profile-scraper', profile)]}))
        entry = {'asset_id': 'instagram:1', 'kind': 'image', 'url': url, 'source_envelope': str(source),
                 'source_envelope_sha256': file_hash(source), 'source_item_index': 0, 'source_post_index': 0,
                 'source_media_pointer': '/items/0/latestPosts/0/childPosts/0/displayUrl'}
        plan = {'schema_version': 'production-media-plan-v1', 'entries': [entry]}
        validate_plan(plan)
        entry['asset_id'] = 'instagram:child'
        with self.assertRaisesRegex(ValueError, 'exact source asset'):
            validate_plan(plan)
        entry['asset_id'] = 'instagram:1'; original.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Original cached source'):
            validate_plan(plan)

    def test_existing_checkpoint_tamper_is_rejected_without_fetch(self):
        path = self.plan('1'); output = self.root/'out'; retain(path, output, opener=Opener())
        index = output/'index.json'; data = json.loads(index.read_text()); data['records'][0]['asset_id'] = 'instagram:other'; index.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'exact plan entry'):
            retain(path, output, opener=object())

    def test_deadline_stops_before_get(self):
        result = retain(self.plan('1'), self.root/'out', opener=object(), run_deadline=0.1)
        self.assertEqual(result['records'][0]['reason'], 'run_deadline')
        self.assertEqual(result['summary']['transferred_bytes'], 0)

    def test_cumulative_cap_counts_failed_partial_bytes(self):
        opener = Opener(b'\xff\xd8\xff' + b'x'*100)
        with patch('czlake.production_media.MAX_TOTAL_BYTES', 32), patch('czlake.production_media.MAX_FILE_BYTES', 8):
            result = retain_many([self.plan('1'), self.plan('2')], self.root/'many',
                                 opener=opener, workers=2, cumulative_byte_bound=16)
        self.assertEqual(result['summary']['transferred_bytes'], 16)
        self.assertEqual(result['summary']['downloaded'], 0)
        self.assertEqual(result['summary']['failed'], 2)
        self.assertFalse([p for p in (self.root/'many').rglob('.media-*') if p.suffix != '.lock'])

    def test_restart_does_not_fetch_completed_plan_and_base_url(self):
        p1, p2 = self.plan('1'), self.plan('2'); opener = Opener()
        with patch('czlake.production_media.MAX_TOTAL_BYTES', 32):
            first = retain_many([p1, p2], self.root/'many', opener=opener, cumulative_byte_bound=128, workers=2)
            second = retain_many([p1, p2], self.root/'many', opener=object(), cumulative_byte_bound=128, workers=2)
        self.assertEqual(opener.calls, 2)
        self.assertEqual(first['summary']['transferred_bytes'], second['summary']['transferred_bytes'])
        base = self.root/'many/index.json'
        with patch('czlake.production_media.MAX_TOTAL_BYTES', 32):
            reuse = retain_many([p1], self.root/'reused', base_index=base, opener=object(), cumulative_byte_bound=128)
        self.assertEqual(reuse['summary']['downloaded'], 2)
        self.assertEqual(reuse['summary']['transferred_bytes'], first['summary']['transferred_bytes'])

    def test_crash_restart_keeps_unknown_transferred_file_hold(self):
        path = self.plan('1')
        class Crashed:
            def open(self, request, **kwargs):
                raise RuntimeError('interrupted before checkpoint')
        with patch('czlake.production_media.MAX_TOTAL_BYTES', 32), patch('czlake.production_media.MAX_FILE_BYTES', 8):
            with self.assertRaises(RuntimeError):
                retain_many([path], self.root/'many', opener=Crashed(), cumulative_byte_bound=128, workers=1)
            pending = json.loads((self.root/'many/transfer-budget.json').read_text())
            self.assertEqual(next(iter(pending['plans'].values()))['state'], 'reserved')
            resumed = retain_many([path], self.root/'many', opener=Opener(), cumulative_byte_bound=128, workers=1)
        self.assertEqual(resumed['summary']['uncertain_bytes'], 8)
        self.assertEqual(resumed['summary']['transferred_bytes'], 15)

    def test_distinct_paths_with_identical_plan_bytes_rejected_before_launch(self):
        first = self.plan('1'); duplicate = self.root/'duplicate.json'
        duplicate.write_bytes(first.read_bytes()); opener = Opener()
        with self.assertRaisesRegex(ValueError, 'Duplicate plan content hashes'):
            retain_many([first, duplicate], self.root/'many', opener=opener, cumulative_byte_bound=128, workers=2)
        self.assertEqual(opener.calls, 0)
        self.assertFalse((self.root/'many/transfer-budget.json').exists())

    def test_new_plan_only_resume_preserves_all_prior_completed_resources(self):
        p1, p2 = self.plan('1'), self.plan('2'); opener = Opener()
        with patch('czlake.production_media.MAX_TOTAL_BYTES', 32):
            first = retain_many([p1], self.root/'many', opener=opener, cumulative_byte_bound=128)
            second = retain_many([p2], self.root/'many', opener=opener, cumulative_byte_bound=128)
            reduced = retain_many([p2], self.root/'many', opener=object(), cumulative_byte_bound=128)
        self.assertEqual(opener.calls, 2)
        self.assertEqual({r['asset_id'] for r in second['records']}, {'instagram:1', 'instagram:2'})
        self.assertEqual({r['asset_id'] for r in reduced['records']}, {'instagram:1', 'instagram:2'})
        self.assertEqual(reduced['summary']['transferred_bytes'], 14)

    def test_magic_prefix_with_truncated_declared_body_is_failed(self):
        class Truncated:
            def open(self, request, **kwargs):
                result = Response(b'\xff\xd8\xfftest', request.full_url)
                result.headers = {'Content-Length': '100'}
                return result
        result = retain(self.plan('1'), self.root/'out', opener=Truncated())
        self.assertEqual(result['records'][0]['status'], 'failed')
        self.assertIn('Content-Length', result['records'][0]['reason'])
        self.assertEqual(result['summary']['transferred_bytes'], 7)
        self.assertFalse(list((self.root/'out').glob('*.jpg')))


if __name__ == '__main__':
    unittest.main()
