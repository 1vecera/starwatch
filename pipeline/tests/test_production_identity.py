import argparse
import importlib.util
import io
import os
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE=Path(__file__).resolve().parent
MODULE=BASE.parent/'src/czlake/production_identity.py'
spec=importlib.util.spec_from_file_location('production_identity',MODULE)
h=importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
SCRATCH=Path(os.environ.get('IDENTITY_TEST_SCRATCH',str(BASE/'tmp')))
SCRATCH.mkdir(parents=True,exist_ok=True)
h.NATIVE_ROOT=SCRATCH
T={'entity_id':'fixture-jan','name':'Jan Novák','city':'Brno','source_urls':['https://www.brno.cz/jan-novak']}

def page(content,body_class=''):
    return ('<html><head><meta charset="UTF-8"><title>Jan Novák</title></head><body class="'+body_class+'">'+content+'</body></html>').encode()

class Response(io.BytesIO):
    def __init__(self,data,length=None,status=200,extra=None):
        super().__init__(data); self.headers={'Content-Type':'text/html',**(extra or {})}; self.status=status; self.read_requests=[]
        if length is not None:self.headers['Content-Length']=str(length)
    def read(self,size=-1):self.read_requests.append(size); return super().read(size)

class Tests(unittest.TestCase):
    def test_encoding_role_and_permalinks(self):
        raw='<html><title>Jan Novák</title><body class="cookies--small"><main><p>Jan Novák má na starosti radnice města Brno.</p></main></body></html>'.encode()
        p=h.parse_page(raw,'https://brno.cz/jan-novak','https://brno.cz/jan-novak','now',[T])
        self.assertEqual(p['title'],'Jan Novák');self.assertTrue(p['identity_blocks'][T['entity_id']]);self.assertIsNone(p['identity_blocks'][T['entity_id']][0]['public_role_match'])
        self.assertIsNone(h.ROLE.search(h.fold('Mým posláním je náměstí a starosti radnice')))
        self.assertIsNone(h.account('https://facebook.com/photo.php?fbid=123'));self.assertIsNone(h.account('https://facebook.com/share.php?u=example'))
    def test_heading_keeps_name_and_excludes_nav_locality(self):
        raw=page('<section><h1><a href="/profile">Jan Novák</a></h1><nav>Brno zastupitel</nav><p>Žije a pracuje na jižní Moravě.</p></section>')
        p=h.parse_page(raw,'https://brno.cz/jan-novak','https://brno.cz/jan-novak','now',[T]);b=p['identity_blocks'][T['entity_id']][0]
        self.assertIn('Jan Novák',b['excerpt']);self.assertIsNone(b['locality_match']);self.assertIsNone(b['public_role_match'])
    def test_strict_cap(self):
        r=Response(b'x'*101); raw,error=h.read_bounded(r,100)
        self.assertEqual(len(raw),100); self.assertTrue(error); self.assertEqual(r.tell(),100); self.assertLessEqual(sum(r.read_requests),100)
        r=Response(b'x'*100,100); self.assertEqual(h.read_bounded(r,100),(b'x'*100,None))
        r=Response(b'x'*101,101); self.assertEqual(h.read_bounded(r,100),(b'','response_too_large')); self.assertEqual(r.tell(),0)
    def test_locality_footer_and_comments(self):
        raw=page('<nav>Brno primátor Jan Novák</nav><main><p>Jan Novák, zastupitel.</p></main><footer>Brno<a href="https://instagram.com/jannovak">Jan Novák</a></footer><div class="comments"><p>Jan Novák Brno tel. 123456789 x@y.cz</p></div>')
        p=h.parse_page(raw,'https://brno.cz/jan-novak','https://brno.cz/jan-novak','2026-10-09T00:00:00Z',[T])
        self.assertIsNone(p['identity_blocks'][T['entity_id']][0]['locality_match']); self.assertEqual(p['structural_links'][0]['section'],'footer'); self.assertNotIn('123456789',json.dumps(p)); self.assertNotIn('x@y.cz',json.dumps(p)); self.assertEqual(p['main_text'],'')
    def test_body_presentation_footer_does_not_hide_proof(self):
        raw=page('<main><section><p>Jan Novák, zastupitel města Brno.</p><a href="https://instagram.com/jannovak">Instagram</a></section></main>','use-footer-align--sm-center')
        p=h.parse_page(raw,'https://brno.cz/jan-novak','https://brno.cz/jan-novak','2026-10-09T00:00:00Z',[T])
        self.assertEqual(p['structural_links'][0]['section'],'body'); self.assertTrue(p['identity_blocks'][T['entity_id']][0]['locality_match'])
    def test_roster_not_asset(self):
        content='<main>'+''.join('<li>Jan Novák, zastupitel Brno '+('veřejný program politiky '*12)+'</li>' for _ in range(20))+'</main>'
        p=h.parse_page(page(content),'https://brno.cz/kandidati','https://brno.cz/kandidati','now',[T]); self.assertFalse(p['main_text'])
    def test_excerpt_legacy_and_scope_unknown(self):
        path=Path(__file__)
        p=h.cached_page({'source_url':'https://brno.cz/jan-novak','subject_spans':[{'excerpt':'Jan Novák, zastupitel Brno'}],'structural_links':[{'exact_href':'https://instagram.com/jannovak','subject_context':'Jan Novák, zastupitel Brno'}]},path,[T])
        self.assertTrue(p['target_spans'][T['entity_id']]); self.assertEqual(p['identity_blocks'],{}); self.assertEqual(p['structural_links'][0]['section'],'unknown_cached')
    def test_resume_and_no_overwrite_and_dns_record(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as scratch:
            root=Path(scratch); targets=root/'targets.json'; targets.write_text(json.dumps([T])); output=root/'out'
            args=argparse.Namespace(output_root=output,targets=targets,discovery=[],cache_root=[],city=[],target_id=[],shard_index=0,shard_count=1,max_gets=2,max_sources=2,concurrency=2,batch_size=1,offline=False,resume=False,retry_failures=False)
            runner=h.Harvest(args)
            with patch.object(socket,'getaddrinfo',side_effect=socket.gaierror):runner.fetch(T['source_urls'][0])
            self.assertEqual(runner.requests,[]);self.assertEqual(runner.failures[-1]['status'],'dns_failure')
            runner.args.offline=True;runner.run(); before=(output/'target_results').glob('*.json'); p=next(before); digest=h.sha(p.read_bytes())
            with self.assertRaises(ValueError):h.Harvest(args)
            args.resume=True;args.offline=True;r2=h.Harvest(args);r2.run();self.assertEqual(h.sha(p.read_bytes()),digest); self.assertEqual(len(r2.processed),1)
    def test_strong_remains_proposal(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as scratch:
            root=Path(scratch); targets=root/'targets.json';targets.write_text(json.dumps([T])); output=root/'out'
            args=argparse.Namespace(output_root=output,targets=targets,discovery=[],cache_root=[],city=[],target_id=[],shard_index=0,shard_count=1,max_gets=0,max_sources=2,concurrency=1,batch_size=1,offline=True,resume=False,retry_failures=False)
            runner=h.Harvest(args);p=h.parse_page(page('<main><section><p>Jan Novák, zastupitel města Brno.</p><a href="https://instagram.com/jannovak">Instagram</a></section></main>'),'https://www.brno.cz/jan-novak','https://www.brno.cz/jan-novak','2026-10-09T00:00:00Z',[T]); runner.save_page(p,'fixture');runner.run();c=runner.cards[0];self.assertEqual(c['decision'],'confirm_proposal');self.assertFalse(c['identity_confirmed']);self.assertEqual(c['adjudication'],'pending')
    def test_stale_template_wrong_handle_is_unknown(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as scratch:
            root=Path(scratch); targets=root/'targets.json';targets.write_text(json.dumps([T])); output=root/'out'
            args=argparse.Namespace(output_root=output,targets=targets,discovery=[],cache_root=[],city=[],target_id=[],shard_index=0,shard_count=1,max_gets=0,max_sources=2,concurrency=1,batch_size=1,offline=True,resume=False,retry_failures=False)
            runner=h.Harvest(args);p=h.parse_page(page('<main><section><p>Jan Novák, zastupitel města Brno.</p><a href="https://instagram.com/petrsvoboda">Instagram</a></section></main>'),'https://www.brno.cz/jan-novak','https://www.brno.cz/jan-novak','2026-10-09T00:00:00Z',[T]); runner.save_page(p,'fixture');runner.run();c=runner.cards[0];self.assertEqual(c['decision'],'unknown');self.assertFalse(c['account_name_consistency']);self.assertIsNone(c['public'])
    def test_discovery_does_not_retain_contact_snippets(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as scratch:
            root=Path(scratch);targets=root/'targets.json';targets.write_text(json.dumps([T]));output=root/'out'
            args=argparse.Namespace(output_root=output,targets=targets,discovery=[],cache_root=[],city=[],target_id=[],shard_index=0,shard_count=1,max_gets=0,max_sources=2,concurrency=1,batch_size=1,offline=True,resume=False,retry_failures=False)
            runner=h.Harvest(args);runner.add_discovery(T['entity_id'],{'url':'https://brno.cz/jan-novak/new','description':'Private postal contact: Example Street 9'});runner.seed_plans()
            self.assertNotIn('Example Street', (output/'source_plan.json').read_text());self.assertFalse(h.allowed('https://foaf.sk/osoba/123'));runner.file_lock.close()
    def test_supplement_refresh_preserves_history_and_budget(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as scratch:
            root=Path(scratch); targets=root/'targets.json';targets.write_text(json.dumps([T])); output=root/'out'
            args=argparse.Namespace(output_root=output,targets=targets,discovery=[],cache_root=[],city=[],target_id=[],shard_index=0,shard_count=1,max_gets=1,max_sources=2,concurrency=1,batch_size=1,offline=True,resume=False,retry_failures=False)
            r=h.Harvest(args);r.requests.append({'request_index':1,'source_url':'https://brno.cz/old','status':'http_failure','received_bytes':0});r.run()
            old={str(p):h.sha(p.read_bytes()) for p in (output/'target_results').glob('*.json')}
            supplement=root/'new.json';supplement.write_text(json.dumps({'targets':[{'entity_id':T['entity_id'],'sources':[{'url':'https://brno.cz/new'}]}]}))
            args.resume=True;args.refresh_results=True;args.supplement_discovery=[supplement];args.max_gets=2;r=h.Harvest(args);r.run()
            self.assertEqual(len(r.requests),1);self.assertEqual(len(list((output/'target_results').glob('*.json'))),2)
            self.assertTrue(all(h.sha(Path(p).read_bytes())==digest for p,digest in old.items()));self.assertIn('https://brno.cz/new',r.discoveries[T['entity_id']]);self.assertTrue((output/'config_history').exists())
    def test_canonical_redirect_and_missing_location_audited(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as scratch:
            root=Path(scratch); targets=root/'targets.json';targets.write_text(json.dumps([T])); output=root/'out'
            args=argparse.Namespace(output_root=output,targets=targets,discovery=[],cache_root=[],city=[],target_id=[],shard_index=0,shard_count=1,max_gets=3,max_sources=2,concurrency=1,batch_size=1,offline=False,resume=False,retry_failures=False)
            runner=h.Harvest(args)
            responses=[Response(b'',status=301,extra={'Location':'https://brno.cz/jan-novak'}),Response(page('<p>Jan Novák, zastupitel Brno.</p>'))]
            opener=unittest.mock.Mock();opener.open.side_effect=responses
            with patch.object(h,'resolve_public',return_value=[(None,None,None,None,('1.1.1.1',443))]),patch.object(h.urllib.request,'build_opener',return_value=opener):p=runner.fetch('https://brno.cz/jan-novak/')
            self.assertIsNotNone(p);self.assertEqual(len(runner.requests),2);self.assertEqual(runner.requests[0]['status'],'redirect');self.assertEqual(runner.requests[1]['status'],'parsed_saved')
            opener.open.side_effect=[Response(b'',status=302)]
            with patch.object(h,'resolve_public',return_value=[(None,None,None,None,('1.1.1.1',443))]),patch.object(h.urllib.request,'build_opener',return_value=opener):runner.fetch('https://brno.cz/missing')
            self.assertEqual(runner.requests[-1]['status'],'redirect_missing_location');self.assertEqual(len(runner.requests),3)
            self.assertFalse(h.allowed('https://wa.me/?text=foo'));self.assertFalse(h.safe_link('https://brno.cz/a b'))
            runner.file_lock.close()

if __name__=='__main__':unittest.main()
