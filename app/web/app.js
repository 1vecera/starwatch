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
.sw-data{pointer-events:auto;position:relative;display:inline-flex;flex:none;width:auto;align-items:center;gap:7px;height:calc(var(--chrome-h,46px) - 8px);margin-left:6px;padding:6px 12px 6px 10px;border:0;border-radius:999px;font:500 12.5px var(--font);color:var(--label2);background:none;cursor:pointer;white-space:nowrap;transition:transform .2s var(--ease)}
.sw-data>span{position:relative;font:500 12.5px var(--font);letter-spacing:0}
.sw-data::after{content:"";position:absolute;inset:0;border-radius:inherit;background:rgba(15,23,42,.06);opacity:0;transform:scale(.88);transition:opacity .2s var(--ease),transform .3s var(--ease)}
.sw-data:hover{color:var(--label)}
.sw-data:hover::after,.sw-data:focus-visible::after{opacity:1;transform:none}
.sw-data:active{transform:scale(.96)}
.sw-data:focus-visible{outline:2px solid var(--brand);outline-offset:1px}
.sw-data:not(.sw-switchable){cursor:default}.sw-data:not(.sw-switchable):hover::after{opacity:0}
.sw-data i{position:relative;flex:none;width:7px;height:7px;border-radius:50%;background:var(--orange)}
.sw-data.real i{background:var(--green)}
.sw-data.real i::after{content:"";position:absolute;inset:0;border-radius:50%;background:var(--green);animation:sw-live 2.4s var(--ease) infinite}
.sw-data .d-k{color:var(--label);font-weight:550}
@keyframes sw-live{0%{transform:scale(1);opacity:.45}70%,100%{transform:scale(2.6);opacity:0}}
.c-left>.sw-data{background:var(--float-bg);-webkit-backdrop-filter:var(--float-blur);backdrop-filter:var(--float-blur);border:1px solid var(--float-line);box-shadow:var(--float-shadow);margin-left:0}
@media (max-width:860px){.sw-data{margin-left:4px;padding:6px 10px 6px 9px}.sw-data .d-u{display:none}}
@media (prefers-reduced-motion:reduce){.sw-data.real i::after{animation:none;opacity:0}}
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
  if(/^All (data|names).*mock/i.test(t))el.textContent='Live production data · '+SW.source.detail;
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
const ch=SWChrome.mount(document.body,{active:me,routes:true,mock:false,
  onBack(){if(me!=='atlas')location.href='atlas.html'}});
// quiet data status in the brand pill: "Live · updated 05:40" or "Simulated"; click switches when both exist
const canSwitch=real||!!SW.available.real;
const exp=real&&SW.source.exported_at?new Date(SW.source.exported_at):null;
const hm=d=>d.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:'Europe/Prague'});
const day=d=>d.toLocaleDateString('en-GB',{day:'numeric',month:'short',timeZone:'Europe/Prague'});
const when=exp&&!isNaN(exp)?(day(exp)===day(new Date())?hm(exp):`${day(exp)} ${hm(exp)}`):'';
const badge=document.createElement('button');
badge.className='sw-data'+(real?' real':'')+(canSwitch?' sw-switchable':'');
badge.title=[real?'Live production data':'Simulated universe',exp&&!isNaN(exp)?'exported '+exp.toLocaleString('en-GB',{timeZone:'Europe/Prague'}):'',SW.source.checkpoint?'checkpoint '+SW.source.checkpoint:'',SW.source.detail||'',canSwitch?(real?'Click to switch to simulated data':'Click to switch to live data'):''].filter(Boolean).join('\n');
badge.setAttribute('aria-label',(real?'Live data'+(when?', updated '+when:''):'Simulated data')+(canSwitch?'. Switch data source':''));
badge.innerHTML=real?`<i></i><span><span class="d-k">Live</span>${when?` · <span class="d-u">updated </span>${when}`:''}</span>`:`<i></i><span class="d-k">Simulated</span>`;
badge.addEventListener('click',()=>{if(!canSwitch)return;const u=new URL(location.href);u.searchParams.set('data',real?'sim':'real');location.href=u.toString()});
const host=ch.el.querySelector('.c-brand')||ch.el.querySelector('.c-left');host&&host.appendChild(badge);
})();
