/* Starwatch finishing layer: consistent tab titles, browser colour, install icons, share cards,
   a polite offline notice and an empty-state helper. Classic script, no dependencies, safe to include twice.
   Include in <head> on every screen, after the stylesheets:  <script src="fx/meta.js"></script>
   API (window.SWMeta):
     SWMeta.title('Praha 7')            -> "Praha 7 · Spotlight · Starwatch"; SWMeta.title() resets
     SWMeta.empty(el,{title,body,action:{label,onClick}})  -> renders a calm empty state into el
     SWMeta.busy(el,true|false)         -> aria-busy + progress cursor while something loads
   Head tags are only added when the page does not already declare them. */
(function(){
"use strict";
if(window.SWMeta)return;
const d=document,head=d.head||d.documentElement;
const self=d.currentScript;
const root=new URL('../',self&&self.src||location.href).href;      // web root, wherever fx/ is served from
const abs=p=>new URL(p,root).href;

const NAME='Starwatch';
const SCREENS={atlas:'Star Atlas',spotlight:'Spotlight',pulse:'Pulse',radar:'Radar',data:'By the numbers',about:'About'};
const file=(location.pathname.split('/').pop()||'index.html').replace(/\.html?$/,'');
const key=(self&&self.dataset.screen)||d.documentElement.dataset.screen||file||'index';
const screen=SCREENS[key]||null;
const TAGLINE="Who's being heard. Not just who's talking.";
const DESC='A snapshot of public posts by candidates in the 2026 Czech municipal elections in ten cities, collected 8–9 October 2026 and linked to the people and lists behind them. Every number opens its public source.';
const BG=(getComputedStyle(d.documentElement).getPropertyValue('--space')||'').trim()||'#F2F7F7'; // browser bar blends into the canvas

/* ----- tab title ----- */
const baseTitle=screen?`${screen} · ${NAME}`:`${NAME} · Who's being heard`;
function title(sub){d.title=sub?`${sub} · ${baseTitle}`:baseTitle}
title();

/* ----- head tags ----- */
function meta(attr,k,v){if(head.querySelector(`meta[${attr}="${k}"]`))return;const m=d.createElement('meta');m.setAttribute(attr,k);m.content=v;head.appendChild(m)}
function link(rel,href,extra){if(head.querySelector(`link[rel="${rel}"]`))return;const l=d.createElement('link');l.rel=rel;l.href=href;if(extra)for(const k in extra)l.setAttribute(k,extra[k]);head.appendChild(l)}
meta('name','color-scheme','light');
meta('name','theme-color',BG);
meta('name','description',DESC);
meta('name','application-name',NAME);
meta('name','apple-mobile-web-app-title',NAME);
meta('name','mobile-web-app-capable','yes');
link('icon',abs('brand/favicon.svg'),{type:'image/svg+xml'});
link('apple-touch-icon',abs('brand/app-icon-180.png'),{sizes:'180x180'});
link('manifest',abs('manifest.webmanifest'));
const shareTitle=screen?`${screen} · ${NAME}`:`${NAME}: ${TAGLINE}`;
const img=abs('og.png'),alt='Starwatch: '+TAGLINE+' A snapshot of public posts in the 2026 Czech municipal elections.';
const url=location.origin+location.pathname;
[['og:type','website'],['og:site_name',NAME],['og:title',shareTitle],['og:description',DESC],['og:url',url],
 ['og:image',img],['og:image:type','image/png'],['og:image:width','1200'],['og:image:height','630'],['og:image:alt',alt]]
 .forEach(([k,v])=>meta('property',k,v));
[['twitter:card','summary_large_image'],['twitter:title',shareTitle],['twitter:description',DESC],['twitter:image',img],['twitter:image:alt',alt]]
 .forEach(([k,v])=>meta('name',k,v));

/* ----- component styles (self-contained, so screens without theme-c.css get them too) ----- */
const css=`.sw-net{position:fixed;left:0;right:0;margin-inline:auto;width:max-content;top:calc(var(--chrome-top,12px) + var(--chrome-h,46px) + 10px);z-index:400;display:flex;align-items:center;gap:10px;max-width:calc(100vw - 32px);min-height:36px;padding:7px 14px 7px 12px;border-radius:999px;background:var(--surface,#fff);color:var(--label,#0F172A);border:1px solid var(--hairline-strong,rgba(15,23,42,.18));box-shadow:0 1px 2px rgba(15,23,42,.06),0 10px 28px -12px rgba(15,23,42,.22);font:500 13px/1.35 var(--font,system-ui);opacity:0;transform:translateY(-6px);pointer-events:none;transition:opacity .25s cubic-bezier(.25,1,.5,1),transform .35s cubic-bezier(.25,1,.5,1)}
.sw-net.show{opacity:1;transform:none;pointer-events:auto}
.sw-net i{flex:none;width:8px;height:8px;border-radius:50%;background:var(--orange,#B45309)}
.sw-net.ok i{background:var(--green,#15803D)}
.sw-net span{color:var(--label2,#475569)}
.sw-net b{font-weight:600;color:var(--label,#0F172A)}
.sw-empty{display:grid;justify-items:center;align-content:center;gap:6px;min-height:160px;padding:28px 20px;text-align:center;color:var(--label2,#475569);animation:sw-empty-in .45s cubic-bezier(.25,1,.5,1) both}
.sw-empty .sw-mark{width:28px;height:28px;color:var(--label3,#64748B);opacity:.55;margin-bottom:6px}
.sw-empty b{font:650 15px/1.3 var(--font,system-ui);color:var(--label,#0F172A)}
.sw-empty p{max-width:36ch;font-size:13.5px;line-height:1.5;text-wrap:pretty}
.sw-empty button{margin-top:10px}
@keyframes sw-empty-in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@media (max-width:860px){.sw-net{top:calc(env(safe-area-inset-top,0px) + 70px)}}
@media (prefers-reduced-motion:reduce){.sw-net,.sw-empty{transition:none;animation:none}}`;
if(!d.getElementById('sw-meta-css')){const s=d.createElement('style');s.id='sw-meta-css';s.textContent=css;head.appendChild(s)}

const STAR='<svg class="sw-mark" viewBox="-32 -32 64 64" aria-hidden="true"><path fill="currentColor" d="M-30,0L-10.06,8.55L-6.77,-1.31L-5.21,-0.79L-0.91,-5.09L-10.59,-8.32ZM0,30L8.55,10.06L-1.31,6.77L-0.79,5.21L-5.09,0.91L-8.32,10.59ZM30,0L10.06,-8.55L6.77,1.31L5.21,0.79L0.91,5.09L10.59,8.32ZM0,-30L-8.55,-10.06L1.31,-6.77L0.79,-5.21L5.09,-0.91L8.32,-10.59Z"/></svg>';
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* ----- empty state: says what is missing and why, never shows "0" for "not observed" ----- */
function empty(el,o){
  if(!el)return null;o=o||{};
  const off=!navigator.onLine;
  const t=o.title||(off?'Offline':'Nothing observed here yet');
  const b=o.body!=null?o.body:(off?'This view needs data that has not loaded. It will fill in once you are back online.':'No verified public posts match this view. Not observed is not the same as zero.');
  const box=d.createElement('div');box.className='sw-empty';box.setAttribute('role','status');
  box.innerHTML=`${STAR}<b>${esc(t)}</b>${b?`<p>${esc(b)}</p>`:''}`;
  if(o.action&&o.action.label){const btn=d.createElement('button');btn.type='button';btn.className='pill';btn.textContent=o.action.label;btn.addEventListener('click',o.action.onClick||(()=>{}));box.appendChild(btn)}
  el.replaceChildren(box);return box;
}
function busy(el,on){el=el||d.body;if(!el)return;on===false?el.removeAttribute('aria-busy'):el.setAttribute('aria-busy','true')}

/* ----- polite connection notice ----- */
let net,hideT;
function notice(online){
  if(!d.body)return;
  if(!net){net=d.createElement('div');net.className='sw-net';net.setAttribute('role','status');net.setAttribute('aria-live','polite');d.body.appendChild(net)}
  clearTimeout(hideT);
  net.classList.toggle('ok',online);
  net.innerHTML=online?'<i></i><span><b>Back online</b></span>':'<i></i><span><b>You are offline</b> · showing what already loaded</span>';
  requestAnimationFrame(()=>net.classList.add('show'));
  if(online)hideT=setTimeout(()=>net.classList.remove('show'),2400);
}
addEventListener('offline',()=>notice(false));
addEventListener('online',()=>{if(net&&net.classList.contains('show'))notice(true)});
if(!navigator.onLine)(d.readyState==='loading'?d.addEventListener('DOMContentLoaded',()=>notice(false),{once:true}):notice(false));

window.SWMeta={screen:key,name:screen||NAME,title,empty,busy,notice};
})();
