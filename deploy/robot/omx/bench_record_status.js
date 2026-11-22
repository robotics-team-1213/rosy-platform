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
  // the preview service names arm_s's top camera arm_s_top; a missing preview is a warning, not a reason to refuse
  // a start (the recorder opens the device itself): 2026-11-21 this line blocked every arm_s start from the page
  const warns=[];
  const topName=arm==='arm_s'?'arm_s_top':'top';
  if(m&&Array.isArray(m.cameras)&&m.cameras.includes('top')&&lastCamState&&(!lastCamState[topName]||lastCamState[topName].fresh===false)){
    warns.push('주의: 선택 설정의 top 카메라('+topName+')가 현재 8767 미리보기에서 미수신 상태입니다');
  }
  if(typeof renderCapsEditor==='function')renderCapsEditor();
  if(typeof renderParamsPanel==='function')renderParamsPanel();
  if(typeof updateCameraRecordingMask==='function')updateCameraRecordingMask();
  if(typeof window.syncPrimaryCamForArm==='function')window.syncPrimaryCamForArm(arm);
  const box=$('binding-issues');
  box.dataset.blocking=issues.length?'1':'0';
  box.className=issues.length?'alert warn':'alert';
  if(issues.length||warns.length){box.textContent=(issues.length?'조치 필요: '+issues.join(' / '):'')+(issues.length&&warns.length?' / ':'')+warns.join(' / ');box.hidden=false;}
  else{box.hidden=true;box.textContent='';}
}

function validateStart(){
  const reasons=[];
  if(!statusLoaded)reasons.push('현재 상태를 아직 확인하지 못했습니다');
  if(benchSessionActive())reasons.push('세션이 이미 진행 중입니다');
  if(typeof poseInFlight!=='undefined'&&poseInFlight)reasons.push('포즈 작업이 진행 중입니다');
  if(cameraRestartInFlight)reasons.push('카메라를 재시작하는 중입니다');
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

  const locks=Array.isArray(lastStatus?.active_locks)?lastStatus.active_locks:[];
  if(locks.length){
    reasons.push('다른 OMX 세션 락 점유 중 ('+locks.map(h=>h.lock).join(', ')+')');
  }
  const biEl=$('binding-issues');
  const biText=biEl&&!biEl.hidden?biEl.textContent.trim():'';
  if(biEl&&biEl.dataset.blocking!=='0'&&biText){
    reasons.push(biText);
  }
  const warnText=(biEl&&biEl.dataset.blocking==='0'&&biText)?biText:'';
  const lbox=$('lock-conflict-box'), llist=$('lock-conflict-list');
  if(lbox&&llist){
    const lockSig=JSON.stringify(locks);
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
          btn.disabled=!item.pid;
          if(item.pid){
            btn.addEventListener('click',async()=>{
              btn.disabled=true;
              try{setReqError('');renderStatus(await api('/release_lock',{pid:item.pid}));}
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

  window.benchStartReady=!startInFlight&&!stopInFlight&&reasons.length===0;
  const busyNow=benchSessionActive()||poseInFlight||startInFlight||cameraRestartInFlight;
  const armOk=Boolean(f.arm.value&&armContractValid()&&choices.instances[f.arm.value]&&armVerifiedBindings(f.arm.value));
  const armInfo=lastArmsStatus&&f.arm.value?lastArmsStatus[f.arm.value]:null;
  const hil=$('home-include-leader');
  const hasLP=Boolean(armInfo&&armInfo.has_leader_pose);
  const canLeaderAlign=Boolean(armOk&&armInfo&&(armInfo.leader_connected===true||(armInfo.leader_connected!==false&&hasLP)));
  if(hil){hil.disabled=!canLeaderAlign||busyNow;}
  const hb=$('hdr-home-btn');
  if(hb){
    hb.disabled=!armOk||busyNow||locks.length>0;
    if(!poseInFlight){
      const lbl=hb.querySelector('.btn-lbl');
      const txt=(canLeaderAlign&&hil?.checked)?'홈 이동 (팔로워+리더)':'홈 이동';
      if(lbl)lbl.textContent=txt;else hb.textContent=txt;
    }
  }
  const sb=$('save-init-pose-btn');
  if(sb)sb.disabled=!armOk||busyNow||locks.length>0;
  const lb=$('save-leader-pose-btn');
  if(lb)lb.disabled=!armOk||busyNow||locks.length>0;
  if($('ev-extra')&&armInfo){
    $('ev-extra').textContent='리더포즈: '+(armInfo.has_leader_pose?'저장됨':'미저장')+' / 팔로워포즈: '+(armInfo.has_initial_pose?'저장됨':'미저장');
  }
  if(poseFeedbackMsg&&Date.now()<poseFeedbackUntil){
    $('start-guard-note').textContent=poseFeedbackMsg;
  }else{
    const poseHint=(armInfo&&armInfo.leader_connected!==true&&!armInfo.has_leader_pose)?' (리더 포즈 미저장 — 리더 포즈 저장 필요)':'';
    $('start-guard-note').textContent=(reasons.length?'시작 대기 조건: '+reasons.join(' · '):'녹화 시작 가능 상태입니다.')+poseHint;
  }
  if(reasons.length&&!busyNow){
    setNotice('start-reasons','warn','시작 대기: '+reasons.join(' · '));
  }else if(warnText&&!busyNow){
    setNotice('start-reasons','muted',warnText);
  }else{
    clearNotice('start-reasons');
  }

  const canStop=benchSessionActive();
  $('stop-note').hidden=!canStop;

  const r1=Boolean(f.arm.value&&NAME_RE.test(f.name.value.trim())&&NAME_RE.test(f.rig_revision.value.trim()));
  const r2=Boolean(f.config.value&&f.caps.value&&robotCals.length>=needRobot&&leaderCals.length>0);
  const r3=Boolean(reasons.length===0);
  const setRail=(id,ok,txt)=>{const el=$(id);if(!el)return;el.textContent=ok?'완료':txt;el.className='rail-step'+(ok?' ok':'');};
  setRail('rail-1',r1,'입력');setRail('rail-2',r2,'선택');setRail('rail-3',r3,'대기');
  if($('sum-bind-drawer')){
    $('sum-bind-drawer').textContent=(f.config.value||'설정 미선택')+' · '+(f.caps.value||'caps 미선택')+' · 보정 '+(robotCals.length+leaderCals.length)+'개';
  }
  if($('sum-pose-drawer')){
    const fP=armInfo?(armInfo.has_initial_pose?'저장됨':'미저장'):'미확인';
    const lP=armInfo?(armInfo.has_leader_pose?'저장됨':'미저장'):'미확인';
    $('sum-pose-drawer').textContent='팔로워 '+fP+' · 리더 '+lP+($('align-leader')?.checked?' · 시작 전 정렬':'');
  }
  const sfs=$('setup-fieldset');
  if(sfs)sfs.disabled=busyNow;
  const rfs=$('records-fieldset');
  if(rfs)rfs.disabled=busyNow;
  for(const b of document.querySelectorAll('#rail-arm-pills button[data-arm]'))b.disabled=busyNow;
  for(const b of document.querySelectorAll('[data-drawer-btn]'))b.disabled=busyNow&&(b.dataset.drawerBtn!=='records');
  for(const b of document.querySelectorAll('#sec-goal button,#sec-guide button'))b.disabled=busyNow;
  updateGoalSummaryRows();
  renderStatusKv();
  if(typeof syncHeaderAndSlimBar==='function')syncHeaderAndSlimBar();
  if(typeof renderArmCards==='function')renderArmCards();
  if(typeof renderParamsPanel==='function')renderParamsPanel();
  return reasons.length===0;
}

function autoHomeView(ah,code){
  if(ah&&typeof ah==='object'){
    if(ah.ok)return {text:'홈 복귀 완료',tag:'자동 홈: 완료',tone:'good'};
    if(ah.cancelled)return {text:ah.message||'자동 홈 취소됨',tag:'자동 홈: 취소',tone:'warn'};
    if(ah.skipped)return {text:'자동 홈 생략 ('+(ah.reason||ah.message||'가드 중단')+') — 안전 확인 후 "지금 홈 포즈" 클릭',tag:'자동 홈: 생략',tone:'warn'};
    return {text:'홈 복귀 실패('+(ah.error||ah.message||'원인 미상')+')',tag:'자동 홈: 실패',tone:'crit'};
  }
  const wait=(code==='sealed'||code==='stopped_safe');
  return {text:wait?'실행 대기/미기록':'해당 없음',tag:wait?'자동 홈: 대기':'자동 홈: 해당 없음',tone:wait?'warn':''};
}

let lastActivitySig='';
let cueInit=false, prevCueStep='', prevCuePhase='', prevCueEp=null, prevCueAutoHome=false, prevCueCode='', prevCueAhFail=false, prevCueFault=false;

function renderStatus(st){
  if(!st||typeof st!=='object'||typeof st.status!=='string'||!st.status){
    throw new Error('상태 응답에 status 필드가 없습니다');
  }
  const prevCode=lastStatus?lastStatus.status:'';
  lastStatus=st;
  statusLoaded=true;
  const code=st.status;
  const [label]=STATUS_MAP[code]||[code,'warn'];
  if(benchSessionActive(st)&&st.arm&&f&&f.arm&&f.arm.value!==st.arm&&[...f.arm.options].some(o=>o.value===st.arm)){
    f.arm.value=st.arm;
    applyArmRules(false);
    if(typeof updateCameraRecordingMask==='function')updateCameraRecordingMask();
    if(typeof window.syncPrimaryCamForArm==='function')window.syncPrimaryCamForArm(st.arm);
  }
  if(st.stop_result?.message)setNotice('stop-result',st.stop_result.stopped===false?'muted':'good',st.stop_result.message);
  if(st.link_last_command&&st.link_last_command.applied===false){
    setNotice('link-cmd-rejected','warn',st.link_last_command.reason||'이전 연동 요청이 적용되지 않았습니다');
  }else{
    clearNotice('link-cmd-rejected');
  }

  const key=sessionKey(st);
  const metaMatch=Boolean(lastStartMeta&&key&&lastStartMeta.key===key);
  const activeName=st.name||(metaMatch?lastStartMeta.name:'');
  const activeArm=st.arm||(metaMatch?lastStartMeta.arm:'');
  const activeTask=st.task||(metaMatch?lastStartMeta.task:'');
  const phaseNow=resolveBenchPhase(code,lastTelemetryActive,st.phase);
  const curStep=st.prepare?.ready===true?'ready':(st.prepare?.step??st.starting_step??(st.step==='camera_restart'?'camera_restart':''));
  if(typeof setActivity==='function'){
    const sig=[code,phaseNow,curStep,st.episodes_done??'',st.stop_cause||'',st.error||''].join('|');
    if(sig!==lastActivitySig){
      lastActivitySig=sig;
      const stepTxt=curStep==='ready'?'연동됨 (녹화 대기)':curStep==='camera_restart'?'카메라 재시작 중':(STARTING_STEP_MAP[curStep]||'');
      const actTone=st.error_kind==='needs_person'||st.restore_errors?.length?'crit':STATUS_MAP[code]?.[1]||'muted';
      const detailParts=[activeArm||(f&&f.arm?f.arm.value:'')];
      if(st.episodes_done!=null&&code!=='idle')detailParts.push('에피소드 '+st.episodes_done+'회');
      if(st.error||st.stop_cause)detailParts.push(st.error||st.stop_cause);
      setActivity(stepTxt||label,curStep==='ready'?'good':actTone,detailParts.filter(Boolean).join(' · '));
    }
  }
  const ahOk=st.auto_home?.ok===true, ahFail=st.auto_home?.ok===false&&!st.auto_home?.cancelled&&!st.auto_home?.skipped;
  const isWarnCode=(code==='stopped_safe'||code==='failed'||code==='unsafe_or_failed'||code==='seal_failed');
  if(!cueInit){
    cueInit=true;
    prevCueStep=curStep;prevCuePhase=phaseNow;
    prevCueEp=Number.isInteger(st.episodes_done)?st.episodes_done:null;
    prevCueAutoHome=ahOk;prevCueCode=code;prevCueAhFail=ahFail;
  }else{
    const epInc=Number.isInteger(st.episodes_done)&&prevCueEp!=null&&st.episodes_done>prevCueEp;
    if(curStep==='ready'&&prevCueStep!=='ready'){
      if(epInc){
        if(typeof benchBeep==='function')benchBeep('saved');
        if(typeof setActivity==='function')setActivity('에피소드 '+st.episodes_done+'회 저장 완료 — Space로 다음 녹화','good',activeArm||(f&&f.arm?f.arm.value:''));
      }else if(typeof benchBeep==='function'){
        benchBeep('ready');
      }
    }else if(phaseNow==='recording'&&prevCuePhase!=='recording'){
      if(typeof benchBeep==='function')benchBeep('rec_start');
    }else if(epInc){
      if(typeof benchBeep==='function')benchBeep('saved');
    }
    if(ahOk&&!prevCueAutoHome){
      if(typeof benchBeep==='function')benchBeep('done');
      if(typeof setActivity==='function')setActivity('자동 홈 복귀 완료 — 바로 다음 수집 가능','good',activeArm||(f&&f.arm?f.arm.value:''));
    }else if(code==='sealed'&&prevCueCode!=='sealed'){
      if(typeof benchBeep==='function')benchBeep('done');
    }else if((isWarnCode&&code!==prevCueCode)||(ahFail&&!prevCueAhFail)){
      if(typeof benchBeep==='function')benchBeep('warn');
    }
    prevCueStep=curStep;prevCuePhase=phaseNow;
    prevCueEp=Number.isInteger(st.episodes_done)?st.episodes_done:prevCueEp;
    prevCueAutoHome=ahOk;prevCueCode=code;prevCueAhFail=ahFail;
  }

  $('top-checked').textContent='마지막 확인: '+nowText();

  $('ev-status').textContent=label;
  $('ev-arm').textContent=activeArm||'미확인';
  $('ev-folder').textContent=st.folder||'미확인';
  const dsRows=Array.isArray(st.lerobot_datasets)?st.lerobot_datasets:[];
  const fBase=st.folder?String(st.folder).split('/').pop():'';
  const dsHit=dsRows.find(r=>r&&(r.name===activeName||(fBase&&r.name===fBase)))||null;
  const dsEl=$('ev-dataset');
  if(dsEl){
    if(dsHit){
      const sz=typeof dsHit.size_bytes==='number'?(dsHit.size_bytes>=1048576?(dsHit.size_bytes/1048576).toFixed(1)+' MB':Math.max(1,Math.round(dsHit.size_bytes/1024))+' KB'):'';
      dsEl.textContent=dsHit.episodes+'회'+(sz?' · '+sz:'');
    }else if(st.episodes_done!=null){
      dsEl.textContent=st.episodes_done+'회';
    }else{
      dsEl.textContent='미확인';
    }
  }
  const seEl=$('ev-safe-end');
  if(seEl){
    const safeTxt=st.safe_end===true?'안전 종료 확인':(st.safe_end===false?'안전 종료 미확인':'미확인');
    const cause=(Array.isArray(st.restore_errors)&&st.restore_errors[0])||st.error||st.stop_cause||(st.interrupted?'사용자/비상 중단':(st.exit_code!=null&&st.exit_code!==0?'종료 코드 '+st.exit_code:''));
    seEl.textContent=cause?(safeTxt+' · '+cause):safeTxt;
  }
  const ahView=autoHomeView(st.auto_home,code);
  if($('ev-auto-home'))$('ev-auto-home').textContent=ahView.text;
  if($('hdr-auto-home')){$('hdr-auto-home').textContent=ahView.tag;$('hdr-auto-home').dataset.tone=ahView.tone;}

  const resEl=$('ev-restore');
  const resErr=Array.isArray(st.restore_errors)?st.restore_errors:[];
  const logTail=String(st.log_tail||'').trim();
  const errKind=st.error_kind||'';
  if(resErr.length){
    const msg=formatErrorKind('복구 오류: '+resErr.join(', ')+(st.error?' ('+st.error+')':''),errKind);
    resEl.textContent=msg;
    resEl.hidden=false;
    setNotice('status-error',errKind==='recovered'?'warn':'crit',msg,{persistent:errKind!=='recovered'});
  }else if(st.error){
    const msg=formatErrorKind('세션 오류: '+st.error,errKind);
    resEl.textContent=msg;
    resEl.hidden=false;
    setNotice('status-error',errKind==='recovered'?'warn':'crit',msg,{persistent:errKind!=='recovered'});
  }else if(code==='stopped_safe'){
    resEl.textContent='중단 원인: '+(st.stop_cause||'로그에 원인 줄 없음')+' · 팔은 안전 종료 확인됨(session.json). 다음 녹화를 시작할 수 있습니다.';
    resEl.hidden=false;
    clearNotice('status-error');
  }else if(code==='unsafe_or_failed'||code==='failed'||code==='seal_failed'){
    const unconf=Array.isArray(st.unconfirmed)?st.unconfirmed:[];
    let msg='';
    if(code==='unsafe_or_failed'&&unconf.length){
      msg='안전 종료 미확인 항목: '+unconf.join(', ')+(logTail?' · 실패 로그: '+logTail:'');
    }else if(logTail.includes('session.lock')){
      msg='실패 원인: 다른 OMX 세션(예: cell_calibrate 또는 다른 팔 작업)이 session.lock을 점유 중입니다. 진행 중인 세션이 끝난 뒤 다시 시작하세요.';
    }else if(logTail){
      msg='실패 로그: '+logTail;
    }else{
      msg='실패 (종료 코드: '+(st.exit_code!=null?st.exit_code:'미확인')+')';
    }
    msg=formatErrorKind(msg,errKind);
    resEl.textContent=msg;
    resEl.hidden=false;
    setNotice('status-error',errKind==='recovered'?'warn':'crit',msg,{persistent:errKind!=='recovered'});
  }else{
    resEl.hidden=true;
    clearNotice('status-error');
  }

  const manEl=$('ev-manual');
  if(st.manual_attention){
    const manMsg=formatErrorKind('현장 수동 확인 필요(manual_attention): 팔 상태와 안전 종료 여부를 확인하세요.',errKind||'needs_person');
    manEl.textContent=manMsg;
    manEl.hidden=false;
    setNotice('manual-attention','warn',manMsg);
  }else{
    manEl.hidden=true;
    clearNotice('manual-attention');
  }

  const vRow=$('sb-verdict-row');
  if(vRow){
    const tags=[];
    if(st.safe_end===true)tags.push('안전종료 확인');
    else if(st.safe_end===false)tags.push('안전종료 미확인');
    if(st.manual_attention)tags.push('수동 확인 필요');
    const unconf=Array.isArray(st.unconfirmed)?st.unconfirmed:[];
    if(unconf.length)tags.push('미확인: '+unconf.join(', '));
    if(resErr.length)tags.push('복구오류: '+resErr.join(', '));
    vRow.textContent=tags.join(' · ');
    vRow.hidden=!tags.length;
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
  if($('sum-recent-drawer')){
    const recN=Array.isArray(st.recent_sessions)?st.recent_sessions.length:0;
    const dsN=Array.isArray(st.lerobot_datasets)?st.lerobot_datasets.length:0;
    $('sum-recent-drawer').textContent='최근 '+recN+'건 · LeRobot '+dsN+'개';
  }
  const scSig=JSON.stringify(st.scenario_counts||{});
  if($('task-listbox')&&$('task-listbox').dataset.scSig!==scSig){
    $('task-listbox').dataset.scSig=scSig;
    renderTaskListbox();
    updateTaskSummary();
  }
  syncBenchPhase();
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
let lastTelemetry=null;
function setStatusCell(id,value,group){
  const el=$(id);
  const text=value??'';
  if(el.textContent!==text)el.textContent=text;
  el.title=text;
  (group||el.closest('dd').parentElement).hidden=text==='';
}

function renderStatusKv(){
  const st=lastStatus;
  const d=lastTelemetry?.active?lastTelemetry:null;
  const rows=Array.isArray(d?.motors)?d.motors:[];
  const follower=rows.some(m=>m.present_raw!=null)?'연결됨':'';
  const leader=rows.some(m=>m.leader_raw!=null)?'연결됨':'';
  const on=rows.filter(m=>m.torque_enabled===true).length;
  const off=rows.filter(m=>m.torque_enabled===false).length;
  const torque=on&&off?'토크 ON '+on+' · OFF '+off:on?'토크 ON':off?'토크 OFF':'';
  setStatusCell('sb-st-follower',follower,$('sb-st-follower'));
  setStatusCell('sb-st-torque',torque,$('sb-st-torque'));
  $('sb-st-follower').closest('dd').parentElement.hidden=!(follower||torque);
  setStatusCell('sb-st-leader',leader);

  const fault=Boolean(d?.fault)||rows.some(m=>m.fault||m.hardware_error);
  const holdJoint=typeof d?.hold==='string'?d.hold:d?.hold?.joint;
  const holding=Boolean(d?.hold)||st?.status==='leader_manual_check';
  const fh=Boolean(fault||holding);
  if(cueInit&&fh&&!prevCueFault&&typeof benchBeep==='function')benchBeep('warn');
  prevCueFault=fh;
  const holdLabel=holding?'정체 hold'+(holdJoint?': '+holdJoint:''):'';
  const degree=Number.isFinite(st?.starting_deg_left)?' '+st.starting_deg_left.toFixed(1)+'도 남음':'';
  const track=fault?'차단':holdLabel||((st?.starting_step==='aligning'||d?.tracking===false)?'정렬 중'+degree:d?.tracking===true?'추종 중':'');
  setStatusCell('tel-track',track);
  $('tel-track').dataset.tone=fault?'crit':holding?'warn':d?.tracking===true?'good':'live';

  const speed=st?.teleop_speed??d?.teleop_speed;
  const rate=speed?.track_deg_s;
  setStatusCell('status-speed',Number.isFinite(rate)?rate+'°/s':speed?.stage!=null?'단계 '+speed.stage:'');
  const cameras=st?.cameras??d?.cameras;
  const labels=cameras?previewCamsForArm(Object.keys(cameras),st?.arm||f.arm.value):[];
  const source={unit:'유닛',recorder:'녹화기'}[st?.camera_source??d?.camera_source];
  setStatusCell('status-cameras',labels.length?labels.filter(label=>cameras[label]?.fresh===true).length+'/'+labels.length:'',$('status-cameras'));
  setStatusCell('status-camera-source',source,$('status-camera-source'));
  $('status-cameras').closest('dd').parentElement.hidden=$('status-cameras').hidden&&!source;
  $('hdr-cam-health').hidden=labels.length>0;

  const holdReason=(typeof st?.manual_attention==='string'&&st.manual_attention)||st?.error||
    (st?.manual_attention||st?.error_kind==='needs_person'?'사람 확인 필요':null)||
    (fault?'모터 이상/차단':null)||(holding?'정체 (hold)':null)||
    (Array.isArray(st?.active_locks)&&st.active_locks.length?'락 '+st.active_locks.length+'건':null);
  const holdObserved=statusLoaded&&(Array.isArray(st?.active_locks)||Object.hasOwn(st,'error_kind'));
  setStatusCell('sb-st-hold',holdReason||(holdObserved?'없음':''));
  $('sb-st-hold').dataset.tone=fault||st?.error_kind==='needs_person'?'crit':holdReason?'warn':'';
}
function renderTelemetry(d){
  lastTelemetry=d||null;
  const active=Boolean(d?.active);
  if(active!==lastTelemetryActive){
    lastTelemetryActive=active;
    syncBenchPhase();
  }
  renderStatusKv();
  syncHeaderAndSlimBar();
  const lat=$('tel-lat'), grid=$('tel-grid'), note=$('tel-note');
  if(!active){
    lat.textContent='-- ms';lat.dataset.tone='warn';
    grid.hidden=true;if(note)note.hidden=false;
    return;
  }
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
  try{renderTelemetry(await api('/api/telemetry'));}catch(_){renderTelemetry(null);}
}
setInterval(pollTelemetry,400);
