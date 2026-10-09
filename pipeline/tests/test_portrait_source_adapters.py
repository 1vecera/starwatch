"""Behavior checks for explicit retained source adapters and publisher evidence."""
import json
import unittest
from pathlib import Path

from test_production_graph import save
import test_production_images as fixtures
import production_images as images


class SourceValueTests(unittest.TestCase):
    def test_bom_and_utf8_keep_czech_name(self):
        dom = images.retained_dom(b'\xef\xbb\xbf' + '<p>Čeněk Šimůnek</p>'.encode())
        self.assertEqual(dom.text_content(), 'Čeněk Šimůnek')

    def test_picfit_original_is_exact_known_municipal_recipe(self):
        page = 'https://www.brno.cz/zastupitelstvo'
        original = 'https://www.brno.cz/documents/20121/0/portrait.jpg/uuid'
        dom = images.retained_dom(('<img src="/picfit/display?url='+original+'&amp;w=80&amp;op=resize">').encode())
        self.assertIn(original, images.retained_image_urls(dom, page))
        for wrong in ['https://attacker.example/picfit/display?url='+original, '/picfit/display?url='+original+'&amp;url=https://www.brno.cz/documents/evil.jpg', '/picfit/display?url=https://attacker.example/x.jpg']:
            node = images.retained_dom(('<img src="'+wrong+'">').encode())
            self.assertNotIn(original, images.retained_image_urls(node, page))

    def test_linked_original_requires_image_child(self):
        page='https://official.example/roster'
        image=images.retained_dom(b'<a href="/original.jpg"><img src="/thumb.jpg"></a>')
        ordinary=images.retained_dom(b'<a href="/original.jpg">Article</a>')
        self.assertIn('https://official.example/original.jpg',images.retained_image_urls(image,page))
        self.assertNotIn('https://official.example/original.jpg',images.retained_image_urls(ordinary,page))

    def test_css_image_is_literal_and_city_forms_are_bounded(self):
        image=images.retained_dom(b'<div style="background-image: url(\'/portrait.webp\')"></div>')
        self.assertIn('https://official.example/portrait.webp',images.retained_image_urls(image,'https://official.example/'))
        self.assertTrue(images.city_in_text('Hradec Králové','Zastupitel v Hradci Králové'))
        self.assertTrue(images.city_in_text('Praha','Zastupitel města Prahy'))
        self.assertFalse(images.city_in_text('Brno','Nové Brnovice'))
        self.assertFalse(images.city_in_text('Praha','Prachatice'))


class PublisherEvidenceTests(unittest.TestCase):
    setUp = fixtures.ImageTests.setUp
    tearDown = fixtures.ImageTests.tearDown
    sha = fixtures.ImageTests.sha
    export = fixtures.ImageTests.export
    update_review = fixtures.ImageTests.update_review

    def configure_publisher_roster(self):
        self.raw.write_text('<html><head><title>Council roster</title></head><body><main><h2>Candidate council</h2><figure><p>Same Name local candidate</p><img src="/photo.png" alt="Same Name"/></figure></main></body></html>')
        digest=self.sha(self.raw)
        self.source['original_source']['sha256']=digest
        self.image['source_page']['raw_page_sha256']=digest
        review_path=Path(self.source['identity_evidence']['binding_review']['path'])
        review=json.loads(review_path.read_text())
        verdict=review['reviews']['source-image-1']
        verdict.pop('target_specific_proof')
        verdict['source_page_sha256']=digest
        scope_path=self.root/'roster-scope.json'
        packet={'raw_sha256':digest,'original_source':{'path':str(self.raw),'sha256':digest},'scope':{'dom_pointer':'/html/body/main','heading':{'dom_pointer':'/html/body/main/h2','text':'Candidate council'},'city_title':{'dom_pointer':'/html/head/title','text':'Council roster'},'cards':[{'dom_pointer':'/html/body/main/figure','text':'Same Name local candidate','images':[{'dom_pointer':'/html/body/main/figure/img','url':self.image['original_image_url']}]}]}}
        save(scope_path,packet)
        verdict['roster_scope']={'scope_source':{'path':str(scope_path),'sha256':self.sha(scope_path),'pointer':'/scope'}}
        publisher_dir=self.root/'tmp/production/native/publisher_reviewer'
        publisher_dir.mkdir(parents=True)
        legal=publisher_dir/'legal.html'
        legal.write_text('<html><body><main><p>Město Fixture city</p></main></body></html>')
        receipt=publisher_dir/'retrieval.json'
        save(receipt,{'final_url':'https://official.example/legal','path':str(legal),'sha256':self.sha(legal)})
        proof={'schema_version':'independently-reviewed-municipal-publisher-v1','reviewer':'native:/root/publisher_reviewer','decision':'accept','city':'Fixture city','hostname':'official.example','source_url':'https://official.example/legal','source_path':str(legal),'source_sha256':self.sha(legal),'identity_pointer':'/html/body/main/p','identity_text':'Město Fixture city','retrieval_receipt_path':str(receipt),'retrieval_receipt_sha256':self.sha(receipt)}
        proof_path=publisher_dir/'proof.json'
        save(proof_path,proof)
        self.source['identity_evidence']['publisher_city_proof']={'path':str(proof_path),'sha256':self.sha(proof_path)}
        self.update_review(review)
        return proof_path,proof,legal,review,scope_path,packet

    def test_official_publisher_city_and_same_scoped_heading_pass(self):
        self.configure_publisher_roster()
        result=self.export('publisher-roster')
        self.assertEqual(result['quality']['status'],'passed')

    def test_copied_publisher_city_and_other_hostname_fail(self):
        path,proof,legal,review,scope_path,packet=self.configure_publisher_roster()
        for field,value in [('identity_text','Město Fixture city invented'),('hostname','unrelated.example')]:
            original=proof[field]
            proof[field]=value
            save(path,proof)
            self.source['identity_evidence']['publisher_city_proof']['sha256']=self.sha(path)
            self.update_review(review)
            with self.assertRaises(ValueError):self.export('bad-publisher')
            proof[field]=original

    def test_publisher_proof_cannot_supply_person_role_from_footer(self):
        path,proof,legal,review,scope_path,packet=self.configure_publisher_roster()
        self.raw.write_text(self.raw.read_text().replace('<h2>Candidate council</h2>','<footer><h2>Candidate council</h2></footer>'))
        digest=self.sha(self.raw)
        self.source['original_source']['sha256']=digest
        self.image['source_page']['raw_page_sha256']=digest
        review['reviews']['source-image-1']['source_page_sha256']=digest
        packet['raw_sha256']=digest
        packet['original_source']['sha256']=digest
        packet['scope']['heading']['dom_pointer']='/html/body/main/footer/h2'
        save(scope_path,packet)
        review['reviews']['source-image-1']['roster_scope']['scope_source']['sha256']=self.sha(scope_path)
        self.update_review(review)
        with self.assertRaisesRegex(ValueError,'physically bind'):self.export('footer-role')


class NamedRoleCardTests(unittest.TestCase):
    setUp = fixtures.ImageTests.setUp
    tearDown = fixtures.ImageTests.tearDown
    sha = fixtures.ImageTests.sha
    export = fixtures.ImageTests.export
    update_review = fixtures.ImageTests.update_review

    def configure_role(self, role_pointer):
        self.raw.write_text('<html><head><title>Fixture city</title></head><body><main><div>Candidate council unrelated</div><figure><p>Same Name local candidate</p><img src="/photo.png" alt="Same Name"/></figure></main></body></html>')
        digest=self.sha(self.raw)
        self.source['original_source']['sha256']=digest
        self.image['source_page']['raw_page_sha256']=digest
        path=Path(self.source['identity_evidence']['binding_review']['path'])
        review=json.loads(path.read_text())
        verdict=review['reviews']['source-image-1']
        verdict['source_page_sha256']=digest
        anchor=verdict['target_specific_proof']['sources'][0]
        anchor.update(sha256=digest,role_pointer=role_pointer,exact_role='candidate')
        verdict['target_specific_proof']['image_page_binding']['sha256']=digest
        self.update_review(review)

    def test_actual_role_inside_named_image_card_passes(self):
        self.configure_role('/html/body/main/figure/p')
        self.assertEqual(self.export('role-in-card')['quality']['status'],'passed')

    def test_named_card_block_boundary_before_contact_is_preserved(self):
        self.raw.write_text('<html><head><title>Fixture city</title></head><body><main><h1>Candidate council</h1><figure><p>Same Name</p><p>public-contact@example.test</p><img src="/photo.png"/></figure></main></body></html>')
        digest=self.sha(self.raw)
        self.source['original_source']['sha256']=digest
        self.image['source_page']['raw_page_sha256']=digest
        path=Path(self.source['identity_evidence']['binding_review']['path'])
        review=json.loads(path.read_text())
        verdict=review['reviews']['source-image-1']
        verdict['source_page_sha256']=digest
        verdict['target_specific_proof']['sources'][0]['sha256']=digest
        verdict['target_specific_proof']['image_page_binding']['sha256']=digest
        self.update_review(review)
        self.assertEqual(self.export('named-block-boundary')['quality']['status'],'passed')

    def test_bounded_card_name_survives_adjacent_role_block(self):
        self.raw.write_text('<html><head><title>Fixture city</title></head><body><main><figure><p>Same Name</p><p>candidate in Fixture city</p><img src="/photo.png"/></figure></main></body></html>')
        digest=self.sha(self.raw)
        self.source['original_source']['sha256']=digest
        self.image['source_page']['raw_page_sha256']=digest
        path=Path(self.source['identity_evidence']['binding_review']['path'])
        review=json.loads(path.read_text())
        verdict=review['reviews']['source-image-1']
        verdict['source_page_sha256']=digest
        verdict.pop('target_specific_proof')
        verdict['exact_proof']=[{'source_path':str(self.raw),'source_packet_sha256':digest,'dom_pointer':'/html/body/main/figure'}]
        self.update_review(review)
        self.assertEqual(self.export('bounded-named-block-boundary')['quality']['status'],'passed')

    def test_unrelated_div_role_outside_card_cannot_be_borrowed(self):
        self.configure_role('/html/body/main/div')
        with self.assertRaisesRegex(ValueError,'actual named image card'):
            self.export('borrowed-role-div')


if __name__=='__main__':unittest.main()
