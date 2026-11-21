async function pollArms(){
  try{const res=await api('/api/arms');if(res&&res.arms){lastArmsStatus=res.arms;validateStart();}}catch(_){}
}
if($('hdr-home-btn')){
  $('hdr-home-btn').addEventListener('click',async()=>{
    const btn=$('hdr-home-btn');
    const incL=Boolean(lastArmsStatus&&f.arm.value&&lastArmsStatus[f.arm.value]?.has_leader_pose&&$('home-include-leader')?.checked);
    poseInFlight=true;btn.disabled=true;btn.textContent='홈 이동 중...';validateStart();
    try{
      setReqError('');
      const st=await api('/home',{arm:f.arm.value,include_leader:incL});
      renderStatus(st);
      poseFeedbackMsg='홈(이니셜) 위치 이동 완료: '+((st.home_moved||[]).join(', ')||f.arm.value)+(incL?' (리더 토크 OFF 복구됨)':'');
      poseFeedbackUntil=Date.now()+6000;
      setNotice('pose-feedback','good',poseFeedbackMsg,{ttlMs:6000});
    }catch(err){setReqError(err.message);}
    finally{poseInFlight=false;btn.textContent='홈 이동';validateStart();}
  });
}
if($('home-include-leader'))$('home-include-leader').addEventListener('change',validateStart);
if($('save-leader-pose-btn')){
  $('save-leader-pose-btn').addEventListener('click',async()=>{
    const btn=$('save-leader-pose-btn');
    poseInFlight=true;btn.disabled=true;btn.textContent='읽는 중...';validateStart();
    try{
      setReqError('');
      const st=await api('/save_leader_pose',{arm:f.arm.value});
      renderStatus(st);
      poseFeedbackMsg='리더 홈 포즈 저장 완료 ('+Object.keys(st.leader_pose_saved||{}).join(', ')+')';
      poseFeedbackUntil=Date.now()+6000;
      setNotice('pose-feedback','good',poseFeedbackMsg,{ttlMs:6000});
      pollArms();
    }catch(err){setReqError(err.message);}
    finally{poseInFlight=false;btn.textContent='리더 포즈 저장';validateStart();}
  });
}
if($('save-init-pose-btn')){
  $('save-init-pose-btn').addEventListener('click',async()=>{
    const btn=$('save-init-pose-btn');
    poseInFlight=true;btn.disabled=true;btn.textContent='저장 중...';validateStart();
    try{
      setReqError('');
      const st=await api('/save_initial_pose',{arm:f.arm.value});
      renderStatus(st);
      const sv=st.initial_pose_saved||{};
      const txt=Object.entries(sv).map(([k,v])=>k+': ['+v.join(', ')+']').join(' / ');
      poseFeedbackMsg='이니셜 포즈 저장 완료: '+txt;
      poseFeedbackUntil=Date.now()+6000;
      setNotice('pose-feedback','good',poseFeedbackMsg,{ttlMs:6000});
      pollArms();
    }catch(err){setReqError(err.message);}
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
  if(!host||(BUSY.has(lastStatus?.status)&&name!=='records'))return;
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
if($('hdr-refresh-btn'))$('hdr-refresh-btn').addEventListener('click',()=>{pollStatus();pollCameras();});
if($('hdr-help-btn'))$('hdr-help-btn').addEventListener('click',()=>{
  const sec=$('sec-shortcuts');
  if(!sec)return;
  sec.open=true;
  sec.scrollIntoView({block:'nearest'});
});
if($('hdr-next-ep-btn'))$('hdr-next-ep-btn').addEventListener('click',()=>{
  if(typeof setNotice==='function')setNotice('start-reasons','warn','서버 요청 없음: POST /api/episode/next (다음 에피소드)');
});
if($('hdr-rerecord-btn'))$('hdr-rerecord-btn').addEventListener('click',()=>{
  if(typeof setNotice==='function')setNotice('start-reasons','warn','서버 요청 없음: POST /api/episode/rerecord (다시 녹화)');
});
f.arm.addEventListener('change',()=>{
  for(const cb of document.querySelectorAll('#cal-robot-list input, #cal-leader-list input'))cb.checked=false;
  applyArmRules(true);
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
  stopInFlight=true;setReqError('');
  try{
    const st=await api('/stop',{});renderStatus(st);
    if(st&&st.stop_result&&st.stop_result.stopped===false)setNotice('stop-result','info',st.stop_result.message,{ttlMs:4000});
  }catch(err){setReqError('정지 요청: '+err.message);}
  finally{stopInFlight=false;syncHeaderAndSlimBar();}
}
document.addEventListener('keydown',e=>{
  if(e.repeat)return;
  const editable=isEditableTarget(e.target);
  const low=String(e.key||'').toLowerCase();
  if((e.ctrlKey&&e.key==='Enter')||(e.altKey&&low==='s')){
    if(window.benchStartReady&&!BUSY.has(lastStatus?.status)){e.preventDefault();f.requestSubmit();}
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
    if(BUSY.has(lastStatus?.status))return;
    openDrawer('setup',$('btn-drawer-setup'),$('task-search'));
    setTaskListOpen(true);
    const ts=$('task-search');if(ts){e.preventDefault();ts.focus();ts.select();}
  }else if(e.code==='Space'||e.key===' '){
    if(e.target&&e.target.closest&&e.target.closest('button, [role="button"], a, summary'))return;
    const rb=$('hdr-record-btn');if(rb&&!rb.disabled){e.preventDefault();rb.click();}
  }else if(e.key==='ArrowRight'||(!e.shiftKey&&low==='n')){
    const nb=$('hdr-next-ep-btn');if(nb&&!nb.disabled){e.preventDefault();nb.click();}
  }else if(e.key==='ArrowLeft'||(!e.shiftKey&&low==='r')){
    const rb=$('hdr-rerecord-btn');if(rb&&!rb.disabled){e.preventDefault();rb.click();}
  }else if(e.shiftKey&&low==='r'){
    const rfb=$('hdr-refresh-btn');if(rfb&&!rfb.disabled){e.preventDefault();rfb.click();}
  }else if(!e.shiftKey&&low==='h'){
    const hb=$('hdr-home-btn');if(hb&&!hb.disabled){e.preventDefault();hb.click();}
  }else if(!e.shiftKey&&low==='c'){
    if(camLabels.length>1){e.preventDefault();cyclePrimaryCam();}
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

$('next-ep-btn').addEventListener('click',()=>{
  const cur=f.name.value.trim();
  const m=cur.match(/^(.*?)(\d+)$/);
  if(m)f.name.value=m[1]+String(Number(m[2])+1).padStart(m[2].length,'0');
  else if(cur)f.name.value=cur+'-02';
  nameManuallyEdited=Boolean(f.name.value.trim());
  validateStart();
});

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

f.addEventListener('submit',async e=>{
  e.preventDefault();
  if(startInFlight||!validateStart())return;
  startInFlight=true;
  setReqError('');
  validateStart();
  const lp={};
  const sEp=$('lp-episodes')?.value?.trim()||'', sEt=$('lp-ep-time')?.value?.trim()||'', sRt=$('lp-reset-time')?.value?.trim()||'';
  if(sEp){const v=Number(sEp);if(!Number.isInteger(v)||v<1||v>500){setReqError('에피소드 수(num_episodes)는 1~500 정수여야 합니다.');startInFlight=false;validateStart();return;}lp.num_episodes=v;}
  if(sEt){const v=Number(sEt);if(!Number.isFinite(v)||v<1||v>3600){setReqError('에피소드 시간(episode_time_s)은 1~3600초여야 합니다.');startInFlight=false;validateStart();return;}lp.episode_time_s=v;}
  if(sRt){const v=Number(sRt);if(!Number.isFinite(v)||v<0.5||v>600){setReqError('리셋 시간(reset_time_s)은 0.5~600초여야 합니다.');startInFlight=false;validateStart();return;}lp.reset_time_s=v;}
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
    lerobot_params:lp,
    calibrations:[...document.querySelectorAll('#cal-robot-list input:checked:not(:disabled), #cal-leader-list input:checked:not(:disabled)')].map(i=>i.value)
  };
  const seq=++latestStatusSeq;
  try{
    const st=await api('/start',body);
    if(seq!==latestStatusSeq)return;
    saveArmPreset();
    lastStartMeta={key:sessionKey(st),name:body.name,arm:body.arm,task:body.task};
    renderStatus(st);
  }catch(err){
    setReqError(err.message);
  }finally{
    startInFlight=false;
    validateStart();
  }
});
