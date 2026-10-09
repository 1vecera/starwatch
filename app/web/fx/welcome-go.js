/* Welcome slide → Star Atlas: warm the map's files while the slide is up, then leave softly.
   The slide fades into the Atlas canvas colour; Atlas's own cross-document view transition fades the map in. */
(()=>{
  const TARGET='atlas.html';
  for(const href of [TARGET,'data/real.js','geo/cz.js','geo/cz-border.js']){const l=document.createElement('link');l.rel='prefetch';l.href=href;document.head.appendChild(l)}
  const st=document.createElement('style');
  st.textContent='@view-transition{navigation:auto}.sw-leave{position:fixed;inset:0;z-index:2147483647;background:#F2F7F7;opacity:0;pointer-events:none;transition:opacity .7s cubic-bezier(.25,1,.5,1)}.sw-leave.on{opacity:1}';
  document.head.appendChild(st);
  let leaving=false;
  window.swGo=()=>{
    if(leaving)return;leaving=true;
    const v=document.createElement('div');v.className='sw-leave';document.body.appendChild(v);
    const stage=document.querySelector('.stage,#stage,main');
    if(stage&&stage.animate)stage.animate([{opacity:1},{opacity:.4}],{duration:700,easing:'cubic-bezier(.25,1,.5,1)',fill:'forwards'});
    requestAnimationFrame(()=>requestAnimationFrame(()=>v.classList.add('on')));
    setTimeout(()=>{location.href=TARGET},720);
  };
})();
