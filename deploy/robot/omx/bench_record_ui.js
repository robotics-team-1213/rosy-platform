const H={'Content-Type':'application/json','X-Bench':'1'};
const $=id=>document.getElementById(id);
const f=$('bench-form');
const STATUS_MAP={
  idle:['대기','good'],
  handing_over:['시작 중 (인계)','live'],
  homing:['홈 이동 중','live'],
  recording:['녹화 중','live'],
  restoring:['복구 중','warn'],
  sealing:['봉인 중','live'],
  sealed:['완료 (봉인됨)','good'],
  stopped_not_sealed:['원본만 보관 (중단됨)','warn'],
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

function setReqError(msg){
  const el=$('request-error');
  if(!msg){el.hidden=true;el.textContent='';return;}
  el.textContent='요청 오류: '+msg;
  el.hidden=false;
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

const ROW_LABELS=['왼쪽','가운데','오른쪽'];
const LAYER_LABELS=['1층(바닥)','2층(중간)','3층(맨 위)'];

function describeSpot(code){
  if(!code)return '미확인';
  const s=String(code);
  if(s==='belt')return '벨트 인출단 (Arm A/B 집는 곳 · belt)';
  if(s==='belt-in'||s==='belt-s')return '벨트 공급단 (Arm S 놓는 곳 · belt-in)';
  if(s==='pinky'||s.startsWith('pinky-'))return '핑키 로봇 ('+s+')';
  let m=s.match(/^ship-h(\d)r(\d)-l(\d)$/);
  if(m){
    const r=Number(m[2]), l=Number(m[3]);
    const rTxt=ROW_LABELS[r]||(r+'번 칸');
    const lTxt=LAYER_LABELS[l]||((l+1)+'층');
    return '중앙 선박 h'+m[1]+' · '+rTxt+' 칸 · '+lTxt+' ['+s+']';
  }
  m=s.match(/^tmp-([ab])-(\d+)(?:-l(\d+))?$/);
  if(m){
    const side=m[1]==='a'?'왼쪽':'오른쪽';
    const lTxt=m[3]?(LAYER_LABELS[Number(m[3])]||((Number(m[3])+1)+'층')):'';
    return '임시대 '+m[1].toUpperCase()+'('+side+') · '+m[2]+'번 칸'+(lTxt?' · '+lTxt:'');
  }
  return s;
}

function pickTaskBySpot(spot){
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
  const noteEl=$('cam-map-note');
  if(!pool.length){
    if($('task-search')){$('task-search').value=spot;renderTaskListbox();}
    if(noteEl)noteEl.textContent=spot+' 구역에 해당하는 작업 카드가 없습니다.';
    return;
  }
  const curIdx=pool.indexOf(f.task.value);
  const nextTask=pool[(curIdx+1)%pool.length];
  if($('task-search'))$('task-search').value='';
  selectTask(nextTask);
  const selOpt=$('task-listbox')?.querySelector('[aria-selected="true"]');
  if(selOpt)selOpt.scrollIntoView({block:'nearest'});
  if(noteEl)noteEl.textContent=spot+' 선택 -> 작업 카드 '+nextTask+' 자동 연결됨 ('+pool.length+'개 중 '+(pool.indexOf(nextTask)+1)+'번째)';
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
  let html='<div style="display:flex;flex-direction:column;gap:8px">';
  html+='<div class="guide-head"><div><b>집을 곳:</b> <span style="color:#58a6ff">'+org+'</span> &rarr; <b>놓을 곳:</b> <span style="color:#3dd68c">'+tgt+'</span></div><button type="button" id="swap-zones-btn" class="btn-tool" title="집을 곳과 놓을 곳을 서로 바꿉니다 [Alt+W]" aria-pressed="'+(swapped?'true':'false')+'">⇄ 집기↔놓기 스왑'+(swapped?' (적용됨)':'')+'</button></div>';
  html+='<div id="cam-map-note" class="quiet" style="font-size:.82rem">작업 카드 선택용 배치도입니다(로봇 좌표 제어 아님 · 리더 팔로 직접 조작). 파랑 = 집을 곳 · 초록 = 놓을 곳.</div>';
  html+='<svg viewBox="0 0 360 122" style="width:100%;height:auto;background:#111113;border:1px solid var(--bd);border-radius:6px" aria-label="작업대 구역 배치도">';
  html+='<g class="map-spot" data-spot="tmp-a" role="button" tabindex="0"><rect x="8" y="8" width="84" height="54" rx="6" fill="'+zoneBg('tmp-a')+'" stroke="'+zoneCol('tmp-a')+'" stroke-width="2"/><text x="50" y="31" fill="#eeeeef" font-size="11" text-anchor="middle">임시대 A (좌)</text><text x="50" y="47" fill="#b0b4ba" font-size="9" text-anchor="middle">tmp-a</text></g>';
  html+='<g class="map-spot" data-spot="ship-" role="button" tabindex="0"><rect x="108" y="8" width="144" height="54" rx="6" fill="'+zoneBg('ship-')+'" stroke="'+zoneCol('ship-')+'" stroke-width="2"/><text x="180" y="31" fill="#eeeeef" font-size="11" text-anchor="middle">중앙 선박 h1</text><text x="180" y="47" fill="#b0b4ba" font-size="9" text-anchor="middle">3칸 × 3층 (바닥~3층)</text></g>';
  html+='<g class="map-spot" data-spot="tmp-b" role="button" tabindex="0"><rect x="268" y="8" width="84" height="54" rx="6" fill="'+zoneBg('tmp-b')+'" stroke="'+zoneCol('tmp-b')+'" stroke-width="2"/><text x="310" y="31" fill="#eeeeef" font-size="11" text-anchor="middle">임시대 B (우)</text><text x="310" y="47" fill="#b0b4ba" font-size="9" text-anchor="middle">tmp-b</text></g>';
  html+='<g class="map-spot" data-spot="pinky" role="button" tabindex="0"><rect x="8" y="72" width="96" height="40" rx="6" fill="'+zoneBg('pinky')+'" stroke="'+zoneCol('pinky')+'" stroke-width="2"/><text x="56" y="89" fill="#eeeeef" font-size="10" text-anchor="middle">핑키 로봇</text><text x="56" y="103" fill="#b0b4ba" font-size="8.5" text-anchor="middle">pinky (앞쪽)</text></g>';
  html+='<g class="map-spot" data-spot="belt-in" role="button" tabindex="0"><rect x="114" y="72" width="110" height="40" rx="6" fill="'+zoneBg('belt-in')+'" stroke="'+zoneCol('belt-in')+'" stroke-width="2"/><text x="169" y="89" fill="#eeeeef" font-size="10" text-anchor="middle">벨트 공급단 (S)</text><text x="169" y="103" fill="#b0b4ba" font-size="8.5" text-anchor="middle">belt-in (놓는 곳)</text></g>';
  html+='<text x="232" y="96" fill="#b0b4ba" font-size="12" text-anchor="middle">&rarr;</text>';
  html+='<g class="map-spot" data-spot="belt" role="button" tabindex="0"><rect x="240" y="72" width="112" height="40" rx="6" fill="'+zoneBg('belt')+'" stroke="'+zoneCol('belt')+'" stroke-width="2"/><text x="296" y="89" fill="#eeeeef" font-size="10" text-anchor="middle">벨트 인출단 (A/B)</text><text x="296" y="103" fill="#b0b4ba" font-size="8.5" text-anchor="middle">belt (집는 곳)</text></g>';
  html+='</svg>';
  if(okCard&&c.single_task)html+='<div class="quiet">'+String(c.single_task).replace(/</g,'&lt;')+'</div>';
  if(okCard&&c.cameras_note)html+='<div class="quiet">카메라 기준: '+String(c.cameras_note).replace(/</g,'&lt;')+'</div>';
  const sm=tStr.match(/^ship-h1r(\d)-l(\d)$/);
  const tr=sm?Number(sm[1]):-1, tl=sm?Number(sm[2]):-1;
  html+='<div style="display:grid;grid-template-columns:68px repeat(3,minmax(0,1fr));gap:4px;align-items:center" aria-label="선박 층·위치 선택">';
  html+='<div></div>';
  for(const row of [0,1,2]){
    html+='<div class="quiet" style="text-align:center;font-size:.75rem;font-weight:700">'+ROW_LABELS[row]+' (r'+row+')</div>';
  }
  for(const lv of [2,1,0]){
    html+='<div class="quiet" style="font-size:.75rem;font-weight:700;text-align:right;padding-right:4px">'+LAYER_LABELS[lv]+'</div>';
    for(const row of [0,1,2]){
      const hit=(row===tr&&lv===tl);
      const spot='ship-h1r'+row+'-l'+lv;
      html+='<button type="button" class="slot-btn'+(hit?' active':'')+'" aria-pressed="'+(hit?'true':'false')+'" data-spot="'+spot+'" style="display:flex;flex-direction:column;line-height:1.15;padding:5px 4px"><span>'+(lv+1)+'층·'+ROW_LABELS[row]+(hit?' ★':'')+'</span><span class="mono" style="font-size:.68rem;opacity:.8">r'+row+'·l'+lv+'</span></button>';
    }
  }
  html+='</div>';
  box.innerHTML=html+'</div>';
  box.hidden=false;
  for(const el of box.querySelectorAll('[data-spot]')){
    el.addEventListener('click',()=>pickTaskBySpot(el.dataset.spot));
    el.addEventListener('keydown',(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pickTaskBySpot(el.dataset.spot);}});
  }
  const swBtn=$('swap-zones-btn');
  if(swBtn){
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

function applyArmRules(autoPickSingle){
  if(!choices)return;
  const hasArms=armContractValid();
  const arm=f.arm.value;
  if(typeof updateCameraRecordingMask==='function')updateCameraRecordingMask();
  if(typeof syncReplayUI==='function')syncReplayUI();
  const inst=hasArms?choices.instances[arm]:null;
  const bindings=hasArms&&inst?armVerifiedBindings(arm):null;
  const issues=[];

  if(!hasArms){
    $('arm-note').textContent='서버가 팔별 계약(arms/instances)을 제공하지 않아 시작을 차단합니다.';
    issues.push('팔별 계약 누락');
  }else if(!inst){
    $('arm-note').textContent=arm+'의 로봇 프로필이 준비 폴더에 없어 시작할 수 없습니다.';
    issues.push(arm+' 로봇 프로필 누락');
  }else if(!bindings){
    $('arm-note').textContent=arm+' ('+inst+') — 서버가 팔별 검증 조합(arm_bindings)을 제공하지 않아 시작을 차단합니다.';
    issues.push('팔별 검증 조합(arm_bindings) 미제공');
  }else{
    $('arm-note').textContent=arm+' ('+inst+') — 서버가 검증한 조합만 선택할 수 있습니다.';
  }

  const allowedCfg=bindings?new Set(bindings.configs):new Set();
  const allowedCaps=bindings?new Set(bindings.caps):new Set();
  const allowedCal=bindings?new Set(bindings.calibrations):new Set();

  for(const o of f.config.options){
    if(!o.value)continue;
    const ok=allowedCfg.has(o.value);
    o.disabled=!ok;
    o.textContent=o.value+(ok?'':' (허용 안 됨)');
  }
  for(const o of f.caps.options){
    if(!o.value)continue;
    const ok=allowedCaps.has(o.value);
    o.disabled=!ok;
    o.textContent=o.value+(ok?'':' (허용 안 됨)');
  }
  for(const row of document.querySelectorAll('#cal-robot-list .check-row, #cal-leader-list .check-row')){
    const cb=row.querySelector('input');
    const ok=allowedCal.has(cb.value);
    cb.disabled=!ok;
    row.hidden=!ok;
    if(!ok)cb.checked=false;
  }

  if(autoPickSingle&&bindings){
    for(const sel of [f.config,f.caps]){
      const valid=[...sel.options].filter(o=>o.value&&!o.disabled);
      if(valid.length===1)sel.value=valid[0].value;
      else if(sel.selectedOptions[0]?.disabled)sel.value='';
    }
    const robotCbs=[...$('cal-robot-list').querySelectorAll('input:not(:disabled)')];
    const leaderCbs=[...$('cal-leader-list').querySelectorAll('input:not(:disabled)')];
    const needRobot=arm==='arm_ab'?2:1;
    if(!robotCbs.some(c=>c.checked)){
      robotCbs.slice(0,needRobot).forEach(c=>{c.checked=true;});
    }
    if(!leaderCbs.some(c=>c.checked)&&leaderCbs.length){
      leaderCbs[0].checked=true;
    }
  }else{
    if(f.config.selectedOptions[0]?.disabled)f.config.value='';
    if(f.caps.selectedOptions[0]?.disabled)f.caps.value='';
  }

  if(bindings){
    if(![...f.config.options].some(o=>o.value&&!o.disabled))issues.push(arm+'에 검증된 녹화 설정 없음');
    if(![...f.caps.options].some(o=>o.value&&!o.disabled))issues.push(arm+'에 검증된 caps 파일 없음');
    if(![...$('cal-robot-list').querySelectorAll('input:not(:disabled)')].length)issues.push(arm+'에 검증된 팔로워 보정 없음');
  }
  const m=choices.config_meta?choices.config_meta[f.config.value]:null;
  if(m&&Array.isArray(m.camera_issues)&&m.camera_issues.length){
    issues.push('카메라 설정 점검: '+m.camera_issues.join(', '));
  }
  if(m&&Array.isArray(m.cameras)&&m.cameras.includes('top')&&lastCamState&&(!lastCamState.top||lastCamState.top.fresh===false)){
    issues.push('주의: 선택 설정의 top 카메라가 현재 8767에서 미수신 상태입니다');
  }
  renderCapsEditor();
  if(typeof updateCameraRecordingMask==='function')updateCameraRecordingMask();
  const box=$('binding-issues');
  if(issues.length){box.textContent='조치 필요: '+issues.join(' / ');box.hidden=false;}
  else{box.hidden=true;box.textContent='';}
}

function validateStart(){
  const reasons=[];
  if(!statusLoaded)reasons.push('현재 상태를 아직 확인하지 못했습니다');
  if(lastStatus&&BUSY.has(lastStatus.status))reasons.push('세션이 이미 진행 중입니다');
  if(typeof poseInFlight!=='undefined'&&poseInFlight)reasons.push('포즈 작업이 진행 중입니다');
  if(!armContractValid()||!f.arm.value||!choices.instances[f.arm.value])reasons.push('팔 및 로봇 프로필 확인 필요');
  else if(!armVerifiedBindings(f.arm.value))reasons.push('서버 팔별 검증 조합(arm_bindings) 필요');
  const t=f.task.value;
  if(t&&choices?.task_cards?.[t]?.valid===false)reasons.push('선택한 과제 카드 검증 실패');
  if(!NAME_RE.test(f.name.value.trim()))reasons.push('수집명 형식 확인(소문자·숫자·-, 3~64자)');
  if(!NAME_RE.test(f.rig_revision.value.trim()))reasons.push('배치 리비전 형식 확인');
  if(!f.config.value||f.config.selectedOptions[0]?.disabled)reasons.push('녹화 설정 선택');
  if(!f.caps.value||f.caps.selectedOptions[0]?.disabled)reasons.push('caps 선택');
  const robotCals=[...$('cal-robot-list').querySelectorAll('input:checked:not(:disabled)')];
  const leaderCals=[...$('cal-leader-list').querySelectorAll('input:checked:not(:disabled)')];
  const calCnt=$('cal-summary-count');
  if(calCnt)calCnt.textContent=(robotCals.length+leaderCals.length)+'개';
  const needRobot=f.arm.value==='arm_ab'?2:1;
  if(robotCals.length<needRobot)reasons.push('팔로워 보정 '+needRobot+'개 선택');
  if(leaderCals.length<needRobot)reasons.push('리더 보정 '+needRobot+'개 선택');
  if(!f.at_bench.checked)reasons.push('작업대 현장 확인 체크');

  const locks=Array.isArray(lastStatus?.active_locks)?lastStatus.active_locks:[];
  if(locks.length){
    reasons.push('다른 OMX 세션 락 점유 중 ('+locks.map(h=>h.lock).join(', ')+')');
  }
  const biEl=$('binding-issues');
  if(biEl&&!biEl.hidden&&biEl.textContent.trim()){
    reasons.push(biEl.textContent.trim());
  }
  const lbox=$('lock-conflict-box'), llist=$('lock-conflict-list');
  if(lbox&&llist){
    const lockSig=JSON.stringify(locks)+'|'+Boolean(f.at_bench.checked);
    if(locks.length){
      if(llist.dataset.sig!==lockSig){
        llist.dataset.sig=lockSig;
        const byPid=new Map();
        for(const h of locks){
          const key=h.pid?String(h.pid):h.lock;
          if(!byPid.has(key))byPid.set(key,{pid:h.pid,locks:[],cmd:h.cmd||''});
          byPid.get(key).locks.push(h.lock);
        }
        $('lock-conflict-text').textContent='공용 카메라·옵저버 인계를 위해 아래 점유 세션이 끝나야 시작할 수 있습니다. 필요한 세션만 골라 종료할 수 있습니다:';
        llist.innerHTML='';
        for(const item of byPid.values()){
          const row=document.createElement('div');
          row.style.cssText='display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;padding:6px 8px;background:var(--ground-deep);border:1px solid var(--bd);border-radius:6px';
          const info=document.createElement('span');info.className='mono';info.style.fontSize='.82rem';
          info.textContent=item.locks.join(', ')+(item.pid?' (PID '+item.pid+')':'');
          const btn=document.createElement('button');btn.type='button';btn.className='btn-stop';
          btn.style.cssText='min-height:36px;padding:0 12px;font-size:.84rem';
          btn.textContent=item.pid?('PID '+item.pid+'만 정상 종료'):'PID 미확인';
          btn.disabled=!f.at_bench.checked||!item.pid;
          if(item.pid){
            btn.addEventListener('click',async()=>{
              btn.disabled=true;
              try{setReqError('');renderStatus(await api('/release_lock',{at_bench:f.at_bench.checked,pid:item.pid}));}
              catch(err){setReqError(err.message);btn.disabled=false;}
            });
          }
          row.append(info,btn);llist.append(row);
        }
      }
      lbox.hidden=false;
    }else{
      llist.dataset.sig='';
      lbox.hidden=true;llist.innerHTML='';
    }
  }

  window.benchStartReady=!startInFlight&&reasons.length===0;
  const busyNow=Boolean(lastStatus&&BUSY.has(lastStatus.status))||poseInFlight;
  const armOk=Boolean(f.arm.value&&armContractValid()&&choices.instances[f.arm.value]&&armVerifiedBindings(f.arm.value));
  const armInfo=lastArmsStatus&&f.arm.value?lastArmsStatus[f.arm.value]:null;
  const hb=$('hdr-home-btn');
  if(hb){
    hb.disabled=!f.at_bench.checked||!armOk||busyNow||locks.length>0;
    if(!poseInFlight)hb.textContent=(armInfo&&armInfo.has_leader_pose)?'홈 이동 (팔로워+리더)':'홈 이동';
  }
  const sb=$('save-init-pose-btn');
  if(sb)sb.disabled=!f.at_bench.checked||!armOk||busyNow||locks.length>0;
  const lb=$('save-leader-pose-btn');
  if(lb)lb.disabled=!f.at_bench.checked||!armOk||busyNow||locks.length>0;
  if($('ev-extra')&&armInfo){
    $('ev-extra').textContent='리더포즈: '+(armInfo.has_leader_pose?'저장됨':'미저장')+' / 팔로워포즈: '+(armInfo.has_initial_pose?'저장됨':'미저장');
  }
  if(poseFeedbackMsg&&Date.now()<poseFeedbackUntil){
    $('start-guard-note').textContent=poseFeedbackMsg;
  }else{
    const poseHint=(armInfo&&!armInfo.has_leader_pose)?' (리더 포즈 미저장 — 리더 포즈 저장 필요)':'';
    $('start-guard-note').textContent=(reasons.length?'시작 대기 조건: '+reasons.join(' · '):'모든 확인이 완료되었습니다. 녹화 시작 시 리더(토크 OFF)를 움직이면 팔로워가 실시간 연동됩니다.')+poseHint;
  }

  const canStop=Boolean(lastStatus&&(lastStatus.status==='handing_over'||lastStatus.status==='recording'));
  $('stop-note').hidden=!canStop;
  if(typeof syncHeaderAndSlimBar==='function')syncHeaderAndSlimBar();

  const r1=Boolean(f.arm.value&&NAME_RE.test(f.name.value.trim())&&NAME_RE.test(f.rig_revision.value.trim()));
  const r2=Boolean(f.config.value&&f.caps.value&&robotCals.length>=needRobot&&leaderCals.length>0);
  const r3=Boolean(f.at_bench.checked&&reasons.length===0);
  const setRail=(id,ok,txt)=>{const el=$(id);if(!el)return;el.textContent=ok?'완료':txt;el.className='rail-step'+(ok?' ok':'');};
  setRail('rail-1',r1,'입력');setRail('rail-2',r2,'선택');setRail('rail-3',r3,'대기');
  return reasons.length===0;
}

function renderStatus(st){
  if(!st||typeof st!=='object'||typeof st.status!=='string'||!st.status){
    throw new Error('상태 응답에 status 필드가 없습니다');
  }
  const prevCode=lastStatus?lastStatus.status:'';
  lastStatus=st;
  statusLoaded=true;
  const code=st.status;
  if(BUSY.has(prevCode)&&(code==='sealed'||code==='stopped_not_sealed')){
    f.at_bench.checked=false;
  }
  const [label,tone]=STATUS_MAP[code]||[code,'warn'];
  const badge=$('top-badge');
  badge.textContent=label;
  badge.dataset.tone=tone;

  const key=sessionKey(st);
  const metaMatch=Boolean(lastStartMeta&&key&&lastStartMeta.key===key);
  const activeName=st.name||(metaMatch?lastStartMeta.name:'');
  const activeArm=st.arm||(metaMatch?lastStartMeta.arm:'');
  const activeTask=st.task||(metaMatch?lastStartMeta.task:'');

  const topParts=[];
  if(activeArm)topParts.push(activeArm);
  if(activeTask)topParts.push(activeTask);
  if(activeName)topParts.push(activeName);
  $('top-summary').textContent=topParts.length?topParts.join(' · '):(code==='idle'?'대기 중 (회차 없음)':label);
  $('top-checked').textContent='마지막 확인: '+nowText();

  $('ev-status').textContent=label;
  $('ev-name').textContent=st.name||'미확인';
  $('ev-arm').textContent=activeArm||'미확인';
  $('ev-task').textContent=activeTask||'미확인';
  $('ev-folder').textContent=st.folder||'미확인';

  const resEl=$('ev-restore');
  const resErr=Array.isArray(st.restore_errors)?st.restore_errors:[];
  const logTail=String(st.log_tail||'').trim();
  if(resErr.length){
    resEl.textContent='복구 오류: '+resErr.join(', ')+(st.error?' ('+st.error+')':'');
    resEl.hidden=false;
  }else if(st.error){
    resEl.textContent='세션 오류: '+st.error;
    resEl.hidden=false;
  }else if(code==='unsafe_or_failed'||code==='failed'||code==='seal_failed'){
    if(logTail.includes('session.lock')){
      resEl.textContent='실패 원인: 다른 OMX 세션(예: cell_calibrate 또는 다른 팔 작업)이 session.lock을 점유 중입니다. 진행 중인 세션이 끝난 뒤 다시 시작하세요.';
    }else if(logTail){
      resEl.textContent='실패 로그: '+logTail;
    }else{
      resEl.textContent='실패 (종료 코드: '+(st.exit_code!=null?st.exit_code:'미확인')+')';
    }
    resEl.hidden=false;
  }else{
    resEl.hidden=true;
  }

  const manEl=$('ev-manual');
  if(st.manual_attention){
    manEl.textContent='현장 수동 확인 필요(manual_attention): 팔 상태와 안전 종료 여부를 확인하세요.';
    manEl.hidden=false;
  }else{
    manEl.hidden=true;
  }

  const sealEl=$('ev-seal');
  const postAct=$('post-actions');
  if(code==='sealed'){
    sealEl.textContent='봉인 완료: '+[activeArm,activeTask,st.name,st.folder].filter(Boolean).join(' · ')+' — 아래 버튼으로 다음 회차를 이어서 찍거나 모델 PC로 반입하세요.';
    sealEl.className='alert good';
    sealEl.hidden=false;
    postAct.hidden=false;
  }else if(code==='stopped_not_sealed'){
    sealEl.textContent=st.safe_end===true
      ?'중단됨 · 안전 종료(safe_end) 확인 후 자동 봉인 없이 원본 폴더에 보관했습니다.'
      :'중단됨 · 자동 봉인 안 함 (safe_end 미확인 — 원본만 보관)';
    sealEl.className='alert warn';
    sealEl.hidden=false;
    postAct.hidden=false;
  }else{
    sealEl.hidden=true;
    sealEl.className='alert good';
    postAct.hidden=true;
  }
  const logEl=$('ev-log-tail');
  if(st.log_tail){logEl.textContent=st.log_tail;logEl.hidden=false;}
  else{logEl.hidden=true;logEl.textContent='';}
  renderRecent(st.recent_sessions);
  if(typeof renderLeRobotPanel==='function')renderLeRobotPanel(st);
  const scSig=JSON.stringify(st.scenario_counts||{});
  if($('task-listbox')&&$('task-listbox').dataset.scSig!==scSig){
    $('task-listbox').dataset.scSig=scSig;
    renderTaskListbox();
    updateTaskSummary();
  }
  validateStart();
}

function renderRecent(rows){
  const ul=$('recent-list'), empty=$('recent-empty');
  if(!Array.isArray(rows)||!rows.length){ul.innerHTML='';empty.hidden=false;return;}
  empty.hidden=true;
  ul.innerHTML='';
  for(const r of rows){
    const li=document.createElement('li');li.className='sess-item';
    const left=document.createElement('span');left.className='mono';left.textContent=r.folder||'';
    const right=document.createElement('span');right.className='quiet';
    const sealText=r.sealed?'봉인됨':(r.interrupted?'중단됨(원본)':(r.safe_end===true?'안전종료':'미봉인'));
    const hfText=r.hf_uploaded?'HF 업로드됨':'HF 미업로드 (모델 PC 검수 후 업로드)';
    right.textContent=sealText+' · '+hfText;
    li.append(left,right);
    ul.append(li);
  }
}

const ARM_PREVIEW_CAMS={
  arm_a:new Set(['top','side','arm_a_wrist']),
  arm_b:new Set(['top','side','arm_b_wrist']),
  arm_ab:new Set(['top','side','arm_a_wrist','arm_b_wrist']),
  arm_s:new Set(['arm_s_top','arm_s_wrist']),
};
function renderTelemetry(d){
  const tr=$('tel-track'), lat=$('tel-lat'), grid=$('tel-grid'), note=$('tel-note');
  if(!tr||!lat||!grid)return;
  if(!d||!d.active){
    tr.textContent='대기';tr.dataset.tone='warn';lat.textContent='-- ms';lat.dataset.tone='warn';
    grid.hidden=true;if(note)note.hidden=false;return;
  }
  const hasFault=Boolean(d.fault)||(Array.isArray(d.motors)&&d.motors.some(m=>m.fault));
  tr.textContent=hasFault?'차단':(d.tracking?'추적 중':'정렬 중');
  tr.dataset.tone=hasFault?'crit':(d.tracking?'good':'live');
  const ms=d.loop_latency_ms;
  lat.textContent=(typeof ms==='number')?(ms.toFixed(1)+' ms'):'-- ms';
  lat.dataset.tone=(typeof ms==='number'&&ms>40)?'warn':'good';
  const rows=Array.isArray(d.motors)?d.motors:[];
  if(!rows.length){grid.hidden=true;return;}
  if(note)note.hidden=true;
  grid.hidden=false;
  const deg=v=>((Number(v)||0)*360/4096).toFixed(1)+'°';
  let h='<div class="tel-hd">관절</div><div class="tel-hd">리더</div><div class="tel-hd">팔로워</div><div class="tel-hd">Δ°</div>';
  for(const m of rows){
    const lRaw=m.leader_raw, fRaw=m.present_raw;
    const dl=(lRaw!=null&&fRaw!=null)?Math.abs((lRaw-fRaw)*360/4096):Math.abs(Number(m.error_deg)||0);
    const col=dl>=5?'var(--crit)':(dl>=3?'var(--warn)':'var(--good)');
    h+='<div>'+String(m.name||m.id||'')+'</div><div>'+(lRaw!=null?deg(lRaw):'--')+'</div><div>'+(fRaw!=null?deg(fRaw):'--')+'</div><div style="color:'+col+'">'+dl.toFixed(2)+'°</div>';
  }
  grid.innerHTML=h;
}
async function pollTelemetry(){
  try{renderTelemetry(await api('/api/telemetry'));}catch(_){}
}
setInterval(pollTelemetry,400);
