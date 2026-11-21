const H={'Content-Type':'application/json','X-Bench':'1'};
const $=id=>document.getElementById(id);
const f=$('bench-form');
const STATUS_MAP={
  idle:['대기','good'],
  handing_over:['시작 중 (인계)','live'],
  homing:['리더가 움직입니다 — 손을 대지 마세요','live'],
  recording:['녹화 중','live'],
  restoring:['복구 중','warn'],
  sealing:['봉인 중','live'],
  sealed:['완료 (봉인됨)','good'],
  stopped_not_sealed:['원본만 보관 (중단됨)','warn'],
  stopped_safe:['중단됨 (안전 종료 확인)','warn'],
  unsafe_or_failed:['실패 (안전 종료 미확인)','crit'],
  seal_failed:['실패 (봉인 실패)','crit'],
  failed:['실패','crit']
};
const BUSY=new Set(['handing_over','homing','recording','restoring','sealing']);
const NAME_RE=/^[a-z0-9][a-z0-9-]{2,63}$/;

let choices=null;
let lastStatus=null;
let statusLoaded=false;
let startInFlight=false;
let stopInFlight=false;
let latestStatusSeq=0;
let lastStartMeta=null;
let lastTelemetryActive=false;
let lastAutoPhase='setup';
let manualPhase=null;

function resolveBenchPhase(statusCode,telemetryActive){
  const code=String(statusCode||'idle');
  if(BUSY.has(code))return 'live';
  if(code==='sealed'||code==='stopped_safe'||code==='stopped_not_sealed'||code==='unsafe_or_failed'||code==='seal_failed'||code==='failed'||code==='leader_manual_check')return 'result';
  if(telemetryActive)return 'live';
  return 'setup';
}

function currentBenchPhase(){
  return manualPhase||lastAutoPhase;
}

function applyBenchPhase(phase){
  const p=(phase==='live'||phase==='result')?phase:'setup';
  const shell=document.querySelector('.app-shell');
  if(shell)shell.dataset.phase=p;
  for(const btn of document.querySelectorAll('#phase-tabs [data-phase-tab]')){
    const on=btn.dataset.phaseTab===p;
    if(on)btn.setAttribute('aria-current','step');
    else btn.removeAttribute('aria-current');
  }
  for(const el of document.querySelectorAll('[data-tabs]')){
    const tabs=String(el.dataset.tabs||'').split(/\s+/).filter(Boolean);
    el.hidden=!tabs.includes(p);
  }
  const camBaseBtn=$('save-cam-base-btn');
  if(camBaseBtn)camBaseBtn.hidden=(p==='live');
  if(p==='live'&&typeof window.closeDrawer==='function'&&window.activeDrawerName?.()!=='records')window.closeDrawer(false);
  if(p==='setup'||p==='live')renderCamGuide();
  if(typeof updateGoalSummaryRows==='function')updateGoalSummaryRows();
}

function syncBenchPhase(){
  const nextAuto=resolveBenchPhase(lastStatus?lastStatus.status:'idle',lastTelemetryActive);
  if(nextAuto!==lastAutoPhase){
    lastAutoPhase=nextAuto;
    manualPhase=null;
  }
  applyBenchPhase(currentBenchPhase());
}

window.resolveBenchPhase=resolveBenchPhase;
window.applyBenchPhase=applyBenchPhase;
window.setManualBenchPhase=p=>{manualPhase=p;applyBenchPhase(currentBenchPhase());};

async function api(path,body){
  const res=await fetch(path,body?{method:'POST',headers:H,body:JSON.stringify(body)}:{cache:'no-store'});
  let data={};
  try{data=await res.json();}catch(_){}
  if(!res.ok)throw new Error(data.error||('HTTP '+res.status));
  return data;
}

function nowText(){
  const d=new Date();
  return [d.getHours(),d.getMinutes(),d.getSeconds()].map(n=>String(n).padStart(2,'0')).join(':');
}

const ERROR_KIND_PREFIX={refused:'거절됨',needs_person:'사람 확인 필요',recovered:'자동 복구됨'};
const STARTING_STEP_MAP={
  follower_home:'팔로워 홈 이동 중',
  leader_align:'리더 정렬 중 (손을 대지 마세요)',
  starting_recorder:'녹화기 시작 중',
  connecting_cameras:'카메라 연결 중',
  aligning:'가드 정렬 중'
};
const NOTICE_PRIO={crit:4,warn:3,good:2,muted:1};
const NOTICE_TONE_LABEL={crit:'오류',warn:'주의',good:'완료',muted:'안내'};
const activeNotices=new Map();
const dismissedNoticeMsg=new Map();
const noticeHistory=[];

function formatErrorKind(msg,kind){
  const text=String(msg||'').trim();
  const prefix=kind?ERROR_KIND_PREFIX[kind]:'';
  if(!text||!prefix)return text;
  return text.startsWith(prefix)?text:(prefix+': '+text);
}
window.formatErrorKind=formatErrorKind;

function syncHeadHeight(){
  const head=document.querySelector('.app-topbar');
  if(head)document.documentElement.style.setProperty('--head-h',head.offsetHeight+'px');
}
window.syncHeadHeight=syncHeadHeight;

function renderNoticeHistory(){
  const ul=$('notice-history-list'), empty=$('notice-history-empty'), sum=$('sb-notice-sum');
  if(sum)sum.textContent=noticeHistory.length+'건';
  if(!ul||!empty)return;
  if(!noticeHistory.length){ul.innerHTML='';empty.hidden=false;return;}
  empty.hidden=true;
  ul.innerHTML='';
  for(const item of noticeHistory){
    const li=document.createElement('li');
    li.className='notice-hist-item';
    li.dataset.tone=item.tone;
    const meta=document.createElement('div');
    meta.className='notice-hist-meta mono';
    const left=document.createElement('span');left.textContent=(NOTICE_TONE_LABEL[item.tone]||item.tone)+' · '+item.key;
    const right=document.createElement('span');right.textContent=item.ts;
    meta.append(left,right);
    const body=document.createElement('div');
    body.textContent=item.msg;
    li.append(meta,body);
    ul.append(li);
  }
}

function renderNoticeBar(){
  const now=Date.now();
  for(const [k,v] of activeNotices.entries()){
    if(v.expiresAt&&now>=v.expiresAt)activeNotices.delete(k);
  }
  const reasonBar=$('start-reason-bar'), hdrReasons=$('hdr-start-reasons');
  const moreBtn=$('reason-more-btn'), expBtn=$('reason-expand-btn'), closeBtn=$('reason-close-btn');
  if(!reasonBar||!hdrReasons)return;
  const list=[...activeNotices.values()].sort((a,b)=>(NOTICE_PRIO[b.tone]||0)-(NOTICE_PRIO[a.tone]||0));
  if(!list.length){
    hdrReasons.textContent='';
    reasonBar.hidden=true;
    reasonBar.classList.remove('expanded','muted','crit','good');
    if(moreBtn){moreBtn.hidden=true;moreBtn.textContent='';}
    if(expBtn){expBtn.hidden=true;expBtn.setAttribute('aria-expanded','false');expBtn.textContent='자세히';}
    if(closeBtn)closeBtn.hidden=true;
    syncHeadHeight();
    return;
  }
  const top=list[0];
  reasonBar.hidden=false;
  reasonBar.classList.remove('muted','crit','good');
  if(top.tone==='muted'||top.tone==='crit'||top.tone==='good')reasonBar.classList.add(top.tone);
  const expanded=reasonBar.classList.contains('expanded');
  hdrReasons.textContent=expanded?list.map(n=>n.msg).join(' | '):top.msg;
  if(moreBtn){
    const extra=list.length-1;
    moreBtn.hidden=expanded||extra<=0;
    moreBtn.textContent=extra>0?('(+'+extra+'건)'):'';
  }
  if(expBtn){
    const needExp=list.length>1||top.msg.length>72;
    expBtn.hidden=!needExp;
    expBtn.setAttribute('aria-expanded',expanded?'true':'false');
    expBtn.textContent=expanded?'접기':'자세히';
  }
  if(closeBtn){
    closeBtn.hidden=!(top.persistent||top.tone==='crit'||top.tone==='good');
    closeBtn.dataset.noticeKey=top.key;
  }
  syncHeadHeight();
}

function setNotice(key,tone,msg,opts){
  const text=String(msg||'').trim();
  if(!text){clearNotice(key);return;}
  if(dismissedNoticeMsg.get(key)===text)return;
  dismissedNoticeMsg.delete(key);
  const prev=activeNotices.get(key);
  const ts=nowText();
  const persistent=Boolean(opts&&opts.persistent)||tone==='crit';
  const expiresAt=(tone==='good')?(Date.now()+((opts&&opts.ttlMs)||6000)):0;
  activeNotices.set(key,{key,tone,msg:text,ts,persistent,expiresAt});
  if(!prev||prev.msg!==text||prev.tone!==tone){
    noticeHistory.unshift({ts,key,tone,msg:text});
    if(noticeHistory.length>20)noticeHistory.length=20;
    renderNoticeHistory();
  }
  renderNoticeBar();
}

function clearNotice(key){
  dismissedNoticeMsg.delete(key);
  if(activeNotices.delete(key))renderNoticeBar();
}

function dismissTopNotice(){
  const list=[...activeNotices.values()].sort((a,b)=>(NOTICE_PRIO[b.tone]||0)-(NOTICE_PRIO[a.tone]||0));
  if(!list.length)return;
  const top=list[0];
  dismissedNoticeMsg.set(top.key,top.msg);
  activeNotices.delete(top.key);
  renderNoticeBar();
}

window.setNotice=setNotice;
window.clearNotice=clearNotice;
window.dismissTopNotice=dismissTopNotice;
setInterval(()=>{if(activeNotices.size)renderNoticeBar();},1000);

function initSidebarSections(){
  const narrow1366=typeof window.matchMedia==='function'&&window.matchMedia('(max-width: 1366px)').matches;
  for(const el of document.querySelectorAll('#bench-sidebar details.sb-sec[id]')){
    const k='omx_sb_sec_'+el.id;
    try{
      const saved=localStorage.getItem(k);
      if(saved==='1')el.open=true;
      else if(saved==='0')el.open=false;
      else if(el.id==='sec-guide'&&narrow1366)el.open=false;
    }catch(_){}
    el.addEventListener('toggle',()=>{
      try{localStorage.setItem(k,el.open?'1':'0');}catch(_){}
    });
  }
}
initSidebarSections();

function setReqError(msg){
  if(!msg){clearNotice('req-error');return;}
  setNotice('req-error','crit','요청 오류: '+msg,{persistent:true});
}

function armContractValid(){
  return Boolean(choices&&Array.isArray(choices.arms)&&choices.arms.length>0&&choices.instances&&typeof choices.instances==='object');
}

function armVerifiedBindings(arm){
  const b=choices&&choices.arm_bindings&&typeof choices.arm_bindings==='object'?choices.arm_bindings[arm]:null;
  if(!b||typeof b!=='object')return null;
  if(!Array.isArray(b.configs)||!Array.isArray(b.caps)||!Array.isArray(b.calibrations))return null;
  return b;
}

function sessionKey(st){
  if(!st||typeof st!=='object')return '';
  return String(st.session_id||st.folder||st.started||st.name||'');
}

// Ship address ship-h<hold>r<row>-l<layer>: counts from 0 for rows and layers (tools/sim/omx_two_arm_sites.py r08_sites; r0 is nearest arm_a, r2 arm_b).
// The names below count layers from 1 (tier numbers of shared/web/cell-site-map.json). Hold h1 is columns 4~6 and h2 columns 1~3 there (Harbor's hold 1 is h2).
const ROW_LABELS=['A쪽 줄','가운데 줄','B쪽 줄'];
const LAYER_LABELS=['1층(바닥)','2층(중간)','3층(맨 위)'];
const HOLD_COLUMNS={1:'4~6열',2:'1~3열'};

function describeSpot(code){
  if(!code)return '미확인';
  const s=String(code);
  if(s==='belt')return '벨트 인출단 (Arm A/B 집는 곳 · belt)';
  if(s==='belt-in'||s==='belt-s')return '벨트 공급단 (Arm S 놓는 곳 · belt-in)';
  if(s==='stand'||s==='stand:r1-s1'||s==='stand:r1-s1-t1')return '반출대 (Arm A 전용 · 컨베이어 우측 · stand)';
  if(s==='pinky'||s.startsWith('pinky-'))return '핑키 로봇 ('+s+')';
  let m=s.match(/^ship-h(\d)r(\d)-l(\d)$/);
  if(m){
    const r=Number(m[2]), l=Number(m[3]);
    const rTxt=ROW_LABELS[r]||((r+1)+'번째 줄');
    const lTxt=LAYER_LABELS[l]||((l+1)+'층');
    return '화물칸 h'+m[1]+' · '+rTxt+' · '+lTxt+' ['+s+']';
  }
  m=s.match(/^tmp-([ab])-(\d+)(?:-l(\d+))?$/);
  if(m){
    const side=m[1]==='a'?'왼쪽':'오른쪽';
    const lTxt=m[3]?(LAYER_LABELS[Number(m[3])]||((Number(m[3])+1)+'층')):'';
    return '임시대 '+m[1].toUpperCase()+'('+side+') · '+m[2]+'번 칸'+(lTxt?' · '+lTxt:'');
  }
  return s;
}

function splitSpotDisplay(text){
  const s=String(text||'');
  const m=s.match(/^(.+?)\s*(?:\(([^)]+)\)|\[([^\]]+)\])\s*$/);
  if(!m)return {main:s,sub:''};
  return {main:m[1].trim(),sub:(m[2]||m[3]||'').trim()};
}

let lastMapNote='';
window.clearMapNote=()=>{lastMapNote='';};

function pickTaskBySpot(spot){
  if(BUSY.has(lastStatus?.status))return;
  if(!choices||!Array.isArray(choices.tasks))return;
  const cards=choices.task_cards||{};
  const validTasks=choices.tasks.filter(v=>cards[v]&&cards[v].valid!==false);
  let pool=[];
  if(spot==='belt-in'){
    pool=validTasks.filter(v=>{
      const c=cards[v];
      const txt=(v+' '+(c.single_task||'')+' '+(c.raw||'')).toLowerCase();
      return txt.includes('conveyor')||txt.includes('supply')||txt.includes('arm s');
    });
  }else if(spot==='pinky'){
    pool=validTasks.filter(v=>{
      const c=cards[v];
      const txt=(v+' '+(c.origin||'')+' '+(c.target_slot||'')+' '+(c.single_task||'')).toLowerCase();
      return txt.includes('pinky');
    });
  }else{
    const exactTgt=validTasks.filter(v=>String(cards[v].target_slot||'')===spot);
    const prefTgt=validTasks.filter(v=>String(cards[v].target_slot||'').startsWith(spot));
    const anySpot=validTasks.filter(v=>{
      const c=cards[v];
      return String(c.origin||'').startsWith(spot)||String(c.target_slot||'').startsWith(spot)||String(v).toLowerCase().includes(spot.toLowerCase());
    });
    pool=exactTgt.length?exactTgt:(prefTgt.length?prefTgt:anySpot);
  }
  const holdSel=spot.match(/^ship-h(\d)$/);
  window.shipHold=holdSel&&!pool.length?Number(holdSel[1]):null;
  if(!pool.length){
    lastMapNote=spot+' 구역: 이 조합의 과제 카드 없음'+(holdSel?' (화물칸 h'+holdSel[1]+')':'');
    if(holdSel){renderCamGuide();return;}
    if($('task-search')){$('task-search').value=spot;renderTaskListbox();}
    const noteEl=$('cam-map-note');
    if(noteEl){noteEl.textContent=lastMapNote;noteEl.hidden=false;}
    return;
  }
  const curIdx=pool.indexOf(f.task.value);
  const nextTask=pool[(curIdx+1)%pool.length];
  if($('task-search'))$('task-search').value='';
  selectTask(nextTask);
  lastMapNote=spot+' 선택 · 일치 과제 카드 '+pool.length+'개 ('+(pool.indexOf(nextTask)+1)+'/'+pool.length+' · '+nextTask+')';
  const noteEl=$('cam-map-note');
  if(noteEl){noteEl.textContent=lastMapNote;noteEl.hidden=false;}
  const selOpt=$('task-listbox')?.querySelector('[aria-selected="true"]');
  if(selOpt)selOpt.scrollIntoView({block:'nearest'});
}

function renderCamGuide(){
  const box=$('cam-guide');
  const t=f.task.value;
  const c=choices&&choices.task_cards&&t?choices.task_cards[t]:null;
  const okCard=Boolean(c&&c.valid!==false);
  const taskLow=(String(t||'')+' '+String(c?.single_task||'')).toLowerCase();
  const isPinky=okCard&&taskLow.includes('pinky');
  const isBeltIn=okCard&&(taskLow.includes('conveyor')||taskLow.includes('supply'));
  const rawO=okCard?(c.origin?String(c.origin):(isPinky?'pinky':'')):'';
  const rawT=okCard?(c.target_slot?String(c.target_slot):(isBeltIn?'belt-in':'')):'';
  const swapped=Boolean(window.zoneSwapped&&okCard&&(rawO||rawT));
  const oStr=swapped?rawT:rawO;
  const tStr=swapped?rawO:rawT;
  const org=okCard?describeSpot(oStr):'미선택';
  const tgt=okCard?describeSpot([tStr,c?.target_layer].filter(Boolean).join('-')):'미선택';
  const zoneCol=(z)=>(z==='belt'?tStr==='belt':tStr.startsWith(z))?'#3dd68c':((z==='belt'?oStr==='belt':oStr.startsWith(z))?'#58a6ff':'#363a3f');
  const zoneBg=(z)=>(z==='belt'?tStr==='belt':tStr.startsWith(z))?'#14261e':((z==='belt'?oStr==='belt':oStr.startsWith(z))?'#132238':'#18191b');
  const cardCount=(pre)=>Object.values((choices&&choices.task_cards)||{}).filter(x=>x&&x.valid!==false&&String(x.raw||'').includes(pre)).length;
  const holdOf=(z)=>{const h=String(z).match(/^ship-h(\d)/);return h?Number(h[1]):0;};
  const hold=holdOf(tStr)||holdOf(oStr);
  const goalEmpty=$('goal-empty'), goalActive=$('goal-active'), swBtn=$('swap-zones-btn');
  if(goalEmpty&&goalActive){
    goalEmpty.hidden=okCard;
    goalActive.hidden=!okCard;
    if(swBtn){
      swBtn.hidden=!okCard;
      swBtn.setAttribute('aria-pressed',swapped?'true':'false');
      swBtn.textContent='⇄ 집기↔놓기 스왑'+(swapped?' (적용됨)':'');
    }
    if(okCard){
      const oDisp=splitSpotDisplay(org);
      const tDisp=splitSpotDisplay(tgt);
      if($('goal-origin-name'))$('goal-origin-name').textContent=oDisp.main;
      if($('goal-origin-sub')){$('goal-origin-sub').textContent=oDisp.sub;$('goal-origin-sub').hidden=!oDisp.sub;}
      if($('goal-target-name'))$('goal-target-name').textContent=tDisp.main;
      if($('goal-target-sub')){$('goal-target-sub').textContent=tDisp.sub;$('goal-target-sub').hidden=!tDisp.sub;}
      const instrEl=$('goal-instruction');
      if(instrEl){
        const rawInstr=c.single_task?String(c.single_task):'';
        instrEl.textContent=(swapped&&rawInstr&&typeof window.flipTaskLabel==='function')?(window.flipTaskLabel(rawInstr)+' [스왑]'):rawInstr;
      }
      const q=typeof epQuota==='function'?epQuota(c):null;
      if($('goal-rep-count'))$('goal-rep-count').textContent=q?(q.done+' / '+q.goal+' 회'):(c.num_episodes!=null?('0 / '+c.num_episodes+' 회'):'— / — 회');
      if($('goal-prog-fill')){
        const pct=q?q.pct:0;
        $('goal-prog-fill').style.width=pct+'%';
        $('goal-prog-fill').style.background=(q&&q.rem===0&&q.goal>0)?'var(--good)':'var(--pri)';
      }
    }
  }
  let html='<div class="cam-guide-inner">';
  html+='<div id="cam-map-note" class="cam-map-note quiet" hidden></div>';
  html+='<svg class="cam-guide-svg" viewBox="0 0 360 178" preserveAspectRatio="xMidYMid meet" aria-label="작업대 구역 배치도">';
  html+='<g class="map-spot" data-spot="tmp-a" role="button" tabindex="0"><rect x="8" y="8" width="84" height="70" rx="6" fill="'+zoneBg('tmp-a')+'" stroke="'+zoneCol('tmp-a')+'" stroke-width="2"/><text x="50" y="40" fill="#eeeeef" font-size="12" text-anchor="middle">임시대 A (좌)</text><text x="50" y="56" fill="#b0b4ba" font-size="9.5" text-anchor="middle">tmp-a</text></g>';
  html+='<g class="map-spot" data-spot="tmp-b" role="button" tabindex="0"><rect x="268" y="8" width="84" height="70" rx="6" fill="'+zoneBg('tmp-b')+'" stroke="'+zoneCol('tmp-b')+'" stroke-width="2"/><text x="310" y="40" fill="#eeeeef" font-size="12" text-anchor="middle">임시대 B (우)</text><text x="310" y="56" fill="#b0b4ba" font-size="9.5" text-anchor="middle">tmp-b</text></g>';
  for(const [k,y] of [[2,8],[1,46]]){
    const n=cardCount('ship-h'+k);
    html+='<g class="map-spot" data-spot="ship-h'+k+'" role="button" tabindex="0"><rect x="100" y="'+y+'" width="160" height="32" rx="6" fill="'+zoneBg('ship-h'+k)+'" stroke="'+zoneCol('ship-h'+k)+'" stroke-width="2"/><text x="180" y="'+(y+14)+'" fill="#eeeeef" font-size="11" text-anchor="middle">'+(k===hold?'▶ ':'')+'화물칸 h'+k+' · '+HOLD_COLUMNS[k]+'</text><text x="180" y="'+(y+26)+'" fill="#b0b4ba" font-size="9" text-anchor="middle">'+(n?'과제 카드 '+n+'개':'과제 카드 없음')+'</text></g>';
  }
  html+='<g transform="translate(0,16)">';
  html+='<g class="map-spot" data-spot="pinky" role="button" tabindex="0"><rect x="8" y="72" width="96" height="40" rx="6" fill="'+zoneBg('pinky')+'" stroke="'+zoneCol('pinky')+'" stroke-width="2"/><text x="56" y="89" fill="#eeeeef" font-size="11" text-anchor="middle">핑키 로봇</text><text x="56" y="103" fill="#b0b4ba" font-size="9" text-anchor="middle">pinky (앞쪽)</text></g>';
  html+='<g class="map-spot" data-spot="belt-in" role="button" tabindex="0"><rect x="114" y="72" width="110" height="40" rx="6" fill="'+zoneBg('belt-in')+'" stroke="'+zoneCol('belt-in')+'" stroke-width="2"/><text x="169" y="89" fill="#eeeeef" font-size="11" text-anchor="middle">벨트 공급단 (S)</text><text x="169" y="103" fill="#b0b4ba" font-size="9" text-anchor="middle">belt-in (놓는 곳)</text></g>';
  html+='<text x="232" y="96" fill="#b0b4ba" font-size="12" text-anchor="middle">&rarr;</text>';
  html+='<g class="map-spot" data-spot="belt" role="button" tabindex="0"><rect x="240" y="72" width="112" height="40" rx="6" fill="'+zoneBg('belt')+'" stroke="'+zoneCol('belt')+'" stroke-width="2"/><text x="296" y="89" fill="#eeeeef" font-size="11" text-anchor="middle">벨트 인출단 (A/B)</text><text x="296" y="103" fill="#b0b4ba" font-size="9" text-anchor="middle">belt (집는 곳)</text></g>';
  html+='</g>';
  html+='<g class="map-spot" data-spot="stand" role="button" tabindex="0"><rect x="8" y="134" width="344" height="36" rx="6" fill="'+zoneBg('stand')+'" stroke="'+zoneCol('stand')+'" stroke-width="2"/><text x="180" y="149" fill="#eeeeef" font-size="11" text-anchor="middle">반출대 (Arm A · 컨베이어 우측 상단)</text><text x="180" y="163" fill="#b0b4ba" font-size="9" text-anchor="middle">stand:r1-s1 (top.jpg ROI 410..570 × 30..125)</text></g>';
  html+='</svg>';
  if(hold){
    const sm=tStr.match(/^ship-h(\d)r(\d)-l(\d)$/);
    const th=sm?Number(sm[1]):0, tr=sm?Number(sm[2]):-1, tl=sm?Number(sm[3]):-1;
    // one grid: the selected hold (hold boxes above sit in site-map column order, h2 = columns 1~3 on top, h1 = columns 4~6 below)
    const k=hold, n=cardCount('ship-h'+k);
    html+='<div><b>화물칸 h'+k+'</b> · '+HOLD_COLUMNS[k]+' · 3줄 × 3층 · '+(n?'과제 카드 '+n+'개':'과제 카드 없음 (칸을 눌러도 연결되지 않음)')+'</div>';
    html+='<div class="ship-grid'+(n?'':' empty')+'" aria-label="화물칸 h'+k+' 층·줄 선택" style="display:grid;grid-template-columns:68px repeat(3,minmax(0,1fr));gap:4px;align-items:center"><div></div>';
    for(const row of [0,1,2]){
      html+='<div class="quiet" style="text-align:center;font-size:.75rem;font-weight:700">'+ROW_LABELS[row]+'</div>';
    }
    for(const lv of [2,1,0]){
      html+='<div class="quiet" style="font-size:.75rem;font-weight:700;text-align:right;padding-right:4px">'+LAYER_LABELS[lv]+'</div>';
      for(const row of [0,1,2]){
        const hit=(k===th&&row===tr&&lv===tl);
        const spot='ship-h'+k+'r'+row+'-l'+lv;
        html+='<button type="button" class="slot-btn'+(hit?' active':'')+'" aria-pressed="'+(hit?'true':'false')+'" data-spot="'+spot+'" title="'+describeSpot(spot)+'" aria-label="'+describeSpot(spot)+'" style="padding:5px 4px">'+(lv+1)+'층'+(hit?' ★':'')+'</button>';
      }
    }
    html+='</div>';
  }
  box.innerHTML=html+'</div>';
  const nEl=$('cam-map-note');
  if(nEl){nEl.textContent=lastMapNote;nEl.hidden=!lastMapNote;}
  box.hidden=(currentBenchPhase()==='live');
  for(const el of box.querySelectorAll('[data-spot]')){
    el.addEventListener('click',()=>pickTaskBySpot(el.dataset.spot));
    el.addEventListener('keydown',(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pickTaskBySpot(el.dataset.spot);}});
  }
  if(swBtn&&!swBtn.dataset.bound){
    swBtn.dataset.bound='1';
    swBtn.addEventListener('click',()=>{
      window.zoneSwapped=!window.zoneSwapped;
      renderCamGuide();
      updateTaskSummary();
    });
  }
  for(const tag of $('cam-grid').querySelectorAll('.cam-tag')){
    tag.textContent=(okCard&&c.target_slot)?('목표 '+c.target_slot):'';
    tag.hidden=!(okCard&&c.target_slot);
  }
  updateGoalSummaryRows();
}

function updateGoalSummaryRows(){
  const phase=currentBenchPhase();
  const st=lastStatus;
  const t=f&&f.task?f.task.value:(st&&st.task?st.task:'');
  const c=choices&&choices.task_cards&&t?choices.task_cards[t]:null;
  const busyRun=Boolean(st&&BUSY.has(st.status));
  const showSession=busyRun||phase==='result';
  const meta=lastStartMeta&&sessionKey(st)===lastStartMeta.key?lastStartMeta:null;
  const nm=(showSession&&(st?.name||meta?.name))||f.name.value.trim()||'수집명 미정';
  const tid=(showSession&&(st?.task||meta?.task))||(c&&c.valid!==false&&c.task_id)||t||'과제 미선택';
  for(const [id,value,label] of [['hdr-task-summary',tid,'과제'],['goal-name-btn',nm,'수집명']]){
    const btn=$(id);
    btn.textContent=value;
    btn.title=label+' '+value;
    btn.setAttribute('aria-label',label+' '+value);
  }
  const resEl=$('goal-result-line');
  resEl.hidden=phase!=='result'||!st;
  if(!resEl.hidden){
    const lbl=STATUS_MAP[st.status]?.[0]||st.status||'완료';
    const epDone=st.episodes_done!=null?(st.episodes_done+'회'):'';
    resEl.textContent=['방금 결과:',lbl,epDone].filter(Boolean).join(' · ');
    resEl.title=resEl.textContent;
  }
  const cfg=(busyRun&&st.config)?st.config:(f&&f.config&&f.config.value?f.config.value:'미선택');
  const cap=(busyRun&&st.caps)?st.caps:(f&&f.caps&&f.caps.value?f.caps.value:'미선택');
  const epGoal=(busyRun&&st.target_episodes!=null)?String(st.target_episodes):($('lp-episodes')?.value?.trim()||(c&&c.num_episodes!=null?String(c.num_episodes):'기본'));
  const epRaw=$('lp-ep-time')?.value?.trim()||(c&&c.episode_time_s!=null?String(c.episode_time_s):'');
  const rstRaw=$('lp-reset-time')?.value?.trim()||(c&&c.reset_time_s!=null?String(c.reset_time_s):'');
  const epTime=epRaw?(epRaw+'초'):'기본';
  const rstTime=rstRaw?(rstRaw+'초'):'기본';
  if($('sb-param-config'))$('sb-param-config').textContent=cfg;
  if($('sb-param-caps'))$('sb-param-caps').textContent=cap;
  if($('sb-param-episodes'))$('sb-param-episodes').textContent=epGoal+'회';
  if($('sb-param-timing'))$('sb-param-timing').textContent='회차 길이 '+epTime+' · 사이 대기 '+rstTime;
}

function updateTaskSummary(){
  const t=f.task.value;
  const cards=choices&&choices.task_cards?choices.task_cards:{};
  const c=t?cards[t]:null;
  const errEl=$('task-error');
  const invalidList=Object.entries(cards).filter(([,v])=>v&&v.valid===false);
  if(t&&c&&c.valid===false){
    errEl.textContent='과제 카드 검증 실패 ('+t+'): '+(c.error||'형식 오류');
    errEl.hidden=false;
  }else if(invalidList.length){
    errEl.textContent='선택 불가 과제 카드: '+invalidList.map(([k,v])=>k+' ('+(v.error||'형식 오류')+')').join(' / ');
    errEl.hidden=false;
  }else{
    errEl.hidden=true;
    errEl.textContent='';
  }
  const ok=c&&c.valid!==false;
  const sw=Boolean(window.zoneSwapped);
  const rawTask=ok&&c.single_task?String(c.single_task):'미확인';
  $('tc-single').textContent=(sw&&ok&&c.single_task&&typeof window.flipTaskLabel==='function')?(window.flipTaskLabel(rawTask)+' [스왑]'):rawTask;
  $('tc-raw').textContent=c&&c.raw?String(c.raw):(t?'내용 없음':'카드를 선택하세요.');
  const origTxt=ok&&c.origin?describeSpot(c.origin):'미확인';
  const tgt=ok&&(c.target_slot||c.target_layer)?describeSpot([c.target_slot,c.target_layer].filter(Boolean).join('-')):'미확인';
  $('tc-origin').textContent=sw?tgt:origTxt;
  $('tc-target').textContent=sw?origTxt:tgt;
  const q=typeof epQuota==='function'?epQuota(c):null;
  if(q){
    $('tc-episodes').innerHTML=(q.rem===0?'목표 '+q.goal+'회 달성 (현재 '+q.done+'회)':'목표 '+q.goal+'회 중 현재 '+q.done+'회 수집 · 앞으로 '+q.rem+'회 남음')+'<div class="prog-track"><div class="prog-fill" style="width:'+q.pct+'%;background:'+(q.rem===0?'var(--good)':'var(--pri)')+'"></div></div>';
  }else{
    $('tc-episodes').textContent=ok&&c.num_episodes!=null?c.num_episodes+'회':'미확인';
  }
  const times=[];
  if(ok&&c.episode_time_s!=null)times.push('회차 '+c.episode_time_s+'초');
  if(ok&&c.reset_time_s!=null)times.push('초기화 '+c.reset_time_s+'초');
  $('tc-time').textContent=times.length?times.join(' / '):'미확인';
  $('tc-photo').textContent=ok&&c.cameras_note?String(c.cameras_note):'미확인 (상태 응답에 없음)';
  renderCamGuide();
}

