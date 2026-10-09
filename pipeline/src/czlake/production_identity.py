#!/usr/bin/env python3
"""Bounded resumable public-identity acquisition in isolated production shards.

CLI: ``python -m czlake.production_identity --help``. All identity outputs are
proposals; independent ownership review remains required before graph admission.
The CLI never calls a paid service, fetches a social page, or writes the lake.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import ipaddress
import http.client
import json
import re
import socket
import threading
import time
import fcntl
import os
import copy
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from lxml import html

BASE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('CZLAKE_PROJECT', '/home/vecera/code/agents007-hackathon'))
MAX_GETS = 100
MAX_BYTES = 4_000_000
TIMEOUT = 10
CONCURRENCY = 6
PRIORITY = ['Plzeň', 'Hradec Králové', 'České Budějovice', 'Praha', 'Brno', 'Ostrava', 'Liberec', 'Olomouc', 'Pardubice', 'Ústí nad Labem']
POLITICAL = re.compile(r'primator|starost|mistostar|namest|zastupitel|radni|predsed|kandidat|komunal|volb|politic|politika|ods|pirat|kdu|top 09|hnuti|stan\b|program|koalic')
OFFICIAL_HOSTS = ('ods.cz','top09.cz','kdu.cz','pirati.cz','starostove.cz','anobudelip.cz','zeleni.cz','svobodni.cz','praha.eu','praha9.cz','praha18.cz','kolovraty.cz','brno.cz','ostrava.cz','plzen.eu','liberec.cz','vratislavice.cz','olomouc.eu','c-budejovice.cz','hradeckralove.org','pardubice.eu','usti.cz','pardubickykraj.cz','msk.cz','kraj-jihocesky.cz')
PARTY_LOCAL = {'stanplzen.cz','proplzen.cz','odsbudejce.cz','zahradec.cz','starostoveolomouc.cz','odsolomouc.cz','jednousti.cz','spoluprousti.cz','spolecne-usti.cz','srdcempropardubice.cz','libereckadevitka.cz','liberecka9.cz','lepsi-liberec.cz','tymbrno.cz','za-luzanky.cz','brnonejlepsiadresa.cz','brnoblizlidem.cz','volimprahu.cz','vlasta10.cz','prahasobe.cz','hnutispolecne.cz','proolomouc.cz','ostravak.cz','nezavisli.cz','starostoveprolibereckykraj.cz'}
SOCIAL = ('instagram.com','facebook.com','fb.com','fb.me','twitter.com','x.com','linkedin.com','tiktok.com','threads.net','youtube.com','youtu.be','spotify.com','apple.com','wa.me','whatsapp.com','t.me','telegram.me')
BLOCKED = ('sazkynavolby.cz','zdeneknytra.cz','kurzynavolby.cz','yield3.app','preddy.trade','seznam.cz','google.com','google.cz','apify.com','api.apify.com','lide.cz','wikipedia.org','wikidata.org','researchgate.net','prijmeni.cz','fakturujzdarma.cz','foaf.sk','foaf.cz')
AUTH_PATH = re.compile(r'/(?:login|logout|sign(?:in|up|on|out)?|authorize|oauth|authentication)(?:[/.?]|$)',re.I)
AUTH_HOST = re.compile(r'^(?:auth|accounts|login|ucet|sso|oauth)\.',re.I)
BAD_PATH = re.compile(r'/diskus|/komentare|/comment|/question|/otazka|/kontakt|/kontakty|/components/form/|/statistiky/|/usneseni/|/uloziste/|bin_soubor|/assets/file\.ashx|/sflf/get|smlouva/soubor|spamprotection|rejstrik',re.I)
MEDIA = re.compile(r'\.(?:pdf|mp4|mp3|m4a|ogg|wav|jpe?g|png|gif|webp|avif|svg|ico|docx?|xlsx?|zip)(?:$|[?#])|at_download/file|/storage/get/|/issue/download/', re.I)
EMAIL = re.compile(r'[\w.+-]+\s*(?:@|\[at\])\s*[\w.-]+\.[A-Za-z]{2,}')
PHONE = re.compile(r'(?<!\w)(?:\+420\s*)?(?:\d[\s\u00a0().-]*){9}(?!\w)')
DROP_ATTR = re.compile(r'comment|diskus|discussion|disqus|repl(?:y|ies)|engager|visitor|cookie|consent|tracking|newsletter|related|sidebar|advert|banner|share-buttons|social-feed|socialfeed|instagram-feed|facebook-feed|cff-|sbi_|contact-directory|contacts-list|adresar', re.I)


def now(): return datetime.now(timezone.utc).isoformat()
def sha(b): return hashlib.sha256(b).hexdigest()
def fold(s): return ''.join(c for c in unicodedata.normalize('NFKD',s.lower()) if not unicodedata.combining(c))
def clean(s):
    s = re.sub(r'\s+', ' ', s or '').strip()
    return PHONE.sub('[phone omitted]', EMAIL.sub('[email omitted]',s))
def host(u): return (urllib.parse.urlsplit(u).hostname or '').lower().removeprefix('www.')
def is_host(h, domains): return any(h == d or h.endswith('.'+d) for d in domains)
def official(u): return is_host(host(u),OFFICIAL_HOSTS) or host(u) in PARTY_LOCAL

def norm_url(u):
    p=urllib.parse.urlsplit(u)
    q=urllib.parse.parse_qsl(p.query,keep_blank_values=True)
    q=[(k,v) for k,v in q if not k.lower().startswith(('utm_','srsltid','fbclid','gclid'))]
    return urllib.parse.urlunsplit((p.scheme,p.netloc,p.path or '/',urllib.parse.urlencode(q),'')).rstrip('/')

def allowed(u):
    try:
        p=urllib.parse.urlsplit(u); h=host(u)
        if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or re.search(r'[\x00-\x20\x7f]',u): return False
        if any(k.lower() in {'text','share','url','u'} for k,v in urllib.parse.parse_qsl(p.query)): return False
        if not h or is_host(h,SOCIAL+BLOCKED+('predplatne.denik.cz',)) or AUTH_HOST.search(h) or AUTH_PATH.search(urllib.parse.unquote(p.path)) or BAD_PATH.search(urllib.parse.unquote(u)) or MEDIA.search(u):return False
        if re.search(r'kurzy.cz|hlidacstatu|programydovoleb|poradnaproobce|penize.cz|finance.cz|firmy.euro|cylex|infobel|maptons|zlatestranky|antikavion|nacr.cz|library.|journals.|autoconfig|finreg|orsr.sk|podnikatel|pravednes|demagog|zastupko|dostartu|celebwiki|slaviste',h):return False
        ip=None
        try: ip=ipaddress.ip_address(h)
        except ValueError: pass
        return ip is None or ip.is_global
    except ValueError:return False

def safe_link(u):
    try:
        p=urllib.parse.urlsplit(u)
        return p.scheme in ('http','https') and not p.username and not p.password and p.hostname and len(u)<1800 and not AUTH_HOST.search(p.hostname) and not AUTH_PATH.search(urllib.parse.unquote(p.path)) and not re.search(r'[\x00-\x20\x7f]',u) and not re.search(r'(?:token|password|email|form_build_id|access_token|api_key|state|nonce|session|sessionid|code)=',u,re.I) and not EMAIL.search(u)
    except ValueError:return False

def account(u):
    p=urllib.parse.urlsplit(u); h=host(u); parts=[urllib.parse.unquote(x) for x in p.path.split('/') if x]
    if h in ('instagram.com','facebook.com','twitter.com','x.com','fb.com'):
        platform='instagram' if h=='instagram.com' else 'facebook' if h in ('facebook.com','fb.com') else 'x'
        if not parts:return None
        if parts[0].lower() in {'p','reel','reels','stories','explore','share','share.php','sharer.php','sharer','dialog','intent','watch','groups','events','login','hashtag','search','plugins','photo.php','permalink.php','story.php','video.php','sharer-sharer.php'}:return None
        if platform=='facebook' and parts[0]=='profile.php':
            value=dict(urllib.parse.parse_qsl(p.query)).get('id')
            return (platform,value,u) if value and value.isdigit() else None
        if any(x.lower() in {'posts','videos','photos','status','with_replies','all'} for x in parts[1:]):return None
        if parts[0]=='pages' and len(parts)>=3:return (platform,parts[-1],u)
        if len(parts)>1:return None
        return platform,parts[0],u
    return None

SCHEMA = 2
PARSER_VERSION = 'identity-engine-4'
ROLE = re.compile(r'\b(?:primator(?:ka|ky|kou|em|a|ovi|i|u)?|(?:misto)?starost(?:a|ka|y|ky|kou|ou|u|ovi|ove|ek)?|namest(?:ek|ka|kem|ci|ku|kum|kyne|kyni|kyn|ky|kach)|zastupitel(?:ka|ky|kou|ku|em|e|i|u|um|ech)?|radni(?:m|ho|ch)?|predsed\w*|kandidat\w*|politic\w*|poslan(?:ec|ce|cem|ci|cu|cum|cich|kyne|kyni|kyn)|senator\w*|hnuti|koalic\w*)\b')
CHROME = re.compile(r'footer|paticka|menu|navigation|sidebar|related|contact|kontakt|breadcrumb|cookie|consent|comment|diskus|discussion|disqus|reply|replies', re.I)
CONTENT_TAGS = {'p', 'h1', 'h2', 'h3', 'li', 'td', 'dd'}
NATIVE_ROOT = ROOT/'tmp/production/native'


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.pending')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n')
    tmp.replace(path)
    return sha(path.read_bytes())


def exact_name(text, name):
    return bool(re.search(r'(?<!\w)'+re.escape(fold(name))+r'(?!\w)', fold(text)))


def locality_match(text, target):
    # Explicit full locality / supplied grammatical aliases only; no first-word match.
    aliases = [target['city']]+target.get('locality_aliases', [])
    grammatical = {'Praha':['Prahy','Praze'], 'Brno':['Brna','Brně'], 'Ostrava':['Ostravy','Ostravě'], 'Plzeň':['Plzně','Plzni'], 'Liberec':['Liberce','Liberci'], 'Olomouc':['Olomouce','Olomouci'], 'Pardubice':['Pardubic','Pardubicích'], 'Hradec Králové':['Hradce Králové','Hradci Králové'], 'České Budějovice':['Českých Budějovic','Českých Budějovicích'], 'Ústí nad Labem':['Ústí nad Labem']}
    aliases += grammatical.get(target['city'], [])
    return next((a for a in aliases if exact_name(text, a)), None)


def chrome(node):
    return any(isinstance(n.tag, str) and n.tag not in {'html','body','main'} and (n.tag.lower() in {'nav','header','footer','aside'} or CHROME.search(' '.join(n.get(k,'') for k in ('id','class','role','aria-label')))) for n in [node]+list(node.iterancestors()))


def section(node):
    for n in [node]+list(node.iterancestors()):
        if n.tag in {'html','body','main'}: continue
        attrs=' '.join(n.get(k,'') for k in ('id','class','role','aria-label'))
        if n.tag == 'footer' or re.search(r'footer|paticka', attrs, re.I): return 'footer'
        if n.tag in ('nav','header','aside') or CHROME.search(attrs): return 'navigation'
    return 'body'


def body_context(node):
    return clean(' '.join(str(s) for s in node.xpath('.//text()') if not chrome(s.getparent())))


def nearby_context(node):
    # Stop before page-wide containers: an anchor next to a biography may be used,
    # but a whole roster/body cannot provide person scope to a shared account link.
    best = body_context(node)
    for parent in node.iterancestors():
        if parent.tag in {'html','body','main'}: break
        text = body_context(parent)
        if len(text)>1600: break
        best = text
        if parent.tag in {'article','li','tr','section'}: break
    return best[:1600]


def parse_page(raw, source, final, fetched, targets):
    try:
        decoded = raw.decode('utf-8')
    except UnicodeDecodeError:
        decoded = raw  # lxml uses a declared legacy charset when UTF-8 is invalid.
    doc = html.fromstring(decoded, base_url=final)
    title = clean(' '.join(doc.xpath('//title/text()')))[:350]
    dates=[]
    for el in doc.xpath('//meta[@content] | //time[@datetime]'):
        key=(el.get('property') or el.get('name') or '').lower()
        value=el.get('datetime') if el.tag=='time' else el.get('content')
        if (el.tag=='time' or key in {'article:published_time','datepublished','date','pubdate','publishdate'}) and re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[T ].{1,32})?',value or ''):
            dates.append({'value':value,'method':'explicit time datetime' if el.tag=='time' else 'explicit publication meta','exact_attribute':key or 'datetime'})
    for el in list(doc.iter()):
        if not isinstance(el.tag,str):
            if el.getparent() is not None: el.getparent().remove(el)
            continue
        attrs=' '.join(el.get(k,'') for k in ('class','id','role','aria-label'))
        if el.tag.lower() in {'script','style','noscript','iframe','form','input','textarea','select','button','svg','address'} or (el.tag not in {'html','body','main'} and (DROP_ATTR.search(attrs) or re.search(r'fb-page|fb-post|fb-like|fb-comments|fb-root|facebook-widget|facebook-plugin|instagram-widget',attrs,re.I))):
            if el.getparent() is not None: el.drop_tree()
    for el in doc.xpath('//a[starts-with(@href,"mailto:") or starts-with(@href,"tel:")]'): el.drop_tree()
    blocks=[]
    for el in doc.iter():
        if not isinstance(el.tag,str) or el.tag.lower() not in CONTENT_TAGS or chrome(el): continue
        # Outermost block only, avoiding repeated paragraph/list text.
        if any(a.tag in CONTENT_TAGS for a in el.iterancestors()): continue
        value=clean(' '.join(el.itertext()))
        if len(value)<3 or len(value)>12000: continue
        if re.search(r'^e-mail|^telefon|^mobil|^fax|^adresa|\bdatum narozeni\b|\bnarozen[aiy]?\s+\d|\bmanzel|\bdeti\b',fold(value)): continue
        blocks.append({'text':value,'tag':el.tag.lower(),'path':doc.getroottree().getpath(el),'linked_fraction':sum(len(clean(' '.join(a.itertext()))) for a in el.xpath('.//a'))/max(len(value),1)})
    identities={}
    for t in targets:
        matches=[]
        for i,b in enumerate(blocks):
            if not exact_name(b['text'],t['name']): continue
            # Adjacent unlinked prose may establish local profile role, never nav/title.
            context=b['text']
            if b['tag'].startswith('h'):
                context=' '.join([b['text']]+[x['text'] for x in blocks[i+1:i+4] if x['tag']=='p' and x['linked_fraction']<0.5])[:1600]
                node=doc.getroottree().xpath(b['path'])
                scoped=nearby_context(node[0]) if node else ''
                if len(scoped)>len(context) and exact_name(scoped,t['name']): context=scoped
            if not exact_name(context,t['name']): continue
            matches.append({'excerpt':context[:1800],'exact_name':t['name'],'public_role_match':ROLE.search(fold(context)).group(0) if ROLE.search(fold(context)) else None,'locality_match':locality_match(context,t),'section':'body','block_path':b['path']})
            if len(matches)>=4: break
        if matches: identities[t['entity_id']]=matches
    links=[]; seen=set()
    for el in doc.xpath('//a[@href]'):
        href=el.get('href','').strip(); resolved=urllib.parse.urljoin(final,href)
        if not safe_link(resolved) or resolved in seen: continue
        label=clean(' '.join(el.itertext()))[:200]; ac=account(resolved)
        kind='account_link' if ac else 'discovered_media' if MEDIA.search(resolved) or is_host(host(resolved),('youtube.com','youtu.be')) else 'political_navigation'
        if not ac and not MEDIA.search(resolved) and not is_host(host(resolved),('youtube.com','youtu.be')) and not re.search(r'program|kandidat|nasi-lide|nasi-zastup|/persons/|/profil|/o-mne|/o-nas|/lide|/team|/tym|clenove|zastupitel',fold(urllib.parse.urlsplit(resolved).path+' '+label)) and not any(exact_name(label,t['name']) or fold(t['name']).replace(' ','-') in fold(urllib.parse.unquote(urllib.parse.urlsplit(resolved).path)) for t in targets): continue
        context=nearby_context(el)
        ids=[t['entity_id'] for t in targets if exact_name(context,t['name'])]
        links.append({'exact_href':href,'resolved_url':resolved,'label':label,'section':section(el),'context':context,'target_ids_in_context':ids,'kind':kind})
        seen.add(resolved)
        if len(links)>=500: break
    # Roster/list summaries and menus never become assets. Require substantial
    # unlinked prose in p elements, with at least two long paragraphs.
    prose=[b['text'] for b in blocks if b['tag']=='p' and len(b['text'])>=160 and b['linked_fraction']<0.35]
    body_text='\n\n'.join(prose)
    roster_hint=bool(re.search(r'(?:/kandidati(?:/|$)|/nasi-lide(?:/|$)|/clenove-zastupitelstva|/slozeni-zastupitelstva|/team(?:[/?]|$)|/author/|/tag/|/stitek/|/category/|/volby/(?:vysledky|celkove))',fold(final)))
    meaningful=len(prose)>=2 and len(body_text)>=550 and bool(POLITICAL.search(fold(body_text))) and not roster_hint
    text=body_text[:24000] if meaningful else ''
    return {'schema_version':SCHEMA,'source_url':source,'final_url':final,'fetched_at':fetched,'raw_sha256':sha(raw),'raw_bytes':len(raw),'title':title,'target_spans':{eid:[m['excerpt'] for m in matches] for eid,matches in identities.items()},'identity_blocks':identities,'structural_links':links,'main_text':text,'main_text_status':'substantive' if meaningful else 'identity_or_navigation_only','main_text_sha256':sha(text.encode()) if text else None,'text_truncated':meaningful and len(body_text)>24000,'explicit_publication_dates':dates[:3],'omitted_content_reason':['scripts/forms/embedded feeds/discussion/comments/contact channels omitted','email and phone patterns omitted','navigation excluded from identity/locality/content proof','no raw HTML retained'],'parser_version':PARSER_VERSION}


def cached_page(old, path, targets):
    """Historical sanitized caches may supply spans/anchors, never strong proofs."""
    source=old.get('source_url') or old.get('url'); final=old.get('final_url',source)
    if not source or not allowed(source) or not allowed(final): return None
    spans={}; values=old.get('subject_spans',[])
    for t in targets:
        vals=[clean(v.get('excerpt',v.get('text','')) if isinstance(v,dict) else v) for v in values]
        vals += [clean(v) for v in old.get('target_spans',{}).get(t['entity_id'],[])]
        matches=list(dict.fromkeys(v for v in vals if exact_name(v,t['name'])))
        if matches: spans[t['entity_id']]=matches[:4]
    links=[]
    for link in old.get('structural_links',[]):
        href=link.get('exact_href',''); resolved=link.get('resolved_url') or link.get('resolved_href') or urllib.parse.urljoin(final,href)
        if not safe_link(resolved): continue
        links.append({'exact_href':href,'resolved_url':resolved,'label':clean(link.get('label','')),'section':'unknown_cached','context':clean(link.get('subject_context',link.get('context',''))),'target_ids_in_context':[],'kind':link.get('kind','political_navigation')})
    return {'schema_version':SCHEMA,'source_url':source,'final_url':final,'http_status':old.get('http_status',old.get('status',200)),'fetched_at':old.get('fetched_at',old.get('observed_at')),'raw_sha256':old.get('raw_sha256'),'raw_bytes':old.get('raw_bytes',0),'title':clean(old.get('title','')),'target_spans':spans,'identity_blocks':{},'structural_links':links,'main_text':'','main_text_status':'historical_sanitized_identity_only','main_text_sha256':None,'text_truncated':False,'explicit_publication_dates':[],'omitted_content_reason':['historical sanitized structure; full article not available','historical location/section not independently established','no raw HTML retained'],'parser_version':'identity-engine-2','upstream_evidence_path':str(path),'upstream_evidence_sha256':sha(path.read_bytes())}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def read_bounded(response, cap=MAX_BYTES, deadline=None):
    """Never ask/read cap+1. At cap without exact Content-Length, abstain."""
    length=response.headers.get('Content-Length','')
    size=int(length) if length.isdigit() else None
    if size is not None and size>cap: return b'', 'response_too_large'
    chunks=[]; received=0
    while received<cap:
        if deadline is not None:
            remaining=deadline-time.monotonic()
            if remaining<=0: raise TimeoutError('response_deadline')
            try: response.fp.raw._sock.settimeout(min(TIMEOUT,remaining))
            except AttributeError: pass
        chunk=response.read(min(65536,cap-received))
        if not chunk: return b''.join(chunks), None
        chunks.append(chunk); received+=len(chunk)
        if size is not None and received>=size: return b''.join(chunks), None
    return b''.join(chunks), None if size==cap else 'response_cap_reached_completeness_unknown'


def resolve_public(name, semaphore):
    # OS resolution does not honor socket timeouts. Bound caller waiting and
    # limit lingering resolver threads to the shard's network concurrency.
    if not semaphore.acquire(timeout=TIMEOUT): raise TimeoutError('dns_slot_timeout')
    done=threading.Event(); result={}
    def run():
        try: result['addresses']=socket.getaddrinfo(name,443,type=socket.SOCK_STREAM)
        except Exception as e: result['error']=e
        finally: semaphore.release(); done.set()
    threading.Thread(target=run,daemon=True).start()
    if not done.wait(TIMEOUT): raise TimeoutError('dns_resolution_timeout')
    if 'error' in result: raise result['error']
    return result['addresses']


class Harvest:
    def __init__(self,args):
        self.args=args; self.base=args.output_root.resolve(); self.lock=threading.RLock(); self.pages={}; self.requests=[]; self.failures=[]; self.discoveries=defaultdict(dict); self.cards=[]; self.assets=[]; self.processed=[]; self.plans={}
        self.dns_semaphore=threading.BoundedSemaphore(args.concurrency)
        if not self.base.is_relative_to(NATIVE_ROOT.resolve()): raise ValueError('output-root must be isolated under tmp/production/native')
        self.base.mkdir(parents=True,exist_ok=True)
        self.file_lock=(self.base/'.run.lock').open('a+')
        fcntl.flock(self.file_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        target_data=json.loads(args.targets.read_text())
        rows=target_data if isinstance(target_data,list) else target_data.get('targets',target_data.get('candidates',[]))
        self.targets=[]
        for r in rows:
            t=dict(r); t['entity_id']=str(t.get('entity_id') or t.get('key') or t.get('id') or '')
            if not all(isinstance(t.get(k),str) and t[k] for k in ('entity_id','name','city')): raise ValueError('target requires entity_id/key, name, city')
            if args.city and t['city'] not in args.city: continue
            if args.target_id and t['entity_id'] not in args.target_id: continue
            self.targets.append(t)
        if len({t['entity_id'] for t in self.targets})!=len(self.targets): raise ValueError('duplicate target entity_id')
        self.targets=self.targets[args.shard_index::args.shard_count]
        if not self.targets: raise ValueError('selected shard contains no targets')
        args.supplement_discovery=getattr(args,'supplement_discovery',[])
        args.refresh_results=getattr(args,'refresh_results',False)
        self.input_hashes={str(p.resolve()):sha(p.read_bytes()) for p in [args.targets]+args.discovery}
        config={'schema_version':SCHEMA,'inputs':self.input_hashes,'target_ids':[t['entity_id'] for t in self.targets],'max_gets':args.max_gets,'max_sources':args.max_sources,'cache_roots':[str(p.resolve()) for p in args.cache_root],'policy':{'max_response_bytes':MAX_BYTES,'timeout_seconds':TIMEOUT,'network_concurrency':args.concurrency,'paid_calls':0}}
        config_path=self.base/'run_config.json'
        if config_path.exists():
            if not args.resume: raise ValueError('output already exists; use --resume with exact matching config or choose new output-root')
            original=json.loads(config_path.read_text())
            comparable=dict(original); comparable['max_gets']=config['max_gets']
            if comparable!=config: raise ValueError('resume inputs/config mismatch; use --supplement-discovery for new discovery or choose new output-root')
            if original!=config:
                put(self.base/'config_history'/(str(time.time_ns())+'.json'),original)
                put(config_path,config)
            manifest=json.loads((self.base/'retrieval_manifest.json').read_text()) if (self.base/'retrieval_manifest.json').exists() else {}
            self.requests=manifest.get('requests',[]); self.failures=manifest.get('failure_events',[])
            for r in self.requests:
                if r['status']=='pending': r.update(status='interrupted_unknown',finished_at=now())
            if len(self.requests)>args.max_gets: raise ValueError('resume max-gets below existing request count')
            for p in sorted((self.base/'evidence').glob('page-*.json')):
                d=json.loads(p.read_text())
                if d.get('parser_version')!=PARSER_VERSION:
                    d.update(retrieval_mode='cached_sanitized_structure',main_text='',main_text_sha256=None,identity_blocks={})
                key=norm_url(d['source_url']); existing=self.pages.get(key)
                if existing and existing.get('parser_version')==PARSER_VERSION and existing.get('retrieval_mode')!='cached_sanitized_structure': continue
                self.pages[key]={**d,'evidence_path':str(p),'evidence_sha256':sha(p.read_bytes())}
            latest={}
            for p in (self.base/'target_results').glob('*.json'):
                d=json.loads(p.read_text())
                if d['entity_id'] not in latest or d['updated_at']>latest[d['entity_id']]['updated_at']: latest[d['entity_id']]=d
            if not args.refresh_results:
                for d in latest.values(): self.processed.append(d['entity_id']); self.cards.extend(d['cards']); self.assets.extend(d['assets'])
        else:
            if any(p.name!='.run.lock' for p in self.base.iterdir()): raise ValueError('new output-root must be empty')
            put(config_path,config)
        supplement_path=self.base/'supplement_inputs.json'
        supplements=json.loads(supplement_path.read_text()) if supplement_path.exists() else {}
        for p in args.supplement_discovery:
            key=str(p.resolve()); digest=sha(p.read_bytes())
            if key in supplements and supplements[key]!=digest: raise ValueError('supplement input changed; preserve original and use new path')
            supplements[key]=digest
        for path,digest in supplements.items():
            if sha(Path(path).read_bytes())!=digest: raise ValueError('stored supplement hash mismatch')
        put(supplement_path,supplements); self.input_hashes.update(supplements)
        self.discovery_inputs=args.discovery+[Path(p) for p in supplements]
        self.load_discovery(); self.load_cache(); self.augment(); self.seed_plans(); self.persist_manifest()

    def __del__(self):
        lock=getattr(self,'file_lock',None)
        if lock is not None and not lock.closed: lock.close()

    def load_discovery(self):
        byid={t['entity_id']:t for t in self.targets}; byquery={t.get('query'):t for t in self.targets if t.get('query')}
        for t in self.targets:
            for u in t.get('source_urls',[])+t.get('identity_anchor_urls',[]):
                self.add_discovery(t['entity_id'],{'url':u,'origin':'explicit_target_anchor'})
        for path in self.discovery_inputs:
            data=json.loads(path.read_text()); rows=data if isinstance(data,list) else data.get('items',data.get('discoveries',data.get('targets',[])))
            for r in rows:
                eid=str(r.get('entity_id') or r.get('key') or '')
                term=r.get('searchQuery',{}).get('term') if isinstance(r.get('searchQuery',{}),dict) else None
                target=byid.get(eid) or byquery.get(term)
                if not target and term:
                    matches=[t for t in self.targets if exact_name(term,t['name']) and locality_match(term,t)]
                    if len(matches)==1: target=matches[0]
                if not target: continue
                entries=r.get('organicResults',r.get('sources',[r]))
                for entry in entries:
                    self.add_discovery(target['entity_id'],{**entry,'origin':entry.get('origin','discovery_envelope'),'discovery_path':str(path),'discovery_sha256':sha(path.read_bytes())})

    def add_discovery(self,eid,row):
        u=row.get('url') or row.get('source_url')
        if not isinstance(u,str) or not safe_link(u): return
        if allowed(u) or account(u) or MEDIA.search(u): self.discoveries[eid].setdefault(norm_url(u),{'url':u,'title':clean(row.get('title','')),'description':'','origin':row.get('origin','discovery'),'position':row.get('position'),'referrer':row.get('referrer')})

    def save_page(self,d,mode):
        d['retrieval_mode']=mode
        p=self.base/'evidence'/('page-'+sha(norm_url(d['source_url']).encode())[:24]+'-'+mode+'-'+PARSER_VERSION+'-'+str(d.get('raw_sha256') or sha(json.dumps(d,sort_keys=True).encode()))[:12]+'.json')
        if p.exists(): return self.pages.get(norm_url(d['source_url']))
        digest=put(p,d); self.pages[norm_url(d['source_url'])]={**d,'evidence_path':str(p),'evidence_sha256':digest}
        return self.pages[norm_url(d['source_url'])]

    def load_cache(self):
        for root in self.args.cache_root:
            for path in sorted(root.rglob('*.json')):
                try:
                    old=json.loads(path.read_text())
                    if not isinstance(old,dict): continue
                    u=old.get('source_url') or old.get('url')
                    if not u or not allowed(u): continue
                    existing=self.pages.get(norm_url(u))
                    if existing and existing.get('retrieval_mode')!='cached_sanitized_structure': continue
                    if old.get('http_status',old.get('status',200))!=200: continue
                    final=old.get('final_url',u)
                    if not allowed(final): continue
                    raw_name=old.get('path') or old.get('raw_source_path')
                    rawpath=Path(raw_name or '')
                    if raw_name and not rawpath.is_absolute(): rawpath=path.parent/rawpath
                    if raw_name and rawpath.is_file() and rawpath.stat().st_size<=MAX_BYTES:
                        raw=rawpath.read_bytes(); d=parse_page(raw,u,final,old.get('observed_at',old.get('fetched_at')),self.targets)
                        d.update(http_status=200,cache_metadata_path=str(path),cache_metadata_sha256=sha(path.read_bytes()),cache_raw_path=str(rawpath))
                        self.save_page(d,'cached_html_reparsed')
                    elif not existing and ('structural_links' in old or 'subject_spans' in old or 'target_spans' in old):
                        d=cached_page(old,path,self.targets)
                        if d: self.save_page(d,'cached_sanitized_structure')
                except (OSError,ValueError,TypeError,KeyError) as e:
                    self.failures.append({'status':'cache_parse_failure','path':str(path),'error_type':type(e).__name__,'observed_at':now(),'http_get_count':0})

    def augment(self):
        for p in self.pages.values():
            for t in self.targets:
                eid=t['entity_id']
                if eid in p['target_spans']: self.add_discovery(eid,{'url':p['source_url'],'title':p['title'],'origin':'cached_exact_target_mention'})
                for l in p['structural_links']:
                    if allowed(l['resolved_url']) and (exact_name(l['label'],t['name']) or fold(t['name']).replace(' ','-') in fold(urllib.parse.unquote(urllib.parse.urlsplit(l['resolved_url']).path))): self.add_discovery(eid,{'url':l['resolved_url'],'title':l['label'],'origin':'exact_structural_link','referrer':p['source_url']})

    def rank(self,t,r):
        text=fold(r.get('title','')+' '+r.get('description','')+' '+urllib.parse.unquote(r['url']))
        return 60*official(r['url'])+30*(norm_url(r['url']) in {norm_url(u) for u in t.get('identity_anchor_urls',[])})+20*exact_name(text,t['name'])+15*(fold(t['name']).replace(' ','-') in text)+10*bool(locality_match(text,t))+5*bool(POLITICAL.search(text))-30*bool(re.search(r'/tag|/stitek|/wiki|/volby/celkove|vysledky',r['url']))

    def seed_plans(self):
        for t in self.targets: self.plans[t['entity_id']]=sorted([r for r in self.discoveries[t['entity_id']].values() if allowed(r['url'])],key=lambda r:self.rank(t,r),reverse=True)[:self.args.max_sources]
        put(self.base/'source_plan.json',{'updated_at':now(),'targets':[{'entity_id':t['entity_id'],'name':t['name'],'city':t['city'],'sources':self.plans[t['entity_id']]} for t in self.targets]})

    def manifest(self):
        return {'schema_version':SCHEMA,'updated_at':now(),'policy':{'max_gets_including_redirects':self.args.max_gets,'max_response_bytes':MAX_BYTES,'timeout_seconds':TIMEOUT,'concurrency':self.args.concurrency,'paid_calls':0,'social_pages_fetched':0},'request_count':len(self.requests),'requests':self.requests,'failure_events':self.failures,'bytes_downloaded_this_shard':sum(r.get('received_bytes',0) for r in self.requests),'pages':[{'source_url':p['source_url'],'final_url':p['final_url'],'retrieval_mode':p['retrieval_mode'],'raw_bytes':p['raw_bytes'],'raw_sha256':p['raw_sha256'],'evidence_path':p['evidence_path'],'evidence_sha256':p['evidence_sha256']} for p in self.pages.values()],'no_raw_html_or_media_saved':True,'native_subscription_cost_status':'unpriced'}

    def persist_manifest(self):
        with self.lock: put(self.base/'retrieval_manifest.json',self.manifest())

    def fail(self,status,source,current,**kw):
        with self.lock:
            self.failures.append({'status':status,'source_url':source,'request_url':current,'observed_at':now(),'http_get_count':0,**kw}); self.persist_manifest()

    def fetch(self,u):
        key=norm_url(u)
        if key in self.pages and self.pages[key].get('retrieval_mode')!='cached_sanitized_structure': return self.pages[key]
        if self.args.offline: return None
        if not self.args.retry_failures and any(r['source_url']==u for r in self.requests): return None
        current=u; chain=[]; visited=set()
        for hop in range(6):
            if not allowed(current): self.fail('destination_blocked',u,current); return None
            loop_key=urllib.parse.urlunsplit(urllib.parse.urlsplit(current)._replace(fragment=''))
            if loop_key in visited: self.fail('redirect_loop',u,current); return None
            visited.add(loop_key)
            try:
                addresses=resolve_public(urllib.parse.urlsplit(current).hostname,self.dns_semaphore)
                if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses): self.fail('dns_non_public_destination',u,current); return None
            except socket.gaierror as e: self.fail('dns_failure',u,current,error_type=type(e).__name__); return None
            except TimeoutError as e: self.fail('dns_timeout',u,current,error_type=type(e).__name__); return None
            with self.lock:
                if len(self.requests)>=self.args.max_gets: self.fail('shard_get_budget_exhausted',u,current); return None
                record={'request_index':len(self.requests)+1,'source_url':u,'request_url':current,'started_at':now(),'status':'pending','received_bytes':0}; self.requests.append(record); self.persist_manifest()
            response=None
            try:
                deadline=time.monotonic()+TIMEOUT
                req=urllib.request.Request(current,headers={'User-Agent':'PublicPoliticalEvidence/2.0','Accept':'text/html,application/xhtml+xml','Accept-Encoding':'identity'})
                try: response=urllib.request.build_opener(NoRedirect()).open(req,timeout=TIMEOUT)
                except urllib.error.HTTPError as e: response=e
                status=response.status; record['http_status']=status
                if status in (301,302,303,307,308):
                    location=response.headers.get('Location')
                    if not location: record.update(status='redirect_missing_location'); return None
                    dest=urllib.parse.urljoin(current,location)
                    record.update(status='redirect',redirect_url=dest if safe_link(dest) else None)
                    if not allowed(dest): record.update(status='redirect_blocked'); return None
                    chain.append({'from':current,'to':dest,'status':status}); current=dest
                    continue
                if status!=200: record.update(status='http_failure'); return None
                ctype=response.headers.get('Content-Type','').lower()
                if ctype and not ('html' in ctype or 'text/plain' in ctype): record.update(status='non_html_not_downloaded'); return None
                if response.headers.get('Content-Encoding','identity').lower() not in {'','identity'}: record.update(status='encoded_response_not_downloaded'); return None
                raw,error=read_bounded(response,deadline=deadline); record['received_bytes']=len(raw)
                if error: record.update(status=error); return None
                if not raw.lstrip().startswith(b'<'): record.update(status='non_html'); return None
                d=parse_page(raw,u,current,now(),self.targets); d.update(http_status=200,redirect_chain=chain)
                with self.lock:
                    page=self.save_page(d,'free_public_https_get'); record.update(status='parsed_saved',raw_sha256=d['raw_sha256'])
                return page
            except (urllib.error.URLError,TimeoutError,OSError,ValueError,http.client.HTTPException,html.etree.ParserError) as e:
                record.update(status='transport_or_parse_failure',error_type=type(e).__name__); return None
            finally:
                if response is not None: response.close()
                record['finished_at']=now(); self.persist_manifest()
        self.fail('redirect_limit_exceeded',u,current,redirect_chain=chain)
        return None

    def fetch_many(self,urls):
        unique=list({norm_url(u):u for u in urls}.values())
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.args.concurrency) as ex: list(ex.map(self.fetch,unique))

    def proof(self,p):
        return {k:p.get(k) for k in ('source_url','final_url','fetched_at','raw_sha256','evidence_path','evidence_sha256')}

    def review(self,t):
        eid=t['entity_id']; cards=[]; assets=[]
        pages=[self.pages[norm_url(r['url'])] for r in self.plans[eid] if norm_url(r['url']) in self.pages]
        for p in pages:
            blocks=p.get('identity_blocks',{}).get(eid,[]); spans=p['target_spans'].get(eid,[])
            exact_blocks=[b for b in blocks if b.get('public_role_match') and b.get('locality_match')]
            excerpt=exact_blocks[0]['excerpt'] if exact_blocks else spans[0] if spans else ''
            dedicated=exact_name(p['title'],t['name']) or fold(t['name']).replace(' ','-') in fold(urllib.parse.unquote(urllib.parse.urlsplit(p['final_url']).path))
            trusted=official(p['source_url']) or norm_url(p['source_url']) in {norm_url(u) for u in t.get('identity_anchor_urls',[])}
            for l in p['structural_links']:
                ac=account(l['resolved_url'])
                if not ac or not spans: continue
                platform,handle,url=ac
                link_name=exact_name(l['context'],t['name'])
                scoped=link_name and (len([x for x in self.targets if exact_name(l['context'],x['name'])])==1)
                handle_normal=re.sub(r'[^a-z0-9]','',fold(handle))
                name_tokens=[re.sub(r'[^a-z0-9]','',fold(w)) for w in t['name'].split()]
                owner_consistent=exact_name(l['label'],t['name']) or (bool(name_tokens) and all(token and token in handle_normal for token in name_tokens))
                strong=trusted and dedicated and bool(exact_blocks) and l['section']=='body' and scoped and owner_consistent
                decision='confirm_proposal' if strong else 'reject' if l['section'] in {'footer','navigation'} else 'unknown'
                card={'review_id':sha((eid+p['source_url']+url).encode())[:24],'entity_id':eid,'name':t['name'],'city':t['city'],'entity_type':t.get('entity_type',t.get('kind','candidate')),'platform':platform,'handle':handle,'url':url,'profile_url':url,'decision':decision,'relation':'account_owner',**self.proof(p),'observed_at':p['fetched_at'],'exact_href':l['exact_href'],'excerpt':excerpt,'link_context':l['context'],'link_section':l['section'],'public_role_evidence':[{'excerpt':b['excerpt'],'match':b['public_role_match'],'block_path':b['block_path']} for b in exact_blocks],'locality_evidence':[{'excerpt':b['excerpt'],'match':b['locality_match'],'block_path':b['block_path']} for b in exact_blocks],'anchor_links_account':bool(strong),'identity_confirmed':False,'public':None,'anchor_source_public':True,'account_public_status':'unverified','adjudication':'pending','promotion_status':'independent_review_required','account_name_consistency':owner_consistent,'rationale':'Exact name, public role and locality in body evidence plus target-scoped exact anchor; independent reviewer must adjudicate.' if strong else 'Shared footer/navigation account is outside personal owner scope.' if decision=='reject' else 'Exact anchor exists but independent identity, body locality or target-specific account scope/name consistency is insufficient.'}
                cards.append(card)
            text=p['main_text']
            if text and exact_name(text,t['name']) and POLITICAL.search(fold(text)):
                assets.append({'asset_candidate_id':sha((eid+p['source_url']).encode())[:24],'entity_id':eid,'name':t['name'],'city':t['city'],'relation':'about','relation_evidence':next((paragraph for paragraph in text.split('\n\n') if exact_name(paragraph,t['name'])),''),'title':p['title'],'source_url':p['source_url'],'final_url':p['final_url'],'raw_sha256':p['raw_sha256'],'text_sha256':p['main_text_sha256'],'observed_at':p['fetched_at'],'content_published_at':p['explicit_publication_dates'][0]['value'] if p['explicit_publication_dates'] else None,'content_published_at_evidence':p['explicit_publication_dates'][0] if p['explicit_publication_dates'] else None,'source_type':'programme' if re.search(r'program',fold(p['source_url']+' '+p['title'])) else 'official_website' if official(p['source_url']) else 'news','main_text':text,'text_truncated':p['text_truncated'],'omitted_content_reason':p['omitted_content_reason'],'evidence_path':p['evidence_path'],'evidence_sha256':p['evidence_sha256'],'source_statement_speaker':None,'publisher_owner_status':'separate_review_required','media_downloaded':False,'identity_confirmed':False,'promotion_status':'independent_review_required'})
        known={(c['platform'],c['handle']) for c in cards}
        for r in list(t.get('cached_accounts',[]))+list(self.discoveries[eid].values()):
            ac=account(r.get('url',''))
            if not ac or (ac[0],ac[1]) in known: continue
            cards.append({'review_id':sha((eid+ac[2]+'unknown').encode())[:24],'entity_id':eid,'name':t['name'],'city':t['city'],'platform':ac[0],'handle':ac[1],'url':ac[2],'profile_url':ac[2],'decision':'unknown','relation':'account_owner','source_url':None,'observed_at':None,'exact_href':None,'excerpt':'','anchor_links_account':False,'identity_confirmed':False,'adjudication':'pending','promotion_status':'independent_review_required','rationale':'Discovery/cached account only; SERP, bio, candidacy or earlier acceptance does not establish independent owner proof.'}); known.add((ac[0],ac[1]))
        if not cards:
            p=next((p for p in pages if eid in p['target_spans']),None)
            cards.append({'review_id':sha((eid+'gap').encode())[:24],'entity_id':eid,'name':t['name'],'city':t['city'],'platform':None,'handle':None,'url':None,'profile_url':None,'decision':'unknown','relation':'account_owner',**(self.proof(p) if p else {}),'observed_at':p['fetched_at'] if p else None,'exact_href':None,'excerpt':p['target_spans'][eid][0] if p else '', 'anchor_links_account':False,'identity_confirmed':False,'adjudication':'pending','promotion_status':'independent_review_required','rationale':'No exact independent personal social-account anchor in selected bounded sources.','retrieval_gap':None if p else 'no_exact_body_full_name_match'})
        cards=list({c['review_id']:c for c in cards}.values())
        assets=list({a['asset_candidate_id']:a for a in assets}.values())
        result={'schema_version':SCHEMA,'entity_id':eid,'cards':cards,'assets':assets,'selected_sources':self.plans[eid],'updated_at':now()}
        path=self.base/'target_results'/(sha(eid.encode())[:24]+'-'+str(time.time_ns())+'.json')
        if path.exists(): raise ValueError('immutable target result already exists')
        put(path,result); self.processed.append(eid); self.cards.extend(cards); self.assets.extend(assets)

    def checkpoint(self,status):
        counts=dict(Counter(c['decision'] for c in self.cards)); metrics={city:{'target_count':sum(t['city']==city for t in self.targets),'processed':sum(t['city']==city and t['entity_id'] in self.processed for t in self.targets),'web_assets':sum(a['city']==city for a in self.assets),'confirm_proposals':sum(c['city']==city and c['decision']=='confirm_proposal' for c in self.cards)} for city in dict.fromkeys(t['city'] for t in self.targets)}
        discovered=[]
        for t in self.targets:
            for p in self.pages.values():
                if t['entity_id'] not in p['target_spans']: continue
                for l in p['structural_links']:
                    if l['kind']=='discovered_media': discovered.append({'entity_id':t['entity_id'],'city':t['city'],'url':l['resolved_url'],'source_url':p['source_url'],'exact_href':l['exact_href'],'status':'discovered_only','downloaded':False,'evidence_path':p['evidence_path'],'evidence_sha256':p['evidence_sha256']})
        payloads={'review_cards.json':{'schema_version':SCHEMA,'status':status,'target_count':len(self.targets),'targets_processed':len(self.processed),'decisions':counts,'policy':'Proposals only; independent review required; publisher/subject/speaker distinct','cards':self.cards},'web_asset_candidates.json':{'schema_version':SCHEMA,'status':status,'assets':self.assets,'discovered_only_links':list({(x['entity_id'],x['url']):x for x in discovered}.values()),'media_download_count':0},'metrics.json':{'schema_version':SCHEMA,'per_city':metrics,'request_count':len(self.requests),'failure_statuses':dict(Counter(r['status'] for r in self.requests+self.failures))},'status.json':{'schema_version':SCHEMA,'status':status,'updated_at':now(),'targets_processed':len(self.processed),'review_cards':len(self.cards),'confirm_proposals':counts.get('confirm_proposal',0),'web_asset_candidates':len(self.assets),'page_gets_including_redirects':len(self.requests),'paid_calls':0,'shared_writes':0,'promotion':'pending_independent_review','native_subscription_cost_status':'unpriced'}}
        checkpoint=self.base/'checkpoints'/str(time.time_ns())
        for name,data in payloads.items(): put(checkpoint/name,data); put(self.base/name,data)
        self.persist_manifest()
        outputs={str(p):sha(p.read_bytes()) for p in self.base.rglob('*.json') if '.pending' not in p.name and p.name!='hashes.json'}
        put(self.base/'hashes.json',{'inputs':self.input_hashes,'outputs':outputs})
        print(json.dumps(payloads['status.json']),flush=True)

    def run(self):
        pending=[t for t in self.targets if t['entity_id'] not in self.processed]
        try:
            for start in range(0,len(pending),self.args.batch_size):
                batch=pending[start:start+self.args.batch_size]
                self.fetch_many([r['url'] for t in batch for r in self.plans[t['entity_id']][:1]])
                self.augment(); self.seed_plans()
                self.fetch_many([r['url'] for t in batch for r in self.plans[t['entity_id']]])
                for t in batch: self.review(t)
                self.checkpoint('collecting')
            self.checkpoint('collected_pending_independent_review')
        except KeyboardInterrupt:
            self.checkpoint('interrupted_resumable'); raise
        finally: self.file_lock.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--targets',type=Path,required=True); p.add_argument('--discovery',type=Path,action='append',default=[])
    p.add_argument('--output-root',type=Path,required=True); p.add_argument('--cache-root',type=Path,action='append',default=[])
    p.add_argument('--city',action='append',default=[]); p.add_argument('--target-id',action='append',default=[])
    p.add_argument('--shard-index',type=int,default=0); p.add_argument('--shard-count',type=int,default=1)
    p.add_argument('--max-gets',type=int,default=100); p.add_argument('--concurrency',type=int,default=6)
    p.add_argument('--max-sources',type=int,default=3); p.add_argument('--batch-size',type=int,default=10)
    p.add_argument('--offline',action='store_true'); p.add_argument('--resume',action='store_true'); p.add_argument('--retry-failures',action='store_true')
    p.add_argument('--supplement-discovery',type=Path,action='append',default=[],help='Append immutable discovery envelope to existing run; originals need not be changed')
    p.add_argument('--refresh-results',action='store_true',help='Re-review targets into new immutable result versions, preserving old snapshots and cumulative GET ledger')
    args=p.parse_args()
    if not 0<=args.max_gets<=100 or not 1<=args.concurrency<=6 or not 1<=args.max_sources<=5 or not 1<=args.batch_size<=100 or not 0<=args.shard_index<args.shard_count: p.error('bounds: GETs 0..100, concurrency 1..6, sources 1..5, batch 1..100, shard index<count')
    Harvest(args).run()


if __name__=='__main__': main()
