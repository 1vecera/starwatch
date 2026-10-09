/* Starwatch shared panels: topic mix, program and promises, in the news (classic script; exposes window.SWPanels).
   Load after sw-real.js (needs window.SW) and after the optional data files:
     <script src="data/programs.js"></script><script src="data/articles.js"></script><script src="sw-panels.js"></script>
   Every function returns an HTML string ('' when there is nothing honest to show), so a host screen decides where it goes.
   Topic rows and promise topic chips carry `${opts.attr||'data-sw-topic'}="<SW.TOP index>"`; the host's own click
   handler filters or opens the posts. No topic, program or article is ever invented here. */
(function(){
"use strict";
const SW=window.SW;
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nf=n=>Number(n).toLocaleString('en-GB');
const day=s=>{if(!s)return '';const d=new Date(/^\d{4}-\d{2}-\d{2}$/.test(s)?s+'T12:00:00Z':s);return isNaN(d)?String(s):d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'Europe/Prague'})};
const host=u=>{try{return new URL(u).hostname.replace(/^www\./,'')}catch(e){return ''}};
const safeUrl=u=>/^https?:\/\//i.test(String(u||''))?String(u):'';
const TOP=()=>(SW&&SW.TOP)||[];
const isOther=t=>/(^|:)other$/.test(String((TOP()[t]||[])[2]||''))||/^other$/i.test(String((TOP()[t]||[])[0]||''));
const isIssue=t=>(TOP()[t]||[])[4]==='issue';

const TOPIC_NOTE=(SW&&SW.TOPIC_NOTE)||'Reviewed labels come from a checked sample; machine labels cover the rest, each backed by a quoted phrase, and can be wrong.';
/* per-label provenance: SW.topicMeta (sw-real.js) when present, else the asset's own status */
function meta(a,t){
  if(SW&&typeof SW.topicMeta==='function'){try{const m=SW.topicMeta(a,t);if(m)return {machine:!!m.machine,evidence:m.evidence||null}}catch(e){}}
  const ev=a&&a.topicEvidence&&a.topicEvidence[t];
  return {machine:!!a&&a.topicStatus==='machine'&&!isIssue(t),evidence:ev||null};
}
/* a short, safe title for one label on one post: 'Machine label · “phrase”' or 'Reviewed label' */
function mark(a,t){const m=meta(a,t);return m.machine?`<span class="sw-mlab" title="${esc(labelTitle(a,t))}">machine</span>`:''}
function labelTitle(a,t){const m=meta(a,t);return m.machine?`Machine label${m.evidence?` · “${String(m.evidence).replace(/\s+/g,' ').trim().slice(0,160)}”`:''}`:'Reviewed label'}

/* ----- styles (ds.css tokens; no side stripes, no nested cards, no gradient text) ----- */
const CSS=`.swp{font-family:var(--font);color:var(--label);min-width:0}
.swp+.swp{margin-top:22px}
.swp-h{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 10px;margin-bottom:12px}
.swp-h h3{font-family:var(--font);font-size:16px;font-weight:650;letter-spacing:-.01em;line-height:1.3}
.swp-s{font-size:12.5px;color:var(--label3);font-variant-numeric:var(--num)}
.swp-note{margin-top:10px;font-size:12px;line-height:1.5;color:var(--label3);max-width:72ch}
.swp-empty{font-size:13px;line-height:1.5;color:var(--label2)}
.swp-rows{display:grid;gap:2px}
.swp-tr{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:6px 12px;padding:8px 10px;margin:0 -10px;width:calc(100% + 20px);border:0;border-radius:var(--r-sm);background:none;text-align:left;font:inherit;color:inherit;cursor:pointer;transition:background var(--t-fast,.12s)}
.swp-tr:hover{background:var(--sunken)}
.swp-tr.on{background:var(--brand-soft)}
.swp-tr.on .swp-tn{color:var(--brand)}
.swp-tr:focus-visible{outline:2px solid var(--brand);outline-offset:1px}
.swp-tn{display:flex;align-items:center;gap:8px;min-width:0;font-size:13.5px;font-weight:600;line-height:1.3}
.swp-tn span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.swp-iss{flex:none;font-style:normal;font-size:11px;font-weight:600;color:var(--label2);padding:1px 6px;border-radius:var(--r-xs);border:1px dashed var(--hairline-strong)}
.swp-tv{font-size:12.5px;color:var(--label2);font-variant-numeric:var(--num);white-space:nowrap;text-align:right}
.swp-tv b{color:var(--label);font-weight:650;margin-right:3px}
.swp-bar{grid-column:1/-1;height:5px;border-radius:3px;background:var(--sunken);overflow:hidden}
.swp-bar i{display:block;height:100%;border-radius:3px;background:var(--brand);transform-origin:left center;animation:swp-grow .7s var(--ease-out,cubic-bezier(.25,1,.5,1)) both}
.swp-tr.iss .swp-bar i{background:var(--label2)}
@keyframes swp-grow{from{transform:scaleX(0)}}
.swp-more{font-size:12.5px;color:var(--label3);margin-top:6px}
.swp-doc{display:inline-flex;align-items:baseline;flex-wrap:wrap;gap:4px 10px;font-size:14px;font-weight:600;color:var(--label);text-decoration:none;line-height:1.4}
.swp-doc:hover .swp-dt{color:var(--brand);text-decoration:underline}
.swp-fmt{flex:none;font-size:11px;font-weight:650;letter-spacing:.04em;text-transform:uppercase;color:var(--label2);padding:1px 6px;border-radius:var(--r-xs);background:var(--sunken)}
.swp-sum{margin-top:12px;font-size:14px;line-height:1.55;color:var(--label);max-width:72ch}
.swp-tag{display:inline-block;margin-right:8px;font-size:12px;font-weight:600;color:var(--label2);padding:1px 7px;border-radius:var(--r-xs);border:1px solid var(--hairline-strong);vertical-align:1px;white-space:nowrap}
.swp-pl{list-style:none;margin:14px 0 0;padding:0;display:grid;gap:0}
.swp-pr{padding:14px 0;border-top:1px solid var(--hairline)}
.swp-pr:last-child{padding-bottom:4px}
.swp-pt{font-size:14px;font-weight:600;line-height:1.45;color:var(--label);max-width:72ch}
.swp-q{position:relative;margin:8px 0 0;padding:0 0 0 26px;font-family:var(--display);font-size:15px;font-weight:450;line-height:1.5;letter-spacing:-.005em;color:var(--label2);max-width:72ch;overflow-wrap:anywhere}
.swp-q::before{content:"„";position:absolute;left:2px;top:-6px;font:700 30px/1 var(--display);color:var(--brand)}
.swp-pm{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;margin-top:8px;font-size:12.5px}
.swp-pm a{color:var(--brand);font-weight:550;text-decoration:none}
.swp-pm a:hover{text-decoration:underline}
.swp-chip{display:inline-flex;align-items:center;height:24px;padding:0 9px;border-radius:var(--r-chip,6px);font:500 12px var(--font);background:var(--sunken);color:var(--label2);border:1px solid transparent}
button.swp-chip{cursor:pointer}
button.swp-chip:hover{color:var(--label);border-color:var(--hairline-strong)}
.swp-line{font-size:13px;line-height:1.5;color:var(--label2)}
.swp-line b{color:var(--label);font-weight:600;margin-right:6px}
.swp-line a{color:var(--brand);text-decoration:none;font-weight:550}
.swp-line a:hover{text-decoration:underline}
.swp details>summary{list-style:none;display:inline-flex;align-items:center;gap:6px;margin-top:10px;font-size:13px;font-weight:600;color:var(--brand);cursor:pointer}
.swp details>summary::-webkit-details-marker{display:none}
.swp details>summary:hover{text-decoration:underline}
.swp details[open]>summary{display:none}
.swp-nl{list-style:none;margin:0;padding:0;display:grid}
.swp-nl li{border-top:1px solid var(--hairline)}
.swp-nl li:first-child{border-top:0}
.swp-nl a{display:grid;gap:3px;padding:10px 0;text-decoration:none;color:inherit}
.swp-nl a:hover .swp-nt{color:var(--brand);text-decoration:underline}
.swp-nt{font-size:14px;font-weight:600;line-height:1.4;color:var(--label);overflow-wrap:anywhere}
.swp-nm{font-size:12.5px;color:var(--label3);font-variant-numeric:var(--num)}
.swp-nm b{font-weight:600;color:var(--label2)}
@media (prefers-reduced-motion:reduce){.swp-bar i{animation:none}}`;
if(!document.getElementById('sw-panels-css')){const s=document.createElement('style');s.id='sw-panels-css';s.textContent=CSS;(document.head||document.documentElement).appendChild(s)}

/* ----- topic mix ----- */
function topicMix(assetIdxs,opts){
  opts=opts||{};const attr=opts.attr||'data-sw-topic',max=opts.max||8,title=opts.title==null?'Topic mix':opts.title,act=opts.active==null?-1:+opts.active;
  const A=(SW&&SW.assets)||[],T=TOP();const cnt=new Map(),mcn=new Map();let M=0,N=0,NR=0,NM=0;
  (assetIdxs||[]).forEach(i=>{const a=A[i];if(!a)return;M++;const ts=(a.topics||[]).filter(t=>T[t]);if(!ts.length)return;N++;
    let anyRev=false;ts.forEach(t=>{cnt.set(t,(cnt.get(t)||0)+1);if(meta(a,t).machine)mcn.set(t,(mcn.get(t)||0)+1);else anyRev=true});
    if(anyRev)NR++;else NM++});
  const split=NM?` · ${nf(NR)} reviewed, ${nf(NM)} machine`:'';
  const head=title?`<div class="swp-h"><h3>${esc(title)}</h3>${N?`<span class="swp-s">${nf(N)} of ${nf(M)} post${M===1?'':'s'} labelled${split}</span>`:''}</div>`:'';
  if(!N){if(opts.emptyHidden)return '';return `<section class="swp swp-mix">${head}<p class="swp-empty">${M?`None of ${M===1?'this post':'these '+nf(M)+' posts'} carries a topic label.`:'No posts to label.'} <span class="swp-s">${esc(TOPIC_NOTE)}</span></p></section>`}
  const rows=[...cnt.entries()].sort((a,b)=>isOther(a[0])-isOther(b[0])||b[1]-a[1]||String(T[a[0]][0]).localeCompare(String(T[b[0]][0])));
  let shown=rows.slice(0,max);if(act>=0&&cnt.has(act)&&!shown.some(r=>r[0]===act))shown=[...shown.slice(0,max-1),rows.find(r=>r[0]===act)];
  const mx=Math.max(...shown.map(r=>r[1]));
  const body=shown.map(([t,n])=>{const share=Math.round(n/N*100),iss=isIssue(t),on=t===act,mn=mcn.get(t)||0;
    const prov=mn?(mn===n?' · all machine labels':` · ${nf(n-mn)} reviewed, ${nf(mn)} machine`):'';
    return `<button type="button" class="swp-tr${on?' on':''}${iss?' iss':''}" ${attr}="${t}" aria-pressed="${on}" title="${nf(n)} of ${nf(N)} labelled posts (${share} %)${prov}${on?' · click again to show all posts':' · show these posts'}"><span class="swp-tn"><span>${esc(T[t][0])}</span>${iss?'<em class="swp-iss" title="A named local issue, reviewed against the post caption">local issue</em>':''}</span><span class="swp-tv"><b>${nf(n)}</b>${n===1?'post':'posts'} · ${share} %</span><span class="swp-bar" aria-hidden="true"><i style="width:${Math.max(2,n/mx*100).toFixed(1)}%"></i></span></button>`}).join('');
  const rest=rows.length-shown.length;
  return `<section class="swp swp-mix">${head}<div class="swp-rows" role="group" aria-label="${esc(title||'Topic mix')}">${body}</div>${rest>0?`<p class="swp-more">and ${rest} more topic${rest===1?'':'s'} with fewer posts</p>`:''}${opts.note===false?'':`<p class="swp-note">${esc(TOPIC_NOTE)} Shares are of labelled posts; a post can carry several topics.</p>`}</section>`;
}

/* ----- program and promises ----- */
function topicIndex(id){if(!id)return -1;const T=TOP();let k=T.findIndex(t=>t[2]===id);if(k<0){const s=String(id).split(':').pop();k=T.findIndex(t=>String(t[2]||'').split(':').pop()===s)}return k}
const topicLabel=id=>{const s=String(id||'').split(':').pop().replace(/_/g,' ').trim();return s?s.charAt(0).toUpperCase()+s.slice(1):''};
function programs(listIdx,opts){
  opts=opts||{};const P=window.SW_PROGRAMS,L=SW&&SW.lists&&SW.lists[listIdx];
  if(!P||!P.lists||!L)return '';const e=P.lists[L.id];if(!e)return '';
  const attr=opts.attr||'data-sw-topic',max=opts.max==null?4:opts.max,title=opts.title||'Program and promises';
  const checked=e.fetched_at||P.generated_at;const url=safeUrl(e.program_url);
  if(e.status==='not_found')return `<section class="swp swp-prog"><p class="swp-line"><b>Program</b>No published program found for ${opts.owner?esc(opts.owner):'this list'}${checked?` (checked ${esc(day(checked))})`:''}.</p></section>`;
  if(e.status==='unreachable')return `<section class="swp swp-prog"><p class="swp-line"><b>Program</b>${url?`A program was found at <a href="${esc(url)}" target="_blank" rel="noopener">${esc(host(url)||'its source')} ↗</a> but could not be read`:'A program was found but could not be read'}${checked?` (checked ${esc(day(checked))})`:''}.</p></section>`;
  if(e.status!=='found')return '';
  const fmtL=e.format==='pdf'?'PDF':e.format==='html'?'Web page':'';
  const pr=(Array.isArray(e.promises)?e.promises:[]).filter(p=>p&&(p.text||p.quote));
  const one=p=>{const ti=topicIndex(p.topic),src=safeUrl(p.source_url)||url,pg=(/#page=(\d+)/.exec(String(p.source_url||''))||[])[1];
    const chip=ti>=0?`<button type="button" class="swp-chip" ${attr}="${ti}" title="Show posts labelled ${esc(TOP()[ti][0])}">${esc(TOP()[ti][0])}</button>`:p.topic?`<span class="swp-chip">${esc(topicLabel(p.topic))}</span>`:'';
    return `<li class="swp-pr">${p.text?`<p class="swp-pt">${esc(p.text)}</p>`:''}${p.quote?`<blockquote class="swp-q" lang="cs">${esc(p.quote)}“</blockquote>`:''}<div class="swp-pm">${chip}${src?`<a href="${esc(src)}" target="_blank" rel="noopener">${pg?`Source, page ${esc(pg)}`:'Source'} ↗</a>`:''}</div></li>`};
  const head=`<div class="swp-h"><h3>${esc(title)}</h3>${opts.sub?`<span class="swp-s">${esc(opts.sub)}</span>`:''}</div>`;
  const doc=url?`<a class="swp-doc" href="${esc(url)}" target="_blank" rel="noopener">${fmtL?`<span class="swp-fmt">${fmtL}</span>`:''}<span class="swp-dt">${esc(e.program_title||host(url)||'Published program')} ↗</span></a>${checked?` <span class="swp-s">fetched ${esc(day(checked))}</span>`:''}`:'';
  const sum=e.summary?`<p class="swp-sum"><span class="swp-tag">Machine-written summary</span>${esc(e.summary)}</p>`:'';
  const list=pr.length?`<ol class="swp-pl">${pr.slice(0,max).map(one).join('')}</ol>${pr.length>max?`<details><summary>Show ${pr.length-max} more promise${pr.length-max===1?'':'s'}</summary><ol class="swp-pl">${pr.slice(max).map(one).join('')}</ol></details>`:''}`:'';
  const note=`<p class="swp-note"${P.method?` title="${esc(P.method)}"`:''}>${sum||pr.length?'Summary and promise paraphrases are machine-written; each promise quotes the program verbatim and links to its source. A promise is what the list published, not a prediction.':''}</p>`;
  return `<section class="swp swp-prog">${head}${doc}${sum}${list}${sum||pr.length?note:''}</section>`;
}

/* ----- in the news ----- */
function news(ref,opts){
  opts=opts||{};const X=window.SW_ARTICLES;if(!X||!Array.isArray(X.items)||!ref||!SW)return '';
  let id=null,pick=null;
  if(ref.list!=null&&SW.lists[ref.list]){id=SW.lists[ref.list].id;pick=it=>Array.isArray(it.lists)&&it.lists.includes(id)}
  else if(ref.cand!=null&&SW.cands[ref.cand]){id=SW.cands[ref.cand].id;pick=it=>Array.isArray(it.cands)&&it.cands.includes(id)}
  else if(ref.city!=null&&SW.cities[ref.city]){id=SW.cities[ref.city].id;pick=it=>it.city_id===id}
  if(!pick)return '';
  const seen=new Set();const items=X.items.filter(it=>it&&safeUrl(it.url)&&it.title&&pick(it)&&!seen.has(it.url)&&seen.add(it.url))
    .sort((a,b)=>String(b.published_at||'').localeCompare(String(a.published_at||''))||String(a.title).localeCompare(String(b.title)));
  if(!items.length)return '';
  const max=opts.max||6,title=opts.title||'In the news';
  const li=it=>`<li><a href="${esc(it.url)}" target="_blank" rel="noopener"><span class="swp-nt">${esc(it.title)}</span><span class="swp-nm"><b>${esc(it.outlet||host(it.url))}</b>${it.published_at?` · ${esc(day(it.published_at))}`:''}${it.match==='title'?' · named in the title':it.match==='text'?' · named in the text':''}</span></a></li>`;
  return `<section class="swp swp-news"><div class="swp-h"><h3>${esc(title)}</h3><span class="swp-s">${nf(items.length)} article${items.length===1?'':'s'}</span></div><ul class="swp-nl">${items.slice(0,max).map(li).join('')}</ul>${items.length>max?`<details><summary>+${items.length-max} more</summary><ul class="swp-nl">${items.slice(max).map(li).join('')}</ul></details>`:''}<p class="swp-note"${X.method?` title="${esc(X.method)}"`:''}>Matched by name in the title or text; a mention is not endorsement. Titles and links only; the articles stay with their publishers.</p></section>`;
}

window.SWPanels={TOPIC_NOTE,topicMix,programs,news,topicIndex,topicMeta:meta,labelTitle,machineMark:mark,
  get loaded(){return {programs:!!(window.SW_PROGRAMS&&window.SW_PROGRAMS.lists),articles:!!(window.SW_ARTICLES&&Array.isArray(window.SW_ARTICLES.items))}}};
})();
