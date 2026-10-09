import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from czlake.production_budget import file_hash
from czlake.production_media import allowed_url, retain, validate_plan


class Response(io.BytesIO):
    headers: ClassVar[dict] = {}

    def geturl(self):
        return "https://scontent.cdninstagram.com/public.jpg"


class MediaTests(unittest.TestCase):
    def setUp(self):
        Path("tmp").mkdir(exist_ok=True)
        folder = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        source = self.root / "source.json"
        url = "https://scontent.cdninstagram.com/public.jpg"
        source.write_text(json.dumps({"schema_version": 1, "actor": "apify/instagram-scraper", "policy_version": "public-metadata-v1", "items": [{"id": "1", "displayUrl": url}]}))
        self.plan = {"schema_version": "production-media-plan-v1", "entries": [{
            "asset_id": "instagram:1", "kind": "image", "url": url,
            "source_envelope": str(source), "source_envelope_sha256": file_hash(source), "source_item_index": 0}]}
        self.path = self.root / "plan.json"
        self.path.write_text(json.dumps(self.plan))

    def opener(self, data):
        class Opener:
            def open(self, *args, **kwargs):
                return Response(data)
        return Opener()

    def test_source_url_and_cdn_boundary(self):
        for url in ["http://s.cdninstagram.com/x", "https://cdninstagram.com.evil/x", "https://localhost/x", "https://s.fbcdn.net:bad/x"]:
            self.assertFalse(allowed_url(url))
        self.plan["entries"][0]["url"] = "https://s.fbcdn.net/other"
        with self.assertRaisesRegex(ValueError, "exact source"):
            validate_plan(self.plan)

    def test_real_bytes_hash_and_restart_without_fetch(self):
        data = b"\xff\xd8\xff" + b"test" * 20
        result = retain(self.path, self.root / "out", opener=self.opener(data))
        record = result["records"][0]
        self.assertEqual(record["status"], "downloaded")
        self.assertEqual(file_hash(Path(record["path"])), record["sha256"])
        self.assertEqual(retain(self.path, self.root / "out", opener=object()), result)

    def test_html_is_failed_not_retained_image(self):
        result = retain(self.path, self.root / "out", opener=self.opener(b"<html>login</html>"))
        self.assertEqual(result["summary"]["downloaded"], 0)
        self.assertEqual(result["records"][0]["status"], "failed")
        self.assertFalse(list((self.root / "out").glob("*.jpg")))

    def test_streaming_bound_counts_failed_bytes_and_removes_partial(self):
        with patch("czlake.production_media.MAX_FILE_BYTES", 8):
            result = retain(self.path, self.root / "out", opener=self.opener(b"\xff\xd8\xff" + b"a" * 100))
        self.assertEqual(result["summary"]["downloaded"], 0)
        self.assertEqual(result["summary"]["transferred_bytes"], 9)
        self.assertFalse(list((self.root / "out").glob(".media-*")))
