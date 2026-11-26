// Manual hold diagnosis/recovery panel and per-episode evaluation, playback, DO_NOT_TRAIN, and deletion.
(function(){
let autoRecoverInFlight=false, lastAutoRecoverSig='', lastAutoRecoverAt=0;
const fleetSyncInFlight=new Set(), fleetSyncAt=new Map();

async function syncFleetIncident(arm, manual){
  if(fleetSyncInFlight.has(arm))return;
  fleetSyncInFlight.add(arm);
  fleetSyncAt.set(arm,Date.now());
  try{
    const result=await api('/api/recover/sync_incident',{arm});
    if(manual||result.cleared)await pollStatus();
  }catch(error){
    if(manual)setReqError(error.message);
  }finally{
    fleetSyncInFlight.delete(arm);
  }
}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function collectHardwareReadiness(arm){
  if(typeof benchSessionActive==='function'&&benchSessionActive())return {arm:'',issues:[],hasCrit:false,hasAny:false};
  const a=arm||(typeof f!=='undefined'&&f&&f.arm?f.arm.value:'')||lastStatus?.arm||'';
  const issues=[];
  const conn=a?(typeof armConnectivity==='function'?armConnectivity(a):(lastArmsStatus?.[a]||null)):null;
  const hasReplay=Boolean($('replay')?.value);
  if(conn?.follower_connected===false){
    issues.push({kind:'follower_offline',tone:'crit',label:a+' 팔로워 USB 미연결',detail:'로봇 제어·녹화 불가 — 팔로워 USB/전원 확인 후 연결 재확인하세요.',action:'recheck'});
  }
  if(conn?.leader_connected===false&&!hasReplay){
    issues.push({kind:'leader_offline',tone:'crit',label:a+' 리더 USB 미연결',detail:'텔레옵 녹화·학습 데이터 수집 불가 — 리더 USB를 연결하거나 리플레이 모드를 선택하세요.',action:'recheck'});
  }
  if(a&&typeof window.expectedCamsForArm==='function'&&typeof lastCamState==='object'&&lastCamState){
    const req=window.expectedCamsForArm(a,(typeof f!=='undefined'&&f?.config?.value)||'');
    const miss=req.filter(l=>!Object.hasOwn(lastCamState,l)||lastCamState[l]?.fresh===false);
    if(miss.length){
      const critMiss=miss.filter(l=>!(a==='arm_s'&&l==='arm_s_top'));
      issues.push({kind:'cam_missing',tone:critMiss.length?'crit':'warn',label:'학습 카메라 미수신 ('+miss.join(', ')+')',detail:'필수 '+req.length+'대 중 '+(req.length-miss.length)+'대만 수신 중 — 누락 상태로 녹화하면 학습 입력 불완전',action:'restart_cam'});
    }
    const badQ=req.filter(l=>Object.hasOwn(lastCamState,l)&&lastCamState[l]?.fresh!==false&&lastCamState[l]?.quality&&(lastCamState[l].quality.condition!=='NORMAL'||lastCamState[l].quality.usable===false));
    if(badQ.length){
      issues.push({kind:'cam_quality',tone:'warn',label:'학습 카메라 영상 불량 ('+badQ.map(l=>l+':'+(lastCamState[l]?.quality?.condition||'불량')).join(', ')+')',detail:'조명/노출 비정상 — 이대로 녹화하면 학습 데이터 검수 탈락 위험',action:'restart_cam'});
    }
  }
  if(typeof statusLoaded!=='undefined'&&statusLoaded&&lastStatus&&lastStatus.hf_logged_in===false){
    issues.push({kind:'hf_offline',tone:'warn',label:'HF 팀 계정 미로그인',detail:'로컬 녹화는 가능하나 모델 PC·팀 저장소 학습 업로드 불가',action:'open_records'});
  }
  const hasCrit=issues.some(x=>x.tone==='crit');
  return {arm:a,issues,hasCrit,hasAny:issues.length>0};
}
function hwReadinessAction(kind){
  if(kind==='restart_cam')return {label:'카메라 재시작',run:()=>$('hdr-camera-restart-btn')?.click()};
  if(kind==='open_records')return {label:'기록·HF 확인',run:()=>{if(typeof openDrawer==='function')openDrawer('records');}};
  return {label:'연결 재확인',run:async()=>{await Promise.all([typeof pollArms==='function'?pollArms():null,typeof pollCameras==='function'?pollCameras():null,typeof pollStatus==='function'?pollStatus():null]);}};
}
function syncHardwareReadiness(){
  const rd=collectHardwareReadiness();
  if(typeof setNotice==='function'&&typeof clearNotice==='function'){
    if(!rd.hasAny){clearNotice('hw-readiness');}
    else{
      const top=rd.issues.find(x=>x.tone==='crit')||rd.issues[0];
      const summary=rd.issues.map(x=>x.label).join(' · ')+(top.detail?' — '+top.detail:'');
      setNotice('hw-readiness',rd.hasCrit?'crit':'warn',summary,{persistent:rd.hasCrit,sig:'hw:'+rd.arm+':'+rd.issues.map(x=>x.kind+':'+x.label).join('|'),action:hwReadinessAction(top.action)});
    }
  }
  renderManualHoldCard(lastStatus);
}
window.collectHardwareReadiness=collectHardwareReadiness;
window.syncHardwareReadiness=syncHardwareReadiness;

function renderManualHoldCard(st){
  const card=$('manual-hold-card');
  if(!card)return;
  const mh=st&&st.manual_hold&&st.manual_hold.active?st.manual_hold:null;
  const rec=st&&st.recovery&&st.recovery.has_issues?st.recovery:null;
  const rd=collectHardwareReadiness();
  if(!mh&&!rec&&!rd.issues.length){card.hidden=true;return;}
  card.hidden=false;
  const isHold=Boolean(mh||rec?.incident_holds&&Object.keys(rec.incident_holds).length);
  card.dataset.tone=(mh?.runner_alive||isHold||rd.hasCrit)?'crit':'warn';
  if($('h-manual-hold'))$('h-manual-hold').textContent=mh?'수동 확인 보류 · 안전 복구 안내':(rec?'작업대 문제 진단 · 복구 안내':(rd.hasCrit?'학습·녹화 준비 오류 · 즉시 점검':'학습·녹화 준비 주의'));
  if($('mh-reason'))$('mh-reason').textContent=mh?.reason||st?.error||(rec?.issues?.[0]?.label)||(rd.issues[0]?(rd.issues[0].label+' — '+rd.issues[0].detail):'확인 또는 복구가 필요합니다');
  const badge=$('mh-torque-badge');
  if(badge){
    if(mh){
      badge.textContent=mh.runner_alive?'토크 ON 유지 중 (PID '+mh.runner_pid+')':(mh.lease_hold?'임대 hold 확인 필요':'러너 종료됨 (복원 대기)');
      badge.dataset.tone=mh.runner_alive?'crit':(mh.lease_hold?'warn':'good');
    }else if(rec){
      badge.textContent='복구 가능 ('+(rec?.issues?.length||1)+'건)';
      badge.dataset.tone='warn';
    }else{
      badge.textContent=(rd.hasCrit?'학습 불가 ':'점검 필요 ')+rd.issues.length+'건';
      badge.dataset.tone=rd.hasCrit?'crit':'warn';
    }
  }
  const facts=$('mh-facts');
  if(facts){
    const parts=[];
    const armLabel=mh?.arm||st?.arm||(f&&f.arm?f.arm.value:'');
    if(armLabel)parts.push('팔: '+armLabel);
    if(mh?.runner_pid)parts.push('PID: '+mh.runner_pid+(mh.runner_alive?' (실행 중)':' (종료)'));
    if(Array.isArray(mh?.live_pose))parts.push('관절: ['+mh.live_pose.join(', ')+']');
    const pUnits=mh?.pending_units||rec?.pending_units||[];
    if(pUnits.length)parts.push('중지 유닛: '+pUnits.length+'개');
    facts.textContent=parts.join(' · ')||'아래 버튼을 눌러 바로 복구할 수 있습니다.';
  }
  const issUl=$('mh-issue-list');
  if(issUl){
    const rows=[...(Array.isArray(rec?.issues)?rec.issues:[]),...rd.issues];
    issUl.hidden=!rows.length;issUl.innerHTML='';
    for(const it of rows){
      const li=document.createElement('li');
      li.textContent=it.label+(it.detail?(' — '+it.detail):'');
      issUl.append(li);
    }
  }
  const hint=$('mh-cause-hint');
  if(hint){
    if(mh?.runner_alive&&rec?.auto_recover?.eligible===false&&rec?.auto_recover?.reason){hint.textContent='자동 토크 해제 보류: '+rec.auto_recover.reason;hint.hidden=false;}
    else if(rec?.incident_holds&&Object.keys(rec.incident_holds).length&&rec?.auto_recover?.eligible===false&&rec?.auto_recover?.reason){hint.textContent='자동 복구 보류: '+rec.auto_recover.reason;hint.hidden=false;}
    else if(mh?.worker_human_hold){hint.textContent='원인 추정: cell-task-worker 또는 워치독이 홈 이동 중 human-hold를 보냈습니다. 새 버전에서는 홈 이동 중 워커를 자동 일시정지합니다.';hint.hidden=false;}
    else if(mh?.detail){hint.textContent='세부 사유: '+mh.detail;hint.hidden=false;}
    else{hint.hidden=true;}
  }
  const tailEl=$('mh-log-tail');
  if(tailEl){const txt=Array.isArray(mh?.log_tail)?mh.log_tail.join('\n'):'';tailEl.textContent=txt;tailEl.hidden=!txt;}

  const lockBox=$('mh-locks-box'), locks=Array.isArray(st?.active_locks)?st.active_locks:[];
  if(lockBox){
    if(locks.length){
      lockBox.hidden=false;lockBox.innerHTML='<span class="quiet">점유 락:</span>';
      const seenPids=new Set();
      for(const lk of locks){
        if(!lk.pid||seenPids.has(lk.pid))continue;
        seenPids.add(lk.pid);
        const btn=document.createElement('button');btn.type='button';btn.className='btn-tool btn-xs';btn.dataset.tone='warn';
        btn.textContent='PID '+lk.pid+' ('+(lk.lock||'lock')+') 정상 종료';
        btn.addEventListener('click',async()=>{btn.disabled=true;try{renderStatus(await api('/release_lock',{pid:lk.pid}));}catch(e){setReqError(e.message);}finally{btn.disabled=false;}});
        lockBox.append(btn);
      }
    }else{lockBox.hidden=true;lockBox.innerHTML='';}
  }
  const relBox=$('mh-release-box'), clearBtn=$('mh-clear-btn'), relBtn=$('mh-release-btn'), deadWrap=$('mh-dead-lease-wrap');
  const deadArms=(mh?.dead_lease_arms||rec?.dead_lease_arms||[]);
  if(relBox)relBox.hidden=!mh?.runner_alive;
  if(deadWrap)deadWrap.hidden=!mh||mh.runner_alive||!deadArms.length;
  if(relBtn&&!relBtn.dataset.busy)relBtn.disabled=!($('mh-support-check')?.checked);
  if(clearBtn){
    clearBtn.hidden=!mh;
    clearBtn.disabled=Boolean(mh?.runner_alive||(deadArms.length&&!$('mh-dead-lease-check')?.checked));
  }
  const qa=$('mh-quick-actions');
  if(qa){
    const qaOld=[...qa.children];qa.innerHTML='';
    const tgtArm=rec?.auto_recover?.arm||mh?.arm||st?.arm||(f&&f.arm&&f.arm.value!=='arm_ab'?f.arm.value:'arm_a');
    if(rec?.auto_recover?.eligible){
      const arBtn=document.createElement('button');arBtn.type='button';arBtn.id='mh-auto-recover-btn';arBtn.className='btn-primary btn-xs';
      arBtn.textContent=autoRecoverInFlight?'안전 자동 복구 중...':'안전 자동 복구 · 홈 복귀';
      arBtn.disabled=autoRecoverInFlight;
      arBtn.addEventListener('click',()=>runAutoRecover(false,tgtArm));
      qa.append(arBtn);
      const arSig=JSON.stringify([mh?.arm||'',mh?.runner_pid||null,Object.keys(rec.incident_holds||{}).sort(),(rec.issues||[]).map(i=>i.kind),rec.dead_lease_arms||[],rec.pending_units||[],Boolean(rec.baseline_needed)]);
      const nowMs=Date.now();
      if(!autoRecoverInFlight&&!(typeof benchSessionActive==='function'&&benchSessionActive())&&arSig!==lastAutoRecoverSig&&nowMs-lastAutoRecoverAt>=30000){
        lastAutoRecoverSig=arSig;lastAutoRecoverAt=nowMs;
        queueMicrotask(()=>runAutoRecover(true,tgtArm));
      }
    }
    if(rec?.baseline_needed&&!mh?.active&&tgtArm&&tgtArm!=='arm_ab'){
      const bBtn=document.createElement('button');bBtn.type='button';bBtn.className='btn-tool btn-xs';bBtn.textContent=tgtArm+' 기준 캡 복원 (torque OFF)';
      bBtn.addEventListener('click',async()=>{bBtn.disabled=true;setReqError('');try{const r=await api('/api/recover/baseline',{arm:tgtArm});if(r.status)renderStatus(r.status);if(typeof window.pollLiveLogs==='function')window.pollLiveLogs();}catch(e){setReqError(e.message);}finally{bBtn.disabled=false;}});
      qa.append(bBtn);
    }
    if(rec?.can_restore_units){
      const uBtn=document.createElement('button');uBtn.type='button';uBtn.className='btn-tool btn-xs';uBtn.textContent='중지된 유닛 지금 복원';
      uBtn.addEventListener('click',async()=>{uBtn.disabled=true;setReqError('');try{renderStatus(await api('/api/recover/restore_units',{}));}catch(e){setReqError(e.message);}finally{uBtn.disabled=false;}});
      qa.append(uBtn);
    }
    if(rec?.incident_holds){
      for(const incArm of Object.keys(rec.incident_holds)){
        if(rec.fleet_clear_available){
          const link=document.createElement('a');
          link.className='btn-tool btn-xs';link.textContent=incArm+' Fleet 사고 해제 ↗';
          link.href='/api/recover/fleet_clear?arm='+encodeURIComponent(incArm);
          link.target='_blank';link.rel='noopener noreferrer';
          qa.append(link);
        }
        const sBtn=document.createElement('button');sBtn.type='button';sBtn.className='btn-tool btn-xs';sBtn.textContent=incArm+' Fleet 보류 동기화';
        sBtn.disabled=fleetSyncInFlight.has(incArm);
        sBtn.addEventListener('click',async()=>{sBtn.disabled=true;setReqError('');try{await syncFleetIncident(incArm,true);}finally{sBtn.disabled=false;}});
        const canSync=rec.fleet_clear_available&&(st.status==='idle'||ENDED.has(st.status)&&st.status!=='leader_manual_check')
          &&!benchSessionActive(st)&&!mh&&!locks.length&&!rec.pending_units?.length;
        if(canSync&&Date.now()-(fleetSyncAt.get(incArm)||0)>=15000)void syncFleetIncident(incArm,false);
        qa.append(sBtn);
      }
      const alt=['arm_a','arm_b','arm_s'].find(a=>!rec.incident_holds[a]);
      if(alt&&typeof window.selectArm==='function'){
        const sw=document.createElement('button');sw.type='button';sw.className='btn-tool btn-xs';sw.textContent='정상 팔('+alt+')로 전환';
        sw.addEventListener('click',()=>window.selectArm(alt));
        qa.append(sw);
      }
    }
    if(rec?.can_ack_error){
      const aBtn=document.createElement('button');aBtn.type='button';aBtn.className='btn-tool btn-xs';aBtn.textContent='오류 확인 · 대기 복귀';
      aBtn.addEventListener('click',async()=>{aBtn.disabled=true;setReqError('');try{renderStatus(await api('/api/recover/ack_error',{}));}catch(e){setReqError(e.message);}finally{aBtn.disabled=false;}});
      qa.append(aBtn);
    }
    if(rd.issues.some(x=>x.kind==='cam_missing'||x.kind==='cam_quality')){
      const cBtn=document.createElement('button');cBtn.type='button';cBtn.className='btn-tool btn-xs';cBtn.textContent='카메라 지금 재시작';
      cBtn.addEventListener('click',()=>$('hdr-camera-restart-btn')?.click());
      qa.append(cBtn);
    }
    if(rd.issues.some(x=>x.kind==='follower_offline'||x.kind==='leader_offline')){
      const rBtn=document.createElement('button');rBtn.type='button';rBtn.className='btn-tool btn-xs';rBtn.textContent='연결·상태 재확인';
      rBtn.addEventListener('click',()=>hwReadinessAction('recheck').run());
      qa.append(rBtn);
      const getConn=a=>typeof armConnectivity==='function'?armConnectivity(a):lastArmsStatus?.[a];
      const alt=['arm_a','arm_b','arm_s'].find(a=>a!==rd.arm&&getConn(a)?.follower_connected===true&&getConn(a)?.leader_connected===true);
      if(alt&&typeof window.selectArm==='function'&&!Object.keys(rec?.incident_holds||{}).length){
        const swBtn=document.createElement('button');swBtn.type='button';swBtn.className='btn-tool btn-xs';swBtn.textContent='정상 팔('+alt+')로 전환';
        swBtn.addEventListener('click',()=>window.selectArm(alt));
        qa.append(swBtn);
      }
    }
    const qaSig=tgtArm+'|'+qa.innerHTML;// same buttons: keep the old nodes so keyboard focus survives the poll
    if(qaSig===qa.dataset.sig)qa.replaceChildren(...qaOld);else qa.dataset.sig=qaSig;
  }
}
async function runAutoRecover(isAuto,arm){
  if(autoRecoverInFlight||(typeof benchSessionActive==='function'&&benchSessionActive()))return;
  autoRecoverInFlight=true;setReqError('');
  if($('mh-auto-recover-btn')){$('mh-auto-recover-btn').disabled=true;$('mh-auto-recover-btn').textContent='안전 자동 복구 중...';}
  if(typeof setActivity==='function')setActivity(isAuto?'안전 접힘 확인 · 자동 복구 중...':'안전 자동 복구 · 홈 복귀 중...','live',arm||'');
  try{
    const payload=Object.assign({},arm?{arm}:{},isAuto?{return_home:false}:{return_home:true,include_leader:true});
    const res=await api('/api/recover/auto',payload);
    if(res&&res.status)renderStatus(res.status);else await pollStatus();
    if(typeof window.pollLiveLogs==='function')window.pollLiveLogs();
    if(res&&res.home_failed){
      const guide='복구는 완료되었으나 홈 복귀 실패: '+(res.home_error||'')+(res.next_action?(' → 다음 조치: '+res.next_action):'');
      if($('mh-cause-hint')){$('mh-cause-hint').textContent=guide;$('mh-cause-hint').hidden=false;}
      if(typeof setNotice==='function')setNotice('pose-feedback','warn',guide,{persistent:true});
      if(typeof window.pushBenchLog==='function')window.pushBenchLog('pose','warn',guide);
      if(typeof setActivity==='function')setActivity('홈 복귀 실패 — 조치 필요','warn',res.next_action||res.home_error||'');
    }else{
      const steps=Array.isArray(res?.steps)?res.steps.join(' → '):'완료';
      if(typeof window.pushBenchLog==='function')window.pushBenchLog('bench','good','안전 자동 복구 완료 ('+steps+')');
      if(typeof setNotice==='function')setNotice('pose-feedback','good','안전 자동 복구 완료: '+steps,{ttlMs:6000});
      if(typeof setActivity==='function')setActivity('안전 자동 복구 완료','good',steps);
    }
  }catch(e){
    const msg=e.message||String(e);
    if(typeof setNotice==='function')setNotice('pose-feedback','warn','자동 복구 보류: '+msg,{persistent:true});
    if(typeof window.pushBenchLog==='function')window.pushBenchLog('bench','warn','자동 복구 보류: '+msg);
    if(typeof setActivity==='function')setActivity('자동 복구 보류','warn',msg);
    await pollStatus();
  }finally{
    autoRecoverInFlight=false;
    if($('mh-auto-recover-btn')){$('mh-auto-recover-btn').disabled=false;$('mh-auto-recover-btn').textContent='안전 자동 복구 · 홈 복귀';}
  }
}
window.runAutoRecover=runAutoRecover;
window.renderManualHoldCard=renderManualHoldCard;

$('mh-dead-lease-check')?.addEventListener('change',()=>{if(lastStatus)renderManualHoldCard(lastStatus);});
if($('mh-support-check')&&$('mh-release-btn')){
  $('mh-support-check').addEventListener('change',()=>{
    $('mh-release-btn').disabled=!$('mh-support-check').checked||Boolean($('mh-release-btn').dataset.busy);
  });
  $('mh-release-btn').addEventListener('click',async()=>{
    const btn=$('mh-release-btn'), mh=lastStatus?.manual_hold;
    if(!mh||!$('mh-support-check').checked)return;
    btn.dataset.busy='1';btn.disabled=true;setReqError('');
    try{
      const res=await api('/api/manual_hold/release_runner',{arm:mh.arm,pid:mh.runner_pid,arm_supported_confirmed:true});
      $('mh-support-check').checked=false;
      if(typeof window.pushBenchLog==='function')window.pushBenchLog('pose','warn','HOLD 러너(PID '+mh.runner_pid+') SIGUSR2 해제 요청 완료');
      if(res&&res.status)renderStatus(res.status);else await pollStatus();
    }catch(e){setReqError(e.message||String(e));}
    finally{delete btn.dataset.busy;btn.disabled=!$('mh-support-check').checked;}
  });
}
if($('mh-clear-btn')&&$('mh-clear-confirm')){
  const runManualClear=async(returnHome)=>{
    $('mh-clear-confirm').hidden=true;setReqError('');
    try{
      const forceDead=Boolean($('mh-dead-lease-check')?.checked);
      const mhArm=lastStatus?.manual_hold?.arm||(typeof f!=='undefined'&&f?.arm&&f.arm.value!=='arm_ab'?f.arm.value:'');
      const payload=returnHome?{confirmed:true,force_dead_lease:forceDead,return_home:true,include_leader:true,arm:mhArm}:{confirmed:true,force_dead_lease:forceDead,return_home:false};
      const st=await api('/api/manual_hold/clear',payload);
      if($('mh-dead-lease-check'))$('mh-dead-lease-check').checked=false;
      renderStatus(st);
      if(typeof window.pollLiveLogs==='function')window.pollLiveLogs();
      if(st&&st.home_failed){
        const guide='보류 해제는 완료되었으나 홈 복귀 실패: '+(st.home_error||'')+(st.next_action?(' → 다음 조치: '+st.next_action):'');
        if($('mh-cause-hint')){$('mh-cause-hint').textContent=guide;$('mh-cause-hint').hidden=false;}
        if(typeof setNotice==='function')setNotice('pose-feedback','warn',guide,{persistent:true});
        if(typeof window.pushBenchLog==='function')window.pushBenchLog('pose','warn',guide);
      }else{
        const okMsg=returnHome?'보류 해제 및 홈 복귀 완료':'수동 확인 보류 해제 및 대기 복귀 완료';
        if(typeof window.pushBenchLog==='function')window.pushBenchLog('bench','good',okMsg);
        if(typeof setNotice==='function')setNotice('pose-feedback','good',okMsg,{ttlMs:6000});
      }
    }catch(e){setReqError(e.message||String(e));await pollStatus();}
  };
  $('mh-clear-btn').addEventListener('click',()=>{$('mh-clear-confirm').hidden=false;});
  $('mh-clear-no')?.addEventListener('click',()=>{$('mh-clear-confirm').hidden=true;});
  $('mh-clear-yes')?.addEventListener('click',()=>runManualClear(true));
  $('mh-clear-only-yes')?.addEventListener('click',()=>runManualClear(false));
}
$('mh-log-btn')?.addEventListener('click',()=>{$('sec-live-log')?.scrollIntoView({block:'nearest'});});

const openTrays=new Map();
const RATING_LABELS={good:'합격',bad:'불량',retry:'재녹화',unrated:'미평가'};

async function renderEpisodeReviewPanel(host,dsName){
  if(!host||!dsName)return;
  host.innerHTML='<div class="quiet mono" style="padding:6px">에피소드 평가 정보를 불러오는 중...</div>';
  let data;
  try{data=await api('/api/dataset/episodes?dataset='+encodeURIComponent(dsName));}
  catch(e){host.innerHTML='<div class="alert crit">'+esc(e.message||String(e))+'</div>';return;}

  const eps=Array.isArray(data.episodes)?data.episodes:[];
  const cams=Array.isArray(data.cameras)?data.cameras:[];
  let selCam=host.dataset.selCam||(cams.includes('top')?'top':(cams[0]||''));
  const sum=data.summary||{};
  const badIndices=eps.filter(e=>e.rating==='bad').map(e=>e.index);
  const busy=(typeof benchSessionActive==='function'&&benchSessionActive());

  let h='<div class="ep-review-box">';
  h+='<div class="ep-review-head"><div class="mono" style="font-size:.78rem"><b>'+esc(dsName)+'</b> · '+eps.length+'회 · 합격 '+(sum.good||0)+' · 불량 '+(sum.bad||0)+' · 미평가 '+(sum.unrated||0)+'</div>';
  h+='<div class="ep-review-bulk">';
  if(badIndices.length)h+='<button type="button" class="btn-tool btn-xs" data-tone="warn" data-ep-del-bad="1"'+(busy?' disabled':'')+'>불량 '+badIndices.length+'개 일괄 삭제</button>';
  h+='<button type="button" class="btn-tool btn-xs" data-ds-dnt="'+(data.do_not_train?'0':'1')+'"'+(busy?' disabled':'')+'>'+(data.do_not_train?'학습제외 해제':'학습제외(DO_NOT_TRAIN)')+'</button>';
  h+='<button type="button" class="btn-tool btn-xs" data-tone="warn" data-ds-trash="1"'+(busy?' disabled':'')+'>데이터셋 삭제</button>';
  h+='</div></div>';
  h+='<div class="reset-confirm-bar" data-confirm-box hidden><span class="quiet" data-confirm-msg></span><div style="display:flex;gap:6px"><button type="button" class="btn-primary btn-xs" data-confirm-yes>삭제 확인</button><button type="button" class="btn-tool btn-xs" data-confirm-no>취소</button></div></div>';

  if(cams.length){
    h+='<div class="ep-video-wrap" data-video-wrap hidden><div class="ep-video-bar"><div class="dir-toggle">';
    for(const c of cams)h+='<button type="button" class="pill-btn'+(c===selCam?' active':'')+'" data-ep-cam="'+esc(c)+'">'+esc(c)+'</button>';
    h+='</div><span class="mono quiet" data-ep-play-lbl></span></div><video class="ep-video-el" controls preload="metadata" playsinline></video></div>';
  }

  h+='<ul class="ep-list">';
  for(const ep of eps){
    const rCls=ep.rating||'unrated';
    const meta=[ep.length?(ep.length+'프레임'):'',ep.duration_s!=null?(ep.duration_s+'s'):'',ep.static?'정지 의심':''].filter(Boolean).join(' · ');
    h+='<li class="ep-row" data-ep-rating="'+esc(rCls)+'">';
    h+='<div class="ep-row-top"><span class="mono"><b>#'+ep.index+'</b>'+(meta?' <span class="quiet">('+esc(meta)+')</span>':'')+'</span>';
    h+='<div class="ep-row-btns">';
    if(cams.length)h+='<button type="button" class="btn-tool btn-xs" data-ep-play="'+ep.index+'">재생</button>';
    for(const k of ['good','bad','retry']){
      h+='<button type="button" class="pill-btn'+(rCls===k?' active':'')+'" data-ep-rate="'+ep.index+'" data-rate-val="'+k+'" data-rate-tone="'+k+'">'+RATING_LABELS[k]+'</button>';
    }
    h+='<button type="button" class="btn-tool btn-xs" data-tone="warn" data-ep-del="'+ep.index+'"'+(busy?' disabled':'')+'>삭제</button>';
    h+='</div></div>';
    h+='<input type="text" class="ep-note-inp" data-ep-note="'+ep.index+'" value="'+esc(ep.note||'')+'" data-rate-cur="'+esc(rCls)+'" placeholder="메모 (불량 사유 등 · Enter 저장)">';
    h+='</li>';
  }
  if(!eps.length)h+='<li class="quiet" style="padding:6px">에피소드가 없습니다.</li>';
  host.innerHTML=h+'</ul></div>';

  const confirmBox=host.querySelector('[data-confirm-box]'), confirmMsg=host.querySelector('[data-confirm-msg]');
  let pendingAct=null;
  const askConfirm=(msg,fn)=>{if(!confirmBox)return;confirmMsg.textContent=msg;pendingAct=fn;confirmBox.hidden=false;};
  host.querySelector('[data-confirm-no]')?.addEventListener('click',()=>{confirmBox.hidden=true;pendingAct=null;});
  host.querySelector('[data-confirm-yes]')?.addEventListener('click',async()=>{
    const fn=pendingAct;confirmBox.hidden=true;pendingAct=null;if(fn)await fn();
  });

  const vidWrap=host.querySelector('[data-video-wrap]'), vid=host.querySelector('.ep-video-el'), playLbl=host.querySelector('[data-ep-play-lbl]');
  let activeEpIdx=null;
  const playEpisode=(idx)=>{
    const epObj=eps.find(x=>x.index===idx);
    if(!vid||!epObj)return;
    const vInfo=(epObj.videos&&epObj.videos[selCam])||{chunk:0,file:0,from_s:0,to_s:0};
    const tFrag=(vInfo.to_s>vInfo.from_s)?('#t='+vInfo.from_s+','+vInfo.to_s):'#t=0';
    const src='/api/dataset/video?dataset='+encodeURIComponent(dsName)+'&cam='+encodeURIComponent(selCam)+'&chunk='+(vInfo.chunk||0)+'&file='+(vInfo.file||0)+tFrag;
    vidWrap.hidden=false;activeEpIdx=idx;
    if(playLbl)playLbl.textContent='ep#'+idx+' · '+selCam+(vInfo.to_s>vInfo.from_s?(' ('+vInfo.from_s+'~'+vInfo.to_s+'s)'):'');
    vid.src=src;vid.play().catch(()=>{});
  };
  for(const b of host.querySelectorAll('[data-ep-cam]'))b.addEventListener('click',()=>{
    selCam=b.dataset.epCam;host.dataset.selCam=selCam;
    for(const x of host.querySelectorAll('[data-ep-cam]'))x.classList.toggle('active',x===b);
    if(activeEpIdx!=null)playEpisode(activeEpIdx);
  });
  for(const b of host.querySelectorAll('[data-ep-play]'))b.addEventListener('click',()=>playEpisode(Number(b.dataset.epPlay)));

  for(const b of host.querySelectorAll('[data-ep-rate]'))b.addEventListener('click',async()=>{
    const epIdx=Number(b.dataset.epRate), nextR=b.dataset.rateVal;
    const cur=eps.find(x=>x.index===epIdx);
    const val=(cur&&cur.rating===nextR)?'unrated':nextR;
    const note=(host.querySelector('[data-ep-note="'+epIdx+'"]')?.value||'').trim();
    try{
      await api('/api/dataset/episode/rate',{dataset:dsName,episode:epIdx,rating:val,note});
      await renderEpisodeReviewPanel(host,dsName);
      if(typeof pollStatus==='function')pollStatus();
    }catch(e){setReqError(e.message||String(e));}
  });
  for(const inp of host.querySelectorAll('[data-ep-note]')){
    const saveNote=async()=>{
      const epIdx=Number(inp.dataset.epNote), rating=inp.dataset.rateCur||'unrated';
      try{await api('/api/dataset/episode/rate',{dataset:dsName,episode:epIdx,rating,note:inp.value.trim()});}catch(e){setReqError(e.message||String(e));}
    };
    inp.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();saveNote();}});
    inp.addEventListener('blur',saveNote);
  }
  const runDeleteEps=(indices)=>askConfirm(dsName+' 에피소드 '+indices.map(i=>'#'+i).join(', ')+'를 삭제하고 재인덱싱할까요? (원본은 .trash/로 백업)',async()=>{
    try{
      const res=await api('/api/dataset/episode/delete',{dataset:dsName,episodes:indices,confirm:true});
      if(typeof window.pushBenchLog==='function')window.pushBenchLog('review','warn',dsName+' 에피소드 삭제: '+indices.join(', '));
      if(res.deleted_all){openTrays.delete(dsName);host.remove();}
      else await renderEpisodeReviewPanel(host,dsName);
      if(typeof pollStatus==='function')await pollStatus();
    }catch(e){setReqError(e.message||String(e));}
  });
  for(const b of host.querySelectorAll('[data-ep-del]'))b.addEventListener('click',()=>runDeleteEps([Number(b.dataset.epDel)]));
  host.querySelector('[data-ep-del-bad]')?.addEventListener('click',()=>runDeleteEps(badIndices));
  host.querySelector('[data-ds-dnt]')?.addEventListener('click',async e=>{
    const dnt=e.currentTarget.dataset.dsDnt==='1';
    try{
      await api('/api/dataset/do_not_train',{dataset:dsName,do_not_train:dnt,reason:'bench_review'});
      await renderEpisodeReviewPanel(host,dsName);
      if(typeof pollStatus==='function')await pollStatus();
    }catch(err){setReqError(err.message||String(err));}
  });
  host.querySelector('[data-ds-trash]')?.addEventListener('click',()=>askConfirm('데이터셋 '+dsName+' 전체를 폐기(.trash/로 이동)할까요?',async()=>{
    try{
      await api('/api/dataset/delete',{dataset:dsName,confirm_nonempty:true});
      openTrays.delete(dsName);host.remove();
      if(typeof window.pushBenchLog==='function')window.pushBenchLog('review','warn','데이터셋 폐기: '+dsName);
      if(typeof pollStatus==='function')await pollStatus();
    }catch(e){setReqError(e.message||String(e));}
  }));
}

window.toggleDatasetReviewTray=(li,dsName)=>{
  if(!li||!dsName)return;
  const ex=li.querySelector('.ep-review-tray');
  if(ex){openTrays.delete(dsName);ex.remove();return;}
  const tray=document.createElement('div');
  tray.className='ep-review-tray';
  openTrays.set(dsName,true);
  li.append(tray);
  renderEpisodeReviewPanel(tray,dsName);
};

window.syncResultEpisodeReview=(st)=>{
  const host=$('ev-episode-review');
  if(!host)return;
  if(!st||(typeof currentBenchPhase==='function'&&currentBenchPhase()!=='result')){host.hidden=true;return;}
  const dsRows=Array.isArray(st.lerobot_datasets)?st.lerobot_datasets:[];
  const fBase=st.folder?String(st.folder).split('/').pop():'';
  const hit=dsRows.find(r=>r&&st.name&&(r.name===st.name||(fBase&&r.name===fBase)||r.name.endsWith('-'+st.name)));
  if(!hit||(hit.episodes||0)<1){host.hidden=true;host.innerHTML='';return;}
  host.hidden=false;
  if(host.dataset.loadedDs!==hit.name){
    host.dataset.loadedDs=hit.name;
    renderEpisodeReviewPanel(host,hit.name);
  }
};
window.renderEpisodeReviewPanel=renderEpisodeReviewPanel;
})();
