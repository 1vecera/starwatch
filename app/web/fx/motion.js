/* Starwatch motion kit (classic script; exposes window.SWMotion). Pair with fx/motion.css.
   Include in <head> after the stylesheets, so its MutationObserver sees every render before the first paint:
     <link rel="stylesheet" href="fx/motion.css"><script src="fx/motion.js"></script>
   It still works when included last, but then numbers already painted on load keep their final value.
   What it does, all with the Web Animations API (transform/opacity only, ease cubic-bezier(.25,1,.5,1)):
   - Reveal: once the page is scrolled, panels/cards/rows that are still outside the viewport are hidden and fade
     up 10px with a 35ms stagger as they enter, once. Load-time entrances stay with each screen's own .rise.
     Elements with their own CSS animation, skeletons, fixed/sticky overlays and the chrome are never touched.
   - Count-up: .num and [data-count] (single text node such as 1.2k, 12,345, 45 %, +3.1) count from 0 when they
     are first drawn on load or revealed by scroll. Width is locked while counting. [data-cu] (Pulse) is skipped.
   - Images: an <img> still loading fades in after decode. Images using the screen's own .ld class are skipped.
   - Hover/press: buttons, links and [role=button] lift 1px (2px when 48px+ tall) for mouse hover and settle to
     .97/.985 on press. Wide rows, segmented controls, tabs and anything whose CSS already moves on :hover/:active
     are left alone. Uses the independent translate/scale properties, so it never overrides a screen's transform.
   Opt-outs: data-motion="off" on any subtree, data-lift="off", data-count="off". Opt-ins: data-reveal,
   data-reveal-group (its children reveal as a list), data-count, data-lift. prefers-reduced-motion disables all. */
(function(){
"use strict";
if(window.SWMotion)return;
const EASE='cubic-bezier(.25,1,.5,1)';
const RM=window.matchMedia?matchMedia('(prefers-reduced-motion: reduce)'):{matches:false};
let reduced=RM.matches;
const OFF='[data-motion="off"],.sw-chrome,.sw-scrim,.sw-toast,.maplibregl-map';
const REVEAL='[data-reveal],[data-reveal-group]>*,section,article,.panel,.card,.tile,.rowc,.lrow,.rrow,.crow,.tr,.tsr,.al,.ent,.col,.rk,.ld3,.wl-row,.mrow,.isl';
const NUM='.num,[data-count]';
const LIFT='button,a[href],[role="button"],[data-lift]';
const NOLIFT='[data-lift="off"],[role="tab"],[role="option"],[disabled],[aria-disabled="true"],.seg *,.sk';
const T0=performance.now();
const WINDOW=3500;               // ms after navigation in which freshly drawn numbers count up
const anim=(el,k,o)=>{try{return el.animate(k,o)}catch(e){return null}};
const off=el=>!!(el.closest&&el.closest(OFF));

/* ---------------- reveal on scroll ---------------- */
const st=new WeakMap();          // el -> 'obs' | 'pre' | 'done'
let armed=false;
const io=('IntersectionObserver' in window)?new IntersectionObserver(onIO,{threshold:0}):null;
function consider(el){if(!io||st.has(el))return;st.set(el,'obs');io.observe(el)}
function inOverlay(el){for(let p=el;p&&p!==document.body&&p!==document.documentElement;p=p.offsetParent){const pos=getComputedStyle(p).position;if(pos==='fixed'||pos==='sticky')return true}return false}
function eligible(el){
  if(off(el)||el.classList.contains('sk')||el.closest('.sk'))return false;
  if(el.querySelector(REVEAL))return false;                 // innermost unit wins: the frame stays, its rows reveal
  if(el.parentElement&&el.parentElement.closest('[data-mx-pre]'))return false;
  const r=el.getClientRects();if(!r.length||r[0].height<16)return false;
  const cs=getComputedStyle(el);
  if(cs.animationName&&cs.animationName!=='none')return false;   // the screen animates it already
  if(cs.visibility==='hidden')return false;
  return !inOverlay(el);
}
function onIO(entries){
  const show=[];
  for(const e of entries){const el=e.target,s=st.get(el);
    if(s==='obs'){
      if(e.isIntersecting||reduced||!eligible(el)){st.set(el,'done');io.unobserve(el);el.removeAttribute('data-mx-pre');continue}
      el.setAttribute('data-mx-pre','');st.set(el,'pre');
    }else if(s==='pre'&&e.isIntersecting)show.push(el);
  }
  if(show.length)reveal(show);
}
function reveal(els){
  const rs=new Map(els.map(el=>[el,el.getBoundingClientRect()]));
  els.sort((a,b)=>(rs.get(a).top-rs.get(b).top)||(rs.get(a).left-rs.get(b).left));
  const live=els.filter(el=>{io.unobserve(el);st.set(el,'done');const had=el.hasAttribute('data-mx-pre');el.removeAttribute('data-mx-pre');return had});
  const plan=live.map(el=>{const cs=getComputedStyle(el);return [el,+cs.opacity,!cs.translate||cs.translate==='none']});
  plan.forEach(([el,op,tr],i)=>{const delay=Math.min(i,8)*35;
    if(!reduced)anim(el,tr?[{opacity:0,translate:'0px 10px'},{opacity:op,translate:'0px 0px'}]:[{opacity:0},{opacity:op}],{duration:480,delay,easing:EASE,fill:'backwards'});
    (el.matches(NUM)?[el]:[]).concat([...el.querySelectorAll(NUM)]).forEach(n=>count(n,delay));
  });
}
function arm(){if(armed||reduced||!io)return;armed=true;document.querySelectorAll(REVEAL).forEach(consider)}
function revealAll(){document.querySelectorAll('[data-mx-pre]').forEach(el=>{el.removeAttribute('data-mx-pre');st.set(el,'done');io&&io.unobserve(el)})}
addEventListener('scroll',arm,{capture:true,passive:true});
addEventListener('beforeprint',revealAll);

/* ---------------- count-up ---------------- */
const counted=new WeakSet();
const RX=/^(\D*?)([-+−]?)(\d{1,3}(?:([,    ])\d{3})+|\d+)(?:([.,])(\d+))?(\D*)$/;
function parse(t){const m=RX.exec(t);if(!m)return null;
  const [,pre,sign,int,g,ds,dec,suf]=m;if(g&&ds===g)return null;
  const v=parseFloat(int.split(g||'\u0000').join('')+(dec?'.'+dec:''));
  if(!isFinite(v)||v===0)return null;
  if(/#\s*$/.test(pre))return null;                                   // ranks
  if(!g&&!dec&&v>=1900&&v<=2100&&!pre.trim()&&!suf.trim())return null; // years
  if(!dec&&v<10)return null;                                           // nothing worth counting
  return {pre,sign,g:g||'',ds:ds||'',dec:dec?dec.length:0,suf,v}}
function fmt(p,x){let s=p.dec?x.toFixed(p.dec):String(Math.round(x));let [i,d]=s.split('.');
  if(p.g&&i.length>3)i=i.replace(/\B(?=(\d{3})+(?!\d))/g,p.g);return p.pre+p.sign+i+(p.dec?p.ds+d:'')+p.suf}
function count(el,delay){
  if(reduced||counted.has(el))return;counted.add(el);
  if(off(el)||el.dataset.count==='off'||el.closest('[data-cu]'))return;
  const node=el.firstChild;if(!node||node.nodeType!==3||el.childNodes.length!==1)return;
  const full=node.nodeValue,lead=full.match(/^\s*/)[0],trail=full.match(/\s*$/)[0],p=parse(full.trim());if(!p)return;
  const w=el.getBoundingClientRect().width;if(!w)return;
  const disp=getComputedStyle(el).display,keep={d:el.style.display,w:el.style.width,ws:el.style.whiteSpace};
  if(disp==='inline')el.style.display='inline-block';
  el.style.width=w+'px';el.style.whiteSpace='nowrap';el.classList.add('mx-counting');
  let last=lead+fmt(p,0)+trail;node.nodeValue=last;
  const t0=performance.now()+(delay||0),D=p.v>=1000?1100:850;
  const done=put=>{if(put&&node.parentNode===el)node.nodeValue=full;el.style.display=keep.d;el.style.width=keep.w;el.style.whiteSpace=keep.ws;el.classList.remove('mx-counting')};
  const step=now=>{
    if(node.parentNode!==el||node.nodeValue!==last){done(false);return}   // the screen rewrote it: hand back
    const t=(now-t0)/D;if(t>=1){done(true);return}
    if(t>0){last=lead+fmt(p,p.v*(1-Math.pow(2,-10*t)))+trail;node.nodeValue=last}
    requestAnimationFrame(step)};
  requestAnimationFrame(step);
}
const vh=()=>innerHeight||document.documentElement.clientHeight;
function inView(r){return r.bottom>0&&r.top<vh()&&r.right>0&&r.left<(innerWidth||document.documentElement.clientWidth)&&r.width>0}

/* ---------------- image fade ---------------- */
function img(el){
  if(reduced||el.classList.contains('ld')||el.classList.contains('mx-img')||el.dataset.motion==='off'||off(el))return;
  if(el.naturalWidth||!el.getAttribute('src'))return;           // already (partly) drawn, or nothing to load
  el.classList.add('mx-img');
  const fin=ok=>{el.removeEventListener('load',L);el.removeEventListener('error',E);
    const go=()=>{if(!el.classList.contains('mx-img'))return;el.classList.remove('mx-img');
      if(ok&&!reduced)anim(el,[{opacity:0},{opacity:+getComputedStyle(el).opacity}],{duration:420,easing:EASE})};
    ok&&el.decode?el.decode().then(go,go):go()};
  const L=()=>fin(true),E=()=>fin(false);
  el.addEventListener('load',L);el.addEventListener('error',E);
  if(el.complete)fin(el.naturalWidth>0);
}

/* ---------------- scanning (MutationObserver runs before the next paint) ---------------- */
const all=(root,sel)=>{const out=root.matches&&root.matches(sel)?[root]:[];return root.querySelectorAll?out.concat([...root.querySelectorAll(sel)]):out};
function scan(roots,initial){
  if(reduced)return;
  const nums=[];
  for(const r of roots){
    all(r,'[data-mx-pre]').forEach(el=>{if(st.get(el)!=='pre')el.removeAttribute('data-mx-pre')});   // copied markup
    all(r,'img').forEach(img);
    if(armed)all(r,REVEAL).forEach(consider);
    if(performance.now()-T0<WINDOW)all(r,NUM).forEach(n=>nums.push(n));
  }
  if(!nums.length)return;
  const painted=initial&&performance.getEntriesByType&&performance.getEntriesByType('paint').length>0;
  const vis=nums.map(n=>[n,inView(n.getBoundingClientRect())]);
  vis.forEach(([n,v])=>{if(v&&!painted&&!n.closest('[data-mx-pre]'))count(n,0)});
}
const mo=new MutationObserver(recs=>{const added=[];for(const r of recs)for(const n of r.addedNodes)if(n.nodeType===1)added.push(n);if(added.length)scan(added,false)});
mo.observe(document.documentElement,{childList:true,subtree:true});
if(document.body)scan([document.body],true);

/* ---------------- hover lift / press ---------------- */
let own={hover:[],active:[]},nSheets=-1,gen=0;
function sheets(){
  if(document.styleSheets.length===nSheets)return;nSheets=document.styleSheets.length;gen++;own={hover:[],active:[]};
  const walk=rules=>{for(const r of rules){
    if(!r.selectorText){if(r.cssRules)try{walk(r.cssRules)}catch(e){}continue}
    const s=r.style;if(!s||!(s.transform||s.translate||s.scale||s.rotate))continue;
    r.selectorText.split(',').forEach(part=>{const m=/:(hover|active)\s*$/.exec(part);if(m)own[m[1]].push(part.trim().replace(/:(hover|active)\s*$/,'')||'*')})}};
  for(const sh of document.styleSheets){try{walk(sh.cssRules)}catch(e){}}
}
const cache=new WeakMap();
function kind(el){
  sheets();const c=cache.get(el);if(c&&c.g===gen)return c;
  const k={g:gen,lift:0,press:0};cache.set(el,k);
  if(off(el)||el.matches(NOLIFT)||el.closest('[data-lift="off"]'))return k;
  const cs=getComputedStyle(el);
  if(cs.display==='inline'||cs.position==='absolute'||cs.position==='fixed')return k;   // inline text links, map markers, overlays
  const r=el.getBoundingClientRect();if(!r.width||(r.width>240&&r.width/r.height>4))return k;   // wide list rows keep their hover fill only
  const big=r.height>=48,has=list=>list.some(s=>{try{return el.matches(s)}catch(e){return false}});
  k.lift=has(own.hover)?0:(big?2:1);k.press=has(own.active)?0:(big?.985:.97);
  return k;
}
const A=new WeakMap();
function tween(el,key,prop,to,dur){
  const m=A.get(el)||{};A.set(el,m);
  const from=getComputedStyle(el)[prop];
  m[key]&&m[key].cancel();
  const a=anim(el,{[prop]:[from&&from!=='none'?from:(prop==='scale'?'1':'0px 0px'),to]},{duration:dur,easing:EASE,fill:'forwards'});
  m[key]=a;return a;
}
function settle(el,key,prop,to,dur){const a=tween(el,key,prop,to,dur);if(!a)return;a.finished.then(()=>{const m=A.get(el);if(m&&m[key]===a){a.cancel();m[key]=null}},()=>{})}
let hov=new Set(),pressed=null;
function hoverTo(target){
  const next=new Set();
  if(!reduced)for(let n=target&&target.closest?target.closest(LIFT):null;n;n=n.parentElement?n.parentElement.closest(LIFT):null){if(kind(n).lift)next.add(n)}
  hov.forEach(n=>{if(!next.has(n))settle(n,'l','translate','0px 0px',260)});
  next.forEach(n=>{if(!hov.has(n))tween(n,'l','translate',`0px -${kind(n).lift}px`,220)});
  hov=next;
}
document.addEventListener('pointerover',e=>{if(e.pointerType!=='touch')hoverTo(e.target)},{passive:true});
document.addEventListener('pointerout',e=>{if(!e.relatedTarget)hoverTo(null)},{passive:true});
document.addEventListener('pointerdown',e=>{
  if(reduced||e.button>0||!e.target.closest)return;const n=e.target.closest(LIFT);if(!n)return;const k=kind(n);if(!k.press)return;
  pressed=n;tween(n,'p','scale',String(k.press),110)},{passive:true});
const release=()=>{if(!pressed)return;const n=pressed;pressed=null;settle(n,'p','scale','1',300)};
addEventListener('pointerup',release,{capture:true,passive:true});
addEventListener('pointercancel',release,{capture:true,passive:true});
addEventListener('dragstart',release,{capture:true,passive:true});

/* ---------------- reduced motion ---------------- */
const onRM=e=>{reduced=e.matches;if(reduced){revealAll();hoverTo(null)}};
RM.addEventListener?RM.addEventListener('change',onRM):RM.addListener&&RM.addListener(onRM);

window.SWMotion={version:1,count:el=>count(el,0),scan:root=>scan([root||document.body],false),arm,revealAll,get reduced(){return reduced}};
})();
