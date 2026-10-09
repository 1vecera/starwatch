/* Starwatch app shell: shared chrome, data-mode badge, selection hand-off and page transitions.
   Include last on every screen: <script src="app.js" data-screen="atlas"></script> */
(function(){
"use strict";
const me=document.currentScript&&document.currentScript.dataset.screen||'atlas';
const SW=window.SW;
const old=document.getElementById('chrome');if(old)old.remove();

// cross-document view transitions (Chrome 126+); harmless elsewhere
const st=document.createElement('style');
st.textContent=`@view-transition{navigation:auto}.sw-chrome{view-transition-name:sw-chrome;z-index:200!important}#thumbs{z-index:2!important}
.sw-data{pointer-events:auto;position:relative;display:inline-flex;flex:none;width:auto;align-items:center;gap:7px;height:calc(var(--chrome-h,46px) - 8px);margin-left:6px;padding:6px 12px 6px 10px;border:0;border-radius:999px;font:500 12.5px var(--font);color:var(--label2);background:none;cursor:pointer;white-space:nowrap;text-decoration:none;transition:transform .2s var(--ease)}
.sw-data>span{position:relative;font:500 12.5px var(--font);letter-spacing:0}
.sw-data::after{content:"";position:absolute;inset:0;border-radius:inherit;background:rgba(15,23,42,.06);opacity:0;transform:scale(.88);transition:opacity .2s var(--ease),transform .3s var(--ease)}
.sw-data:hover{color:var(--label)}
.sw-data:hover::after,.sw-data:focus-visible::after{opacity:1;transform:none}
.sw-data:active{transform:scale(.96)}
.sw-data:focus-visible{outline:2px solid var(--brand);outline-offset:1px}
.sw-data svg{position:relative;flex:none;width:15px;height:15px;color:var(--brand)}
.sw-data.sim svg{color:var(--orange)}
.sw-data .d-k{color:var(--label);font-weight:600}
.c-left>.sw-data{background:var(--float-bg);-webkit-backdrop-filter:var(--float-blur);backdrop-filter:var(--float-blur);border:1px solid var(--float-line);box-shadow:var(--float-shadow);margin-left:0}
@media (max-width:1440px){.sw-data .d-l{display:none}}
@media (max-width:1100px){.sw-data .d-u{display:none}}
@media (max-width:860px){.sw-data{margin-left:2px;padding:6px 10px 6px 8px}}
@media (max-width:340px){.sw-data .d-w{display:none}}
.clm{margin:6px 0;padding:8px 12px;background:var(--sunken);border-radius:8px;font-size:13.5px;line-height:1.45;color:var(--label)}
.cl-note{font-size:11px;color:var(--label3);margin-top:4px}`;
document.head.appendChild(st);

// selection shared between screens (stable within one data mode)
const KEY='sw-sel';
window.SWSel={
  get(){try{const s=JSON.parse(localStorage.getItem(KEY)||'null');return s&&s.mode===SW.source.kind?s:null}catch(e){return null}},
  set(type,i){try{localStorage.setItem(KEY,JSON.stringify({mode:SW.source.kind,type,i}))}catch(e){}}
};
const q=new URLSearchParams(location.search);
['cand','list','asset'].forEach(t=>{if(q.has(t))SWSel.set(t,+q.get(t))});

// screens were designed on the simulation; in live mode their 'mock' notes would be false
if(SW.source.kind==='real'){const fix=()=>document.querySelectorAll('body *').forEach(el=>{if(el.children.length)return;const t=el.textContent.trim();
  if(/^All (data|names).*mock/i.test(t))el.textContent='Snapshot of public posts collected '+SW.snapshot.long+' · '+SW.source.detail;
  else if(/^mock$/i.test(t))el.textContent='computed';
  else if(/^MOCK DATA$/.test(t))el.style.display='none'});fix();setTimeout(fix,1500);setTimeout(fix,4000)}
// Atlas deep links from other screens: fly to the requested city, party, person or post
if(me==='atlas'&&window.__atlas){const A=window.__atlas;setTimeout(()=>{
  if(q.has('asset')&&A.fitAsset)A.fitAsset(+q.get('asset'));else if(q.has('cand')&&A.fitCand)A.fitCand(+q.get('cand'));
  else if(q.has('list')&&A.fitList)A.fitList(+q.get('list'));else if(q.has('city')&&A.fitCity)A.fitCity(+q.get('city'))},400)}
// screen hand-offs carry the current entity (Spotlight sets window.__spotSel)
document.addEventListener('click',e=>{const b=e.target.closest('[data-go-scr]');if(!b)return;const s=window.__spotSel;location.href=`${b.dataset.goScr}.html${s?`?${s[0]}=${s[1]}`:''}`});
if(!window.SWChrome)return;
const real=SW.source.kind==='real';
const ch=SWChrome.mount(document.body,{active:me,routes:true,mock:false,onBack(){}});
// snapshot chip in the brand pill: says plainly that this is a dated collection, not live monitoring; opens About
const exp=real&&SW.source.exported_at?new Date(SW.source.exported_at):null;
const badge=document.createElement('a');
badge.className='sw-data'+(real?'':' sim');
const clock='<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.6V8l2.3 1.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
if(real){
  badge.href='about.html#snapshot';
  badge.title=`Snapshot: public posts collected ${SW.snapshot.long}. Not live monitoring.${exp&&!isNaN(exp)?'\nExported '+exp.toLocaleString('en-GB',{timeZone:'Europe/Prague',day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'})+' (Prague)':''}\nOpen About for coverage and limitations.`;
  badge.setAttribute('aria-label',`Snapshot of public posts collected ${SW.snapshot.long}, not live. About the data`);
  badge.innerHTML=`${clock}<span><span class="d-k">Snapshot</span><span class="d-w"> · <span class="d-l">public posts collected </span>${SW.snapshot.short}</span><span class="d-u"> · not live</span></span>`;
}else{
  const back=!!SW.available.real;
  badge.href=back?(()=>{const u=new URL(location.href);u.searchParams.set('data','real');return u.toString()})():'about.html#snapshot';
  badge.title=back?'Simulated universe (generated names and posts). Click to return to the collected snapshot.':'Simulated universe: generated names, lists, posts and metrics. The collected snapshot is not available here.';
  badge.setAttribute('aria-label',back?'Simulated data. Return to the collected snapshot':'Simulated data');
  badge.innerHTML=`${clock}<span><span class="d-k">Simulated</span><span class="d-u">${back?' · back to snapshot':' · not real data'}</span></span>`;
}
const host=ch.el.querySelector('.c-brand')||ch.el.querySelector('.c-left');host&&host.appendChild(badge);
})();
