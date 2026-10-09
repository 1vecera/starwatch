/* Cross-screen navigation hooks, defined before any screen script runs. */
(function(){
"use strict";
const T={cand:'cand',person:'cand',entity:'cand',list:'list',party:'list',asset:'asset'};
window.openSpotlight=function(ref){
  const t=T[ref&&ref.type]||'cand', id=ref&&ref.id!=null?ref.id:0;
  try{localStorage.setItem('sw-sel',JSON.stringify({mode:(window.SW&&SW.source&&SW.source.kind)||'sim',type:t,i:+id}))}catch(e){}
  location.href=`spotlight.html?${t}=${id}`;
};
})();
// cross-document view transitions can be skipped by a fast navigation; that is not an error
['pagereveal','pageswap'].forEach(ev=>addEventListener(ev,e=>{const t=e.viewTransition;if(t){t.ready&&t.ready.catch(()=>{});t.finished&&t.finished.catch(()=>{});t.updateCallbackDone&&t.updateCallbackDone.catch(()=>{})}}));
addEventListener('unhandledrejection',e=>{if(/Transition was skipped/.test(String(e.reason&&e.reason.message||e.reason)))e.preventDefault()});
