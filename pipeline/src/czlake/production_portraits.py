"""Source-bound public portraits; no face recognition or inferred depicted identity.

Only exact-name image labels or tightly scoped person cards are admitted.
Everything else stays a candidate, and every target has an explicit outcome.
"""
from __future__ import annotations
import argparse, concurrent.futures, datetime as dt, hashlib, http.client, ipaddress, json, pathlib, re, socket, ssl, struct, threading, time, unicodedata, urllib.parse
from lxml import html

SCHEMA_VERSION = 1
MAX_PAGE_BYTES = 4_000_000
MAX_IMAGE_BYTES = 8_000_000
TIMEOUT = 12
ROLE = re.compile(r'zastupitel|primator|starost|mistostarost|kandidat|poslanec|senator|radni|polit[iy]k|clen|predseda|kandiduj|lider|namestek|mistoprimator')
BAD_IMAGE = re.compile(r'logo|favicon|placeholder|default[_ -]?(?:user|avatar|profile)|no[_ -]?(?:photo|image)|sprite|banner|skupin|group|kolektiv',re.I)
SOCIAL_HOSTS = ('instagram.com','facebook.com','fb.com','tiktok.com','x.com','twitter.com')

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def sha(data): return hashlib.sha256(data).hexdigest()
def fold(s): return ''.join(c for c in unicodedata.normalize('NFKD',str(s)).lower() if not unicodedata.combining(c))
def clean(s): return ' '.join(str(s).split())
def name_match(text,name): return bool(re.search(r'(?<!\w)'+re.escape(fold(name))+r'(?!\w)',fold(text)))
def public_url(url):
    try:
        p=urllib.parse.urlsplit(url)
        return p.scheme=='https' and bool(p.hostname) and p.port in (None,443) and not p.username and not p.password and len(url)<8192 and not any(c in url for c in '\r\n\x00')
    except ValueError: return False

def image_info(raw):
    """Sniff raster bytes and dimensions without decoding or transforming them."""
    if raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw)>=24:
        return 'image/png',*struct.unpack('>II',raw[16:24])
    if raw[:6] in (b'GIF87a',b'GIF89a') and len(raw)>=10:
        return 'image/gif',*struct.unpack('<HH',raw[6:10])
    if raw[:2]==b'\xff\xd8':
        i=2
        while i+4<=len(raw):
            if raw[i]!=255: i+=1;continue
            while i<len(raw) and raw[i]==255:i+=1
            if i>=len(raw):break
            marker=raw[i];i+=1
            if marker in (0xD8,0xD9) or 0xD0<=marker<=0xD7:continue
            if i+2>len(raw):break
            length=int.from_bytes(raw[i:i+2],'big')
            if marker in (0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF) and i+7<=len(raw):
                return 'image/jpeg',int.from_bytes(raw[i+5:i+7],'big'),int.from_bytes(raw[i+3:i+5],'big')
            if length<2:break
            i+=length
    if raw[:4]==b'RIFF' and raw[8:12]==b'WEBP' and len(raw)>=30:
        if raw[12:16]==b'VP8X':return 'image/webp',int.from_bytes(raw[24:27],'little')+1,int.from_bytes(raw[27:30],'little')+1
        if raw[12:16]==b'VP8 ' and raw[23:26]==b'\x9d\x01\x2a':return 'image/webp',int.from_bytes(raw[26:28],'little')&0x3fff,int.from_bytes(raw[28:30],'little')&0x3fff
        if raw[12:16]==b'VP8L' and raw[20]==0x2f:
            bits=int.from_bytes(raw[21:25],'little');return 'image/webp',(bits&0x3fff)+1,((bits>>14)&0x3fff)+1
    if len(raw)>=32 and raw[4:8]==b'ftyp' and b'avif' in raw[8:40]:
        offset=raw.find(b'ispe',0,min(len(raw),1_000_000))
        if offset>=4 and offset+16<=len(raw) and int.from_bytes(raw[offset-4:offset],'big')>=20:
            return 'image/avif',int.from_bytes(raw[offset+8:offset+12],'big'),int.from_bytes(raw[offset+12:offset+16],'big')
    raise ValueError('unsupported_or_invalid_raster')

class PublicFetcher:
    """HTTPS, public DNS/IP, pinned socket, bounded redirects/body/deadline/GETs."""
    def __init__(self, output_root, max_gets=100, concurrency=6, cutoff='2026-10-09T03:30:00+00:00'):
        self.output=pathlib.Path(output_root);self.output.mkdir(parents=True,exist_ok=True)
        self.max_gets=max_gets;self.records=[];self.lock=threading.RLock();self.dns_slots=threading.BoundedSemaphore(concurrency)
        self.cutoff=dt.datetime.fromisoformat(cutoff)
        manifest=self.output/'retrieval_manifest.json'
        if manifest.exists():
            prior=json.loads(manifest.read_text());self.records=prior.get('requests',[])
            if len(self.records)>self.max_gets:raise ValueError('max_gets_below_existing_cumulative_ledger')
    def persist(self):
        with self.lock:
            tmp=self.output/'retrieval_manifest.tmp';tmp.write_text(json.dumps({'schema_version':1,'observed_at':now(),'max_gets':self.max_gets,'request_count':len(self.records),'requests':self.records,'paid_calls':0,'shared_writes':0},ensure_ascii=False,indent=2));tmp.replace(self.output/'retrieval_manifest.json')
    def resolve(self,host):
        if not self.dns_slots.acquire(timeout=TIMEOUT):raise TimeoutError('dns_slot_timeout')
        done=threading.Event();out={}
        def worker():
            try:out['addresses']=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
            except Exception as e:out['error']=e
            finally:self.dns_slots.release();done.set()
        threading.Thread(target=worker,daemon=True).start()
        if not done.wait(TIMEOUT):raise TimeoutError('dns_timeout')
        if 'error'in out:raise out['error']
        addresses=out['addresses']
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError('non_public_ip')
        return addresses
    def fetch(self,url,kind='page'):
        cap=MAX_IMAGE_BYTES if kind in ('image','logo') else MAX_PAGE_BYTES;current=url;chain=[];seen=set()
        for hop in range(5):
            if not public_url(current):return None,'unsafe_url'
            if current in seen:return None,'redirect_loop'
            seen.add(current)
            if dt.datetime.now(dt.timezone.utc)>=self.cutoff:return None,'network_cutoff'
            p=urllib.parse.urlsplit(current)
            try:addresses=self.resolve(p.hostname)
            except Exception as e:return None,str(e)
            with self.lock:
                if len(self.records)>=self.max_gets:return None,'get_budget_exhausted'
                record={'request_index':len(self.records)+1,'original_url':url,'request_url':current,'kind':kind,'started_at':now(),'status':'pending','received_bytes':0};self.records.append(record);self.persist()
            conn=None
            try:
                deadline=time.monotonic()+TIMEOUT
                address=addresses[0];rawsock=socket.socket(address[0],socket.SOCK_STREAM);rawsock.settimeout(TIMEOUT)
                rawsock.connect(address[4]);tls=ssl.create_default_context().wrap_socket(rawsock,server_hostname=p.hostname)
                conn=http.client.HTTPSConnection(p.hostname,timeout=TIMEOUT);conn.sock=tls
                path=urllib.parse.quote(p.path or '/',safe="/%:@!$&'()*+,;=-._~")
                if p.query:path+='?'+urllib.parse.quote(p.query,safe="/%?:@!$&'()*+,;=-._~")
                conn.request('GET',path,headers={'User-Agent':'StarwatchPublicPortraitEvidence/1.0','Accept':'image/*' if kind in ('image','logo') else 'text/html,application/xhtml+xml','Accept-Encoding':'identity'})
                resp=conn.getresponse();record['http_status']=resp.status
                if resp.status in (301,302,303,307,308):
                    dest=urllib.parse.urljoin(current,resp.getheader('Location') or '')
                    record.update(status='redirect',redirect_url=dest if public_url(dest) else None);chain.append({'from':current,'to':dest,'status':resp.status});current=dest;continue
                if resp.status!=200:record['status']='http_failure';return None,'http_'+str(resp.status)
                if resp.getheader('Content-Encoding','identity').lower() not in ('','identity'):raise ValueError('encoded_response')
                length=resp.getheader('Content-Length');expected=int(length) if length and length.isdigit() else None
                if expected is not None and expected>cap:raise ValueError('response_too_large')
                chunks=[];size=0
                while size<cap:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('response_deadline')
                    tls.settimeout(min(TIMEOUT,remaining));chunk=resp.read(min(65536,cap-size))
                    if not chunk:break
                    chunks.append(chunk);size+=len(chunk);record['received_bytes']=size
                    if (expected is not None and size>=expected) or resp.isclosed():break
                raw=b''.join(chunks)
                if expected is not None and size!=expected:raise ValueError('incomplete_declared_length')
                if size==cap and expected!=cap:raise ValueError('response_cap_completeness_unknown')
                content_type=resp.getheader('Content-Type','').split(';')[0].strip().lower()
                if kind=='page' and not raw.removeprefix(b'\xef\xbb\xbf').lstrip().startswith(b'<'):raise ValueError('non_html')
                if kind=='image':
                    mime,width,height=image_info(raw)
                    if width<40 or height<40 or width>20000 or height>20000:raise ValueError('invalid_image_dimensions')
                    if content_type and content_type not in (mime,'application/octet-stream','binary/octet-stream'):raise ValueError('content_type_magic_mismatch')
                if kind=='logo':
                    from czlake.production_logos import logo_type
                    mime=logo_type(raw)
                    if content_type and content_type not in (mime,'application/octet-stream','binary/octet-stream'):raise ValueError('content_type_magic_mismatch')
                digest=sha(raw);record.update(status='downloaded',sha256=digest,received_bytes=len(raw),content_type=content_type,final_url=current)
                return {'raw':raw,'original_url':url,'final_url':current,'sha256':digest,'bytes':len(raw),'content_type':content_type,'observed_at':now(),'redirect_chain':chain},None
            except Exception as e:record.update(status='failed',error=str(e)[:200]);return None,str(e)
            finally:
                if conn:conn.close()
                record['finished_at']=now();self.persist()
        return None,'redirect_limit'


def extract_candidates(raw,page_url,targets,observed_at=None,source_path=None):
    try: decoded=raw.decode('utf-8')
    except UnicodeDecodeError: decoded=raw
    doc=html.fromstring(decoded,base_url=page_url);tree=doc.getroottree();digest=sha(raw);out=[]
    for tag in doc.xpath('//script|//style|//noscript|//form'):tag.drop_tree()
    page_text=clean(' '.join(doc.itertext()))
    headings=' '.join(clean(' '.join(x.itertext())) for x in doc.xpath('//h1'))
    for img in doc.xpath('//img'):
        ancestors=list(img.iterancestors())
        if any(a.tag in ('nav','footer') for a in ancestors):continue
        if any(a.tag=='header' for a in ancestors) and not re.search(r'portrait|profile|avatar|rounded-full',img.get('class',''),re.I):continue
        alt=clean(img.get('alt',''));title=clean(img.get('title',''));label=alt+' '+title
        src=img.get('src') or img.get('data-src') or img.get('data-lazy-src') or ''
        if src.startswith('data:'):src=img.get('data-src') or img.get('data-lazy-src') or ''
        if not src:continue
        image_url=urllib.parse.urljoin(page_url,src)
        if not public_url(image_url) or BAD_IMAGE.search(label+' '+image_url) or urllib.parse.urlsplit(image_url).path.lower().endswith(('.svg','.ico')):continue
        # A scoped ancestor must have bounded content and one target, not a full roster.
        scoped=None
        for ancestor in [img,*list(img.iterancestors())[:4]]:
            if ancestor.tag in ('html','body','main') or ancestor.xpath('.//h1'):continue
            text=clean(' '.join(ancestor.itertext()))
            if not text or len(text)>900:continue
            matching=[t for t in targets if name_match(text,t['name'])]
            if len(matching)==1:
                imgs=ancestor.xpath('.//img')
                if len(imgs)==1:scoped=(text,matching[0],tree.getpath(ancestor));break
        for target in targets:
            label_targets=[t for t in targets if name_match(label,t['name'])]
            exact_label=name_match(label,target['name']) and len(label_targets)==1
            if len(label_targets)>1:continue
            same_card=scoped is not None and scoped[1]['entity_id']==target['entity_id']
            personal_heading=name_match(headings,target['name']) and sum(name_match(headings,t['name']) for t in targets)==1
            filename=urllib.parse.unquote(urllib.parse.urlsplit(image_url).path.rsplit('/',1)[-1])
            filename_name=fold(target['name']).replace(' ','-') in fold(filename) or fold(target['name']).replace(' ','') in re.sub(r'[^a-z0-9]','',fold(filename))
            if not (exact_label or same_card or (personal_heading and filename_name)):continue
            context=scoped[0] if same_card else label
            role=ROLE.search(fold(context))
            locality=name_match(context,target['city'])
            binding='exact_image_label' if exact_label else 'single_person_dom_card' if same_card else 'exact_person_heading_and_named_image'
            article_teaser=bool(re.search(r':',label) and not ROLE.search(fold(label.split(':',1)[-1])))
            group_label=bool(re.search(r'\s(?:and|with|spolu|s|a)\s',fold(label)) and not ROLE.search(fold(label.split(target['name'],1)[-1])))
            strong=bool((exact_label or same_card or (personal_heading and filename_name)) and role and locality and not article_teaser and not group_label)
            evidence={'method':binding,'binding_scope':'bounded_person_card' if same_card else 'exact_image_label','exact_name':target['name'],'image_alt':alt,'image_title':title,'exact_src':src,'dom_pointer':tree.getpath(img),'card_pointer':scoped[2] if same_card else None,'context':context,'role_match':role.group(0) if role else None,'locality_match':target['city'] if locality else None,'page_heading':headings[:300],'source_path':str(source_path) if source_path else None,'depicted_identity_method':'publisher label only; no facial inference'}
            out.append({'schema_version':1,'image_id':'portrait_'+sha((target['entity_id']+'\0'+page_url+'\0'+image_url+'\0'+evidence['dom_pointer']).encode())[:24],'target_id':target['entity_id'],'entity_id':target['entity_id'],'person_id':target.get('person_id'),'exact_name':target['name'],'role':target.get('entity_kind','qualified_public_political_candidate'),'locality':target['city'],'kind':'source_bound_portrait','original_image_url':image_url,'source_page_url':page_url,'source_page_sha256':digest,'source_pointer':evidence['dom_pointer'],'identity_evidence':evidence,'observed_at':observed_at or now(),'admission_status':'admitted' if strong else 'candidate','admission_basis':'exact publisher image/card label plus public political role and locality' if strong else 'name-bound candidate; missing role/locality evidence','download':None})
    return list({x['image_id']:x for x in out}.values())

def download_candidate(candidate,fetcher):
    item=dict(candidate)
    result,error=fetcher.fetch(item['original_image_url'],'image')
    if not result:item['download_status']='failed';item['download_error']=error;return item
    raw=result.pop('raw');mime,width,height=image_info(raw);ext={'image/jpeg':'jpg','image/png':'png','image/gif':'gif','image/webp':'webp','image/avif':'avif'}[mime]
    blob=fetcher.output/'images'/(result['sha256']+'.'+ext);blob.parent.mkdir(exist_ok=True)
    if not blob.exists():blob.write_bytes(raw)
    item['download_status']='downloaded';item['download']={**result,'local_path':str(blob.resolve()),'mime':mime,'width':width,'height':height}
    return item

def load_targets(path):
    data=json.loads(pathlib.Path(path).read_text());return data if isinstance(data,list) else data['targets']

def save_index(output,targets,images):
    output=pathlib.Path(output);output.mkdir(parents=True,exist_ok=True)
    rows=[]
    for t in targets:
        ids=[i['image_id'] for i in images if i['target_id']==t['entity_id'] and i.get('download_status')=='downloaded' and i.get('admission_status')=='admitted']
        candidates=[i['image_id'] for i in images if i['target_id']==t['entity_id'] and i.get('admission_status')!='admitted']
        rows.append({'target_id':t['entity_id'],'person_id':t.get('person_id'),'name':t['name'],'city':t['city'],'portrait_status':'available_source_bound' if ids else 'unknown','image_ids':ids,'candidate_image_ids':candidates,'unknown_reason':None if ids else 'No downloaded image with sufficient exact source label, role and locality binding.'})
    payload={'schema_version':1,'observed_at':now(),'target_count':len(targets),'source_bound_downloaded_people':sum(r['portrait_status']!='unknown' for r in rows),'image_count':len(images),'targets':rows,'images':images,'policy':{'facial_recognition':False,'generated_portraits':False,'unknowns_explicit':True,'paid_calls':0,'shared_writes':0}}
    tmp=output/'index.tmp';tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2));tmp.replace(output/'index.json');return payload


def run(args):
    targets=load_targets(args.targets);fetcher=PublicFetcher(args.output_root,args.max_gets,args.concurrency,args.cutoff);urls=set(args.page_url);scores={}
    for base in args.evidence_root:
        for p in pathlib.Path(base).rglob('page-*.json'):
            try:d=json.loads(p.read_text())
            except Exception:continue
            u=d.get('final_url') or d.get('source_url');spans=d.get('target_spans') or d.get('identity_blocks') or {}
            if public_url(u) and not any((urllib.parse.urlsplit(u).hostname or '').endswith(h) for h in SOCIAL_HOSTS):
                hits=len(set(spans)&{t['entity_id'] for t in targets})
                if hits:scores[u]=max(scores.get(u,0),hits)
    for t in targets:
        for u in t.get('identity_anchor_urls',[])+t.get('source_urls',[]):
            if public_url(u):scores[u]=max(scores.get(u,0),1)
    urls=list(urls)+[u for u in sorted(scores,key=lambda u:(-scores[u],u)) if u not in urls]
    images=[];seen_images=set();pages_dir=fetcher.output/'pages';pages_dir.mkdir(exist_ok=True)
    for url in urls[:args.max_pages]:
        result,error=fetcher.fetch(url,'page')
        if not result:continue
        raw=result['raw'];p=pages_dir/(result['sha256']+'.json')
        candidates=extract_candidates(raw,result['final_url'],targets,result['observed_at'],p)
        packet={'schema_version':1,'source_page_url':result['final_url'],'raw_page_sha256':result['sha256'],'raw_page_bytes':result['bytes'],'observed_at':result['observed_at'],'raw_html_retained':False,'images':[{'original_image_url':c['original_image_url'],'target_id':c['target_id'],'identity_evidence':c['identity_evidence']} for c in candidates]}
        p.write_text(json.dumps(packet,ensure_ascii=False,indent=2));packet_sha=sha(p.read_bytes())
        for n,c in enumerate(candidates):
            c['source_page']={'path':str(p.resolve()),'sha256':packet_sha,'url':result['final_url'],'text_pointer':f'/images/{n}/identity_evidence','raw_page_sha256':result['sha256']}
            c['source_image_pointer']=f'/images/{n}/original_image_url'
            c['relation_status']='source_identified' if c['admission_status']=='admitted' else 'unknown'
        # Keep all candidates, but download strongly bound images first.
        candidates.sort(key=lambda c:c['admission_status']!='admitted')
        for c in candidates:
            key=(c['target_id'],c['original_image_url'])
            if key in seen_images:continue
            seen_images.add(key);images.append(c)
        save_index(fetcher.output,targets,images)
    queue=[i for i in images if i['admission_status']=='admitted']+[i for i in images if i['admission_status']!='admitted']
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for item in pool.map(lambda c:download_candidate(c,fetcher),queue):
            images=[item if i['image_id']==item['image_id'] else i for i in images];save_index(fetcher.output,targets,images)
    return save_index(fetcher.output,targets,images)

def main():
    p=argparse.ArgumentParser();p.add_argument('--targets',type=pathlib.Path,required=True);p.add_argument('--output-root',type=pathlib.Path,required=True);p.add_argument('--evidence-root',action='append',default=[]);p.add_argument('--page-url',action='append',default=[]);p.add_argument('--max-gets',type=int,default=100);p.add_argument('--max-pages',type=int,default=30);p.add_argument('--concurrency',type=int,default=6);p.add_argument('--cutoff',default='2026-10-09T03:30:00+00:00');args=p.parse_args();r=run(args);print(json.dumps({k:r[k] for k in ('target_count','source_bound_downloaded_people','image_count')}))
if __name__=='__main__':main()
