import importlib.util
import json
import os
import sys
import types
import tempfile
import unittest
from pathlib import Path

BASE=Path(__file__).resolve().parent
MODULE=BASE.parent/'src/czlake/production_social_discovery.py'
pkg=types.ModuleType('identity_draft');pkg.__path__=[str(MODULE.parent)];sys.modules['identity_draft']=pkg
s=importlib.util.spec_from_file_location('identity_draft.production_social_discovery',MODULE);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
SCRATCH=Path(os.environ.get('IDENTITY_TEST_SCRATCH',str(BASE/'tmp')))
SCRATCH.mkdir(parents=True,exist_ok=True)
m.h.NATIVE_ROOT=SCRATCH

class IntakeTests(unittest.TestCase):
    def test_observed_and_derived_are_separate(self):
        p=m.profile_url('https://www.instagram.com/jan_novak/');self.assertFalse(p['profile_url_is_derived']);self.assertEqual(p['handle'],'jan_novak')
        p=m.profile_url('https://facebook.com/jannovak/posts/123_999');self.assertTrue(p['profile_url_is_derived']);self.assertIsNone(p['page_id']);self.assertIsNone(p['observed_profile_url'])
        p=m.profile_url('https://www.instagram.com/jan_novak/reels/');self.assertTrue(p['profile_url_is_derived'])
        self.assertIsNone(m.profile_url('https://instagram.com/reel/ABC'));self.assertIsNone(m.profile_url('https://facebook.com/share.php?u=x'))
    def test_exact_profile_php_conversion_only(self):
        p=m.profile_url('https://www.facebook.com/profile.php?id=12345');self.assertTrue(p['collection_page_id_normalization_allowed']);self.assertEqual(p['page_id'],'12345')
        p=m.profile_url('https://www.facebook.com/profile.php?id=12345&locale=cs_CZ');self.assertFalse(p['collection_page_id_normalization_allowed']);self.assertIsNone(p['page_id']);self.assertTrue(p['deferred_reason'])
        self.assertIsNone(m.profile_url('http://www.facebook.com/profile.php?id=12345'))
        self.assertIsNone(m.profile_url('https://www.facebook.com/profile.php?id=12345&id=678'))
    def test_query_bound_privacy_and_idempotence(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as folder:
            root=Path(folder);targets=[{'entity_id':str(i),'person_id':None,'name':'Person '+str(i),'city':'Brno','selection':'first300' if i<300 else 'overflow167','qualified':True,'eligible':True} for i in range(467)]
            targetfile=root/'targets.json';targetfile.write_text(json.dumps({'targets':targets}))
            envelope=root/'p030.json';envelope.write_text(json.dumps({'batch_id':'fixture','fetched_at_epoch':1,'items':[{'searchQuery':{'term':'"Person 0" "Brno" (instagram OR facebook)'},'organicResults':[{'url':'https://www.instagram.com/person0/','title':'private address','description':'phone 123456789 contact@example.com','position':1},{'url':'https://facebook.com/person0/posts/123_999','position':2}]}]}))
            out=m.intake(targetfile,[envelope],root/'out');d=json.loads((out/'proposals.json').read_text());self.assertEqual(len(d['proposals']),2);self.assertTrue(all(p['ownership_status']=='unknown' and not p['identity_confirmed'] for p in d['proposals']));self.assertNotIn('contact@example.com',(out/'proposals.json').read_text());self.assertEqual(d['proposals'][0]['source_pointer'],'/items/0/organicResults/0')
            before=(out/'proposals.json').read_bytes();self.assertEqual(out,m.intake(targetfile,[envelope],root/'out'));self.assertEqual(before,(out/'proposals.json').read_bytes())

if __name__=='__main__':unittest.main()
