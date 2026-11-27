// Clickable catalog-only object SVG overlay & confirmed one-shot :8781 PICK_PLACE staging bar.
(function(){
const STALE_MS=5000;
let lastPayload=null;
let lastFetchedMs=0;
let selectedRef=null;
let confirmPending=false;
let inFlight=false;
let statusNote='';
let lastBarKey='';

function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function curArm(){
  const a=typeof f!=='undefined'&&f&&f.arm?f.arm.value:'arm_a';
  return a==='arm_ab'?'arm_a':(a||'arm_a');
}
function topCamLabel(arm){return arm==='arm_s'?'arm_s_top':'top';}
function ptsStr(poly){return poly.map(p=>p[0]+','+p[1]).join(' ');}

function selectedObject(){
  const objs=lastPayload?.objects||[];
  return objs.find(o=>o.object_ref===selectedRef)||null;
}

function destOptions(arm){
  const list=(window.cellMapData&&Array.isArray(window.cellMapData.spot_catalog))?window.cellMapData.spot_catalog:[];
  const filtered=list.filter(s=>!Array.isArray(s.arms)||!s.arms.length||s.arms.includes(arm));
  const out=filtered.map(s=>({value:s.code,label:s.label||s.code}));
  if(!out.length){
    return arm==='arm_s'
      ? [{value:'belt',label:'벨트 (belt)'},{value:'belt-in',label:'벨트 공급 (belt-in)'}]
      : [{value:'stand',label:'반출대 (stand)'},{value:'belt',label:'벨트 (belt)'},{value:'pallet',label:'팔레트 (pallet)'}];
  }
  return out;
}

function isObservationFresh(){
  if(!lastPayload||lastPayload.status==='recording_active')return false;
  if(typeof isActivelyRecording==='function'&&isActivelyRecording())return false;
  return (Date.now()-lastFetchedMs)<=STALE_MS;
}

function renderPickBar(){
  const bar=$('obj-pick-bar');
  if(!bar)return;
  const sel=selectedObject();
  if(!lastPayload||(!lastPayload.objects?.length&&!sel&&!statusNote)){
    bar.hidden=true;
    lastBarKey='';
    return;
  }
  bar.hidden=false;
  const fresh=isObservationFresh();
  const arm=lastPayload.arm_id||curArm();
  const barKey=[arm,fresh,lastPayload.status,(lastPayload.objects||[]).length,sel?.object_ref||'',sel?.pickable,sel?.veto_reason||'',confirmPending,inFlight,statusNote].join('|');
  if(barKey===lastBarKey)return;
  lastBarKey=barKey;
  if(!sel){
    const recTxt=lastPayload.status==='recording_active'?'녹화 중 (객체 선택 일시 중단)':`카탈로그 객체 ${(lastPayload.objects||[]).length}개 감지됨 — 상단 카메라에서 객체를 클릭하세요`;
    bar.innerHTML=`<div class="obj-pick-meta"><span>${esc(statusNote||recTxt)}</span></div>`;
    return;
  }
  const opts=destOptions(arm);
  const prevDst=$('obj-dst-sel')?.value||opts[0]?.value||'';
  const optHtml=opts.map(o=>`<option value="${esc(o.value)}"${o.value===prevDst?' selected':''}>${esc(o.label)}</option>`).join('');
  const lockMsg=!fresh?'관측 만료(5초 초과) · 최신 프레임 수신 후 실행 가능':(!sel.pickable?(`집기 제한: ${sel.veto_reason||'선택 불가'}`):'');
  const blocked=!fresh||!sel.pickable||inFlight;
  bar.innerHTML=`
    <div class="obj-pick-meta">
      <span class="ui-tag mono">① ${esc(sel.catalog_id)} (${esc(sel.site)})</span>
      <span class="quiet mono">${esc(sel.centre_mm?.join(', '))} mm · tol ${esc(sel.bind_tol_mm)} mm</span>
      ${lockMsg?`<span class="quiet">${esc(lockMsg)}</span>`:''}
      ${statusNote?`<span>${esc(statusNote)}</span>`:''}
    </div>
    <div class="obj-pick-actions">
      <label><span>② 놓을 곳</span> <select id="obj-dst-sel" class="ui-field">${optHtml}</select></label>
      <button type="button" id="obj-dryrun-btn" class="btn-tool btn-xs" ${blocked?'disabled':''}>미리보기 (Dry-Run)</button>
      ${confirmPending
        ? `<button type="button" id="obj-exec-confirm-btn" class="btn-primary btn-xs" ${blocked?'disabled':''}>확인 · 1회 집기·놓기 실행</button>
           <button type="button" id="obj-cancel-btn" class="btn-tool btn-xs">취소</button>`
        : `<button type="button" id="obj-exec-btn" class="btn-primary btn-xs" ${blocked?'disabled':''}>집기·놓기 실행</button>`}
      <button type="button" id="obj-clear-btn" class="btn-tool btn-xs">선택 해제</button>
    </div>`;
  $('obj-dryrun-btn')?.addEventListener('click',()=>submitPickPlace(true));
  $('obj-exec-btn')?.addEventListener('click',()=>{confirmPending=true;renderPickBar();});
  $('obj-exec-confirm-btn')?.addEventListener('click',()=>submitPickPlace(false));
  $('obj-cancel-btn')?.addEventListener('click',()=>{confirmPending=false;renderPickBar();});
  $('obj-clear-btn')?.addEventListener('click',()=>{selectedRef=null;confirmPending=false;statusNote='';renderCamObjectsOverlay();renderPickBar();});
}

async function submitPickPlace(dryRun){
  const sel=selectedObject();
  const dst=$('obj-dst-sel')?.value||'';
  if(!sel||!dst||!isObservationFresh())return;
  inFlight=true;
  confirmPending=false;
  statusNote=dryRun?'미리보기(Dry-Run) 검증 중...':':8781 작업 등록 중...';
  renderPickBar();
  try{
    const idem=(typeof crypto!=='undefined'&&crypto.randomUUID)?crypto.randomUUID():`bench-${Date.now()}`;
    const res=await api('/api/pick_place',{
      arm:lastPayload.arm_id||curArm(),
      dest_site:dst,
      dry_run:dryRun,
      idempotency_key:idem,
      target_object:{
        object_ref:sel.object_ref,
        catalog_id:sel.catalog_id,
        site:sel.site,
        centroid_mm:sel.centre_mm,
        source_seq:lastPayload.source_seq,
        observed_at:lastPayload.observed_at,
        ttl_s:lastPayload.ttl_s,
        tolerance_mm:sel.bind_tol_mm,
        cell_state_gen:lastPayload.cell_state_gen
      }
    });
    statusNote=dryRun?`Dry-Run 접수 (${res.id||'ok'})`:`1회 집기·놓기 작업 시작 (${res.id||'ok'})`;
  }catch(err){
    statusNote='요청 거부: '+(err.message||'오류');
  }finally{
    inFlight=false;
    renderPickBar();
  }
}

function renderCamObjectsOverlay(){
  const grid=$('cam-grid');
  if(!grid)return;
  const lbl=topCamLabel(lastPayload?.arm_id||curArm());
  const box=grid.querySelector(`.cam-box[data-cam-box="${lbl}"]`);
  if(!box)return;
  let svg=box.querySelector('svg.cam-objects-overlay');
  if(!box.classList.contains('cam-primary')||!lastPayload){
    if(svg)svg.hidden=true;
    return;
  }
  if(!svg){
    svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('class','cam-objects-overlay');
    svg.setAttribute('viewBox','0 0 640 480');
    svg.setAttribute('preserveAspectRatio','none');
    box.append(svg);
  }
  svg.hidden=false;
  const img=box.querySelector(`img[data-cam="${lbl}"]`);
  if(typeof window.fitCamOverlayToImage==='function')window.fitCamOverlayToImage(box,img,svg);
  const fresh=isObservationFresh();
  svg.dataset.stale=fresh?'false':'true';
  const objs=lastPayload.objects||[];
  svg.innerHTML=objs.map(o=>{
    const sel=o.object_ref===selectedRef;
    const pts=Array.isArray(o.corners_px)&&o.corners_px.length===4?ptsStr(o.corners_px):null;
    const cx=o.centre_px?.[0]??320, cy=o.centre_px?.[1]??240;
    const shape=pts
      ? `<polygon points="${pts}" class="${o.pickable?'cam-obj-poly':'cam-obj-poly-veto'}"/>`
      : `<circle cx="${cx}" cy="${cy}" r="16" class="${o.pickable?'cam-obj-poly':'cam-obj-poly-veto'}"/>`;
    const badge=(sel?'① ':'')+o.catalog_id+(o.pickable?'':` · ${o.veto_reason||'제한'}`);
    const label=`<text x="${cx}" y="${Math.max(14,cy-18)}" text-anchor="middle" fill="#eeeeef" font-size="12" font-weight="700" stroke="#0c0d0f" stroke-width="3" paint-order="stroke">${esc(badge)}</text>`;
    if(!o.pickable)return `<g class="cam-obj-veto" data-cam-veto="${esc(o.object_ref)}"><title>${esc(o.veto_reason||'선택 불가')}</title>${shape}${label}</g>`;
    return `<g class="cam-obj-node" role="button" tabindex="${fresh?0:-1}" aria-pressed="${sel?'true':'false'}" aria-label="${esc(o.catalog_id)} 선택" data-cam-object="${esc(o.object_ref)}">${shape}${label}</g>`;
  }).join('');
  for(const g of svg.querySelectorAll('.cam-obj-node')){
    const pick=ev=>{ev.stopPropagation();selectedRef=g.dataset.camObject;confirmPending=false;statusNote='';renderCamObjectsOverlay();renderPickBar();};
    g.addEventListener('click',pick);
    g.addEventListener('keydown',ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();pick(ev);}});
  }
}

async function pollObjects(){
  const sec=$('sec-cameras');
  if(!sec||sec.hidden)return;
  if(typeof isActivelyRecording==='function'&&isActivelyRecording()){
    if(lastPayload){renderCamObjectsOverlay();renderPickBar();}
    return;
  }
  try{
    lastPayload=await api('/api/objects?arm='+encodeURIComponent(curArm()));
    lastFetchedMs=Date.now();
  }catch(_){}
  if(lastPayload){
    renderCamObjectsOverlay();
    renderPickBar();
  }
}

window.renderCamObjectsOverlay=renderCamObjectsOverlay;
setInterval(pollObjects,1000);
})();
