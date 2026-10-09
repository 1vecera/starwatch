import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from czlake.production_graph import Inputs
from czlake.production_ingest import pin_file
from czlake.production_logos import import_logo_supplement, logo_type


class LogoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0L10 10"/></svg>'
        page = self.pin('page.html', b'<html><head><title>Official Party</title></head><body><header><img src="/logo.svg" alt="Party logo"></header></body></html>')
        image = self.pin('logo.svg', self.svg)
        csv = b'KODZASTUP,OSTRANA,NAZEVCELK,SLOZENI\n1,2,Coalition,"53,80"\n'
        registry = self.pin('kvros.csv', csv)
        with zipfile.ZipFile(self.root/'release.zip', 'w') as z:
            z.writestr('csv_od/kvros.csv', csv)
        archive = self.pin('release.zip', (self.root/'release.zip').read_bytes())
        archive['source_url'] = 'https://volby.gov.cz/opendata/kv2026/KV2026reg20261007_csv.zip'
        self.brand = {'brand_id':'ods','brand_name':'Official Party','registered_party_code':'53','decision':'accept','reviewer':'native:/root','reviewed_at':'2026-10-09T04:00:00+00:00','observed_at':'2026-10-09T03:59:00+00:00','page':page,'image':image,'source_page_url':'https://party.example/','original_image_url':'https://party.example/logo.svg','source_title':'Official Party','source_image_pointer':'/html/body/header/img','source_attribute':'src','content_type':'image/svg+xml','lists':[{'entity_id':'kv2026:1:2','list_name':'Coalition','relationship':'member_party'}]}
        self.document = {'schema_version':'production-official-list-logos-v1','archive':archive,'registry':registry,'brands':[self.brand]}

    def pin(self, name, raw):
        path=self.root/name;path.write_bytes(raw)
        return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}

    def import_rows(self):
        path=self.root/'supplement.json';path.write_text(json.dumps(self.document))
        rows={'entity':[{'entity_id':'kv2026:1:2','kind':'local_list','name':'Coalition'}]}
        import_logo_supplement(rows, Inputs(self.root), path, pin_file)
        return rows

    def test_coalition_member_is_not_its_own_brand(self):
        rows=self.import_rows()
        self.assertEqual(rows['list_logo'][0]['relationship'],'member_party')
        self.assertFalse(rows['list_logo_coverage'][0]['has_list_brand'])
        self.brand['lists'][0]['relationship']='registered_party'
        with self.assertRaises(ValueError):self.import_rows()

    def test_membership_requires_official_composition(self):
        self.brand['registered_party_code']='768'
        with self.assertRaises(ValueError):self.import_rows()

    def test_source_url_cannot_be_swapped(self):
        self.brand['original_image_url']='https://party.example/other.svg'
        with self.assertRaises(ValueError):self.import_rows()

    def test_source_bytes_cannot_change(self):
        Path(self.brand['image']['path']).write_bytes(self.svg.replace(b'L10 10',b'L1 1'))
        with self.assertRaises(ValueError):self.import_rows()

    def test_active_or_external_svg_rejected(self):
        for body in (b'<script>alert(1)</script>',b'<image href="https://other.example/a.png"/>',b'<path onclick="alert(1)"/>',b'<style>@import "https://other.example/a.css";</style>'):
            with self.subTest(body=body),self.assertRaises(ValueError):
                logo_type(b'<svg xmlns="http://www.w3.org/2000/svg">'+body+b'</svg>')

    def test_embedded_data_uri_must_replay_exact_bytes(self):
        from urllib.parse import quote_from_bytes
        page=('<html><head><title>Official Party</title></head><body><header><img src="data:image/svg+xml,'+quote_from_bytes(self.svg)+'"></header></body></html>').encode()
        self.brand.update(page=self.pin('inline.html',page),source_encoding='data_uri',original_image_url='https://party.example/')
        self.assertEqual(len(self.import_rows()['list_logo']),1)
        self.brand['image']=self.pin('different.svg',self.svg.replace(b'L10 10',b'L1 1'))
        with self.assertRaises(ValueError):self.import_rows()


if __name__=='__main__':unittest.main()
