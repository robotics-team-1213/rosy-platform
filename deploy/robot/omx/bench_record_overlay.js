// Live top-camera SVG Pick -> Place goal overlay with toggle, crisp badges, and letterbox-exact image alignment.
(function(){
const OVERLAY_KEY='omx_bench_cam_overlay';
const FB_SPOTS={
  belt:[[271,19],[356,20],[356,162],[270,161]],
  stand:[[382,52],[534,52],[534,148],[382,148]],
  pallet:[[257,151],[388,153],[389,403],[255,403]],
  'tmp-a':[[405,351],[611,347],[624,470],[402,475]],
  'tmp-b':[[8,344],[229,339],[231,478],[10,482]]
};
let resizeObs=null, boundImg=null;
function isOverlayOn(){
  try{return localStorage.getItem(OVERLAY_KEY)!=='0';}catch(_){return true;}
}
function setOverlayOn(on){
  try{localStorage.setItem(OVERLAY_KEY,on?'1':'0');}catch(_){}
  renderCamGoalOverlay();
}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function lerpPoly(q,u0,u1,v0,v1){
  const [tl,tr,br,bl]=q;
  const pt=(u,v)=>[Math.round(tl[0]+(tr[0]-tl[0])*u+((bl[0]+(br[0]-bl[0])*u)-(tl[0]+(tr[0]-tl[0])*u))*v),
    Math.round(tl[1]+(tr[1]-tl[1])*u+((bl[1]+(br[1]-bl[1])*u)-(tl[1]+(tr[1]-tl[1])*u))*v)];
  return [pt(u0,v0),pt(u1,v0),pt(u1,v1),pt(u0,v1)];
}

function resolveSpotPoly(code){
  const s=String(code||'').trim();
  if(!s)return null;
  const sp=(window.cellMapData&&window.cellMapData.camera_overlay&&window.cellMapData.camera_overlay.spots)||{};
  if(sp[s])return sp[s];
  if(s.startsWith('stand:')||s==='stand')return sp.stand||FB_SPOTS.stand;
  let m=s.match(/^(ship-h(\d)r(\d))(?:-l\d+)?$/);
  if(m){
    if(sp[m[1]])return sp[m[1]];
    const uMap={2:[0.06,0.35],1:[0.36,0.64],0:[0.65,0.94]}[Number(m[3])];
    const vMap={1:[0.185,0.515],2:[0.53,0.86]}[Number(m[2])];
    if(uMap&&vMap)return lerpPoly(sp.pallet||FB_SPOTS.pallet,uMap[0],uMap[1],vMap[0],vMap[1]);
  }
  m=s.match(/^(ship-h(\d))$/);
  if(m&&sp[m[1]])return sp[m[1]];
  m=s.match(/^(tmp-([ab])-(\d+))(?:-l\d+)?$/);
  if(m){
    if(sp[m[1]])return sp[m[1]];
    const idx=Math.max(1,Math.min(3,Number(m[3])))-1;
    const base=sp['tmp-'+m[2]]||FB_SPOTS['tmp-'+m[2]];
    const rng=m[2]==='a'?[[0.04,0.34],[0.35,0.65],[0.66,0.96]]:[[0.66,0.96],[0.35,0.65],[0.04,0.34]];
    return lerpPoly(base,rng[idx][0],rng[idx][1],0.08,0.94);
  }
  if(s.startsWith('belt'))return sp.belt||FB_SPOTS.belt;
  return sp[s]||null;
}

function activeGoalEndpoints(){
  const cards=(typeof choices!=='undefined'&&choices&&choices.task_cards)||{};
  const arm=(typeof f!=='undefined'&&f&&f.arm)?f.arm.value:'';
  if(window.goalMode==='custom'){
    const o=String(window.customGoal?.origin||'').trim(), t=String(window.customGoal?.target_slot||'').trim();
    return {arm,origin:o,target:t};
  }
  const tKey=(typeof f!=='undefined'&&f&&f.task)?f.task.value:'';
  const c=tKey?cards[tKey]:null;
  if(!c||c.valid===false)return {arm,origin:'',target:''};
  const {rawO,rawT}=(typeof inferCardSpots==='function')?inferCardSpots(tKey,c):{rawO:c.origin||'',rawT:c.target_slot||''};
  const sw=Boolean(window.zoneSwapped&&(rawO||rawT));
  const o=sw?rawT:rawO;
  let t=sw?rawO:rawT;
  if(!sw&&c.target_layer&&t&&!t.includes('-l'))t=t+'-'+c.target_layer;
  return {arm,origin:o,target:t};
}

function centroid(poly){
  const n=poly.length||1;
  return [poly.reduce((a,p)=>a+p[0],0)/n,poly.reduce((a,p)=>a+p[1],0)/n];
}
function ptsStr(poly){return poly.map(p=>p[0]+','+p[1]).join(' ');}

function fitOverlayToImage(box,img,svg){
  if(!box||!svg)return;
  const bw=box.clientWidth, bh=box.clientHeight;
  if(!bw||!bh)return;
  const natW=(img&&img.naturalWidth)||640, natH=(img&&img.naturalHeight)||480;
  const scale=Math.min(bw/natW,bh/natH);
  const rw=natW*scale, rh=natH*scale;
  svg.style.width=rw+'px';
  svg.style.height=rh+'px';
  svg.style.left=((bw-rw)/2)+'px';
  svg.style.top=((bh-rh)/2)+'px';
}

function drawBadge(x,y,txt,bg,fg){
  const w=Math.min(180,Math.max(46,txt.length*6.3+12));
  const bx=Math.max(4,Math.min(640-w-4,x-w/2));
  const by=Math.max(4,Math.min(480-22,y-9));
  return '<g class="cam-ov-badge"><rect x="'+bx+'" y="'+by+'" width="'+w+'" height="18" rx="4" fill="'+bg+'" stroke="'+fg+'" stroke-width="1.2"/><text x="'+(bx+w/2)+'" y="'+(by+12.2)+'" fill="#eeeeef" font-size="10.5" font-weight="700" font-family="ui-monospace,Consolas,monospace" text-anchor="middle">'+esc(txt)+'</text></g>';
}

function renderCamGoalOverlay(){
  const grid=$('cam-grid');
  if(!grid)return;
  const box=grid.querySelector('.cam-box[data-cam-box="top"]');
  if(!box)return;
  let btn=box.querySelector('.cam-overlay-toggle');
  const on=isOverlayOn();
  if(!btn){
    btn=document.createElement('button');
    btn.type='button';
    btn.className='cam-overlay-toggle';
    btn.addEventListener('click',e=>{e.stopPropagation();setOverlayOn(!isOverlayOn());});
    box.append(btn);
  }
  btn.textContent=on?'목표 표시 ON':'목표 표시 OFF';
  btn.setAttribute('aria-pressed',on?'true':'false');
  btn.hidden=!box.classList.contains('cam-primary');

  let svg=box.querySelector('svg.cam-goal-overlay');
  if(!on||!box.classList.contains('cam-primary')){
    if(svg)svg.hidden=true;
    return;
  }
  if(!svg){
    svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('class','cam-goal-overlay');
    svg.setAttribute('viewBox','0 0 640 480');
    svg.setAttribute('preserveAspectRatio','none');
    svg.setAttribute('aria-hidden','true');
    box.append(svg);
  }
  svg.hidden=false;
  const img=box.querySelector('img[data-cam="top"]');
  if(img&&img!==boundImg){
    boundImg=img;
    img.addEventListener('load',()=>{const cur=$('cam-grid')?.querySelector('.cam-box[data-cam-box="top"]');if(cur)fitOverlayToImage(cur,cur.querySelector('img[data-cam="top"]'),cur.querySelector('svg.cam-goal-overlay'));});
  }
  if(!resizeObs&&typeof ResizeObserver==='function'){
    resizeObs=new ResizeObserver(()=>{const cur=$('cam-grid')?.querySelector('.cam-box[data-cam-box="top"]');if(cur)fitOverlayToImage(cur,cur.querySelector('img[data-cam="top"]'),cur.querySelector('svg.cam-goal-overlay'));});
    resizeObs.observe(box);
  }
  if(!box.dataset.ovImgWatch&&typeof MutationObserver==='function'){
    box.dataset.ovImgWatch='1';
    const mo=new MutationObserver(()=>{
      const curImg=box.querySelector('img[data-cam="top"]'), curSvg=box.querySelector('svg.cam-goal-overlay');
      if(curImg&&curImg.naturalWidth>0&&curSvg){fitOverlayToImage(box,curImg,curSvg);mo.disconnect();}
    });
    mo.observe(box,{childList:true});
  }
  fitOverlayToImage(box,img,svg);

  const {arm,origin,target}=activeGoalEndpoints();
  if(arm==='arm_s'){svg.innerHTML='';svg.hidden=true;return;}
  const oPoly=resolveSpotPoly(origin), tPoly=resolveSpotPoly(target);
  const zones=(window.cellMapData&&window.cellMapData.camera_overlay&&window.cellMapData.camera_overlay.zones)||{};
  let inner='<defs><marker id="cam-ov-arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto"><path d="M 0 1 L 10 5 L 0 9 z" fill="#ffc53d"/></marker></defs>';
  for(const zKey of ['belt','stand','pallet','temp_plate_a','temp_plate_b']){
    const zp=zones[zKey]||FB_SPOTS[zKey==='temp_plate_a'?'tmp-a':(zKey==='temp_plate_b'?'tmp-b':zKey)];
    if(zp)inner+='<polygon points="'+ptsStr(zp)+'" fill="none" stroke="rgba(238,238,239,.22)" stroke-width="1.2" stroke-dasharray="4 4"/>';
  }
  if(oPoly){
    const c=centroid(oPoly);
    inner+='<polygon points="'+ptsStr(oPoly)+'" fill="rgba(88,166,255,.22)" stroke="#58a6ff" stroke-width="2.6" stroke-dasharray="6 3"/>';
    inner+=drawBadge(c[0],Math.max(16,oPoly[0][1]-12),'① 집기 '+origin,'rgba(12,26,46,.92)','#58a6ff');
  }
  if(tPoly){
    const c=centroid(tPoly);
    inner+='<polygon points="'+ptsStr(tPoly)+'" fill="rgba(61,214,140,.24)" stroke="#3dd68c" stroke-width="2.8"/>';
    const by=Math.min(466,Math.max(20,(tPoly[2]?.[1]||c[1])+14));
    inner+=drawBadge(c[0],by,'② 놓기 '+target,'rgba(13,38,26,.92)','#3dd68c');
  }
  if(oPoly&&tPoly){
    const p0=centroid(oPoly), p1=centroid(tPoly);
    if(Math.hypot(p1[0]-p0[0],p1[1]-p0[1])>6){
      const mx=(p0[0]+p1[0])/2+(p0[1]>p1[1]?18:-18), my=(p0[1]+p1[1])/2-18;
      inner+='<path d="M '+p0[0].toFixed(1)+' '+p0[1].toFixed(1)+' Q '+mx.toFixed(1)+' '+my.toFixed(1)+' '+p1[0].toFixed(1)+' '+p1[1].toFixed(1)+'" fill="none" stroke="rgba(12,13,15,.85)" stroke-width="5.2" stroke-linecap="round"/>';
      inner+='<path d="M '+p0[0].toFixed(1)+' '+p0[1].toFixed(1)+' Q '+mx.toFixed(1)+' '+my.toFixed(1)+' '+p1[0].toFixed(1)+' '+p1[1].toFixed(1)+'" fill="none" stroke="#ffc53d" stroke-width="2.8" stroke-dasharray="7 4" marker-end="url(#cam-ov-arr)"/>';
      inner+='<circle cx="'+p0[0].toFixed(1)+'" cy="'+p0[1].toFixed(1)+'" r="8" fill="#58a6ff" stroke="#0c0d0f" stroke-width="1.8"/><text x="'+p0[0].toFixed(1)+'" y="'+(p0[1]+3.5).toFixed(1)+'" fill="#0c0d0f" font-size="10" font-weight="800" text-anchor="middle">1</text>';
      inner+='<circle cx="'+p1[0].toFixed(1)+'" cy="'+p1[1].toFixed(1)+'" r="8" fill="#3dd68c" stroke="#0c0d0f" stroke-width="1.8"/><text x="'+p1[0].toFixed(1)+'" y="'+(p1[1]+3.5).toFixed(1)+'" fill="#0c0d0f" font-size="10" font-weight="800" text-anchor="middle">2</text>';
    }
  }
  svg.innerHTML=inner;
}

window.renderCamGoalOverlay=renderCamGoalOverlay;
window.addEventListener('resize',()=>{const cur=$('cam-grid')?.querySelector('.cam-box[data-cam-box="top"]');if(cur)fitOverlayToImage(cur,cur.querySelector('img[data-cam="top"]'),cur.querySelector('svg.cam-goal-overlay'));});
})();
