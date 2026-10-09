/* Starwatch shared MOCK universe + helpers (classic script; exposes window.SW).
   All names, lists, posts and metrics are generated mock data. Candidate and list counts per city follow the KV2026 registry (7 Oct 2026). */
(function(){
"use strict";
// Party palette: ten hues at matched lightness, so colour encodes WHO posted.
// Brand yellow (#FFD60A) is reserved for UI focus/selection and never used as a party colour.
const PARTY=[[0.733,0.342,0.321],[0,0.56,0.622],[0.3,0.551,0.244],[0.551,0.393,0.719],[0.704,0.384,0.119],[0.046,0.512,0.748],[0,0.573,0.462],[0.659,0.352,0.598],[0.395,0.446,0.778],[0.714,0.335,0.467]]; // OKLCH L=.58 C=.13 for light surfaces, hues spread
let SEED=20261009;
function rng(){SEED|=0;SEED=SEED+0x6D2B79F5|0;let t=Math.imul(SEED^SEED>>>15,1|SEED);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}
const rr=(a,b)=>a+(b-a)*rng(), ri=(a,b)=>Math.floor(rr(a,b+1)), pick=a=>a[Math.floor(rng()*a.length)];
function gauss(){let u=0;while(!u)u=rng();return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*rng())}
const TODAY=new Date('2026-10-09T03:30:00+02:00');
const COS=Math.cos(49.8*Math.PI/180), K=100;
const proj=(lon,lat)=>[(lon-15.5)*COS*K,(lat-49.8)*K];

const CITY=[
 ['Praha',14.423,50.087,1059,24,65],['Brno',16.610,49.200,828,16,55],['Ostrava',18.250,49.830,715,13,55],
 ['Plzeň',13.378,49.747,549,13,47],['Olomouc',17.251,49.594,472,12,45],['České Budějovice',14.474,48.975,405,10,45],
 ['Hradec Králové',15.833,50.209,369,10,37],['Liberec',15.056,50.767,361,11,39],['Pardubice',15.779,50.034,351,9,39],['Ústí nad Labem',14.041,50.661,296,9,37]];
const OUTLINE=[[15.017,51.107],[15.491,50.785],[16.239,50.698],[16.176,50.423],[16.719,50.216],[16.869,50.474],[17.555,50.362],[17.649,50.049],[18.393,49.989],[18.853,49.496],[18.555,49.495],[18.4,49.315],[18.17,49.272],[18.105,49.044],[17.914,48.996],[17.886,48.903],[17.545,48.8],[17.102,48.817],[16.96,48.597],[16.499,48.786],[16.03,48.734],[15.253,49.039],[14.901,48.964],[14.339,48.555],[13.596,48.877],[13.031,49.307],[12.521,49.547],[12.415,49.969],[12.24,50.266],[12.967,50.484],[13.338,50.733],[14.056,50.927],[14.307,51.117],[14.571,51.002],[15.017,51.107]].map(p=>proj(p[0],p[1]));

const PLAT=[
 {k:'instagram',n:'Instagram',c:[.80,.72,1.0],w:.33,ar:1},
 {k:'facebook',n:'Facebook',c:[.58,.74,1.0],w:.27,ar:1.25},
 {k:'tiktok',n:'TikTok',c:[.50,1.0,.92],w:.14,ar:.5625,video:1},
 {k:'youtube',n:'YouTube',c:[1.0,.55,.52],w:.05,ar:1.78,video:1},
 {k:'x',n:'X',c:[.86,.86,.86],w:.06,ar:1.78},
 {k:'news',n:'News',c:[1.0,.86,.62],w:.11,ar:1.78,about:1},
 {k:'web',n:'Web',c:[.68,.84,.70],w:.04,ar:1.78}];
const TOP=[['Housing','bydlení'],['Transport','doprava'],['Climate','klima'],['Safety','bezpečnost'],['Schools','školy'],['Health','zdravotnictví'],['Budget','rozpočet'],['Culture','kultura'],['Transparency','transparentnost'],['Social care','sociální služby']];
const FM=['Jan','Petr','Tomáš','Martin','Jakub','Lukáš','Ondřej','David','Pavel','Michal','Jiří','Filip','Vojtěch','Adam','Marek','Radek','Karel','Roman','Vít','Matěj','Šimon','Aleš'];
const FF=['Jana','Petra','Lucie','Kateřina','Tereza','Eva','Markéta','Veronika','Hana','Barbora','Klára','Zuzana','Alena','Michaela','Anna','Lenka','Monika','Simona','Adéla','Iva'];
const SN=[['Novák','Nováková'],['Svoboda','Svobodová'],['Dvořák','Dvořáková'],['Černý','Černá'],['Procházka','Procházková'],['Kučera','Kučerová'],['Veselý','Veselá'],['Horák','Horáková'],['Němec','Němcová'],['Pospíšil','Pospíšilová'],['Hájek','Hájková'],['Král','Králová'],['Jelínek','Jelínková'],['Růžička','Růžičková'],['Beneš','Benešová'],['Sedláček','Sedláčková'],['Doležal','Doležalová'],['Kolář','Kolářová'],['Navrátil','Navrátilová'],['Čermák','Čermáková'],['Urban','Urbanová'],['Vaněk','Vaňková'],['Blažek','Blažková'],['Kříž','Křížová'],['Kovář','Kovářová'],['Malý','Malá'],['Šťastný','Šťastná'],['Holub','Holubová'],['Vlček','Vlčková'],['Pokorný','Pokorná']];
const LN=['Občanská koalice 26','Hnutí Sever','Nezávislá volba','Město pro všechny','Liga obyvatel','Svobodní sousedé','Zelená alternativa','Rozumná volba','Hnutí Most','Aliance středu','Lidé odsud','Spolu za město','Otevřená radnice','Nová generace','Hnutí Kompas','Koalice Jasně','Sousedé 2026','Klidné město','Pravý blok','Levá fronta města','Moderní radnice','Volba rozumu','Městská iniciativa','Pro sousedy','Rozvoj a řád','Hlas čtvrtí'];
const OUT=['Mock Deník','Městský zpravodaj','Rádio Mock','Zprávy z radnice','Krajský Mock','Týdeník Mock'];
const CAP=['%T je pro nás priorita. Co navrhujeme pro %C? 👇','Včera jsme mluvili s lidmi o tématu %t. Díky za všechny podněty!','Video: tři kroky, jak zlepšit %t v našem městě.','Zastupitelstvo opět odložilo téma %t. Takhle to dál nejde.','Rozhovor o tématu %t — celý odkaz v komentáři.','Debata o %t dnes v 18:00, přijďte!','Čísla nelžou: %t v %C potřebuje změnu.','Dnešní ranní procházka a rozhovor o tématu %t.'];
const HEAD=['%N kritizuje plán na %t','Kandidát %N představil vizi: %t','%C: spor o %t pokračuje, ozval se i %N','%N: „%T musí být priorita“','Debata kandidátů: %t a rozpočet','Radnice čelí otázkám kvůli %t'];

function pickPlat(){let x=rng(),s=0;for(let i=0;i<PLAT.length;i++){s+=PLAT[i].w;if(x<s)return i}return 0}
const cities=[],lists=[],cands=[],assets=[];
CITY.forEach((c,ci)=>{
  const [x,y]=proj(c[1],c[2]);
  const R=3.4+6.2*Math.sqrt(c[3]/1059);
  const city={i:ci,name:c[0],x,y,R,n:c[3],L:c[4],seats:c[5],lists:[],cands:[],assets:[]};
  cities.push(city);
  // list sizes summing exactly to the registry total
  const w=[];for(let i=0;i<c[4];i++)w.push(.3+rng()*(i<5?1.4:1));
  const sw=w.reduce((a,b)=>a+b,0);
  const sz=w.map(v=>Math.max(5,Math.min(c[5],Math.round(c[3]*v/sw))));
  let tot=sz.reduce((a,b)=>a+b,0);
  while(tot<c[3]){const k=ri(0,c[4]-1);if(sz[k]<c[5]){sz[k]++;tot++}}
  while(tot>c[3]){const k=ri(0,c[4]-1);if(sz[k]>5){sz[k]--;tot--}}
  sz.sort((a,b)=>b-a);
  const names=[...LN].sort(()=>rng()-.5);
  const own=['Pro '+c[0],'Naše '+c[0],'Lepší '+c[0]];
  const arm=rr(0,6.28);
  for(let li=0;li<c[4];li++){
    const nm=li<3&&rng()<.7?own[li]:names[li];
    const t=(li+.35)/c[4];
    const ang=arm+li*2.39996+Math.sqrt(t)*2.4;
    const rad=R*(.06+.86*Math.sqrt(t));
    const S=R*.085*Math.sqrt(sz[li]/40)+R*.03;
    const hue=PARTY[li%PARTY.length];
    const L={i:lists.length,city:ci,name:nm,short:nm.split(' ').map(s=>s[0]).join('').toUpperCase().slice(0,4),size:sz[li],x:x+Math.cos(ang)*rad,y:y+Math.sin(ang)*rad,S,col:hue,cands:[],assets:[],popular:rr(.3,1.6)};
    lists.push(L);city.lists.push(L.i);
    for(let k=1;k<=sz[li];k++){
      const fem=rng()<.38, sn=pick(SN);
      const lead=Math.exp(-(k-1)/5);
      const fol=Math.round(Math.exp(4.4+2.6*lead*L.popular+gauss()*1.0)+20);
      const rad2=S*(.16+.84*Math.sqrt((k-.5)/sz[li]));
      const cnd={i:cands.length,name:(fem?pick(FF):pick(FM))+' '+(fem?sn[1]:sn[0]),list:L.i,city:ci,k,fol,
        or:rad2,ph:k*2.39996+rr(-.2,.2),sp:(rng()<.5?-1:1)*0.035/(0.4+rad2),assets:[],about:[],age:ri(24,71)};
      cnd.size=.022+.075*Math.min(1,Math.log10(fol)/4.3)+.06*lead;
      cands.push(cnd);L.cands.push(cnd.i);city.cands.push(cnd.i);
    }
  }
});
// assets
function mkAsset(o){
  const pi=o.plat!=null?o.plat:pickPlat(), P=PLAT[pi];
  const nt=rng()<.12?0:ri(1,rng()<.3?3:2), tp=[];
  while(tp.length<nt){const t=ri(0,TOP.length-1);if(!tp.includes(t))tp.push(t)}
  const age=Math.min(44,Math.pow(rng(),1.5)*45);
  const base=o.fol;
  const video=!!P.video||(pi===0&&rng()<.35);
  const views=video?Math.round(base*Math.exp(gauss()*1.0+.6)*rr(1,4)):0;
  const likes=Math.round((video?views*rr(.02,.09):base*Math.exp(gauss()*.9-2.3))+rr(0,6));
  const a={i:assets.length,owner:o.owner,list:o.list,city:o.city,plat:pi,video,rel:P.about?'about':'created',about:-1,topics:tp,age,
    views,likes,comments:Math.round(likes*rr(.03,.16)),shares:Math.round(likes*rr(.01,.12)),
    ar:pi===0&&video?.5625:P.ar,outlet:P.about?pick(OUT):null,dur:video?ri(9,95):0};
  a.inter=a.likes+a.comments+a.shares;
  const T=tp.length?TOP[tp[0]]:TOP[ri(0,TOP.length-1)], cn=cities[o.city].name;
  a.cap=(P.about?pick(HEAD):pick(CAP)).replace('%T',T[0]==='Social care'?'Sociální služby':T[1][0].toUpperCase()+T[1].slice(1)).replace('%t',T[1]).replace('%C',cn).replace('%N',o.who||'');
  assets.push(a);cities[o.city].assets.push(a.i);
  return a;
}
cands.forEach(c=>{
  const n=c.k===1?ri(28,96):c.k<=3?ri(8,34):c.k<=10?ri(1,13):(rng()<.33?ri(1,4):0);
  const m=Math.round(n*Math.min(1.8,.5+Math.log10(c.fol)/4));
  for(let j=0;j<m;j++){
    let pi=pickPlat();
    const a=mkAsset({owner:c.i,list:c.list,city:c.city,fol:c.fol,plat:pi,who:c.name});
    if(a.rel==='about'){a.about=c.i;a.owner=c.i}
    else if(rng()<.1){const L=lists[pick(cities[c.city].lists)];a.mention=L.cands[Math.min(L.cands.length-1,Math.floor(Math.pow(rng(),3)*8))]}
    a.r=c.size*1.25+.018*Math.sqrt(j+1)+rr(0,.02);a.ph=j*2.39996;a.sp=(rng()<.5?-1:1)*rr(.25,.7)/(1+a.r*10);
    c.assets.push(a.i);
  }
});
lists.forEach(L=>{
  const n=Math.round(ri(18,70)*L.popular);
  for(let j=0;j<n;j++){
    const a=mkAsset({owner:-1,list:L.i,city:L.city,fol:Math.round(900*L.popular*rr(.5,3)),plat:[0,1,1,0,2,4,3][ri(0,6)],who:L.name});
    if(rng()<.3){a.mention=L.cands[Math.floor(Math.pow(rng(),2.5)*Math.min(8,L.cands.length))]}
    a.r=L.S*rr(1.06,1.22);a.ph=rr(0,6.283);a.sp=rr(.012,.03);L.assets.push(a.i);
  }
});
assets.forEach(a=>{if(a.mention!=null)cands[a.mention].about.push(a.i)});
const ownerName=a=>a.owner>=0?cands[a.owner].name:lists[a.list].name;


const fmt=v=>v>=1e6?(v/1e6).toFixed(v>=1e7?0:1)+'M':v>=1e4?Math.round(v/1e3)+'k':v>=1e3?(v/1e3).toFixed(1)+'k':String(Math.round(v));
const fmtN=v=>Math.round(v).toLocaleString('en-US');
const dstr=age=>{const d=new Date(TODAY-age*864e5);return d.getDate()+' '+['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()]};
const ago=age=>age<1/24?Math.round(age*1440)+'m ago':age<1?Math.round(age*24)+'h ago':Math.round(age)+'d ago';
const css=c=>`rgb(${c.map(v=>Math.round(v*255)).join(',')})`;
let uid=0;
function thumb(a,anim){
  const id='t'+(uid++), P=PLAT[a.plat], W0=a.ar>=1?160:90, H0=Math.round(W0/a.ar);
  const h=(a.i*137)%360, T=a.topics.length?TOP[a.topics[0]][0]:'Update';
  const cA=`hsl(${a.plat===5?38:h},${a.plat===5?30:45}%,${14+a.i%9}%)`, cB=`hsl(${(h+60)%360},40%,6%)`;
  let s=`<svg viewBox="0 0 ${W0} ${H0}" preserveAspectRatio="xMidYMid slice" class="${a.video&&anim?'vid':''}"><defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${cA}"/><stop offset="1" stop-color="${cB}"/></linearGradient></defs>`;
  if(a.real&&!a.img){ // real post without a retained preview: first video frame, or an honest neutral tile
    if(a.vsrc)return `<video class="sw-vthumb" src="${a.vsrc}#t=0.5" preload="metadata" muted playsinline aria-hidden="true"></video>`;
    return `<svg viewBox="0 0 ${W0} ${H0}" preserveAspectRatio="xMidYMid slice"><rect width="${W0}" height="${H0}" fill="#E9EDF2"/><text x="${W0/2}" y="${H0/2-2}" text-anchor="middle" font-family="Inter" font-size="${Math.min(W0,H0)*.09}" fill="#64748B">${P.n}</text><text x="${W0/2}" y="${H0/2+12}" text-anchor="middle" font-family="Inter" font-size="${Math.min(W0,H0)*.075}" fill="#94A3B8">no preview retained</text></svg>`}
  if(a.img){s=s.replace('class="vid"','class=""');s+=`<rect width="${W0}" height="${H0}" fill="#0b0b0d"/><g class="kb"><image href="${a.img}" x="0" y="0" width="${W0}" height="${H0}" preserveAspectRatio="xMidYMid slice"/></g><rect width="${W0}" height="${H0}" fill="url(#${id})" opacity=".0"/>`;
    s+=`<rect x="5" y="5" width="${P.n.length*5.2+10}" height="12" rx="6" fill="#000" opacity=".6"/><text x="10" y="14" font-family="JetBrains Mono" font-size="7.5" fill="${css(P.c)}">${P.n.toUpperCase()}</text>`;
    if(a.video){const r=Math.min(W0,H0)*.11;s+=`<g class="pulse"><circle cx="${W0/2}" cy="${H0/2}" r="${r}" fill="#000" opacity=".5"/><path d="M${W0/2-r*.3} ${H0/2-r*.45} l${r*.8} ${r*.45} l-${r*.8} ${r*.45}z" fill="#FFFFFF"/></g>`}
    return s+'</svg>'}
  s+=`<rect width="${W0}" height="${H0}" fill="url(#${id})"/>`;
  s+=`<g class="kb">`;for(let j=0;j<3;j++){const r=8+((a.i*(j+3))%26);s+=`<circle cx="${(a.i*(j+7)*13)%W0}" cy="${(a.i*(j+5)*7)%H0}" r="${r}" fill="${j?'#ffd23f':css(P.c)}" opacity="${.08+j*.05}"/>`}
  s+=`<circle cx="${W0*.5}" cy="${H0*.42}" r="${Math.min(W0,H0)*.18}" fill="#000" opacity=".35"/><circle cx="${W0*.5}" cy="${H0*.36}" r="${Math.min(W0,H0)*.08}" fill="#fff" opacity=".18"/><path d="M${W0*.5-Math.min(W0,H0)*.15} ${H0*.6} q${Math.min(W0,H0)*.15} -${Math.min(W0,H0)*.16} ${Math.min(W0,H0)*.3} 0" fill="#fff" opacity=".14"/></g>`;
  if(a.plat===5){s+=`<rect x="0" y="0" width="${W0}" height="${H0*.18}" fill="#000" opacity=".6"/><text x="8" y="${H0*.13}" font-family="Inter" font-size="${H0*.09}" fill="#FFFFFF" font-weight="700">${a.outlet.toUpperCase()}</text>`;
    s+=`<rect x="8" y="${H0*.66}" width="${W0*.8}" height="5" fill="#fff" opacity=".5"/><rect x="8" y="${H0*.66+9}" width="${W0*.6}" height="5" fill="#fff" opacity=".3"/>`}
  s+=`<text x="${W0/2}" y="${H0*.86}" text-anchor="middle" font-family="Inter" font-weight="700" font-size="${Math.min(W0,H0)*.11}" fill="#fff" opacity=".85" letter-spacing="1">${T.toUpperCase()}</text>`;
  s+=`<rect x="5" y="5" width="${P.n.length*5.2+10}" height="12" fill="#000" opacity=".65"/><text x="10" y="14" font-family="JetBrains Mono" font-size="7.5" fill="${css(P.c)}">${P.n.toUpperCase()}</text>`;
  if(a.video){const r=Math.min(W0,H0)*.11;s+=`<g class="pulse"><circle cx="${W0/2}" cy="${H0/2}" r="${r}" fill="#000" opacity=".55" stroke="#ffd23f" stroke-width="1"/><path d="M${W0/2-r*.3} ${H0/2-r*.45} l${r*.8} ${r*.45} l-${r*.8} ${r*.45}z" fill="#FFFFFF"/></g>`;
    s+=`<rect class="scan" x="0" y="0" width="${W0}" height="${H0*.08}" fill="#FFFFFF" opacity=".07"/>`;
    s+=`<rect x="0" y="${H0-3}" width="${W0}" height="3" fill="#000" opacity=".6"/><rect class="prog" x="0" y="${H0-3}" width="${W0}" height="3" fill="#FFFFFF" style="transform-origin:0 0"/>`;
    s+=`<text x="${W0-6}" y="${H0-8}" text-anchor="end" font-family="JetBrains Mono" font-size="7.5" fill="#fff">0:${String(a.dur%60).padStart(2,'0')}</text>`}
  return s+'</svg>';
}
function spark(vals,w,h,col){const mx=Math.max(1,...vals);let d='';vals.forEach((v,i)=>{d+=(i?'L':'M')+(i/(vals.length-1)*w).toFixed(1)+' '+(h-2-(v/mx)*(h-4)).toFixed(1)});
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><path d="${d} L${w} ${h} L0 ${h}Z" fill="${col}" opacity=".12"/><path d="${d}" fill="none" stroke="${col}" stroke-width="1.4"/></svg>`}
function daily(ids,key,days=30){const v=new Array(days).fill(0);ids.forEach(i=>{const a=assets[i];const d=Math.floor(a.age);if(d<days)v[days-1-d]+=a[key]});return v}
function candStats(c){const ids=c.assets.filter(i=>assets[i].rel==='created'&&assets[i].age<=30);const s={n:ids.length,views:0,likes:0,comments:0,shares:0,inter:0};ids.forEach(i=>{const a=assets[i];s.views+=a.views;s.likes+=a.likes;s.comments+=a.comments;s.shares+=a.shares;s.inter+=a.inter});s.ids=ids;return s}
const handle=c=>c.name.normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase().replace(' ','_');
function avatar(c,sz=64){const ini=c.name.split(' ').map(s=>s[0]).join('');const L=lists[c.list];
  return `<svg class="avatar" viewBox="-32 -32 64 64" width="${sz}" height="${sz}"><defs><radialGradient id="av${c.i}"><stop offset="0" stop-color="${css(L.col)}" stop-opacity=".5"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient></defs><circle r="30" fill="url(#av${c.i})"/><polygon points="0,-24 21,-12 21,12 0,24 -21,12 -21,-12" fill="#0b0a08" stroke="#ffd23f" stroke-width="1"/><text y="6" text-anchor="middle" font-family="Inter" font-weight="700" font-size="17" fill="#fff4c2">${ini}</text><g><animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="14s" repeatCount="indefinite"/><circle r="29" fill="none" stroke="#ffd23f" stroke-opacity=".35" stroke-dasharray="2 5"/><circle cx="29" r="2" fill="#8fdcff"/></g></svg>`}


window.SW={source:{kind:'sim',label:'Simulated universe'},cities,lists,cands,assets,PLAT,TOP,PARTY,OUTLINE,CITY,proj,COS,K,TODAY,rng,rr,ri,pick,gauss,ownerName,fmt,fmtN,dstr,ago,css,thumb,spark,daily,candStats,handle,avatar};
})();
