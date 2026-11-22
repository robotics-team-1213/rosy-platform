window.zoneSwapped=false;
let reverseMode=false;

function mapConfigCamToLabel(rawKey,arm){
  const parts=String(rawKey||'').trim().split('.');
  const prefix=parts.length===2?parts[0]:arm;
  const role=(parts.length===2?parts[1]:parts[0]).toLowerCase();
  if(!role)return [];
  if(role==='top')return [prefix==='arm_s'?'arm_s_top':'top'];
  if(role==='side')return ['side'];
  if(role==='left_wrist')return ['arm_a_wrist'];
  if(role==='right_wrist')return ['arm_b_wrist'];
  if(role==='wrist'||role==='front'){
    if(prefix==='arm_a')return ['arm_a_wrist'];
    if(prefix==='arm_b')return ['arm_b_wrist'];
    if(prefix==='arm_s')return ['arm_s_wrist'];
    if(prefix==='arm_ab')return ['arm_a_wrist','arm_b_wrist'];
  }
  return [role];
}
window.mapConfigCamToLabel=mapConfigCamToLabel;

function resolveRecordingCams(arm,configName){
  const base=ARM_PREVIEW_CAMS[arm];
  const mapped=new Set(base?[...base]:[]);
  const cams=choices&&choices.config_meta&&configName&&choices.config_meta[configName]?choices.config_meta[configName].cameras:null;
  if(Array.isArray(cams)&&cams.length){
    for(const k of cams){for(const lbl of mapConfigCamToLabel(k,arm))mapped.add(lbl);}
  }
  return mapped.size?mapped:null;
}
window.resolveRecordingCams=resolveRecordingCams;
const OPTIONAL_CAMS=new Set(['arm_s_top']);
function isOptionalCam(lbl,arm){return arm==='arm_s'&&OPTIONAL_CAMS.has(lbl);}
function expectedCamsForArm(arm,configName){
  if(!arm)return [];
  const cams=choices&&choices.config_meta&&configName&&choices.config_meta[configName]?choices.config_meta[configName].cameras:null;
  const out=new Set();
  if(Array.isArray(cams)&&cams.length){
    for(const k of cams){for(const lbl of mapConfigCamToLabel(k,arm))out.add(lbl);}
  }else if(ARM_PREVIEW_CAMS[arm]){
    for(const lbl of ARM_PREVIEW_CAMS[arm])out.add(lbl);
  }
  return [...out].filter(lbl=>!isOptionalCam(lbl,arm));
}
window.isOptionalCam=isOptionalCam;
window.expectedCamsForArm=expectedCamsForArm;

function camHealthSummary(st,labels,curArm){
  const cfg=(typeof benchSessionActive==='function'&&benchSessionActive()&&lastStatus?.config)?lastStatus.config:(f&&f.config?f.config.value:'');
  const req=expectedCamsForArm(curArm,cfg);
  const src=(st&&typeof st==='object')?st:{};
  const errs=typeof camFrameErrs!=='undefined'?camFrameErrs:new Map();
  const liveFn=l=>Object.hasOwn(src,l)&&src[l]?.fresh!==false&&(errs.get(l)||0)<3;
  const reqList=req.length?req:labels;
  const liveReq=reqList.filter(liveFn);
  const missingReq=reqList.filter(l=>!liveFn(l));
  return {req:reqList,liveReq,missingReq};
}

function renderCamHealthHeader(st,labels,curArm){
  const hdrCam=$('hdr-cam-health'), rstBtn=$('hdr-camera-restart-btn');
  const {req,liveReq,missingReq}=camHealthSummary(st,labels,curArm);
  if(hdrCam){
    hdrCam.hidden=false;
    if(!req.length){hdrCam.textContent='카메라 0대';hdrCam.dataset.tone='warn';hdrCam.removeAttribute('title');}
    else if(missingReq.length){
      hdrCam.textContent='카메라 '+liveReq.length+'/'+req.length+'대 · '+missingReq.join(', ')+' 미수신';
      hdrCam.dataset.tone=liveReq.length?'warn':'crit';
      hdrCam.title='수신: '+(liveReq.join(', ')||'없음')+' / 미수신: '+missingReq.join(', ');
    }else{
      hdrCam.textContent='카메라 '+liveReq.length+'/'+req.length+'대';
      hdrCam.dataset.tone='good';
      hdrCam.title=req.join(', ');
    }
  }
  if(rstBtn){
    rstBtn.dataset.tone=missingReq.length?'warn':'';
    rstBtn.title=missingReq.length?('미수신 카메라('+(missingReq.join(', '))+') 재시작 [Shift+C]'):'선택한 팔의 카메라 재시작 [Shift+C]';
  }
  return {req,liveReq,missingReq};
}

function syncMissingCamPlaceholders(missingReq){
  const grid=$('cam-grid');
  if(!grid)return;
  for(const el of grid.querySelectorAll('.cam-box.cam-missing'))el.remove();
  if(!missingReq.length)return;
  let stack=grid.querySelector('.cam-pip-stack');
  if(!stack){
    stack=document.createElement('div');
    stack.className='cam-pip-stack';
    grid.append(stack);
  }
  for(const lbl of missingReq){
    if(grid.querySelector('.cam-box[data-cam-box="'+lbl+'"]'))continue;
    const box=document.createElement('div');box.className='cam-box cam-pip cam-missing';box.dataset.missingCam=lbl;box.tabIndex=0;
    const pill=document.createElement('span');pill.className='cam-title-pill';pill.textContent=lbl;
    const rec=document.createElement('span');rec.className='cam-rec-badge on';rec.textContent='● 미수신';
    const body=document.createElement('div');body.className='cam-missing-body';
    const stEl=document.createElement('strong');stEl.textContent=lbl+' 미수신';
    const spEl=document.createElement('span');spEl.textContent='⇧C 카메라 재시작';
    body.append(stEl,spEl);
    box.append(pill,rec,body);
    box.addEventListener('click',()=>$('hdr-camera-restart-btn')?.click());
    box.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('hdr-camera-restart-btn')?.click();}});
    stack.append(box);
  }
}
window.renderCamHealthHeader=renderCamHealthHeader;
window.syncMissingCamPlaceholders=syncMissingCamPlaceholders;

function updateCameraRecordingMask(){
  const arm=f.arm?f.arm.value:'';
  const cfg=f.config?f.config.value:'';
  const recSet=resolveRecordingCams(arm,cfg);
  for(const box of $('cam-grid').querySelectorAll('.cam-box[data-cam-box]')){
    const lbl=box.dataset.camBox;
    const isRec=!recSet||recSet.has(lbl);
    box.classList.toggle('cam-unrecorded',!isRec);
    const badge=box.querySelector('.cam-rec-badge');
    if(badge){
      badge.textContent=isRec?'● 녹화':'미녹화';
      badge.className='cam-rec-badge '+(isRec?'on':'off');
    }
  }
  const note=$('cam-note');
  if(note&&camLabels.length&&recSet){
    const recList=camLabels.filter(l=>recSet.has(l));
    const unrecList=camLabels.filter(l=>!recSet.has(l));
    const missing=[...recSet].filter(l=>!camLabels.includes(l));
    const parts=['실시간 미리보기 — '+(arm||'선택 암')];
    parts.push('녹화: '+(recList.length?recList.join(', '):'없음'));
    if(unrecList.length)parts.push('미녹화: '+unrecList.join(', '));
    if(missing.length)parts.push('미수신: '+missing.join(', '));
    note.textContent=parts.join(' · ');
  }

}
window.updateCameraRecordingMask=updateCameraRecordingMask;

let lastCountdownSec=null;

async function quickRestartAfterResult(){
  if(benchSessionActive()||startInFlight||stopInFlight||poseInFlight||cameraRestartInFlight)return;
  const prevSt=lastStatus;
  const armNow=f&&f.arm?f.arm.value:'';
  const alreadyHomed=Boolean(prevSt?.auto_home?.ok===true&&(!prevSt.auto_home.arm||prevSt.auto_home.arm===armNow)&&(prevSt?.status==='sealed'||prevSt?.status==='stopped_safe'));
  if(typeof bumpCollectionName==='function')bumpCollectionName(prevSt?.name||'');
  if(typeof setManualBenchPhase==='function')setManualBenchPhase('setup');
  validateStart();
  if(!window.benchStartReady){
    if(typeof setActivity==='function')setActivity('바로 다음 시작 대기 — 설정 확인 필요','warn','');
    if(typeof benchBeep==='function')benchBeep('warn');
    return;
  }
  const targetPath=(armNow==='arm_ab'||Boolean($('replay')?.value))?'/start':'/prepare';
  if(typeof setActivity==='function')setActivity(alreadyHomed?'홈 완료 확인 — 바로 다음 연동 시작 중...':'홈 복귀 후 바로 다음 연동 시작 중...','live',[armNow,f.name.value.trim()].filter(Boolean).join(' · '));
  if(typeof startBench==='function')await startBench(targetPath,{skipHome:alreadyHomed});
}

function initPhaseControls(){
  if($('hdr-quick-restart-btn'))$('hdr-quick-restart-btn').addEventListener('click',quickRestartAfterResult);
  if($('back-to-setup-btn')){
    $('back-to-setup-btn').addEventListener('click',()=>{
      if(typeof setManualBenchPhase==='function')setManualBenchPhase('setup');
    });
  }
  if($('next-ep-btn')){
    $('next-ep-btn').addEventListener('click',()=>{
      if(typeof setManualBenchPhase==='function')setManualBenchPhase('setup');
    });
  }
}

function flipTaskLabel(text){
  const s=String(text||'');
  if(!s)return s;
  let m=s.match(/^(.+?)에서\s+(.+?)로(.*)$/);
  if(m)return m[2].trim()+'에서 '+m[1].trim()+'로'+m[3];
  m=s.match(/^(.+?)\s*(?:->|→)\s*(.+)$/);
  if(m)return m[2].trim()+' → '+m[1].trim();
  return s+' [스왑]';
}
window.flipTaskLabel=flipTaskLabel;

function epQuota(c){
  if(!c||c.valid===false||c.num_episodes==null)return null;
  const goal=Number(c.num_episodes)||0;
  const sc=(typeof lastStatus!=='undefined'&&lastStatus&&lastStatus.scenario_counts&&c.task_id)?lastStatus.scenario_counts[c.task_id]:null;
  const done=sc?Number(sc.episodes)||0:0;
  const rem=Math.max(0,goal-done);
  const pct=goal>0?Math.min(100,Math.round(done/goal*100)):0;
  return {done,goal,rem,pct};
}

function syncHeaderAndSlimBar(){
  const st=lastStatus;
  const phase=currentBenchPhase();
  const split=BENCH_PHASES.includes(st?.phase);
  const recording=phase==='recording';
  const ready=phase==='prepare'&&(st?.prepare?.ready===true||st?.ready===true);
  const legacyStarting=!split&&st?.status==='handing_over';
  const stopping=recording||legacyStarting;
  const pending=startInFlight||stopInFlight;
  $('hdr-prepare-btn').disabled=!window.benchStartReady||pending;
  $('hdr-start-now-btn').disabled=$('hdr-prepare-btn').disabled;
  const record=$('hdr-record-btn');
  record.hidden=!(stopping||ready);
  record.disabled=record.hidden||pending||(!stopping&&!statusLoaded);
  record.classList.toggle('is-recording',stopping);
  record.querySelector('.btn-lbl').textContent=recording?'■ 녹화 끝':legacyStarting?'■ 준비 취소':'● 녹화';
  $('hdr-finish-btn').hidden=!ready;
  $('hdr-finish-btn').disabled=!ready||pending||!statusLoaded;
  $('hdr-next-ep-btn').disabled=!recording||pending||!statusLoaded;
  $('hdr-rerecord-btn').disabled=$('hdr-next-ep-btn').disabled;
  $('back-to-setup-btn').disabled=benchSessionActive()||pending;
  const qBtn=$('hdr-quick-restart-btn'), rhBtn=$('hdr-result-home-btn');
  const settling=st?.status==='restoring'||st?.status==='sealing';
  const rhBlocked=Boolean(st?.manual_attention)||st?.error_kind==='needs_person'||st?.status==='unsafe_or_failed'||st?.status==='leader_manual_check'||st?.status==='failed'||st?.safe_end===false;
  const armNow=f&&f.arm?f.arm.value:'';
  const homedOk=Boolean(st?.auto_home?.ok===true&&(!st.auto_home.arm||st.auto_home.arm===armNow)&&(st?.status==='sealed'||st?.status==='stopped_safe'));
  if(rhBtn){
    rhBtn.disabled=benchSessionActive()||pending||poseInFlight||cameraRestartInFlight||settling||rhBlocked;
    if(!poseInFlight){const lbl=rhBtn.querySelector('.btn-lbl');if(lbl)lbl.textContent=homedOk?'홈 완료 (다시 맞춤)':'지금 홈 포즈';}
  }
  if(qBtn){
    qBtn.disabled=benchSessionActive()||pending||poseInFlight||cameraRestartInFlight||settling||rhBlocked;
    qBtn.textContent=settling?'정리 중...':(homedOk?'바로 다음 연동 시작 (홈 완료)':'홈 → 바로 다음 시작');
  }
  $('hdr-camera-restart-btn').disabled=!canRestartCameras();

  const preparationSteps={follower_home:0,leader_align:1,starting_recorder:2,connecting_cameras:2,aligning:3};
  const curStep=st?.prepare?.step??st?.starting_step;
  const step=ready?4:preparationSteps[curStep];
  const statusTone=$('sb-st-hold').dataset.tone;
  const stageTone=st?.error_kind==='refused'?'warn':STATUS_MAP[st?.status]?.[1];
  const tone=statusTone==='crit'||stageTone==='crit'?'crit':
    statusTone==='warn'||stageTone==='warn'?'warn':phase==='result'&&st?.status==='sealed'?'good':'live';
  $('phase-tabs').dataset.tone=tone;
  const ticks=$('prepare-ticks').children;
  for(let i=0;i<ticks.length;i++){
    ticks[i].classList.toggle('done',phase==='recording'||(step!=null&&(i<step||(ready&&i===step))));
    ticks[i].classList.toggle('current',phase==='prepare'&&!ready&&i===step);
  }
  const degrees=Number.isFinite(st?.starting_deg_left)?' · '+st.starting_deg_left.toFixed(1)+'도 남음':'';
  const stepName=STARTING_STEP_MAP[curStep];
  const prepLabel=ready?'연동됨':stepName?stepName+degrees:st?.step==='camera_restart'?'카메라 재시작 중':'';
  const stepBox=$('starting-step-box');
  stepBox.textContent=phase==='prepare'&&prepLabel?'· '+prepLabel:'';
  stepBox.title=stepBox.textContent;
  stepBox.hidden=!stepBox.textContent;

  const progress=lastTelemetry?.status===st?.status?lastTelemetry:null;
  const total=st?.target_episodes??progress?.target_episodes;
  const done=progress?.episodes_done??st?.episodes_done;
  const number=Number.isInteger(done)&&Number.isInteger(total)&&total>0?Math.min(done+1,total):total===1?1:null;
  const quota=recording&&number!=null?number+'/'+total:'';
  const meta=lastStartMeta?.key&&lastStartMeta.key===sessionKey(st)?lastStartMeta:null;
  const duration=st?.episode_time_s??meta?.episodeTime;
  const episodeElapsed=st?.episode_elapsed_s??progress?.episode_elapsed_s;
  const elapsed=episodeElapsed??((!st?.link&&(split||total===1))?(progress?.recording_elapsed_s??st?.recording_elapsed_s):null);
  const timing=recording&&Number.isFinite(elapsed)?Math.floor(elapsed)+'초'+(duration>0?'/'+duration+'초':''):'';
  for(const [id,value] of [['sp-quota',quota],['sp-timer',timing]]){
    $(id).textContent=value;
    $(id).hidden=!value;
  }
  const timed=Boolean(timing)&&duration>0;
  if(recording&&duration>0&&Number.isFinite(elapsed)){
    const remSec=Math.ceil(duration-elapsed);
    if(remSec>=1&&remSec<=3&&remSec!==lastCountdownSec){lastCountdownSec=remSec;if(typeof benchBeep==='function')benchBeep('countdown');}
    else if(remSec>3||remSec<=0){lastCountdownSec=null;}
  }else{
    lastCountdownSec=null;
  }
  $('slim-prog').hidden=!timed;
  const percent=timed?Math.min(100,Math.max(0,elapsed/duration*100)):0;
  $('sp-fill').style.width=percent+'%';
  $('slim-prog').setAttribute('aria-valuenow',Math.round(percent));
  $('slim-prog').setAttribute('aria-valuetext',timing);
  const sessionElapsed=!split&&!timing?(progress?.recording_elapsed_s??st?.recording_elapsed_s):null;
  const recordingLabel=timing||(Number.isFinite(sessionElapsed)?'세션 '+Math.floor(sessionElapsed)+'초':'');

  const track=$('tel-track').textContent;
  const label=phase==='setup'?'설정':phase==='prepare'?
    (track.startsWith('정체')?track:ready?'연동됨 · 녹화 대기':'준비'+(prepLabel?' · '+prepLabel:legacyStarting?' 중':'')):
    phase==='recording'?[track.startsWith('정체')?track:'녹화 중',quota,recordingLabel].filter(Boolean).join(' · '):
    STATUS_MAP[st?.status]?.[0]||'결과';
  const status=$('top-badge');
  status.textContent=statusLoaded||st?label:'확인 중';
  status.title=status.textContent;
  status.dataset.tone=tone;

  const ok=Boolean(statusLoaded);
  $('ftr-server').textContent=ok?'서버 정상':'연결 끊김';
  $('ftr-server').dataset.tone=ok?'good':'crit';
  const locks=st?.active_locks;
  $('ftr-lock').textContent=locks?.length?'락 '+locks.length+'건':'락 없음';
  $('ftr-lock').dataset.tone=locks?.length?'warn':'';
}

const EPISODE_ACTION_LABELS={
  '/record_episode':'에피소드 녹화 시작',
  '/finish':'연동 끝',
  '/api/episode/next':'다음 에피소드',
  '/api/episode/rerecord':'다시 녹화'
};

async function episodeAction(path,fallback){
  if(startInFlight||stopInFlight)return;
  const actionName=EPISODE_ACTION_LABELS[path]||path;
  const stopVersion=stopRequestVersion;
  startInFlight=true;
  setReqError('');
  if(typeof setActivity==='function')setActivity(actionName+' 요청 중...','live',f?.arm?.value||'');
  const seq=++latestStatusSeq;
  validateStart();
  try{
    const st=await api(path,{}).catch(err=>{
      if(err.status!==404||!fallback)throw err;
      return stopVersion===stopRequestVersion?api(fallback,{}):null;
    });
    if(st?.status&&seq===latestStatusSeq&&stopVersion===stopRequestVersion)renderStatus(st);
    await pollStatus();
    if(path==='/api/episode/rerecord'&&typeof benchBeep==='function')benchBeep('rerecord');
    if(typeof setActivity==='function')setActivity(actionName+' 완료','good',st?.status?(STATUS_MAP[st.status]?.[0]||st.status):'');
  }catch(err){
    setReqError(err.status===404?'서버가 이 조작을 지원하지 않습니다.':err.message);
    if(typeof setActivity==='function')setActivity(actionName+' 실패','crit',err.status===404?'서버 미지원':err.message);
    if(typeof benchBeep==='function')benchBeep('warn');
  }
  finally{startInFlight=false;validateStart();}
}

$('hdr-record-btn').addEventListener('click',()=>{
  if($('hdr-record-btn').disabled)return;
  if(currentBenchPhase()==='recording'||lastStatus?.status==='handing_over'&&!(lastStatus?.prepare?.ready===true||lastStatus?.ready===true)){
    keyboardStop();
  }else if(currentBenchPhase()==='prepare'&&(lastStatus?.prepare?.ready===true||lastStatus?.ready===true)){
    episodeAction('/record_episode');
  }
});
$('hdr-finish-btn').addEventListener('click',()=>episodeAction('/finish','/stop'));
$('hdr-next-ep-btn').addEventListener('click',()=>episodeAction('/api/episode/next'));
$('hdr-rerecord-btn').addEventListener('click',()=>episodeAction('/api/episode/rerecord'));

if($('hdr-estop-btn')){
  $('hdr-estop-btn').addEventListener('click',async()=>{
    if(stopInFlight)return;
    stopRequestVersion++;
    stopInFlight=true;setReqError('');
    if(typeof benchBeep==='function')benchBeep('warn');
    if(typeof setActivity==='function')setActivity('비상정지(E-Stop) 요청 중...','crit','');
    try{
      const st=await api('/stop',{});
      renderStatus(st);
      if(typeof setActivity==='function')setActivity('비상정지 요청 전달 완료','warn',st?.stop_result?.message||(STATUS_MAP[st?.status]?.[0]||st?.status||''));
    }
    catch(err){
      setReqError('비상정지 요청: '+err.message);
      if(typeof setActivity==='function')setActivity('비상정지 요청 실패','crit',err.message);
    }
    finally{stopInFlight=false;syncHeaderAndSlimBar();}
  });
}
if($('toggle-reverse-btn')){
  $('toggle-reverse-btn').addEventListener('click',()=>{
    reverseMode=!reverseMode;
    const btn=$('toggle-reverse-btn');
    btn.setAttribute('aria-pressed',reverseMode?'true':'false');
    btn.classList.toggle('active',reverseMode);
    if($('reverse-note'))$('reverse-note').textContent=reverseMode?'역방향 활성 (리플레이 궤적 반전)':'정방향';
    syncHeaderAndSlimBar();
  });
}
initPhaseControls();

async function checkCameraDrift(){
  if(typeof benchSessionActive==='function'&&benchSessionActive())return;
  try{
    const arm=f&&f.arm?f.arm.value:'';
    const d=await api('/api/camera_check?arm='+encodeURIComponent(arm));
    if(!d||!d.cameras){clearNotice('cam-drift');return;}
    const bad=Object.entries(d.cameras).filter(([,v])=>v.status!=='ok'&&v.status!=='no_baseline');
    const noBase=Object.entries(d.cameras).filter(([,v])=>v.status==='no_baseline');
    if(bad.length){
      setNotice('cam-drift','warn','카메라 변화 감지: '+bad.map(([k,v])=>k+'('+v.status+(v.max_px!=null?' '+v.max_px+'px':'')+(v.delta_mean!=null?' Δ밝기'+v.delta_mean:'')+')').join(', ')+' — 각도/조명을 맞추거나 기준 재저장하세요.');
    }else if(noBase.length){
      setNotice('cam-drift','muted','카메라 기준 미저장 ('+noBase.map(([k])=>k).join(', ')+') — 현재 구도·조명이 맞으면 "기준 카메라 저장"을 누르세요.');
    }else{
      clearNotice('cam-drift');
    }
  }catch(_){}
}
if($('save-cam-base-btn')){
  $('save-cam-base-btn').addEventListener('click',async()=>{
    const btn=$('save-cam-base-btn');
    btn.disabled=true;btn.textContent='저장 중...';
    if(typeof setActivity==='function')setActivity('기준 카메라 저장 중...','live',f?.arm?.value||'');
    try{
      setReqError('');
      await api('/api/camera_baseline',{arm:f.arm.value});
      await checkCameraDrift();
      if(typeof setActivity==='function')setActivity('기준 카메라 저장 완료','good',f?.arm?.value||'');
    }
    catch(err){
      setReqError(err.message);
      if(typeof setActivity==='function')setActivity('기준 카메라 저장 실패','crit',err.message);
    }
    finally{btn.disabled=false;btn.textContent='기준 카메라 저장';}
  });
}
setInterval(checkCameraDrift,8000);
setTimeout(checkCameraDrift,800);

function syncReplayUI(){
  const rSel=$('replay');
  if(!rSel)return;
  if(typeof choices!=='undefined'&&choices&&Array.isArray(choices.replays)&&rSel.dataset.loaded!=='1'){
    rSel.dataset.loaded='1';
    for(const r of choices.replays)rSel.append(new Option(r,r));
  }
  const bi=f&&f.arm&&f.arm.value==='arm_ab';
  rSel.disabled=Boolean(bi);
  if(bi)rSel.value='';
}
setInterval(syncReplayUI,1000);
setTimeout(syncReplayUI,600);

const HF_STATE_MAP={idle:['대기','warn'],encoding:['검증 중','live'],uploading:['팀 업로드 중','live'],done:['업로드 완료','good'],failed:['업로드 실패','crit']};
let hfUploadInFlight=false;

async function triggerHfUpload(datasetName){
  if(hfUploadInFlight)return;
  hfUploadInFlight=true;setReqError('');
  try{
    const res=await api('/api/hf/upload',datasetName?{dataset:datasetName}:{});
    if(res&&res.hf_upload&&typeof lastStatus==='object'&&lastStatus)renderLeRobotPanel({...lastStatus,hf_upload:res.hf_upload});
  }catch(err){setReqError('HF 업로드 오류: '+err.message);}
  finally{hfUploadInFlight=false;}
}

function renderLeRobotPanel(st){
  const hfOk=Boolean(st&&st.hf_logged_in);
  const hb=$('hf-login-badge');
  if(hb){hb.textContent=hfOk?'HF 로그인됨':'HF 미로그인';hb.dataset.tone=hfOk?'good':'warn';}
  const up=(st&&st.hf_upload)||{};
  if($('hf-auto-upload')&&document.activeElement!==$('hf-auto-upload')){$('hf-auto-upload').checked=Boolean(up.auto_upload);}
  let state=String(up.state||'idle').toLowerCase();
  if(state==='idle'&&st&&st.status==='sealing')state='encoding';
  const [sTxt,sTone]=HF_STATE_MAP[state]||[state,'warn'];
  const sb=$('hf-sync-badge');
  if(sb){sb.textContent=sTxt;sb.dataset.tone=sTone;}
  const linkEl=$('hf-repo-link');
  if(linkEl){
    if(up.repo_url){linkEl.href=up.repo_url;linkEl.textContent=up.repo_id||'HF Repo';linkEl.hidden=false;}
    else{linkEl.hidden=true;linkEl.removeAttribute('href');}
  }
  const liveBox=$('hf-upload-live');
  if(liveBox){
    const active=(state==='encoding'||state==='uploading'||state==='done'||state==='failed');
    if(active){
      const pct=Math.max(0,Math.min(100,Number(up.progress_pct??(state==='done'?100:0))||0));
      if($('hf-upload-text'))$('hf-upload-text').textContent=[up.dataset||'',up.message||sTxt].filter(Boolean).join(' · ');
      if($('hf-upload-pct'))$('hf-upload-pct').textContent=pct+'%';
      if($('hf-upload-fill')){
        $('hf-upload-fill').style.width=pct+'%';
        $('hf-upload-fill').style.background=state==='failed'?'var(--crit)':(pct>=100?'var(--good)':'var(--pri)');
      }
      liveBox.hidden=false;
    }else{liveBox.hidden=true;}
  }
  const ul=$('lerobot-list'), empty=$('lerobot-empty');
  const rows=st&&Array.isArray(st.lerobot_datasets)?st.lerobot_datasets:[];
  const emptyRows=rows.filter(r=>(r.episodes||0)===0);
  const bulkBtn=$('cleanup-empty-ds-btn');
  const busyAll=hfUploadInFlight||state==='encoding'||state==='uploading';
  if(bulkBtn){
    bulkBtn.hidden=!emptyRows.length;
    bulkBtn.textContent='빈 데이터셋 '+emptyRows.length+'개 정리';
    bulkBtn.disabled=Boolean((typeof benchSessionActive==='function'&&benchSessionActive())||busyAll);
    if(!bulkBtn.dataset.bound){
      bulkBtn.dataset.bound='1';
      bulkBtn.addEventListener('click',async()=>{
        const curEmpty=(lastStatus&&Array.isArray(lastStatus.lerobot_datasets)?lastStatus.lerobot_datasets:[]).filter(r=>(r.episodes||0)===0);
        if(!curEmpty.length)return;
        bulkBtn.disabled=true;setReqError('');
        let done=0, latest=null;
        try{
          for(const row of curEmpty){latest=await api('/api/dataset/delete',{dataset:row.name||''});done++;}
          if(latest&&latest.lerobot_datasets&&lastStatus){lastStatus.lerobot_datasets=latest.lerobot_datasets;}
          if(typeof setActivity==='function')setActivity('빈 데이터셋 정리 완료','good',done+'개 삭제');
          if(typeof pollStatus==='function')await pollStatus();
          else if(lastStatus)renderLeRobotPanel(lastStatus);
        }catch(e){setReqError('빈 데이터셋 정리: '+(e.message||String(e)));if(typeof pollStatus==='function')await pollStatus();}
        finally{bulkBtn.disabled=false;}
      });
    }
  }
  if($('sum-recent-drawer')){
    const recN=Array.isArray(st?.recent_sessions)?st.recent_sessions.length:0;
    $('sum-recent-drawer').textContent='최근 '+recN+'건 · LeRobot '+rows.length+'개'+(emptyRows.length?' (빈 '+emptyRows.length+')':'');
  }
  if(!ul||!empty)return;
  if(!rows.length){ul.dataset.sig='';ul.innerHTML='';empty.hidden=false;return;}
  empty.hidden=true;
  const dsSig=JSON.stringify(rows.map(r=>[r.name,r.episodes,r.videos,r.size_bytes,r.do_not_train,r.hf_uploaded,r.review_summary]))+'|'+hfOk+'|'+busyAll+'|'+(busyAll?(up.dataset+':'+state):'');
  if(ul.dataset.sig===dsSig)return;
  ul.dataset.sig=dsSig;
  const savedTrays=new Map();
  for(const ex of ul.querySelectorAll('li.hf-ds-row')){const tr=ex.querySelector('.ep-review-tray');if(tr&&ex.dataset.dsName)savedTrays.set(ex.dataset.dsName,tr);}
  ul.innerHTML='';
  for(const r of rows){
    const li=document.createElement('li');li.className='sess-item hf-ds-row';li.dataset.dsName=r.name||'';
    const top=document.createElement('div');top.className='hf-ds-top';
    const left=document.createElement('span');left.className='mono';left.textContent=r.name||'';
    const act=document.createElement('div');act.style.cssText='display:flex;align-items:center;gap:6px;flex-wrap:wrap';
    if(r.hf_uploaded){const tag=document.createElement('span');tag.className='ui-tag';tag.dataset.tone='good';tag.textContent='업로드 완료';act.append(tag);}
    if((r.episodes||0)>0){
      const revBtn=document.createElement('button');revBtn.type='button';revBtn.className='btn-tool btn-xs';
      revBtn.textContent='평가·에피소드';revBtn.title='에피소드 재생·평가 및 불량 삭제';
      revBtn.addEventListener('click',()=>window.toggleDatasetReviewTray?.(li,r.name||''));
      act.append(revBtn);
    }
    const btn=document.createElement('button');btn.type='button';btn.className='btn-tool btn-xs';
    btn.textContent=(busyAll&&up.dataset===r.name)?sTxt:'HF(LeRobot) 업로드';
    btn.disabled=Boolean(!hfOk||busyAll||r.do_not_train||(r.episodes||0)<1);
    if((r.episodes||0)<1)btn.title='parquet 에피소드가 없어 업로드할 수 없습니다';
    btn.addEventListener('click',()=>triggerHfUpload(r.name||''));
    act.append(btn);
    if((r.episodes||0)===0){
      const del=document.createElement('button');del.type='button';del.className='btn-tool btn-xs';
      del.textContent='삭제';del.title='빈 데이터셋 폴더 삭제';
      del.addEventListener('click',async()=>{
        del.disabled=true;
        try{
          const out=await api('/api/dataset/delete',{dataset:r.name||''});
          if(typeof setActivity==='function')setActivity('빈 데이터셋 삭제','good',r.name||'');
          if(out&&out.lerobot_datasets&&lastStatus){lastStatus.lerobot_datasets=out.lerobot_datasets;renderLeRobotPanel(lastStatus);}
        }catch(e){setReqError(e.message||String(e));del.disabled=false;}
      });
      act.append(del);
    }
    top.append(left,act);
    const meta=document.createElement('div');meta.className='hf-ds-meta quiet';
    const info=document.createElement('span');
    const sz=typeof r.size_bytes==='number'?(r.size_bytes>=1048576?(r.size_bytes/1048576).toFixed(1)+' MB':Math.max(1,Math.round(r.size_bytes/1024))+' KB'):'';
    const rs=r.review_summary||{};
    const rTxt=(rs.good||rs.bad||rs.retry)?(' · 평가 합격 '+(rs.good||0)+'/불량 '+(rs.bad||0)):'';
    info.textContent=r.episodes+'회(parquet) · '+r.videos+'개(MP4)'+(sz?' · '+sz:'')+(r.episodes===0?' · 빈 데이터셋':'')+(r.do_not_train?' · 정지회차(DO_NOT_TRAIN)':'')+rTxt;
    meta.append(info);
    if(r.hf_repo_url){const a=document.createElement('a');a.href=r.hf_repo_url;a.target='_blank';a.rel='noopener';a.className='mono';a.textContent=r.hf_repo_id||'Repo';meta.append(a);}
    li.append(top,meta);
    if(savedTrays.has(r.name))li.append(savedTrays.get(r.name));
    ul.append(li);
  }
}
window.renderLeRobotPanel=renderLeRobotPanel;

if($('hf-auto-upload')&&!$('hf-auto-upload').dataset.bound){
  $('hf-auto-upload').dataset.bound='1';
  $('hf-auto-upload').addEventListener('change',async()=>{
    try{
      const out=await api('/api/hf/config',{auto_upload:$('hf-auto-upload').checked});
      if(out&&lastStatus){lastStatus.hf_upload=out;renderLeRobotPanel(lastStatus);}
    }catch(err){setReqError('HF 설정 오류: '+err.message);}
  });
}
init();
if(typeof applyBenchPhase==='function')applyBenchPhase('setup');
setInterval(pollArms,10000);
