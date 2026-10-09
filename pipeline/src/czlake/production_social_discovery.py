"""Fast offline all-qualifier social URL intake. Discovery never proves ownership."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl,urlunsplit,unquote

BASE=Path(__file__).resolve().parent
from . import production_identity as h
EXCLUDE={'share','share.php','sharer','sharer.php','login','dialog','plugins','watch','reel','reels','p','stories','explore','groups','events','hashtag','search','photo.php','permalink.php','story.php','video.php'}
INTAKE_VERSION='social-url-2'

def profile_url(raw):
    """Keep observed profiles separate from source-derived post publisher roots."""
    if not h.safe_link(raw):return None
    p=urlsplit(raw);host=h.host(raw);parts=[unquote(x) for x in p.path.split('/') if x]
    if p.scheme!='https':return None
    if not parts:return None
    if h.is_host(host,('instagram.com',)):
        platform='instagram'
        derived=len(parts)>1
        if parts[0].lower() in EXCLUDE or not re.fullmatch(r'[A-Za-z0-9._]{1,30}',parts[0]) or (derived and parts[1].lower() not in {'reels','tagged','channel','p','reel'}):return None
        return {'platform':platform,'handle':parts[0].lower(),'profile_url':'https://www.instagram.com/'+parts[0]+'/', 'profile_url_is_derived':derived,'observed_profile_url':None if derived else raw,'normalization_receipt':{'operation':'publisher root inferred from public subpage URL; discovery only' if derived else 'profile host/query normalization for collection discovery only','original_url':raw},'page_id':None}
    if h.is_host(host,('facebook.com','fb.com')):
        platform='facebook';first=parts[0].lower();derived=False;receipt=None
        if first=='profile.php':
            pairs=parse_qsl(p.query,keep_blank_values=True)
            ids=[v for k,v in pairs if k=='id']
            if len(ids)!=1 or not ids[0].isdigit():return None
            # Root authorized only a single original id= query for conversion.
            single=pairs==[('id',ids[0])]
            return {'platform':platform,'handle':ids[0],'profile_url':raw,'profile_url_is_derived':False,'observed_profile_url':raw,'page_id':ids[0] if single else None,'collection_page_id_normalization_allowed':single,'normalization_receipt':{'operation':'single exact profile.php?id URL conversion candidate' if single else 'extra query deferred; no numeric conversion','original_url':raw,'original_query_pairs':pairs},'deferred_reason':None if single else 'extra_query_profile_php_not_authorized_for_numeric_conversion'}
        if first in EXCLUDE:return None
        if first in {'people','pages'} and len(parts)>=3 and parts[-1].isdigit():
            return {'platform':platform,'handle':parts[-1],'profile_url':raw,'profile_url_is_derived':False,'observed_profile_url':raw,'page_id':None,'collection_page_id_normalization_allowed':False,'normalization_receipt':None}
        if len(parts)>1:
            if parts[1].lower() not in {'posts','photos','videos','about','reels','mentions','reviews'}:return None
            derived=True
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,120}',parts[0]):return None
        canonical='https://www.facebook.com/'+parts[0]+'/'
        if derived:receipt={'operation':'publisher root inferred from public post URL path; discovery only','original_url':raw,'derived_root':canonical}
        return {'platform':platform,'handle':parts[0].lower(),'profile_url':canonical,'profile_url_is_derived':derived,'observed_profile_url':None if derived else raw,'page_id':None,'collection_page_id_normalization_allowed':False,'normalization_receipt':receipt}
    if host in {'x.com','twitter.com'}:
        if parts[0].lower() in EXCLUDE or not re.fullmatch(r'[A-Za-z0-9_]{1,15}',parts[0]):return None
        derived=len(parts)>1
        if derived and parts[1].lower()!='status':return None
        return {'platform':'x','handle':parts[0].lower(),'profile_url':'https://x.com/'+parts[0],'profile_url_is_derived':derived,'observed_profile_url':None if derived else raw,'page_id':None,'normalization_receipt':{'operation':'publisher root inferred from post URL; discovery only','original_url':raw} if derived else None}
    return None


def intake(targets_path,envelopes,output_root,bindings_paths=()):
    output_root=output_root.resolve()
    if not output_root.is_relative_to(h.NATIVE_ROOT.resolve()):raise ValueError('isolated native output required')
    targets=json.loads(targets_path.read_text())['targets'];byid={t['entity_id']:t for t in targets}
    if len(targets)!=467 or len(byid)!=467:raise ValueError('all467 exact target register required')
    byquery={'"'+t['name']+'" "'+t['city']+'" (instagram OR facebook)':t for t in targets}
    inputs={str(targets_path.resolve()):h.sha(targets_path.read_bytes())};bound={}
    for path in bindings_paths:
        d=json.loads(path.read_text());inputs[str(path.resolve())]=h.sha(path.read_bytes())
        for b in d['bindings']:
            t=byid.get(b['entity_id'])
            if not t or t['name']!=b['name'] or t['city']!=b['city']:raise ValueError('query binding target mismatch')
            if b['query'] in bound and bound[b['query']]['entity_id']!=b['entity_id']:raise ValueError('ambiguous query binding')
            bound[b['query']]=b
    proposals=[];unmatched=[];target_queries=[]
    for path in envelopes:
        d=json.loads(path.read_text());digest=h.sha(path.read_bytes());inputs[str(path.resolve())]=digest
        observed=datetime.fromtimestamp(float(d['fetched_at_epoch']),timezone.utc).isoformat() if d.get('fetched_at_epoch') else datetime.now(timezone.utc).isoformat()
        for i,item in enumerate(d.get('items',[])):
            term=item.get('searchQuery',{}).get('term');binding=bound.get(term);target=byid.get(binding['entity_id']) if binding else byquery.get(term)
            if not target:unmatched.append({'source_path':str(path.resolve()),'source_pointer':f'/items/{i}','exact_query':term});continue
            target_queries.append({'entity_id':target['entity_id'],'source_path':str(path.resolve()),'source_pointer':f'/items/{i}','exact_query':term})
            for j,result in enumerate(item.get('organicResults',[])):
                exact=result.get('url','');account=profile_url(exact)
                if not account:continue
                identity={'entity_id':target['entity_id'],'person_id':target.get('person_id'),'name':target['name'],'city':target['city'],'entity_kind':target.get('entity_kind'),'selection':target['selection'],'qualified':target['qualified'],'eligible':target['eligible']}
                source={'source_path':str(path.resolve()),'source_sha256':digest,'source_pointer':f'/items/{i}/organicResults/{j}','exact_query':term,'result_position':result.get('position'),'exact_href':exact,'serp_result_url':exact,'batch_id':d.get('batch_id'),'run_id':d.get('run_id'),'observed_at':observed}
                title=h.clean(result.get('title',''))[:350]
                title_match=h.exact_name(title,target['name'])
                compact_handle=re.sub(r'[^a-z0-9]','',h.fold(account['handle']))
                tokens=[re.sub(r'[^a-z0-9]','',h.fold(w)) for w in target['name'].split()]
                handle_match=bool(tokens) and all(t and t in compact_handle for t in tokens)
                relation='observed_profile_result' if not account['profile_url_is_derived'] else 'derived_publisher_root_from_target_mention'
                evidence={**source,'discovery_relation':relation,'qualifier_name_match_in_title':title_match,'profile_handle_matches_full_name':handle_match}
                proposals.append({**identity,**account,**source,'proposal_id':h.sha((target['entity_id']+exact+digest).encode())[:24],'query':term,'ownership_status':'unknown','identity_confirmed':False,'publicness':'unknown','public_status':'unknown','anchor_links_account':False,'adjudication':'discovery_only','created_by_entity_id':None,'speaker_entity_id':None,'relation':'account_owner_proposal','discovery_relation':relation,'title':title if title_match and not account['profile_url_is_derived'] else None,'description':None,'qualifier_name_match_in_title':title_match,'profile_handle_matches_full_name':handle_match,'roster_name_profile_match':handle_match or (title_match and not account['profile_url_is_derived']),'evidence':[evidence],'privacy_note':'Only matching observed-profile title retained; all SERP descriptions/contact/commenter fields omitted'})
    key=h.sha(json.dumps({'inputs':inputs,'intake_version':INTAKE_VERSION},sort_keys=True).encode())[:20];batch=output_root/('intake-'+key)
    if batch.exists():
        stored=json.loads((batch/'input-hashes.json').read_text())
        if stored!=inputs:raise ValueError('intake identity collision')
        print(json.dumps({'status':'reused','path':str(batch),'proposals':len(json.loads((batch/'proposals.json').read_text())['proposals'])}));return batch
    batch.mkdir(parents=True)
    h.put(batch/'input-hashes.json',inputs);h.put(batch/'proposals.json',{'schema_version':1,'status':'discovery_only','proposals':proposals})
    for platform in ('instagram','facebook','x'):
        h.put(batch/(platform+'-proposals.json'),{'schema_version':1,'status':'discovery_only','proposals':[p for p in proposals if p['platform']==platform]})
    h.put(batch/'target-query-receipts.json',{'receipts':target_queries,'unmatched_queries':unmatched})
    summary={'schema_version':1,'status':'offline_intake_complete','observed_at':datetime.now(timezone.utc).isoformat(),'target_register_count':467,'envelopes':len(envelopes),'query_pages':len(target_queries),'queried_entities':len({q['entity_id'] for q in target_queries}),'proposal_rows':len(proposals),'unique_profile_urls':len({(p['platform'],p['profile_url']) for p in proposals}),'unique_entity_profiles':len({(p['entity_id'],p['platform'],p['profile_url']) for p in proposals}),'per_platform':dict(Counter(p['platform'] for p in proposals)),'exact_observed_profile_rows':sum(not p['profile_url_is_derived'] for p in proposals),'derived_publisher_root_rows':sum(p['profile_url_is_derived'] for p in proposals),'unmatched_queries':len(unmatched),'network_gets':0,'paid_calls':0,'shared_writes':0,'ownership_admissions':0}
    h.put(batch/'summary.json',summary);h.put(batch/'hashes.json',{str(p.resolve()):h.sha(p.read_bytes()) for p in batch.glob('*.json')});print(json.dumps({**summary,'path':str(batch)},ensure_ascii=False));return batch

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--targets',type=Path,required=True);p.add_argument('--discovery',type=Path,action='append',required=True);p.add_argument('--bindings',type=Path,action='append',default=[]);p.add_argument('--output-root',type=Path,required=True);a=p.parse_args();intake(a.targets,a.discovery,a.output_root,a.bindings)
