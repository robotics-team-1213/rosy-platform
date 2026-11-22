async function pollArms(){
  try{const res=await api('/api/arms');if(res&&res.arms){lastArmsStatus=res.arms;validateStart();}}catch(_){}
}
async function triggerHomePose(btn,opts){
  if(!btn||poseInFlight||benchSessionActive()||startInFlight||cameraRestartInFlight)return;
  const arm=(opts?.useStatusArm&&lastStatus?.arm)?lastStatus.arm:f.arm.value;
  const lbl=btn.querySelector('.btn-lbl')||btn;
  const aInfo=lastArmsStatus&&arm?lastArmsStatus[arm]:null;
  const incL=Boolean(opts?.allowLeader&&aInfo&&(aInfo.leader_connected===true||(aInfo.leader_connected!==false&&aInfo.has_leader_pose))&&$('home-include-leader')?.checked);
  poseInFlight=true;btn.disabled=true;lbl.textContent='홈 이동 중...';validateStart();
  if(typeof setActivity==='function')setActivity('홈 이동 요청 중...','live',arm);
  try{
    setReqError('');
    const st=await api('/home',{arm,include_leader:incL,fold_unfolded:opts?.foldUnfolded!==false});
    renderStatus(st);
    poseFeedbackMsg='홈(이니셜) 위치 이동 완료: '+((st.home_moved||[]).join(', ')||arm)+(incL?' (리더 토크 OFF 복구됨)':'');
    poseFeedbackUntil=Date.now()+6000;
    setNotice('pose-feedback','good',poseFeedbackMsg,{ttlMs:6000});
    if(typeof setActivity==='function')setActivity('홈 이동 완료','good',((st.home_moved||[]).join(', ')||arm)+(incL?' (리더 포함)':''));
    if(typeof benchBeep==='function')benchBeep('done');
  }catch(err){
    setReqError(err.message);
    if(typeof setActivity==='function')setActivity('홈 이동 실패','crit',err.message);
    if(typeof benchBeep==='function')benchBeep('warn');
  }
  finally{poseInFlight=false;lbl.textContent=opts?.defaultLabel||'홈 이동';validateStart();}
}
if($('hdr-home-btn'))$('hdr-home-btn').addEventListener('click',()=>triggerHomePose($('hdr-home-btn'),{allowLeader:true,foldUnfolded:true,defaultLabel:'홈 이동'}));
if($('hdr-result-home-btn'))$('hdr-result-home-btn').addEventListener('click',()=>triggerHomePose($('hdr-result-home-btn'),{allowLeader:true,useStatusArm:true,foldUnfolded:true,defaultLabel:'지금 홈 포즈'}));
if($('home-include-leader'))$('home-include-leader').addEventListener('change',validateStart);
if($('save-leader-pose-btn')){
  $('save-leader-pose-btn').addEventListener('click',async()=>{
    const btn=$('save-leader-pose-btn');
    poseInFlight=true;btn.disabled=true;btn.textContent='읽는 중...';validateStart();
    if(typeof setActivity==='function')setActivity('리더 포즈 읽는 중...','live',f.arm.value);
    try{
      setReqError('');
      const st=await api('/save_leader_pose',{arm:f.arm.value});
      renderStatus(st);
      poseFeedbackMsg='리더 홈 포즈 저장 완료 ('+Object.keys(st.leader_pose_saved||{}).join(', ')+')';
      poseFeedbackUntil=Date.now()+6000;
      setNotice('pose-feedback','good',poseFeedbackMsg,{ttlMs:6000});
      if(typeof setActivity==='function')setActivity('리더 포즈 저장 완료','good',Object.keys(st.leader_pose_saved||{}).join(', ')||f.arm.value);
      pollArms();
    }catch(err){
      setReqError(err.message);
      if(typeof setActivity==='function')setActivity('리더 포즈 저장 실패','crit',err.message);
    }
    finally{poseInFlight=false;btn.textContent='리더 포즈 저장';validateStart();}
  });
}
if($('save-init-pose-btn')){
  $('save-init-pose-btn').addEventListener('click',async()=>{
    const btn=$('save-init-pose-btn');
    poseInFlight=true;btn.disabled=true;btn.textContent='저장 중...';validateStart();
    if(typeof setActivity==='function')setActivity('팔로워 포즈 저장 중...','live',f.arm.value);
    try{
      setReqError('');
      const st=await api('/save_initial_pose',{arm:f.arm.value});
      renderStatus(st);
      const sv=st.initial_pose_saved||{};
      const txt=Object.entries(sv).map(([k,v])=>k+': ['+v.join(', ')+']').join(' / ');
      poseFeedbackMsg='이니셜 포즈 저장 완료: '+txt;
      poseFeedbackUntil=Date.now()+6000;
      setNotice('pose-feedback','good',poseFeedbackMsg,{ttlMs:6000});
      if(typeof setActivity==='function')setActivity('팔로워 포즈 저장 완료','good',txt||f.arm.value);
      pollArms();
    }catch(err){
      setReqError(err.message);
      if(typeof setActivity==='function')setActivity('팔로워 포즈 저장 실패','crit',err.message);
    }
    finally{poseInFlight=false;btn.textContent='팔로워 포즈 저장';validateStart();}
  });
}
if($('task-search')){
  $('task-search').addEventListener('input',()=>{setTaskListOpen(true);renderTaskListbox();});
  $('task-search').addEventListener('keydown',e=>{
    if(e.key==='ArrowDown'){e.preventDefault();stepTask(1);}
    else if(e.key==='ArrowUp'){e.preventDefault();stepTask(-1);}
  });
}
if($('task-prev-btn'))$('task-prev-btn').addEventListener('click',()=>stepTask(-1));
if($('task-next-btn'))$('task-next-btn').addEventListener('click',()=>stepTask(1));
if($('task-toggle-btn'))$('task-toggle-btn').addEventListener('click',()=>setTaskListOpen($('task-listbox').hidden));
if($('task-filters'))$('task-filters').addEventListener('click',e=>{
  const btn=e.target.closest('button[data-tfilter]');if(!btn)return;
  taskFilter=btn.dataset.tfilter||'all';
  for(const b of $('task-filters').querySelectorAll('button[data-tfilter]')){b.classList.toggle('active',b===btn);b.setAttribute('aria-pressed',String(b===btn));}
  setTaskListOpen(true);renderTaskListbox();
});
const DRAWER_TITLES={setup:'과제 목록',bindings:'수집·연결 설정',start:'포즈 저장 · 기준',records:'기록 · 시뮬·RL 루프'};
let activeDrawer=null, lastDrawerOpener=null;
function closeDrawer(restoreFocus){
  const host=$('side-drawer-host');
  if(!host||host.hidden)return;
  host.hidden=true;
  for(const p of host.querySelectorAll('[data-drawer-pane]'))p.hidden=true;
  for(const b of document.querySelectorAll('[data-drawer-btn]'))b.setAttribute('aria-expanded','false');
  activeDrawer=null;
  if(restoreFocus&&lastDrawerOpener&&typeof lastDrawerOpener.focus==='function')lastDrawerOpener.focus();
}
function openDrawer(name,openerEl,focusEl){
  const host=$('side-drawer-host');
  if(!host||(benchSessionActive()&&name!=='records'))return;
  if(activeDrawer===name&&!host.hidden){closeDrawer(true);return;}
  const menuWrap=$('drawer-menu-wrap');
  if(menuWrap){menuWrap.classList.remove('open');$('btn-drawer-menu')?.setAttribute('aria-expanded','false');}
  const opener=openerEl||document.querySelector('[data-drawer-btn="'+name+'"]');
  lastDrawerOpener=opener?.closest('#drawer-menu-pop')?$('btn-drawer-menu'):opener;
  activeDrawer=name;
  if(typeof syncHeadHeight==='function')syncHeadHeight();
  host.hidden=false;
  for(const p of host.querySelectorAll('[data-drawer-pane]'))p.hidden=(p.dataset.drawerPane!==name);
  for(const b of document.querySelectorAll('[data-drawer-btn]'))b.setAttribute('aria-expanded',b.dataset.drawerBtn===name?'true':'false');
  if($('drawer-panel-title'))$('drawer-panel-title').textContent=DRAWER_TITLES[name]||'설정 서랍';
  const pane=host.querySelector('[data-drawer-pane="'+name+'"]');
  const tgt=focusEl||(pane?pane.querySelector('input:not([hidden]):not(:disabled),select:not([hidden]):not(:disabled),button:not(:disabled)'):null);
  if(tgt&&typeof tgt.focus==='function')tgt.focus();
}
window.activeDrawerName=()=>activeDrawer;
window.openDrawer=openDrawer;
window.closeDrawer=closeDrawer;
if($('btn-drawer-menu')){
  $('btn-drawer-menu').addEventListener('click',e=>{
    e.stopPropagation();
    const w=$('drawer-menu-wrap');
    if(!w)return;
    const on=w.classList.toggle('open');
    $('btn-drawer-menu').setAttribute('aria-expanded',on?'true':'false');
  });
  document.addEventListener('click',e=>{
    const w=$('drawer-menu-wrap');
    if(w&&w.classList.contains('open')&&!w.contains(e.target)){
      w.classList.remove('open');
      $('btn-drawer-menu').setAttribute('aria-expanded','false');
    }
  });
}
for(const btn of document.querySelectorAll('[data-drawer-btn]')){
  const focusId={ 'hdr-task-summary':'task-search', 'goal-name-btn':'name' }[btn.id];
  btn.addEventListener('click',()=>openDrawer(btn.dataset.drawerBtn,btn,focusId?$(focusId):null));
}
if($('drawer-close-btn'))$('drawer-close-btn').addEventListener('click',()=>closeDrawer(true));
if($('drawer-backdrop'))$('drawer-backdrop').addEventListener('click',()=>closeDrawer(true));
if($('goal-pick-btn'))$('goal-pick-btn').addEventListener('click',()=>openDrawer('setup',$('goal-pick-btn'),$('task-search')));
if($('reason-more-btn')){
  $('reason-more-btn').addEventListener('click',()=>{
    const hist=$('sec-notice-history');
    if(hist){hist.open=true;hist.scrollIntoView({block:'start'});}
  });
}
if($('reason-expand-btn')){
  $('reason-expand-btn').addEventListener('click',()=>{
    const bar=$('start-reason-bar');
    if(!bar)return;
    bar.classList.toggle('expanded');
    if(typeof renderNoticeBar==='function')renderNoticeBar();
  });
}
if($('reason-close-btn')){
  $('reason-close-btn').addEventListener('click',()=>{
    if(typeof dismissTopNotice==='function')dismissTopNotice();
  });
}
if($('hdr-refresh-btn'))$('hdr-refresh-btn').addEventListener('click',()=>{
  if(typeof setActivity==='function')setActivity('상태·카메라 새로고침 중...','muted',f?.arm?.value||'');
  pollStatus();
  pollCameras();
});
if($('hdr-help-btn'))$('hdr-help-btn').addEventListener('click',()=>{
  const sec=$('sec-shortcuts');
  if(!sec)return;
  sec.open=true;
  sec.scrollIntoView({block:'nearest'});
});
f.arm.addEventListener('change',()=>{
  for(const cb of document.querySelectorAll('#cal-robot-list input, #cal-leader-list input'))cb.checked=false;
  applyArmRules(true);
  if(typeof renderCamGuide==='function')renderCamGuide();
  updateCameraRecordingMask();
  pollCameras();
  validateStart();
});
f.caps.addEventListener('change',()=>{renderCapsEditor();validateStart();});
f.task.addEventListener('change',()=>{
  window.zoneSwapped=false;
  renderTaskListbox();
  updateTaskSummary();
  renderConfigMeta();
  autoCollectionName();
  validateStart();
  const sbScroll=$('bench-sidebar-scroll');
  if(sbScroll)sbScroll.scrollTop=0;
});
f.name.addEventListener('input',()=>{
  nameManuallyEdited=Boolean(f.name.value.trim());
  validateStart();
});
f.name.addEventListener('change',validateStart);
for(const el of [f.rig_revision]){
  el.addEventListener('input',validateStart);
  el.addEventListener('change',validateStart);
}
f.config.addEventListener('change',()=>{renderConfigMeta();updateCameraRecordingMask();validateStart();});
$('cal-robot-list').addEventListener('change',validateStart);
$('cal-leader-list').addEventListener('change',validateStart);

function isEditableTarget(el){
  if(!el)return false;
  const tag=el.tagName;
  return tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT'||Boolean(el.isContentEditable);
}
const DRAWER_KEYS={'1':['setup','btn-drawer-setup'],'2':['bindings','btn-drawer-bindings'],'3':['start','btn-drawer-start'],'4':['records','btn-drawer-records']};
async function keyboardStop(){
  if(stopInFlight)return;
  stopRequestVersion++;
  stopInFlight=true;setReqError('');
  if(typeof setActivity==='function')setActivity('정지 요청 중...','warn','');
  try{
    const st=await api('/stop',{});renderStatus(st);
    if(typeof setActivity==='function')setActivity('정지 요청 전달 완료',st.stopped===false?'muted':'good',st.stop_result?.message||(STATUS_MAP[st.status]?.[0]||st.status||''));
  }catch(err){
    setReqError('정지 요청: '+err.message);
    if(typeof setActivity==='function')setActivity('정지 요청 실패','crit',err.message);
  }
  finally{stopInFlight=false;syncHeaderAndSlimBar();}
}
document.addEventListener('keydown',e=>{
  if(e.repeat)return;
  const editable=isEditableTarget(e.target);
  const low=String(e.key||'').toLowerCase();
  if((e.ctrlKey&&e.key==='Enter')||(e.altKey&&low==='s')){
    if(window.benchStartReady&&currentBenchPhase()==='setup'){e.preventDefault();f.requestSubmit();}
    return;
  }
  if(e.key==='Escape'||(e.altKey&&low==='x')){
    /* The page never decides from its last-known status whether a stop is meaningful: the server does (it records a cancel for a coming auto home and
       answers plainly when nothing runs). Only an open drawer takes the first Esc; Alt+X always sends. */
    if(e.key==='Escape'&&$('side-drawer-host')&&!$('side-drawer-host').hidden){e.preventDefault();closeDrawer(true);}
    else{e.preventDefault();keyboardStop();}
    return;
  }
  if(e.altKey&&low==='r'){
    const rb=$('toggle-reverse-btn');if(rb&&!rb.disabled){e.preventDefault();rb.click();}
    return;
  }
  if(e.altKey&&low==='w'){
    const sb=$('swap-zones-btn');if(sb&&!sb.disabled){e.preventDefault();sb.click();}
    return;
  }
  if(e.ctrlKey||e.metaKey||e.altKey||editable)return;
  if(e.key==='/'){
    if(benchSessionActive())return;
    openDrawer('setup',$('btn-drawer-setup'),$('task-search'));
    setTaskListOpen(true);
    const ts=$('task-search');if(ts){e.preventDefault();ts.focus();ts.select();}
  }else if(e.code==='Space'||e.key===' '){
    if(e.target&&e.target.closest&&e.target.closest('button, [role="button"], a, summary'))return;
    const rb=$('hdr-prepare-btn').hidden?$('hdr-record-btn'):$('hdr-prepare-btn');
    if(!rb.hidden&&!rb.disabled){e.preventDefault();rb.click();}
  }else if(e.key==='ArrowRight'||(!e.shiftKey&&low==='n')){
    const nb=$('hdr-next-ep-btn');if(nb&&!nb.disabled){e.preventDefault();nb.click();}
  }else if(e.key==='ArrowLeft'||(!e.shiftKey&&low==='r')){
    const rb=$('hdr-rerecord-btn');if(rb&&!rb.disabled){e.preventDefault();rb.click();}
  }else if(e.shiftKey&&low==='r'){
    const rfb=$('hdr-refresh-btn');if(rfb&&!rfb.disabled){e.preventDefault();rfb.click();}
  }else if(e.shiftKey&&low==='c'){
    const cb=$('hdr-camera-restart-btn');if(!cb.disabled){e.preventDefault();cb.click();}
  }else if(!e.shiftKey&&low==='h'){
    const hb=currentBenchPhase()==='result'?$('hdr-result-home-btn'):$('hdr-home-btn');
    if(hb&&!hb.hidden&&!hb.disabled){e.preventDefault();hb.click();}
  }else if(!e.shiftKey&&low==='c'){
    if(camLabels.length>1){e.preventDefault();cyclePrimaryCam();}
  }else if(!e.shiftKey&&low==='m'){
    const sb=$('hdr-sound-btn');if(sb){e.preventDefault();sb.click();}
  }else if(!e.shiftKey&&low==='x'){
    const cb=$('reason-close-btn');if(cb&&!cb.hidden){e.preventDefault();cb.click();}
  }else if(e.key==='?'){
    const hb=$('hdr-help-btn');if(hb){e.preventDefault();hb.click();}
  }else if(!e.shiftKey&&DRAWER_KEYS[e.key]){
    const [dName,btnId]=DRAWER_KEYS[e.key];
    const btn=$(btnId);
    if(btn&&!btn.disabled){e.preventDefault();openDrawer(dName,btn);}
  }
});

function bumpCollectionName(prevName){
  let cur=f.name.value.trim();
  if(!cur&&typeof autoCollectionName==='function')autoCollectionName();
  cur=f.name.value.trim();
  const inc=s=>{
    const m=s.match(/^(.*?)(\d+)$/);
    return m?(m[1]+String(Number(m[2])+1).padStart(m[2].length,'0')):(s?s+'-02':'');
  };
  let next=inc(cur);
  if(prevName&&next===prevName)next=inc(next);
  if(next)f.name.value=next.slice(0,64);
  nameManuallyEdited=Boolean(f.name.value.trim());
  validateStart();
}
window.bumpCollectionName=bumpCollectionName;
$('next-ep-btn').addEventListener('click',()=>bumpCollectionName());

$('copy-transfer-btn').addEventListener('click',async()=>{
  const folder=(lastStatus&&lastStatus.folder)?lastStatus.folder.split('/').pop():'<session-folder>';
  const cmd='python tools/remote/omx_collection_transfer.py --session '+folder;
  try{await navigator.clipboard.writeText(cmd);$('copy-transfer-btn').textContent='복사됨: '+folder;}
  catch(_){setReqError('수동 실행 명령: '+cmd);}
});

f.addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.ctrlKey&&e.target.tagName==='INPUT'&&e.target.type==='text')e.preventDefault();
  if(e.repeat&&(e.key==='Enter'||e.key===' '))e.preventDefault();
});

f.addEventListener('submit',e=>{e.preventDefault();startBench('/start');});
$('hdr-prepare-btn').addEventListener('click',()=>startBench('/prepare'));
$('hdr-start-now-btn').addEventListener('click',()=>f.requestSubmit());

async function startBench(path,opts){
  validateStart();
  if(!window.benchStartReady||currentBenchPhase()!=='setup')return;
  setReqError('');
  const lp={};
  const sEp=$('lp-episodes')?.value?.trim()||'', sEt=$('lp-ep-time')?.value?.trim()||'', sRt=$('lp-reset-time')?.value?.trim()||'';
  if(sEp){const v=Number(sEp);if(!Number.isInteger(v)||v<1||v>500){setReqError('에피소드 수(num_episodes)는 1~500 정수여야 합니다.');return;}lp.num_episodes=v;}
  if(sEt){const v=Number(sEt);if(!Number.isFinite(v)||v<1||v>3600){setReqError('에피소드 시간(episode_time_s)은 1~3600초여야 합니다.');return;}lp.episode_time_s=v;}
  if(sRt){const v=Number(sRt);if(!Number.isFinite(v)||v<0.5||v>600){setReqError('리셋 시간(reset_time_s)은 0.5~600초여야 합니다.');return;}lp.reset_time_s=v;}
  const revOn=$('toggle-reverse-btn')?.getAttribute('aria-pressed')==='true';
  const body={
    arm:f.arm.value,
    name:f.name.value.trim(),
    rig_revision:f.rig_revision.value.trim(),
    config:f.config.value,
    caps:f.caps.value,
    task:f.task.value,
    replay:$('replay')?.value||'',
    replay_mode:revOn?($('reverse-mode')?.value||'swap_ab'):'none',
    invert_gripper:Boolean($('invert-gripper')?.checked),
    task_override:window.zoneSwapped?{swap_pick_place:true}:null,
    align_leader:Boolean($('align-leader')?.checked),
    home_before_start:Boolean(!opts?.skipHome&&f.arm.value!=='arm_ab'&&!($('replay')?.value)),
    fold_unfolded:Boolean(!opts?.skipHome&&f.arm.value!=='arm_ab'&&!($('replay')?.value)),
    lerobot_params:lp,
    calibrations:[...document.querySelectorAll('#cal-robot-list input:checked:not(:disabled), #cal-leader-list input:checked:not(:disabled)')].map(i=>i.value)
  };
  saveArmPreset();
  startInFlight=true;
  const stopVersion=stopRequestVersion;
  const seq=++latestStatusSeq;
  validateStart();
  const actionLabel=path==='/prepare'?'연동 준비 시작':'녹화 시작';
  if(typeof setActivity==='function')setActivity(actionLabel+' 요청 중...','live',[body.arm,body.name].filter(Boolean).join(' · '));
  try{
    const st=await api(path,body);
    lastStartMeta={key:sessionKey(st),name:body.name,arm:body.arm,task:body.task,
      episodeTime:lp.episode_time_s??choices?.task_cards?.[body.task]?.episode_time_s??choices?.config_meta?.[body.config]?.episode_time_s};
    if(seq===latestStatusSeq&&stopVersion===stopRequestVersion&&st.status)renderStatus(st);
    await pollStatus();
    if(typeof setActivity==='function')setActivity(actionLabel+' 시작됨','good',[body.arm,st?.status?(STATUS_MAP[st.status]?.[0]||st.status):''].filter(Boolean).join(' · '));
  }catch(err){
    setReqError(err.message);
    if(typeof setActivity==='function')setActivity(actionLabel+' 실패','crit',err.message);
    if(typeof benchBeep==='function')benchBeep('warn');
  }finally{
    startInFlight=false;
    validateStart();
  }
}
window.startBench=startBench;
