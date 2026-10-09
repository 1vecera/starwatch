from __future__ import annotations
import copy,hashlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'src/czlake'))
from test_production_graph import AS_OF,SCRATCH,fixture,graph,save
spec=importlib.util.spec_from_file_location('czlake.isolated_facebook_ingest',HERE/'src/czlake/production_ingest.py')
ingest=importlib.util.module_from_spec(spec);spec.loader.exec_module(ingest)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

class FacebookBridgeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=SCRATCH);self.root=Path(self.tmp.name);self.paths=fixture(self.root);self.production=self.root/'production';self.pid='100063690744459';self.vanity='https://www.facebook.com/komrskova.jana';self.reviewer='native:/root/identity_review_west'
  self.official=self.root/'official.json';save(self.official,{'source_url':'https://official.example/person','structural_links':[{'exact_href':self.vanity}]})
  prior={'entity_id':'alice-candidacy','platform':'facebook','profile_url':self.vanity,'decision':'accepted','adjudication':'confirmed_owner_url_only','source_url':'https://official.example/person','observed_at':AS_OF,'reviewer_identity':self.reviewer,'evidence_path':str(self.official),'evidence_sha256':sha(self.official)}
  self.prior=self.root/'prior.json';save(self.prior,{'reviewer_identity':self.reviewer,'proposals':[prior]})
  row={'postId':'5','text':'Public post','url':self.vanity+'/posts/5','topLevelUrl':f'https://www.facebook.com/{self.pid}/posts/5','inputUrl':self.vanity,'pageName':'komrskova.jana','user':{'id':self.pid,'profileUrl':f'https://www.facebook.com/{self.pid}'},'likes':1,'time':AS_OF}
  self.raw=self.production/'raw/apify/fb.json';save(self.raw,{'schema_version':1,'policy_version':'public-metadata-v1','actor':'apify/facebook-posts-scraper','batch_id':'fb','run_id':'fb-run','fetched_at_epoch':__import__('datetime').datetime.fromisoformat(AS_OF).timestamp(),'input_sha256':'a'*64,'manifest_sha256':'b'*64,'items':[row]})
  meta=[{'attribute':'canonical','content':self.vanity,'exact_element':'<link rel="canonical" href="'+self.vanity+'">','xpath':'/html/head/link'},{'attribute':'og:url','content':self.vanity,'exact_element':'<meta property="og:url" content="'+self.vanity+'">','xpath':'/html/head/meta[1]'},{'attribute':'al:android:url','content':'fb://profile/'+self.pid,'exact_element':'<meta property="al:android:url" content="fb://profile/'+self.pid+'">','xpath':'/html/head/meta[2]'}]
  self.evidence=self.root/'metadata.json';save(self.evidence,{'schema_version':'production-fb-public-profile-metadata-v1','entity_id':'alice-candidacy','http_status':200,'response_truncated':False,'observed_at':AS_OF,'raw_sha256':'a'*64,'numeric_page_id':self.pid,'source_url':self.vanity,'final_url':self.vanity,'reviewed_owner_url':self.vanity,'metadata':meta,'profile_header_queries':[{'selectedID':self.pid,'userID':self.pid,'queryName':'ProfileCometHeaderQuery','exact_json':json.dumps({'variables':{'selectedID':self.pid,'userID':self.pid},'queryName':'ProfileCometHeaderQuery'})[1:-1]}],'reviewed_proof_path':str(self.prior),'reviewed_proof_sha256':sha(self.prior),'reviewed_proof_pointer':'/proposals/0','provider_observations':[{'raw_path':str(self.raw),'raw_sha256':sha(self.raw),'source_pointer':'/items/0','author_id':self.pid,'author_profile_url':row['user']['profileUrl']}]})
  proof={'platform':'facebook','profile_url':f'https://www.facebook.com/{self.pid}/','source_url':'https://official.example/person','observed_at':AS_OF,'adjudication':'confirmed','identity_confirmed':True,'anchor_links_account':True,'public':True,'exact_href':self.vanity,'page_id':self.pid,'page_id_link_confirmed':True,'reviewer_identity':self.reviewer,'facebook_binding':{'kind':'official_vanity_public_metadata_numeric','proposer':'native:/root/facebook_binding','independent_reviewer':self.reviewer,'status':'accepted','reviewed_at':AS_OF,'evidence_path':str(self.evidence),'evidence_sha256':sha(self.evidence)}}
  self.review=self.root/'review-fb.json';save(self.review,{'reviewer_identity':self.reviewer,'candidates':{'alice-candidacy':proof},'lists':{}})
 def tearDown(self):self.tmp.cleanup()
 def edit(self,path,fn):
  d=json.loads(path.read_text());fn(d);save(path,d)
 def refresh(self):self.edit(self.review,lambda d:d['candidates']['alice-candidacy']['facebook_binding'].update(evidence_sha256=sha(self.evidence)))
 def build(self,extra=()):
  rows,inputs,date=graph.build_cached_graph(self.root,relevance_dir=self.root/'relevance',reviews=[self.paths['review']],identity_path=self.paths['identity'],as_of=AS_OF)
  return ingest.extend_graph(rows,inputs,date,production_root=self.production,identity_reviews=[self.review,*extra],helpers={'handle':graph.handle,'confirmed_owner':graph.confirmed_owner,'normalize_metric':graph.normalize_metric})
 def relation(self,rows):return next(r for r in rows['account_relation'] if r['account_id']=='facebook:'+self.pid)
 def test_verified_chain_admits_numeric_owner_and_post(self):
  rows=self.build();self.assertEqual(self.relation(rows)['status'],'confirmed');self.assertEqual(next(a for a in rows['asset'] if a['asset_id']=='facebook:5')['verification_status'],'verified_publication_owner')
 def test_request_echo_cannot_replace_observed_canonical(self):
  self.edit(self.evidence,lambda d:d.update(metadata=[m for m in d['metadata'] if m['attribute'] not in ('canonical','og:url')]));self.refresh();self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_other_canonical_page_rejected(self):
  self.edit(self.evidence,lambda d:d['metadata'][0].update(content='https://www.facebook.com/another'));self.refresh();self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_header_and_app_disagreement_rejected(self):
  self.edit(self.evidence,lambda d:d['profile_header_queries'][0].update(userID='999'));self.refresh();self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_conflicting_app_ids_rejected(self):
  self.edit(self.evidence,lambda d:d['metadata'].append({'attribute':'al:ios:url','content':'fb://profile/999'}));self.refresh();self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_provider_request_echo_with_different_author_rejected(self):
  self.edit(self.raw,lambda d:d['items'][0]['user'].update(id='999',profileUrl='https://www.facebook.com/999'));self.edit(self.evidence,lambda d:d['provider_observations'][0].update(raw_sha256=sha(self.raw)));self.refresh();self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_same_reviewer_as_proposer_rejected(self):
  self.edit(self.review,lambda d:d['candidates']['alice-candidacy']['facebook_binding'].update(independent_reviewer='native:/root/facebook_binding'));self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_canonical_scalar_disagrees_with_exact_element_rejected(self):
  self.edit(self.evidence,lambda d:d['metadata'][0].update(exact_element='<link rel="canonical" href="https://www.facebook.com/another">'));self.refresh();self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_header_scalar_disagrees_with_exact_json_rejected(self):
  self.edit(self.evidence,lambda d:d['profile_header_queries'][0].update(exact_json='"variables":{"selectedID":"999","userID":"999"},"queryName":"ProfileCometHeaderQuery"'));self.refresh();self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_official_packet_missing_actual_vanity_anchor_rejected(self):
  self.edit(self.official,lambda d:d.update(structural_links=[]));self.edit(self.prior,lambda d:d['proposals'][0].update(evidence_sha256=sha(self.official)));self.edit(self.evidence,lambda d:d.update(reviewed_proof_sha256=sha(self.prior)));self.refresh();self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_empty_independent_reviewer_rejected(self):
  def blank(d):
   d['reviewer_identity']='';p=d['candidates']['alice-candidacy'];p['reviewer_identity']='';p['facebook_binding']['independent_reviewer']=''
  self.edit(self.review,blank);self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_additional_conflicting_header_query_rejected(self):
  self.edit(self.evidence,lambda d:d['profile_header_queries'].append({'selectedID':'999','userID':'999','queryName':'ProfileCometHeaderQuery','exact_json':'"variables":{"selectedID":"999","userID":"999"},"queryName":"ProfileCometHeaderQuery"'}));self.refresh();self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_scoped_single_anchor_official_packet_supported(self):
  self.edit(self.official,lambda d:(d.pop('structural_links'),d.update(exact_href=self.vanity,ancestors=[{'text':'Alice public official'}])));self.edit(self.prior,lambda d:d['proposals'][0].update(evidence_sha256=sha(self.official)));self.edit(self.evidence,lambda d:d.update(reviewed_proof_sha256=sha(self.prior)));self.refresh();self.assertEqual(self.relation(self.build())['status'],'confirmed')
 def test_pinned_metadata_tamper_blocks_export(self):
  self.edit(self.evidence,lambda d:d.update(http_status=404));self.assertRaises(ValueError,self.build)
 def test_p001_author_container_guard_survives_valid_account_bridge(self):
  self.edit(self.raw,lambda d:d['items'].append({**copy.deepcopy(d['items'][0]),'postId':'6','topLevelUrl':'https://www.facebook.com/999/posts/6','url':self.vanity+'/posts/6'}));self.edit(self.evidence,lambda d:d['provider_observations'][0].update(raw_sha256=sha(self.raw)));self.refresh();rows=self.build();self.assertEqual(self.relation(rows)['status'],'confirmed');self.assertEqual(next(a for a in rows['asset'] if a['asset_id']=='facebook:6')['verification_reason'],'facebook_author_page_mismatch')
 def test_conflicting_exact_owner_reviews_block_existing_bridge(self):
  proof=copy.deepcopy(json.loads(self.review.read_text())['candidates']['alice-candidacy']);proof.pop('facebook_binding');proof['exact_href']='https://www.facebook.com/'+self.pid
  other=self.root/'other-review.json';save(other,{'candidates':{'bob-candidacy':proof},'lists':{}});rows=self.build([other]);self.assertEqual(self.relation(rows)['status'],'conflicted');self.assertEqual(next(a for a in rows['asset'] if a['asset_id']=='facebook:5')['verification_reason'],'conflicting_independent_owner_reviews')
 def test_old_exact_numeric_anchor_still_accepted(self):
  self.edit(self.review,lambda d:(d['candidates']['alice-candidacy'].pop('facebook_binding'),d['candidates']['alice-candidacy'].update(exact_href='https://www.facebook.com/'+self.pid)));self.assertEqual(self.relation(self.build())['status'],'confirmed')
 def test_actual_resumed_proposer_and_root_review_supported(self):
  def resumed(d):
   d['reviewer_identity']='native:/root';p=d['candidates']['alice-candidacy'];p['reviewer_identity']='native:/root';p['facebook_binding'].update(proposer='native:/root/media_platform_resume',independent_reviewer='native:/root')
  self.edit(self.review,resumed);self.assertEqual(self.relation(self.build())['status'],'confirmed')
 def test_resumed_proposer_cannot_self_review(self):
  def resumed(d):
   identity='native:/root/media_platform_resume';d['reviewer_identity']=identity;p=d['candidates']['alice-candidacy'];p['reviewer_identity']=identity;p['facebook_binding'].update(proposer=identity,independent_reviewer=identity)
  self.edit(self.review,resumed);self.assertEqual(self.relation(self.build())['status'],'unknown')
 def test_native_identity_aliases_rejected(self):
  for identity in ['native:/root/','native:/root/a/../media_platform_resume','native:/root//media_platform_resume','native:/root/./media_platform_resume','external-reviewer']:
   self.edit(self.review,lambda d:d['candidates']['alice-candidacy']['facebook_binding'].update(proposer=identity));self.assertEqual(self.relation(self.build())['status'],'unknown')
if __name__=='__main__':unittest.main()
