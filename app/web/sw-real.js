/* Starwatch real-data adapter.
   Loads after data/real.js (window.SW_RAW, optional) and mock.js (window.SW, simulated).
   Unless the simulated universe is requested (?data=sim), it rebuilds the SW arrays IN PLACE
   from the verified production export, so every screen and helper reads real records.
   Mock content is never mixed onto real people: in real mode every asset is a real, verified one. */
(function(){
"use strict";
const SW=window.SW, RAW=window.SW_RAW;
const q=new URLSearchParams(location.search);
let want=q.get('data');
try{if(want)localStorage.setItem('sw-data',want);else want=localStorage.getItem('sw-data')}catch(e){}
SW.available={real:!!RAW,sim:true};
// a screen can require a minimum of verified assets before it trusts live data (data-min-assets on this script tag)
const me=document.currentScript, minA=me&&+me.dataset.minAssets||0, nReal=RAW&&RAW.assets?RAW.assets.length:0;
if(RAW&&want!=='sim'&&nReal<minA){SW.source={kind:'sim',fallback:true,label:'Simulated universe',detail:`Live data has ${nReal} verified assets so far; this screen needs ${minA}+ to be meaningful, so it shows the simulated universe until collection catches up.`};return}
if(!RAW||want==='sim'){SW.source={kind:'sim',label:'Simulated universe',detail:'Generated names, lists, posts and metrics. Per-city candidate and list counts follow the KV2026 registry.'};return}

// Named local issues are independently reviewed caption memberships, kept separate
// from the production export and its admitted broad-category labels. Recheck every
// link against this export so a later refresh cannot silently reuse stale evidence.
const issueCatalog=window.SW_ISSUES;
const issueCoverage=[];
if(issueCatalog&&Array.isArray(issueCatalog.topics)){
  const norm=s=>String(s||'').normalize('NFC').replace(/\s+/g,' ').trim();
  const rawAssets=new Map((RAW.assets||[]).map(a=>[a.id,a]));
  const ownerCities=new Map([...(RAW.cands||[]),...(RAW.lists||[])].map(e=>[e.id,e.city_id]));
  RAW.topics=RAW.topics||[];
  issueCatalog.topics.forEach(t=>{
    if(!t.id||!t.id.startsWith('issue:')||!t.label||!t.city_id)return;
    const matched=[];
    (t.links||[]).forEach(link=>{
      const a=rawAssets.get(link.asset_id), quote=norm(link.exact_quote);
      if(!a||a.url!==link.source_url||ownerCities.get(a.owner_entity_id)!==t.city_id||!quote||!norm(a.text).includes(quote))return;
      a.topics=a.topics||[];if(!a.topics.includes(t.id))a.topics.push(t.id);
      a.issue_topic_evidence=a.issue_topic_evidence||[];
      if(!a.issue_topic_evidence.some(e=>e.topic_id===t.id))a.issue_topic_evidence.push({topic_id:t.id,label:t.label,quote:link.exact_quote,source_url:a.url,reviewed_at:t.reviewed_at,method:'caption_reviewed'});
      matched.push(a);
    });
    if(!matched.length)return;
    if(!RAW.topics.some(x=>x.id===t.id))RAW.topics.push({id:t.id,label:t.label,status:'caption_reviewed',kind:'issue',description:t.description});
    issueCoverage.push({id:t.id,label:t.label,city_id:t.city_id,description:t.description,assets:matched.length,owners:new Set(matched.map(a=>a.owner_entity_id)).size,reviewed_at:t.reviewed_at,limitations:t.limitations||[]});
  });
}
SW.issueTopicCoverage=issueCoverage;

const {cities,lists,cands,assets,PLAT,TOP,PARTY,proj,rng}=SW;
cities.length=0;lists.length=0;cands.length=0;assets.length=0;TOP.length=0;
const exported=RAW.source&&RAW.source.exported_at?new Date(RAW.source.exported_at):new Date();
SW.TODAY&&SW.TODAY.setTime(exported.getTime());

// deterministic hash for stable layout + colours
const hash=s=>{let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}return h>>>0};
const fold=s=>(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
const PI=Object.fromEntries(PLAT.map((p,i)=>[p.k,i]));

const tCount={};(RAW.assets||[]).forEach(a=>(a.topics||[]).forEach(t=>tCount[t]=(tCount[t]||0)+1));
const pretty=l=>{const x=String(l||'').replace(/_/g,' ').replace(/\s+/g,' ').trim();return x.charAt(0).toUpperCase()+x.slice(1)};
const usedTopics=(RAW.topics||[]).filter(t=>tCount[t.id]).sort((a,b)=>(a.id==='other')-(b.id==='other')||tCount[b.id]-tCount[a.id]);
usedTopics.forEach(t=>TOP.push([pretty(t.label),'',t.id,t.status||'admitted',t.kind||'category']));
const topicIx=Object.fromEntries(usedTopics.map((t,i)=>[t.id,i]));

// cities: richest verified evidence first, so screens that default to cities[0] open where the evidence is
const ownerCity={};(RAW.lists||[]).forEach(l=>ownerCity[l.id]=l.city_id);(RAW.cands||[]).forEach(c=>ownerCity[c.id]=c.city_id);
const perCity={};(RAW.assets||[]).forEach(a=>{const c=ownerCity[a.owner_entity_id];if(c)perCity[c]=(perCity[c]||0)+1});
const rawCities=[...(RAW.cities||[])].sort((a,b)=>(perCity[b.id]||0)-(perCity[a.id]||0)||(b.valid_candidacies||0)-(a.valid_candidacies||0));
const cityIx={};
rawCities.forEach(c=>{
  const [x,y]=proj(c.lon,c.lat);const n=c.valid_candidacies||0;
  const R=3.4+6.2*Math.sqrt(n/1059);
  cityIx[c.id]=cities.length;
  cities.push({i:cities.length,id:c.id,name:c.name,x,y,R,n,L:0,seats:null,population:c.population,lists:[],cands:[],assets:[]});
});

// lists: group by city, biggest first, golden-angle spiral (same layout grammar as the simulation)
const listIx={};
const byCity={};(RAW.lists||[]).forEach(l=>{(byCity[l.city_id]=byCity[l.city_id]||[]).push(l)});
Object.entries(byCity).forEach(([cid,ls])=>{
  const city=cities[cityIx[cid]];if(!city)return;
  ls.sort((a,b)=>(b.size||0)-(a.size||0)||String(a.number).localeCompare(String(b.number)));
  const arm=(hash(cid)%628)/100;city.L=ls.length;
  ls.forEach((l,li)=>{
    const t=(li+.35)/ls.length, ang=arm+li*2.39996+Math.sqrt(t)*2.4, rad=city.R*(.06+.86*Math.sqrt(t));
    const size=Math.max(1,l.size||1), S=city.R*.085*Math.sqrt(size/40)+city.R*.03;
    const key=fold(l.short||l.name).replace(/[^a-z0-9]/g,'');
    const L={i:lists.length,id:l.id,logos:l.logos||[],result2022:l.result2022||null,forecast:l.forecast||[],city:city.i,name:l.name,short:(l.short||l.name).slice(0,14),number:l.number,size,relevant:!!l.relevant,
      x:city.x+Math.cos(ang)*rad,y:city.y+Math.sin(ang)*rad,S,col:PARTY[hash(key)%PARTY.length],cands:[],assets:[],popular:1};
    listIx[l.id]=L.i;lists.push(L);city.lists.push(L.i);
  });
});

// candidates
const candIx={};
const followers={};(RAW.accounts||[]).forEach(a=>{if(a.followers!=null)followers[a.entity_id]=Math.max(followers[a.entity_id]||0,a.followers)});
(RAW.cands||[]).forEach(c=>{const li=listIx[c.list_id];if(li==null)return;const L=lists[li];const k=c.position||L.cands.length+1;
  const fol=followers[c.id]||0, lead=Math.exp(-(k-1)/5);
  const rad2=L.S*(.16+.84*Math.sqrt((k-.5)/Math.max(L.size,k)));
  const cnd={i:cands.length,id:c.id,photo:c.photo||null,photo_source:c.photo_source||null,pref2022:c.pref2022||null,forecast:c.forecast||[],name:c.name,list:li,city:L.city,k,fol,folKnown:followers[c.id]!=null,qualified:!!c.qualified,occupation:c.occupation||null,
    or:rad2,ph:k*2.39996+((hash(c.id)%40)-20)/100,sp:((hash(c.id)&1)?-1:1)*0.035/(0.4+rad2),assets:[],about:[],age:c.age||null};
  cnd.size=.02+(fol?.075*Math.min(1,Math.log10(fol)/4.3):0)+.06*lead+(c.qualified?.012:0);
  candIx[c.id]=cnd.i;cands.push(cnd);L.cands.push(cnd.i);cities[L.city].cands.push(cnd.i);
});
lists.forEach(L=>L.cands.sort((a,b)=>cands[a].k-cands[b].k));
// list-account followers
lists.forEach(L=>{L.fol=followers[L.id]||0});

// verified assets only
const typeVideo={video:1,reel:1};
(RAW.assets||[]).forEach(r=>{
  const own=r.owner_entity_id;let owner=-1,li=-1;
  if(candIx[own]!=null){owner=candIx[own];li=cands[owner].list}else if(listIx[own]!=null){li=listIx[own]}else return;
  const L=lists[li], pi=PI[r.platform]!=null?PI[r.platform]:6, video=!!typeVideo[(r.type||'').toLowerCase()]||PLAT[pi].video===1;
  const pub=r.published_at?new Date(r.published_at):null, age=pub?Math.max(0,(exported-pub)/864e5):45;
  const n=v=>v==null?0:v;
  const a={i:assets.length,id:r.id,owner,list:li,city:L.city,plat:pi,video,rel:'created',about:-1,mention:null,
    topics:(r.topics||[]).map(t=>topicIx[t]).filter(x=>x!=null),topicStatus:r.topic_status||null,age,published_at:r.published_at,
    views:n(r.views),likes:n(r.likes),comments:n(r.comments),shares:n(r.shares),na:{views:r.views==null,likes:r.likes==null,comments:r.comments==null,shares:r.shares==null},
    cap:(r.text||'').replace(/\s+/g,' ').trim()||'(no caption)',ar:pi===2||(pi===0&&video)?.5625:pi===0?1:PLAT[pi].ar,outlet:null,
    url:r.url,img:r.image||null,vsrc:r.video||null,vmime:r.video_mime||null,dur:r.duration_s?Math.round(r.duration_s):0,claims:r.claims||[],issueEvidence:r.issue_topic_evidence||[],observed_at:r.observed_at,real:true};
  a.inter=a.likes+a.comments+a.shares;a.reach=r.views!=null?r.views:a.likes+a.comments;a.reachKind=r.views!=null?'views':'engagement';
  (r.relations||[]).forEach(x=>{const m=candIx[x.entity_id];if(m!=null&&m!==owner&&a.mention==null)a.mention=m});
  if(owner>=0){const c=cands[owner];a.r=c.size*1.25+.018*Math.sqrt(c.assets.length+1)+(hash(r.id)%20)/1000;a.ph=c.assets.length*2.39996;a.sp=((hash(r.id)&1)?-1:1)*(.25+(hash(r.id)%45)/100)/(1+a.r*10);c.assets.push(a.i)}
  else{a.r=L.S*(1.06+(hash(r.id)%16)/100);a.ph=(hash(r.id)%628)/100;a.sp=.012+(hash(r.id)%18)/1000;L.assets.push(a.i)}
  assets.push(a);cities[L.city].assets.push(a.i);
});
assets.forEach(a=>{if(a.mention!=null)cands[a.mention].about.push(a.i)});
lists.forEach(L=>{const n=L.assets.length+L.cands.reduce((s,k)=>s+cands[k].assets.length,0);L.popular=.6+Math.min(1,Math.log10(1+n)/2)});

const nAcc=(RAW.accounts||[]).length;
SW.source={kind:'real',label:'Live production data',checkpoint:RAW.source&&RAW.source.checkpoint_id,exported_at:RAW.source&&RAW.source.exported_at,
  detail:`${cands.length.toLocaleString('en-US')} registered candidacies · ${lists.length} lists · ${nAcc} verified accounts · ${assets.length} verified assets${TOP.length?'':' · topics pending review'}`};
SW.coverage=RAW.coverage||[];
// verified-account coverage per entity: "not observed" (no verified account) is different from zero posts
const accBy={};(RAW.accounts||[]).forEach(a=>{(accBy[a.entity_id]=accBy[a.entity_id]||[]).push(a)});
cands.forEach(c=>{c.accounts=accBy[c.id]||[]});lists.forEach(L=>{L.accounts=accBy[L.id]||[];L.observed=L.accounts.length>0||L.cands.some(k=>cands[k].accounts.length>0)});
cities.forEach(c=>{c.observed=c.lists.some(i=>lists[i].observed)});
// platform coverage for every supported platform (from the export when present, otherwise derived)
const PC={};PLAT.forEach(p=>PC[p.k]={platform:p.k,name:p.n,verified_accounts:0,verified_assets:0,playable_videos:0,status:'not_collected'});
(RAW.accounts||[]).forEach(a=>{if(PC[a.platform])PC[a.platform].verified_accounts++});
assets.forEach(a=>{const k=PLAT[a.plat].k;PC[k].verified_assets++;if(a.vsrc)PC[k].playable_videos++});
(RAW.platform_coverage||[]).forEach(p=>{if(PC[p.platform])Object.assign(PC[p.platform],p)});
Object.values(PC).forEach(p=>{if(!RAW.platform_coverage)p.status=p.verified_assets?'observed':p.verified_accounts?'accounts_only':'not_collected'});
SW.platformCoverage=PLAT.map(p=>PC[p.k]);
SW.topicsPending=TOP.length>0&&TOP.every(t=>t[3]!=='admitted');
if(SW.topicsPending)SW.source.detail+=' · topic labels independently reviewed, pending promotion';
if(issueCoverage.length)SW.source.detail+=` · ${issueCoverage.length} caption-reviewed issue topics · partial topic coverage`;
})();
