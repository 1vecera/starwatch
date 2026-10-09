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
// the snapshot chip is drawn by SWChrome.mount; in the simulated universe it says so instead
const badge=ch.el.querySelector('.sw-data');
if(badge&&!real){
  const back=!!SW.available.real;
  badge.classList.add('sim');
  badge.href=back?(()=>{const u=new URL(location.href);u.searchParams.set('data','real');return u.toString()})():'about.html#snapshot';
  badge.title=back?'Simulated universe (generated names and posts). Click to return to the collected snapshot.':'Simulated universe: generated names, lists, posts and metrics. The collected snapshot is not available here.';
  badge.setAttribute('aria-label',back?'Simulated data. Return to the collected snapshot':'Simulated data');
  badge.innerHTML=`${SWChrome.CLOCK}<span><span class="d-k">Simulated</span><span class="d-u">${back?' · back to snapshot':' · not real data'}</span></span>`;
}
})();
