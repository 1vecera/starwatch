import pathlib, struct, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'src/czlake'))
import production_portraits as p

T={'entity_id':'one','person_id':'p1','name':'Jan Šimek','city':'Brno','entity_kind':'qualified_candidate'}
T2={'entity_id':'two','person_id':'p2','name':'Petra Nová','city':'Brno'}
class PortraitTests(unittest.TestCase):
    def test_unrelated_footer_role_city_cannot_identify_namesake(self):
        raw='<div class="card"><img src="/jan.jpg" alt="Jan Šimek"/><span>Jan Šimek manager Praha</span></div><footer>zastupitel Brno</footer>'.encode()
        items=p.extract_candidates(raw,'https://party.example/',[T]);self.assertEqual(items[0]['admission_status'],'candidate')
    def test_avif_original_brand_and_dimensions(self):
        ftyp=struct.pack('>I',24)+b'ftypavif'+b'\0'*4+b'avifmif1'
        ispe=struct.pack('>I',20)+b'ispe'+b'\0'*4+struct.pack('>II',218,270)
        self.assertEqual(p.image_info(ftyp+ispe),('image/avif',218,270))
    def test_cumulative_ledger_resume(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d,'retrieval_manifest.json').write_text(json.dumps({'requests':[{'request_index':1,'status':'failed'}]}))
            fetcher=p.PublicFetcher(d,max_gets=1);self.assertEqual(len(fetcher.records),1)
            with self.assertRaises(ValueError):p.PublicFetcher(d,max_gets=0)
    def test_complete_content_length_does_not_touch_closed_tls(self):
        payload=b'\x89PNG\r\n\x1a\n'+b'\0'*8+struct.pack('>II',640,480)
        class Socket:
            closed=False
            def settimeout(self,value):
                if self.closed:raise OSError('Bad file descriptor')
            def connect(self,addr):pass
            def close(self):self.closed=True
        tls=Socket()
        class Response:
            status=200
            def getheader(self,key,default=None):return {'Content-Length':str(len(payload)),'Content-Type':'image/png'}.get(key,default)
            def read(self,n):tls.closed=True;return payload
            def isclosed(self):return tls.closed
        class Conn:
            def __init__(self,*args,**kwargs):self.sock=None
            def request(self,*args,**kwargs):pass
            def getresponse(self):return Response()
            def close(self):pass
        class Context:
            def wrap_socket(self,*args,**kwargs):return tls
        with tempfile.TemporaryDirectory() as d:
            fetcher=p.PublicFetcher(d,cutoff='2099-01-01T00:00:00+00:00')
            with patch.object(fetcher,'resolve',return_value=[(p.socket.AF_INET,p.socket.SOCK_STREAM,6,'',('93.184.216.34',443))]),patch.object(p.socket,'socket',return_value=Socket()),patch.object(p.ssl,'create_default_context',return_value=Context()),patch.object(p.http.client,'HTTPSConnection',Conn):
                result,error=fetcher.fetch('https://public.example/photo.png','image')
            self.assertIsNone(error);self.assertEqual(result['bytes'],len(payload));self.assertEqual(fetcher.records[0]['status'],'downloaded')
    def test_utf8_name_and_exact_label(self):
        raw='<html><h1>Kandidáti Brno</h1><div><img src="/jan.jpg" alt="Jan Šimek"/>Jan Šimek zastupitel Brno</div></html>'.encode()
        items=p.extract_candidates(raw,'https://party.example/',[T]);self.assertEqual(len(items),1);self.assertEqual(items[0]['admission_status'],'admitted');self.assertEqual(items[0]['original_image_url'],'https://party.example/jan.jpg')
    def test_logos_and_svg_not_candidates(self):
        raw='<h1>Jan Šimek Brno zastupitel</h1><img src="/logo.jpg" alt="Jan Šimek"/><img src="/shape.svg" alt="Jan Šimek"/>'.encode()
        self.assertEqual(p.extract_candidates(raw,'https://party.example/',[T]),[])
    def test_script_role_cannot_admit(self):
        raw='<script>zastupitel Brno</script><img src="/jan.jpg" alt="Jan Šimek"/>'.encode();items=p.extract_candidates(raw,'https://party.example/',[T]);self.assertEqual(items[0]['admission_status'],'candidate')
    def test_multiple_known_people_label_excluded(self):
        raw='<h1>Kandidáti Brno</h1><img src="/people.jpg" alt="Jan Šimek a Petra Nová"/>'.encode();self.assertEqual(p.extract_candidates(raw,'https://party.example/',[T,T2]),[])
    def test_unlisted_second_person_group_not_admitted(self):
        raw='<h1>zastupitelé Brno</h1><img src="/people.jpg" alt="Jan Šimek and John Doe"/>'.encode();items=p.extract_candidates(raw,'https://party.example/',[T]);self.assertTrue(not items or items[0]['admission_status']=='candidate')
    def test_header_navigation_image_excluded(self):
        raw='<header><img src="/jan.jpg" alt="Jan Šimek"/>Jan Šimek zastupitel Brno</header>'.encode();self.assertEqual(p.extract_candidates(raw,'https://party.example/',[T]),[])
    def test_person_hostname_does_not_name_all_images(self):
        raw='<h1>Jan Šimek</h1><div>zastupitel Brno</div><img src="/unrelated.jpg"/>'.encode();self.assertEqual(p.extract_candidates(raw,'https://jansimek.cz/',[T]),[])
    def test_roster_not_a_person_card(self):
        raw='<div>Jan Šimek Petra Nová Brno zastupitelé<img src="/photo.jpg"/></div>'.encode();self.assertEqual(p.extract_candidates(raw,'https://party.example/',[T,T2]),[])
    def test_collapsed_sibling_name_is_recovered(self):
        raw='<div><img src="/jan.jpg"/><span>Jan Šimek</span><span>zastupitel Brno</span></div>'.encode();self.assertEqual(p.extract_candidates(raw,'https://party.example/',[T])[0]['admission_status'],'admitted')
    def test_raster_magic_and_dimensions(self):
        raw=b'\x89PNG\r\n\x1a\n'+b'\0'*8+struct.pack('>II',640,480);self.assertEqual(p.image_info(raw),('image/png',640,480))
        with self.assertRaises(ValueError):p.image_info(b'<svg>fake</svg>')
    def test_public_url_requires_https_no_credentials_standard_port(self):
        for url in ['http://example.com/x','https://user:secret@example.com/x','https://example.com:8443/x','https://example.com/\nfoo']:
            self.assertFalse(p.public_url(url))
    def test_private_resolution_blocks_before_get(self):
        with tempfile.TemporaryDirectory() as d:
            f=p.PublicFetcher(d,cutoff='2099-01-01T00:00:00+00:00')
            with patch.object(p.socket,'getaddrinfo',return_value=[(p.socket.AF_INET,p.socket.SOCK_STREAM,6,'',('127.0.0.1',443))]):
                data,error=f.fetch('https://public.example/photo.jpg','image')
            self.assertIsNone(data);self.assertEqual(error,'non_public_ip');self.assertEqual(len(f.records),0)
    def test_explicit_unknown_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            index=p.save_index(d,[T],[]);self.assertEqual(index['targets'][0]['portrait_status'],'unknown');self.assertEqual(index['target_count'],1)
if __name__=='__main__':unittest.main()
