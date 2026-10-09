/* Starwatch product chrome v4: floating navigation (classic script; exposes window.SWChrome).
   Usage on any screen:
     <link rel="stylesheet" href="ds.css"><link rel="stylesheet" href="brand/chrome.css">
     <script src="mock.js"></script><script src="brand/chrome.js"></script>
     <script>SWChrome.mount(document.body,{active:'atlas',routes:true,onBack:()=>history.back()})</script>
   Floating pills over the page: logo + the snapshot chip (opts.snapshot:false hides it) left, the screen dock
   centred, then search, the author (Daniel Večeřa, with follow links) and the account menu (About, privacy, source, sign out) right.
   routes:true links to atlas/spotlight/pulse/radar/data/about.html; omit it to only fire the 'sw:nav' event / opts.onNav.
   Leave ~64–76px top padding (and ~92px bottom on phones, where the dock floats at the bottom).
   Keys: 1–4 switch screens · ⌘K / Ctrl+K / "/" search · Esc closes palette or menu, else opts.onBack(). */
(function(){
"use strict";
/* ----- icon set: 24px grid, 1.6 stroke, round caps; each glyph carries the Aperture four-point star (.spk) ----- */
const f=n=>+n.toFixed(2);
function star(cx,cy,r,k){const q=r*(k||.27);return `M${f(cx)} ${f(cy-r)}L${f(cx+q)} ${f(cy-q)}L${f(cx+r)} ${f(cy)}L${f(cx+q)} ${f(cy+q)}L${f(cx)} ${f(cy+r)}L${f(cx-q)} ${f(cy+q)}L${f(cx-r)} ${f(cy)}L${f(cx-q)} ${f(cy-q)}Z`}
const SPK=d=>`<path class="spk" d="${d}" fill="currentColor" stroke-width="1"/>`;
const DOT=(x,y)=>`<circle cx="${x}" cy="${y}" r="1.4" fill="currentColor" stroke="none"/>`;
const SCREENS=[
 {k:'atlas',n:'Star Atlas',href:'atlas.html',i:`<path d="M12 21.2s-7.2-6.2-7.2-11.6a7.2 7.2 0 0 1 14.4 0c0 5.4-7.2 11.6-7.2 11.6z"/>${SPK(star(12,9.6,3.7))}`},
 {k:'spotlight',n:'Spotlight',href:'spotlight.html',i:`<path d="M3.5 8V5.5a2 2 0 0 1 2-2H8M16 3.5h2.5a2 2 0 0 1 2 2V8M20.5 16v2.5a2 2 0 0 1-2 2H16M8 20.5H5.5a2 2 0 0 1-2-2V16"/>${SPK(star(12,12,5.4))}`},
 {k:'pulse',n:'Pulse',href:'pulse.html',i:`<path d="M3.5 20.5h17"/><path d="M3.5 16.5l4.2-4.3 3.4 2.6 4.6-5.6"/>${SPK(star(18.2,6.2,4.3))}`},
 {k:'radar',n:'Radar',href:'radar.html',i:`<path d="M20.5 12A8.5 8.5 0 1 1 12 3.5"/><path d="M16.2 12A4.2 4.2 0 1 1 12 7.8"/><path d="M12 12l5.2-5.2"/>${SPK(star(18.4,5.6,3.4))}`}];
/* secondary destinations: compact, after the five screens, no number key */
const EXTRA=[
 {k:'data',n:'By the numbers',short:'Data',href:'data.html',i:`<rect x="3.5" y="4" width="10.5" height="3.6" rx="1.8"/><rect x="3.5" y="10.2" width="16.5" height="3.6" rx="1.8"/><rect x="3.5" y="16.4" width="6.5" height="3.6" rx="1.8"/>${SPK(star(16.4,18.2,3.4))}`},
 {k:'about',n:'About Starwatch',short:'About',href:'about.html',i:`<circle cx="11" cy="12.4" r="8.1"/><path d="M11 11.4v5"/>${DOT(11,8.4)}${SPK(star(18.6,5.4,3.3))}`}];
/* the author, promoted on every screen, and the signed-in user's exits */
const LINKS={linkedin:'https://www.linkedin.com/in/1vecera/',x:'https://x.com/1vecera',repo:'https://github.com/1vecera/starwatch',privacy:'/privacy',logout:'/auth/logout',about:'about.html'};
const G_IN='<svg class="sw-g" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.23 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z"/></svg>';
const G_X='<svg class="sw-g" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M18.9 1.15h3.68l-8.04 9.19L24 22.85h-7.41l-5.8-7.58-6.64 7.58H.47l8.6-9.83L0 1.15h7.59l5.25 6.93zm-1.29 19.5h2.04L6.49 3.24H4.3z"/></svg>';
const I_USER='<circle cx="12" cy="8.6" r="3.9"/><path d="M4.6 20.2c.9-3.6 3.9-5.7 7.4-5.7s6.5 2.1 7.4 5.7"/>';
const I_OUT='<path d="M14 4.5h3.5a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H14"/><path d="M10 8l-4 4 4 4"/><path d="M6 12h9"/>';
const I_EXT='<path d="M9 5H6.5A1.5 1.5 0 0 0 5 6.5v11A1.5 1.5 0 0 0 6.5 19h11a1.5 1.5 0 0 0 1.5-1.5V15"/><path d="M13 5h6v6"/><path d="M19 5l-8 8"/>';
const CLOCK='<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.6V8l2.3 1.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
/* the public snapshot; screens with data pass SW.snapshot / SW.source, public pages use these defaults */
const SNAP={short:'8–9 Oct 2026',long:'8–9 October 2026'};
function chip(){const SW=window.SW,sn=Object.assign({},SNAP,SW&&SW.snapshot||{}),st=window.SW_STATS;
  const ex=SW&&SW.source&&SW.source.exported_at||st&&st.public&&st.public.snapshot&&st.public.snapshot.exported_at;const d=ex?new Date(ex):null;
  const when=d&&!isNaN(d)?'\nExported '+d.toLocaleString('en-GB',{timeZone:'Europe/Prague',day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'})+' (Prague)':'';
  return `<a class="sw-data" href="about.html#snapshot" title="Snapshot: public posts collected ${sn.long}. Not live monitoring.${when}\n${window.SW_RESULTS2026&&window.SW_RESULTS2026.cities?'\n2026 results: Czech Statistical Office, after voting ended. Attention is still not support.':''}\nOpen About for coverage and limitations." aria-label="Snapshot of public posts collected ${sn.long}, not live. About the data">${CLOCK}<span><span class="d-k">Snapshot</span><span class="d-w"> · <span class="d-l">public posts collected </span>${sn.short}</span><span class="d-u"> · not live</span></span></a>`}
const I_LOCK='<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>';
const ALL=SCREENS.concat(EXTRA);
const ICON=(p,cls)=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" class="${cls||''}" aria-hidden="true">${p}</svg>`;
const I_SEARCH='<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.4 15.4L20.5 20.5"/>';
/* ----- the mark: logo A "Aperture" reshaped into a four-point star. Four blades separated by offset slits
   (the aperture's pinwheel) around a clear diamond of negative space. Flat, monochrome (currentColor), static. ----- */
const STAR_D='M-30,0L-10.06,8.55L-6.77,-1.31L-5.21,-0.79L-0.91,-5.09L-10.59,-8.32ZM0,30L8.55,10.06L-1.31,6.77L-0.79,5.21L-5.09,0.91L-8.32,10.59ZM30,0L10.06,-8.55L6.77,1.31L5.21,0.79L0.91,5.09L10.59,8.32ZM0,-30L-8.55,-10.06L1.31,-6.77L0.79,-5.21L5.09,-0.91L8.32,-10.59Z';
function mark(size){return `<svg class="sw-mark" viewBox="-32 -32 64 64" width="${size}" height="${size}" role="img" aria-label="Starwatch"><path d="${STAR_D}" fill="currentColor"/></svg>`}
function lockup(size){return `<span class="sw-lockup sw-logo-host" style="display:inline-flex;align-items:center;gap:${Math.round(size*.22)}px">${mark(size)}<span class="sw-word" style="font-size:${Math.round(size*.56)}px">Starwatch</span></span>`}

/* ----- chrome ----- */
const norm=s=>s.normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
const isMac=/Mac|iPhone|iPad/.test(navigator.platform||navigator.userAgent);
function mount(host,opts){
  opts=Object.assign({active:'atlas',routes:null,mock:true},opts||{});
  const el=document.createElement('header');el.className='sw-chrome';el.setAttribute('role','banner');
  el.innerHTML=`<div class="c-left"><div class="c-brand c-pill"><a class="c-logo" href="atlas.html" aria-label="Starwatch: Star Atlas">${mark(22)}<span class="sw-word">Starwatch</span></a>${opts.snapshot===false?'':chip()}</div>${opts.mock?'<span class="c-mock c-pill" title="All names, posts and metrics on screen are generated"><i></i>MOCK DATA</span>':''}</div>
<nav class="c-seg c-pill" role="tablist" aria-label="Screens">${SCREENS.map((s,i)=>`<button role="tab" data-k="${s.k}" aria-selected="false" aria-label="${s.n}">${ICON(s.i,'ic')}<span class="lbl">${s.n}</span><span class="tip">${s.n}<span class="sw-kbd">${i+1}</span></span></button>`).join('')}<i class="c-div" aria-hidden="true"></i>${EXTRA.map(s=>`<button role="tab" class="c-x" data-k="${s.k}" aria-selected="false" aria-label="${s.n}">${ICON(s.i,'ic')}<span class="lbl">${s.short}</span><span class="tip">${s.n}</span></button>`).join('')}</nav>
<div class="c-right"><button class="c-search c-pill" aria-label="Search" aria-keyshortcuts="${isMac?'Meta+K':'Control+K'}">${ICON(I_SEARCH)}<span class="s-t">Search</span><span class="sw-kbd">${isMac?'⌘K':'Ctrl K'}</span></button>
<div class="c-author c-pill"><a class="c-by" href="${LINKS.about}#author"><span class="c-av" aria-hidden="true">DV</span><span class="c-nm"><small>Made by</small>Daniel Večeřa</span></a><a class="c-fol" href="${LINKS.linkedin}" target="_blank" rel="noopener" aria-label="Follow Daniel Večeřa on LinkedIn">${G_IN}<span>Follow</span></a><a class="c-fol" href="${LINKS.x}" target="_blank" rel="noopener" aria-label="Follow Daniel Večeřa on X">${G_X}<span>Follow</span></a></div>
<button class="c-acct c-pill" aria-haspopup="true" aria-expanded="false" aria-label="Menu: author, about, privacy, sign out">${ICON(I_USER)}<span class="c-av" aria-hidden="true">DV</span></button></div>
<div class="c-menu" role="menu" aria-label="Starwatch menu" hidden>
  <div class="m-auth"><span class="c-av big" aria-hidden="true">DV</span><div><b>Daniel Večeřa</b><small>Prague · made Starwatch</small></div></div>
  <div class="m-fol"><a role="menuitem" class="m-btn" href="${LINKS.linkedin}" target="_blank" rel="noopener">${G_IN}Follow on LinkedIn</a><a role="menuitem" class="m-btn" href="${LINKS.x}" target="_blank" rel="noopener">${G_X}Follow on X</a></div>
  <hr>
  <a role="menuitem" href="${LINKS.about}">${ICON(EXTRA[1].i)}About Starwatch and the data</a>
  <a role="menuitem" href="${LINKS.privacy}">${ICON(I_LOCK)}Privacy</a>
  <a role="menuitem" href="${LINKS.repo}" target="_blank" rel="noopener">${ICON(I_EXT)}Source code on GitHub</a>
  <hr>
  <a role="menuitem" href="${LINKS.logout}" class="m-out">${ICON(I_OUT)}Sign out</a>
</div>`;
  host.appendChild(el);
  const seg=el.querySelector('.c-seg'),btns=[...seg.querySelectorAll('button')];
  function place(){}
  function set(k,user){const s=ALL.find(x=>x.k===k);if(!s)return;btns.forEach(b=>{const on=b.dataset.k===k;b.classList.toggle('on',on);b.setAttribute('aria-selected',on)});
    if(user){const R=opts.routes===true?Object.fromEntries(ALL.map(x=>[x.k,x.href])):opts.routes;if(R&&R[k]){if(k===opts.active&&location.pathname.endsWith(R[k])){return}setTimeout(()=>{location.href=R[k]},110);return}
      host.dispatchEvent(new CustomEvent('sw:nav',{detail:{screen:k,name:s.n},bubbles:true}));opts.onNav&&opts.onNav(k,s)}}
  btns.forEach(b=>b.addEventListener('click',()=>set(b.dataset.k,true)));
  set(opts.active,false);
  /* palette */
  const pal=palette(opts,set);
  el.querySelector('.c-search').addEventListener('click',()=>pal.open());
  /* account menu: author, about, privacy, source, sign out */
  const acct=el.querySelector('.c-acct'),menu=el.querySelector('.c-menu');
  const menuOpen=()=>!menu.hidden;
  function menuSet(on,kb){menu.hidden=!on;acct.setAttribute('aria-expanded',on);if(on){const r=acct.getBoundingClientRect();menu.style.setProperty('--m-right',Math.max(8,innerWidth-r.right)+'px');requestAnimationFrame(()=>menu.classList.add('open'));if(kb){const f=menu.querySelector('a');f&&f.focus({preventScroll:true})}}else menu.classList.remove('open')}
  acct.addEventListener('click',e=>{e.stopPropagation();menuSet(!menuOpen(),e.detail===0)});
  document.addEventListener('pointerdown',e=>{if(menuOpen()&&!menu.contains(e.target)&&!acct.contains(e.target))menuSet(false)});
  menu.addEventListener('keydown',e=>{const it=[...menu.querySelectorAll('[role=menuitem]')],i=it.indexOf(document.activeElement);
    if(e.key==='ArrowDown'){e.preventDefault();it[(i+1)%it.length].focus()}else if(e.key==='ArrowUp'){e.preventDefault();it[(i-1+it.length)%it.length].focus()}});
  addEventListener('keydown',e=>{
    const typing=/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)||document.activeElement.isContentEditable;
    if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();pal.isOpen()?pal.close():pal.open();return}
    if(e.key==='Escape'){if(pal.isOpen()){pal.close();return}if(menuOpen()){menuSet(false);acct.focus();return}if(e.defaultPrevented)return;opts.onBack?opts.onBack():toast('Back');return}
    if(typing||e.metaKey||e.ctrlKey||e.altKey)return;
    if(e.key==='/'){e.preventDefault();pal.open();return}
    const n=+e.key;if(n>=1&&n<=SCREENS.length){flash(btns[n-1]);set(SCREENS[n-1].k,true)}
  });
  return {el,set,open:pal.open,close:pal.close,place};
}
function flash(b){b.classList.add('is-hover','is-press');setTimeout(()=>b.classList.remove('is-press'),140);setTimeout(()=>b.classList.remove('is-hover'),650)}

function palette(opts,set){
  const scrim=document.createElement('div');scrim.className='sw-scrim';
  scrim.innerHTML=`<div class="sw-pal" role="dialog" aria-modal="true" aria-label="Search"><div class="p-in">${ICON(I_SEARCH)}<input placeholder="Search people, party lists, cities…" aria-label="Search"><span class="sw-kbd">esc</span></div><div class="p-list" role="listbox"></div>
<div class="p-foot"><span><span class="sw-kbd">↑</span><span class="sw-kbd">↓</span>move</span><span><span class="sw-kbd">↵</span>open</span><span><span class="sw-kbd">1–4</span>screens</span><span class="p-src">Snapshot of public posts · 8–9 Oct 2026</span></div></div>`;
  document.body.appendChild(scrim);
  const inp=scrim.querySelector('input'),list=scrim.querySelector('.p-list');let rows=[],sel=0;
  const SW=window.SW;
  const idx=[];
  if(SW){
    const css=c=>`rgb(${c.map(v=>Math.round(v*255)).join(',')})`;
    [...SW.cands].sort((a,b)=>b.assets.length-a.assets.length||b.fol-a.fol).forEach(c=>{const L=SW.lists[c.list];idx.push({g:'Candidates',t:c.name,m:`#${c.k} ${L.name} · ${SW.cities[c.city].name}${c.assets.length?' · '+c.assets.length+' posts':''}`,col:css(L.col),s:norm(c.name),ref:['cand',c.i]})});
    SW.lists.forEach(L=>idx.push({g:'Party lists',t:L.name,m:`${SW.cities[L.city].name} · ${L.size} candidates`,col:css(L.col),s:norm(L.name+' '+SW.cities[L.city].name),ref:['list',L.i]}));
    SW.cities.forEach(c=>idx.push({g:'Cities',t:c.name,m:`${c.n.toLocaleString('en-US')} candidates · ${c.L} lists`,col:'var(--label3)',s:norm(c.name),ref:['city',c.i]}));
  }
  function render(){
    const q=norm(inp.value.trim());
    let res;
    if(!q){res=ALL.map((s,i)=>({g:'Jump to',t:s.n,m:'',kb:i<SCREENS.length?String(i+1):'',scr:s.k,icon:s.i})).concat(idx.filter(r=>r.g==='Candidates').slice(0,4).map(r=>Object.assign({},r,{g:'Most active'})))}
    else res=idx.filter(r=>r.s.includes(q)).slice(0,24);
    rows=res;sel=Math.min(sel,Math.max(0,rows.length-1));
    let h='',g='';
    if(!rows.length)h=`<div class="p-h">No match</div>`;
    rows.forEach((r,i)=>{if(r.g!==g){g=r.g;h+=`<div class="p-h">${g}</div>`}
      h+=`<button class="p-r${i===sel?' sel':''}" data-i="${i}" role="option" aria-selected="${i===sel}">${r.icon?ICON(r.icon,'ic'):`<span class="dot" style="background:${r.col}"></span>`}<span class="p-t">${r.t}</span><span class="meta">${r.kb?`<span class="sw-kbd">${r.kb}</span>`:r.m}</span></button>`});
    list.innerHTML=h;
    const s=list.querySelector('.p-r.sel');s&&s.scrollIntoView({block:'nearest'});
  }
  function choose(i){const r=rows[i];if(!r)return;close();if(r.scr)set(r.scr,true);else if(r.ref){location.href=r.ref[0]==='city'?`atlas.html?city=${r.ref[1]}`:`spotlight.html?${r.ref[0]}=${r.ref[1]}`}else{set(r.g==='Cities'?'atlas':'spotlight',true);toast(`${r.t}`)}}
  inp.addEventListener('input',()=>{sel=0;render()});
  inp.addEventListener('keydown',e=>{if(e.key==='ArrowDown'){sel=Math.min(rows.length-1,sel+1);render();e.preventDefault()}if(e.key==='ArrowUp'){sel=Math.max(0,sel-1);render();e.preventDefault()}if(e.key==='Enter')choose(sel)});
  list.addEventListener('click',e=>{const b=e.target.closest('.p-r');if(b)choose(+b.dataset.i)});
  list.addEventListener('mousemove',e=>{const b=e.target.closest('.p-r');if(b&&+b.dataset.i!==sel){sel=+b.dataset.i;list.querySelectorAll('.p-r').forEach(x=>x.classList.toggle('sel',+x.dataset.i===sel))}});
  scrim.addEventListener('mousedown',e=>{if(e.target===scrim)close()});
  function open(){render();scrim.classList.add('open');setTimeout(()=>inp.focus(),30)}
  function close(){scrim.classList.remove('open');inp.blur()}
  return {open,close,isOpen:()=>scrim.classList.contains('open'),el:scrim};
}
let tEl,tT;
function toast(msg){if(!tEl){tEl=document.createElement('div');tEl.className='sw-toast';tEl.setAttribute('role','status');document.body.appendChild(tEl)}
  tEl.innerHTML=msg;tEl.classList.add('show');clearTimeout(tT);tT=setTimeout(()=>tEl.classList.remove('show'),1600)}

window.SWChrome={SCREENS,EXTRA,LINKS,G_IN,G_X,CLOCK,mount,mark,lockup,icon:(k)=>ICON((ALL.find(s=>s.k===k)||{i:I_SEARCH}).i),star,toast,STAR_D};
})();
