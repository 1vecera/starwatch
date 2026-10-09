/* Starwatch party and list picker (classic script; exposes window.SWPicker). Load after sw-real.js.
   One searchable picker for Atlas, Pulse and Radar: national parties (lists of the same party grouped across
   cities, coalitions counted under every member party) and every registered list with its logo, short name and city.
     SWPicker.open({anchor, title, city:-1|cityIdx, groups:true, exclude:Set<listIdx>, note, onPick})
       onPick({type:'list', list}) or onPick({type:'party', key, lists})
     SWPicker.groups / SWPicker.group(key) / SWPicker.groupsOf(listIdx) / SWPicker.posts(listIdx)
     SWPicker.logo(listIdx | group, px) -> HTML    SWPicker.party(q=URLSearchParams) -> group or null (?party=<key>)
   Membership comes from the party logos attached to each list in the export, then from the registry short name
   (e.g. "KDU-ČSL+ODS"); lists of local movements stay on their own. */
(function(){
"use strict";
const SW=window.SW;if(!SW||!SW.lists)return;
const {lists,cities,cands}=SW;
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fold=s=>String(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
const css=c=>Array.isArray(c)?`rgb(${c.map(v=>Math.round(v*255)).join(',')})`:'var(--label3)';

/* national parties: key, display label, the logo/short-name tokens that mean it */
const PARTIES=[
 ['ano','ANO 2011',['ano','ano 2011']],['ods','ODS',['ods']],['stan','STAN',['stan']],['pirati','Piráti',['pirati','pirat']],
 ['spd','SPD',['spd']],['kdu','KDU-ČSL',['kdu-csl','kdu','kducsl']],['top09','TOP 09',['top 09','top09','top']],
 ['zeleni','Zelení',['zeleni','zelen','zel.']],['auto','Motoristé sobě',['auto','motoriste sobe']],['socdem','SOCDEM',['socdem']],
 ['kscm','KSČM',['kscm']],['pro','PRO',['pro']],['prisaha','Přísaha',['prisaha','prisah']],['svobodni','Svobodní',['svobodni','svob','svobo']],
 ['trikolora','Trikolora',['trikolora','trikol','triko']],['stacilo','Stačilo!',['stacilo!']]];
const TOK={};PARTIES.forEach(([k,,ts])=>ts.forEach(t=>TOK[t]=k));

const postCount=new Array(lists.length).fill(0);
lists.forEach(L=>{postCount[L.i]=(L.assets||[]).length+(L.cands||[]).reduce((s,k)=>s+((cands[k]&&cands[k].assets)||[]).length,0)});
const memberOf=lists.map(L=>{const ks=[];const add=k=>{if(k&&!ks.includes(k))ks.push(k)};
  (L.logos||[]).forEach(g=>add(TOK[fold(g.party)]));
  String(L.short||'').split('+').map(s=>fold(s).trim()).forEach(t=>add(TOK[t]));
  return ks});
const logoOf=new Map();
lists.forEach((L,i)=>(L.logos||[]).forEach(g=>{const k=TOK[fold(g.party)];if(k&&g.path&&!logoOf.has(k))logoOf.set(k,g.path)}));
const groups=PARTIES.map(([key,label])=>{const ls=lists.filter(L=>memberOf[L.i].includes(key)).map(L=>L.i);
  const cp={};ls.forEach(i=>{const c=lists[i].city;cp[c]=(cp[c]||0)+postCount[i]});
  return {key,label,lists:ls.sort((a,b)=>postCount[b]-postCount[a]),cities:Object.keys(cp).map(Number).sort((a,b)=>cp[b]-cp[a]),posts:ls.reduce((s,i)=>s+postCount[i],0),logo:logoOf.get(key)||null,
    solo:ls.filter(i=>memberOf[i].length===1).length,s:fold(label+' '+ls.map(i=>lists[i].name+' '+lists[i].short).join(' '))}})
  .filter(g=>g.lists.length).sort((a,b)=>b.posts-a.posts||b.lists.length-a.lists.length||a.label.localeCompare(b.label,'cs'));
const byKey=new Map(groups.map(g=>[g.key,g]));

function initials(s){const w=String(s||'').replace(/[^\p{L}\p{N}\s-]/gu,' ').trim().split(/\s+/).filter(Boolean);return (w.length>1?w[0][0]+w[1][0]:(w[0]||'?').slice(0,3)).toUpperCase()}
function logo(x,px){px=px||28;const g=typeof x==='object'&&x&&x.key?x:null,L=g?null:lists[x];
  const src=g?g.logo:L&&L.logos&&L.logos[0]&&L.logos[0].path;const col=g?'var(--label3)':css(L&&L.col);
  const txt=g?initials(g.label):initials(L&&(L.short||L.name));
  return `<span class="swk-lg" style="--s:${px}px;--gc:${col}" aria-hidden="true">${src?`<img src="${esc(src)}" alt="" loading="lazy" decoding="async" onerror="this.remove()">`:''}<b>${esc(txt.slice(0,3))}</b></span>`}

const CSS=`.swk-lg{position:relative;flex:none;display:grid;place-items:center;width:var(--s);height:var(--s);border-radius:calc(var(--s)*.24);background:#fff;border:1px solid var(--hairline);overflow:hidden}
.swk-lg b{font:650 calc(var(--s)*.34)/1 var(--font);letter-spacing:-.01em;color:color-mix(in srgb,var(--gc) 70%,#0F172A)}
.swk-lg img{position:absolute;inset:12%;width:76%;height:76%;object-fit:contain;background:#fff}
.swk-trigger{display:inline-flex;align-items:center;gap:8px;height:34px;padding:0 12px 0 10px;border-radius:var(--r-control);background:var(--surface);border:1px solid var(--hairline-strong);font:550 13px var(--font);color:var(--label);cursor:pointer;white-space:nowrap;max-width:100%}
.swk-trigger:hover{border-color:var(--brand);color:var(--brand)}
.swk-trigger svg{width:15px;height:15px;flex:none;color:var(--label2)}
.swk-trigger .swk-lg{margin-left:-4px}
.swk-trigger span{overflow:hidden;text-overflow:ellipsis}
.swk-scrim{position:fixed;inset:0;z-index:300;background:rgba(15,23,42,.18);opacity:0;transition:opacity .2s cubic-bezier(.25,1,.5,1)}
.swk-scrim.on{opacity:1}
.swk{position:fixed;z-index:301;width:min(520px,calc(100vw - 24px));max-height:min(620px,calc(100vh - 96px));display:flex;flex-direction:column;border-radius:var(--r-xl);background:var(--surface);border:1px solid var(--hairline);box-shadow:var(--elev-3);overflow:hidden;opacity:0;transform:translateY(-6px);transition:opacity .2s cubic-bezier(.25,1,.5,1),transform .3s cubic-bezier(.25,1,.5,1);font-family:var(--font)}
.swk.on{opacity:1;transform:none}
.swk-h{display:flex;align-items:center;gap:10px;padding:14px 16px 10px}
.swk-h b{font:650 15px var(--font);color:var(--label)}
.swk-h small{margin-left:auto;font-size:12px;color:var(--label3)}
.swk-x{width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:var(--label2);flex:none}
.swk-x:hover{background:var(--sunken);color:var(--label)}
.swk-in{display:flex;align-items:center;gap:10px;margin:0 12px;padding:0 12px;height:42px;border-radius:10px;background:var(--sunken);border:1px solid transparent}
.swk-in:focus-within{border-color:var(--brand);background:var(--surface)}
.swk-in svg{width:17px;height:17px;color:var(--label3);flex:none}
.swk-in input{flex:1;min-width:0;border:0;outline:0!important;background:none;font:500 15px var(--font);color:var(--label);-webkit-appearance:none;appearance:none}
.swk-in input::-webkit-search-cancel-button{-webkit-appearance:none}
.swk-cities{display:flex;gap:6px;padding:10px 12px 8px;overflow-x:auto;scrollbar-width:none;flex:none}
.swk-cities::-webkit-scrollbar{display:none}
.swk-cities button{flex:none;height:28px;padding:0 10px;border-radius:999px;border:1px solid var(--hairline-strong);background:var(--surface);font:550 12.5px var(--font);color:var(--label2);white-space:nowrap}
.swk-cities button:hover{color:var(--label)}
.swk-cities button.on{background:var(--brand);border-color:var(--brand);color:#fff}
.swk-list{flex:1;min-height:0;overflow:auto;padding:2px 6px 8px;overscroll-behavior:contain}
.swk-sec{padding:12px 10px 6px;font-size:12px;font-weight:600;color:var(--label3)}
.swk-r{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;align-items:center;width:100%;min-height:52px;padding:7px 10px;border-radius:10px;text-align:left;color:var(--label);background:none;border:0;cursor:pointer}
.swk-r.sel,.swk-r:hover{background:var(--brand-soft)}
.swk-r[aria-disabled="true"]{opacity:.55;cursor:default}
.swk-r .t{min-width:0}
.swk-r .t b{display:block;font-size:14px;font-weight:600;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.swk-r .t small{display:block;font-size:12.5px;color:var(--label2);line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.swk-r .n{text-align:right;font-size:12.5px;color:var(--label2);font-variant-numeric:tabular-nums;white-space:nowrap}
.swk-r .n b{display:block;font-size:14px;font-weight:650;color:var(--label)}
.swk-r .tag{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:5px;background:var(--sunken);font-size:11px;font-weight:600;color:var(--label2);vertical-align:1px}
.swk-empty{padding:28px 16px;text-align:center;font-size:13.5px;color:var(--label2)}
.swk-f{display:flex;gap:14px;align-items:center;padding:9px 16px;border-top:1px solid var(--hairline);font-size:12px;color:var(--label3)}
.swk-f .sw-kbd{margin-right:4px}
@media (max-width:640px){.swk{left:0!important;right:0;top:auto!important;bottom:0;width:100%;max-height:86vh;border-radius:20px 20px 0 0;transform:translateY(24px)}.swk.on{transform:none}.swk-f{display:none}.swk-list{padding-bottom:calc(10px + env(safe-area-inset-bottom))}}
@media (prefers-reduced-motion:reduce){.swk,.swk-scrim{transition:none}}`;
function style(){if(document.getElementById('swk-css'))return;const s=document.createElement('style');s.id='swk-css';s.textContent=CSS;(document.head||document.documentElement).appendChild(s)}
style();

let cur=null;
function close(){if(!cur)return;const c=cur;cur=null;c.el.classList.remove('on');c.scrim.classList.remove('on');setTimeout(()=>{c.el.remove();c.scrim.remove()},220);
  removeEventListener('keydown',c.key,true);if(c.back&&c.back.focus)c.back.focus({preventScroll:true})}
function open(o){
  style();close();o=Object.assign({title:'Choose a party or list',city:-1,groups:true,exclude:new Set()},o||{});
  const scrim=document.createElement('div');scrim.className='swk-scrim';
  const el=document.createElement('div');el.className='swk';el.setAttribute('role','dialog');el.setAttribute('aria-modal','true');el.setAttribute('aria-label',o.title);
  const cityCounts=cities.map(c=>c.lists.length);
  el.innerHTML=`<div class="swk-h"><b>${esc(o.title)}</b><small>${esc(o.note||`${groups.length} parties · ${lists.length} lists · ${cities.length} cities`)}</small><button class="swk-x" aria-label="Close"><svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 3l8 8M11 3l-8 8"/></svg></button></div>
<label class="swk-in"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.4 15.4 20.5 20.5"/></svg><input type="search" placeholder="Search a party, list or city" aria-label="Search parties and lists" autocomplete="off" spellcheck="false"></label>
<div class="swk-cities" role="group" aria-label="City"><button data-c="-1">All cities</button>${cities.map((c,i)=>`<button data-c="${i}">${esc(c.name)} <span aria-hidden="true">${cityCounts[i]}</span></button>`).join('')}</div>
<div class="swk-list" role="listbox"></div>
<div class="swk-f"><span><span class="sw-kbd">↑</span><span class="sw-kbd">↓</span>move</span><span><span class="sw-kbd">↵</span>choose</span><span><span class="sw-kbd">esc</span>close</span></div>`;
  document.body.append(scrim,el);
  const inp=el.querySelector('input'),box=el.querySelector('.swk-list'),cbar=el.querySelector('.swk-cities');
  let city=o.city>=0&&cities[o.city]?o.city:-1,rows=[],sel=0;
  function render(){
    const q=fold(inp.value.trim());
    cbar.querySelectorAll('button').forEach(b=>b.classList.toggle('on',+b.dataset.c===city));
    const qm=s=>!q||q.split(/\s+/).every(w=>s.includes(w));
    rows=[];let h='';
    if(o.groups){const gs=groups.filter(g=>(city<0||g.cities.includes(city))&&qm(g.s+' '+fold(g.cities.map(i=>cities[i].name).join(' '))));
      if(gs.length){h+=`<div class="swk-sec">${city<0?'National parties, across cities':'National parties in '+esc(cities[city].name)}</div>`;
        gs.forEach(g=>{const ls=city<0?g.lists:g.lists.filter(i=>lists[i].city===city),posts=ls.reduce((s,i)=>s+postCount[i],0);
          const where=city<0?g.cities.map(i=>cities[i].name):ls.map(i=>lists[i].name);
          rows.push({type:'party',key:g.key,lists:ls});
          h+=`<button class="swk-r" role="option" data-r="${rows.length-1}">${logo(g,34)}<span class="t"><b>${esc(g.label)}</b><small>${esc(where.slice(0,4).join(', '))}${where.length>4?` +${where.length-4}`:''}</small></span><span class="n"><b>${posts.toLocaleString('en-US')}</b>${ls.length} list${ls.length===1?'':'s'}</span></button>`})}}
    const ls=lists.filter(L=>(city<0||L.city===city)&&!o.exclude.has(L.i)&&qm(fold(L.name+' '+L.short+' '+cities[L.city].name+' '+memberOf[L.i].map(k=>byKey.get(k)?byKey.get(k).label:'').join(' '))))
      .sort((a,b)=>postCount[b.i]-postCount[a.i]||(b.relevant-a.relevant)||a.name.localeCompare(b.name,'cs'));
    if(ls.length){h+=`<div class="swk-sec">${city<0?'All lists':'Lists in '+esc(cities[city].name)} · ${ls.length}</div>`;
      ls.slice(0,q?80:city<0?60:40).forEach(L=>{rows.push({type:'list',list:L.i});const parts=memberOf[L.i].map(k=>byKey.get(k).label);
        const sub=[city<0?cities[L.city].name:null,L.short&&L.short!==L.name?L.short:null,parts.length>1?parts.join(' + '):null].filter(Boolean);
        h+=`<button class="swk-r" role="option" data-r="${rows.length-1}">${logo(L.i,34)}<span class="t"><b>${esc(L.name)}</b><small>${esc(sub.join(' · ')||cities[L.city].name)}</small></span><span class="n">${postCount[L.i]?`<b>${postCount[L.i].toLocaleString('en-US')}</b>posts`:`<b>—</b>${L.observed===false?'no verified account':'no posts'}`}</span></button>`})}
    if(!rows.length)h=`<div class="swk-empty">No party or list matches “${esc(inp.value.trim())}”${city>=0?` in ${esc(cities[city].name)}. <button class="pill" data-all style="margin-top:10px">Search all cities</button>`:'.'}</div>`;
    box.innerHTML=h;sel=Math.min(sel,Math.max(0,rows.length-1));mark()}
  function mark(scroll){box.querySelectorAll('.swk-r').forEach(b=>{const on=+b.dataset.r===sel;b.classList.toggle('sel',on);b.setAttribute('aria-selected',on)});
    if(scroll){const s=box.querySelector('.swk-r.sel');s&&s.scrollIntoView({block:'nearest'})}}
  function choose(i){const r=rows[i];if(!r)return;close();o.onPick&&o.onPick(r.type==='party'?{type:'party',key:r.key,lists:r.lists,group:byKey.get(r.key)}:{type:'list',list:r.list})}
  inp.addEventListener('input',()=>{sel=0;render();box.scrollTop=0});
  cbar.addEventListener('click',e=>{const b=e.target.closest('[data-c]');if(!b)return;city=+b.dataset.c;sel=0;render();box.scrollTop=0;b.scrollIntoView({block:'nearest',inline:'nearest'})});
  box.addEventListener('click',e=>{if(e.target.closest('[data-all]')){city=-1;render();return}const b=e.target.closest('.swk-r');if(b)choose(+b.dataset.r)});
  box.addEventListener('mousemove',e=>{const b=e.target.closest('.swk-r');if(b&&+b.dataset.r!==sel){sel=+b.dataset.r;mark()}});
  el.querySelector('.swk-x').onclick=close;scrim.onclick=close;
  const key=e=>{if(!cur)return;if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();close();return}
    if(e.key==='ArrowDown'){e.preventDefault();sel=Math.min(rows.length-1,sel+1);mark(true)}else if(e.key==='ArrowUp'){e.preventDefault();sel=Math.max(0,sel-1);mark(true)}
    else if(e.key==='Enter'&&document.activeElement===inp){e.preventDefault();choose(sel)}};
  addEventListener('keydown',key,true);
  // place under the anchor on desktop; phones get a bottom sheet (CSS)
  const a=o.anchor&&o.anchor.getBoundingClientRect&&o.anchor.getBoundingClientRect();
  if(a&&innerWidth>640){const w=el.offsetWidth;el.style.left=Math.max(12,Math.min(innerWidth-w-12,a.left))+'px';const below=a.bottom+8;el.style.top=(below+320>innerHeight?Math.max(12,innerHeight-Math.min(620,innerHeight-96)-12):below)+'px'}
  else if(innerWidth>640){el.style.left=Math.max(12,(innerWidth-el.offsetWidth)/2)+'px';el.style.top='12vh'}
  cur={el,scrim,key,back:document.activeElement};
  render();requestAnimationFrame(()=>{el.classList.add('on');scrim.classList.add('on');if(innerWidth>640||!matchMedia('(pointer:coarse)').matches)inp.focus({preventScroll:true})});
  return {close};
}
function trigger(label,lg){return `${lg||'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.4 15.4 20.5 20.5"/></svg>'}<span>${esc(label)}</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px"><path d="m7 10 5 5 5-5"/></svg>`}
window.SWPicker={groups,group:k=>byKey.get(k)||null,groupsOf:i=>memberOf[i]||[],posts:i=>postCount[i]||0,logo,open,close,trigger,
  party:q=>{q=q||new URLSearchParams(location.search);return byKey.get(q.get('party'))||null},isOpen:()=>!!cur};
})();
