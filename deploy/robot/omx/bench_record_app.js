function updateCameraRecordingMaskHook(){if(typeof updateCameraRecordingMask==='function')updateCameraRecordingMask();}
let camLabels=[];
let lastCamState=null;
let primaryCam='';
let lastCamArm='';
let cameraRestartInFlight=false;

function canRestartCameras(){
  const st=lastStatus;
  return statusLoaded&&Boolean(f.arm.value)&&!benchSessionActive()&&!poseInFlight&&
    !startInFlight&&!stopInFlight&&!cameraRestartInFlight&&
    !st.active_locks?.length&&(st.status==='idle'||ENDED.has(st.status)||st.phase==='result');
}

$('hdr-camera-restart-btn').addEventListener('click',async()=>{
  if(!canRestartCameras())return;
  cameraRestartInFlight=true;
  validateStart();
  setReqError('');
  if(typeof setActivity==='function')setActivity('카메라 재시작 요청 중...','live',f.arm.value);
  try{
    const result=await api('/api/cameras/restart',{arm:f.arm.value});
    const failed=Object.entries(result.units||{}).filter(([,unit])=>!unit.restarted||!unit.active).map(([unit])=>unit);
    setNotice('camera-restart',result.ok?'good':'warn',
      result.ok?'카메라 재시작 완료':'카메라 재시작 실패'+(failed.length?': '+failed.join(', '):''));
    if(typeof setActivity==='function')setActivity(result.ok?'카메라 재시작 완료':'카메라 재시작 실패',result.ok?'good':'warn',failed.length?failed.join(', '):f.arm.value);
  }catch(err){
    setReqError('카메라 재시작: '+err.message);
    if(typeof setActivity==='function')setActivity('카메라 재시작 오류','crit',err.message);
  }
  finally{
    cameraRestartInFlight=false;
    await pollStatus();
    validateStart();
    pollCameras();
  }
});

function previewCamsForArm(allLabels,arm){
  const allowed=(typeof ARM_PREVIEW_CAMS!=='undefined'&&arm)?ARM_PREVIEW_CAMS[arm]:null;
  if(!allowed)return allLabels;
  const filtered=allLabels.filter(l=>allowed.has(l));
  return filtered.length?filtered:allLabels;
}
function defaultPrimaryCam(labels,arm){
  const want=arm==='arm_s'?'arm_s_top':'top';
  return labels.includes(want)?want:(labels[0]||'');
}
function applyCameraLayout(){
  const grid=$('cam-grid');
  if(!grid||!camLabels.length)return;
  if(!primaryCam||!camLabels.includes(primaryCam)){
    primaryCam=defaultPrimaryCam(camLabels,f&&f.arm?f.arm.value:'');
  }
  const boxes=new Map();
  for(const b of grid.querySelectorAll('.cam-box[data-cam-box]'))boxes.set(b.dataset.camBox,b);
  let stack=grid.querySelector('.cam-pip-stack');
  const pBox=boxes.get(primaryCam);
  if(pBox){
    pBox.classList.remove('cam-pip');
    pBox.classList.add('cam-primary');
    pBox.removeAttribute('tabindex');
    pBox.removeAttribute('role');
    pBox.removeAttribute('aria-label');
    grid.insertBefore(pBox,stack||null);
  }
  const secs=camLabels.filter(l=>l!==primaryCam);
  if(secs.length){
    if(!stack){stack=document.createElement('div');stack.className='cam-pip-stack';grid.append(stack);}
    for(const l of secs){
      const b=boxes.get(l);
      if(!b)continue;
      b.classList.remove('cam-primary');
      b.classList.add('cam-pip');
      b.tabIndex=0;
      b.setAttribute('role','button');
      b.setAttribute('aria-label',l+' 주 화면으로 전환');
      stack.append(b);
    }
  }else if(stack){
    stack.remove();
  }
}
function switchPrimaryCam(lbl){
  if(!lbl||!camLabels.includes(lbl)||lbl===primaryCam)return;
  primaryCam=lbl;
  applyCameraLayout();
}
function cyclePrimaryCam(){
  if(camLabels.length<2)return;
  const idx=camLabels.indexOf(primaryCam);
  switchPrimaryCam(camLabels[(idx+1)%camLabels.length]);
}
function syncPrimaryCamForArm(arm){
  const nextArm=arm||'';
  if(nextArm===lastCamArm)return;
  lastCamArm=nextArm;
  if(camLabels.length){
    primaryCam=defaultPrimaryCam(camLabels,lastCamArm);
    applyCameraLayout();
  }
}
window.defaultPrimaryCam=defaultPrimaryCam;
window.switchPrimaryCam=switchPrimaryCam;
window.syncPrimaryCamForArm=syncPrimaryCamForArm;

let emptyCamPolls=0;
const camFrameBusy=new Map();

function tickCameraFrames(){
  const grid=$('cam-grid');
  if(!grid||!camLabels.length)return;
  const ts=Date.now();
  for(const img of grid.querySelectorAll('img[data-cam]')){
    const lbl=img.dataset.cam;
    if(!lbl||camFrameBusy.get(lbl))continue;
    camFrameBusy.set(lbl,true);
    const url='/camera/'+encodeURIComponent(lbl)+'.jpg?t='+ts;
    const nextImg=new Image();
    const commit=()=>{
      camFrameBusy.delete(lbl);
      if(!img.isConnected)return;
      nextImg.alt=img.alt;
      nextImg.dataset.cam=lbl;
      if(img.className)nextImg.className=img.className;
      nextImg.style.display='block';
      img.replaceWith(nextImg);
    };
    nextImg.onload=()=>{
      if(typeof nextImg.decode==='function')nextImg.decode().then(commit,commit);
      else commit();
    };
    nextImg.onerror=()=>{camFrameBusy.delete(lbl);};
    nextImg.src=url;
  }
}

async function pollCameras(){
  const grid=$('cam-grid'), note=$('cam-note');
  try{
    const st=await api('/cameras.json');
    lastCamState=st||{};
    const curArm=(typeof benchSessionActive==='function'&&benchSessionActive()&&lastStatus?.arm)?lastStatus.arm:(f&&f.arm?f.arm.value:'');
    const labels=previewCamsForArm(Object.keys(lastCamState),curArm);
    const hdrCam=$('hdr-cam-health');
    if(!labels.length){
      emptyCamPolls++;
      note.textContent=benchSessionActive()
        ? '녹화 카메라 프레임 대기 중'
        : '카메라 뷰어(8767)가 대기 중이거나 연결된 카메라가 없습니다.';
      if(!camLabels.length||emptyCamPolls>=3){
        if(hdrCam){hdrCam.textContent='카메라 0대';hdrCam.dataset.tone='warn';hdrCam.removeAttribute('title');}
        grid.innerHTML='';camLabels=[];
      }
      return;
    }
    emptyCamPolls=0;
    const freshCnt=labels.filter(l=>lastCamState[l]?.fresh!==false).length;
    if(hdrCam){hdrCam.textContent='카메라 '+freshCnt+'/'+labels.length+'대';hdrCam.dataset.tone=freshCnt===labels.length?'good':'warn';}
    if(hdrCam)hdrCam.title=labels.join(', ');
    note.textContent='실시간 미리보기 ('+labels.join(', ')+')';
    if(labels.join(',')!==camLabels.join(',')){
      camLabels=labels;
      grid.innerHTML='';
      for(const lbl of labels){
        const box=document.createElement('div');box.className='cam-box';box.dataset.camBox=lbl;
        const title=document.createElement('span');title.className='cam-title-pill';title.textContent=lbl+' ('+(st[lbl]?.quality?.condition||'확인 중')+')';
        const rec=document.createElement('span');rec.className='cam-rec-badge on';rec.textContent='● 녹화';
        const tag=document.createElement('span');tag.className='cam-tag';tag.hidden=true;
        const img=document.createElement('img');img.alt=lbl+' 카메라 (프레임 대기 중)';img.dataset.cam=lbl;
        img.style.display='none';
        box.append(title,rec,tag,img);
        box.addEventListener('click',()=>{if(box.classList.contains('cam-pip'))switchPrimaryCam(lbl);});
        box.addEventListener('keydown',e=>{if(box.classList.contains('cam-pip')&&(e.key==='Enter'||e.key===' ')){e.preventDefault();switchPrimaryCam(lbl);}});
        grid.append(box);
      }
      if(!primaryCam||!labels.includes(primaryCam)||curArm!==lastCamArm){
        lastCamArm=curArm;
        primaryCam=defaultPrimaryCam(labels,curArm);
      }
      applyCameraLayout();
      tickCameraFrames();
    }else{
      for(const box of grid.querySelectorAll('.cam-box[data-cam-box]')){
        const lbl=box.dataset.camBox;
        const info=st[lbl];
        const pill=box.querySelector('.cam-title-pill');
        if(pill)pill.textContent=lbl+' ('+(info?.fresh===false?'지연':(info?.quality?.condition||'정상'))+')';
      }
      if(curArm!==lastCamArm)syncPrimaryCamForArm(curArm);
    }
    updateCameraRecordingMask();
  }catch(_){
    note.textContent='카메라 미리보기를 불러오지 못했습니다.';
  }
}

async function pollStatus(){
  const seq=++latestStatusSeq;
  try{
    const st=await api('/status.json');
    if(seq!==latestStatusSeq)return;
    clearNotice('conn-error');
    renderStatus(st);
  }catch(err){
    if(seq!==latestStatusSeq)return;
    const inActive=benchSessionActive();
    setNotice('conn-error',inActive?'warn':'crit','상태 조회 오류: '+(err.message||'네트워크 오류')+(inActive?' (중지 버튼 접근은 유지됩니다)':''),{persistent:!inActive});
    if(!inActive){
      statusLoaded=false;
    }
    validateStart();
  }
}

function saveArmPreset(){
  const arm=f.arm.value;
  if(!arm)return;
  const data={
    task:f.task.value,
    rig_revision:f.rig_revision.value.trim(),
    config:f.config.value,
    caps:f.caps.value,
    calibrations:[...document.querySelectorAll('#cal-robot-list input:checked:not(:disabled), #cal-leader-list input:checked:not(:disabled)')].map(i=>i.value)
  };
  try{localStorage.setItem('omx_bench_preset_'+arm,JSON.stringify(data));}catch(_){}
}

let nameManuallyEdited=false;
function autoCollectionName(){
  if(nameManuallyEdited&&f.name.value.trim())return;
  const arm=f.arm.value;
  if(!arm)return;
  const t=f.task.value;
  const c=choices&&choices.task_cards&&t?choices.task_cards[t]:null;
  const tid=(c&&c.valid&&c.task_id)?String(c.task_id):'teleop';
  const d=new Date();
  const mm=String(d.getMonth()+1).padStart(2,'0'), dd=String(d.getDate()).padStart(2,'0');
  const hh=String(d.getHours()).padStart(2,'0'), mi=String(d.getMinutes()).padStart(2,'0');
  let raw=(tid+'-'+arm+'-'+mm+dd+'-'+hh+mi).toLowerCase().replace(/[^a-z0-9-]+/g,'-').replace(/-{2,}/g,'-').replace(/^-+|-+$/g,'');
  raw=raw.slice(0,64).replace(/-+$/,'');
  if(raw.length<3)raw=(raw+'-01').slice(0,64);
  f.name.value=raw;
  nameManuallyEdited=false;
}

function applyPresetOrRecommended(preferRec){
  const arm=f.arm.value;
  if(!arm||!choices)return;
  let preset=null;
  if(!preferRec){
    try{preset=JSON.parse(localStorage.getItem('omx_bench_preset_'+arm)||'null');}catch(_){}
  }
  const rec=choices.recommended?choices.recommended[arm]:null;
  const src=preset||rec;
  if(!src&&!rec)return;
  if(src&&src.task&&[...f.task.options].some(o=>o.value===src.task&&!o.disabled)){f.task.value=src.task;renderTaskListbox();updateTaskSummary();}
  if(src&&src.rig_revision&&!f.rig_revision.value.trim())f.rig_revision.value=src.rig_revision;
  const pickOpt=(sel,val)=>Boolean(val&&[...sel.options].some(o=>o.value===val&&!o.disabled));
  if(pickOpt(f.config,src?.config))f.config.value=src.config;
  else if(pickOpt(f.config,rec?.config))f.config.value=rec.config;
  if(pickOpt(f.caps,src?.caps))f.caps.value=src.caps;
  else if(pickOpt(f.caps,rec?.caps))f.caps.value=rec.caps;
  const calList=(Array.isArray(src?.calibrations)&&src.calibrations.length)?src.calibrations:(rec?.calibrations||[]);
  if(Array.isArray(calList)&&calList.length){
    const want=new Set(calList);
    const cbs=[...document.querySelectorAll('#cal-robot-list input:not(:disabled), #cal-leader-list input:not(:disabled)')];
    if(cbs.some(cb=>want.has(cb.value))){
      for(const cb of cbs)cb.checked=want.has(cb.value);
    }else if(rec&&Array.isArray(rec.calibrations)){
      const rWant=new Set(rec.calibrations);
      for(const cb of cbs)cb.checked=rWant.has(cb.value);
    }
  }
  autoCollectionName();
  renderCapsEditor();
  renderConfigMeta();
  updateCameraRecordingMask();
  validateStart();
}

function syncArmPillsUI(){
  const cur=f.arm.value;
  for(const btn of document.querySelectorAll('#rail-arm-pills button[data-arm]')){
    const on=btn.dataset.arm===cur;
    btn.classList.toggle('active',on);
    btn.setAttribute('aria-pressed',on?'true':'false');
  }
  if(typeof renderArmCards==='function')renderArmCards();
}

function syncArmSelection(){
  const picked=[...$('arm-checks').querySelectorAll('input:checked')].map(i=>i.value).sort();
  let mapped='';
  if(picked.length===1)mapped=picked[0];
  else if(picked.length===2&&picked[0]==='arm_a'&&picked[1]==='arm_b')mapped='arm_ab';
  else if(picked.length>1)mapped='__unsupported__';
  if(mapped&&mapped!=='__unsupported__'&&[...f.arm.options].some(o=>o.value===mapped))f.arm.value=mapped;
  else f.arm.value='';
  window.mapZone=null;
  window.shipHold=null;
  window.standDir='to-ship';
  window.zoneSwapped=false;
  if(typeof window.clearMapNote==='function')window.clearMapNote();
  syncArmPillsUI();
  if(mapped==='__unsupported__'){
    $('arm-note').textContent='다중 선택은 현재 arm_a + arm_b(양팔 동시)만 지원합니다. arm_s는 단독으로 선택하세요.';
  }
  for(const cb of document.querySelectorAll('#cal-robot-list input, #cal-leader-list input'))cb.checked=false;
  applyArmRules(true);
  applyPresetOrRecommended(false);
  if(f.task.value&&choices?.task_cards&&typeof window.taskFitsArm==='function'&&!window.taskFitsArm(f.task.value,choices.task_cards[f.task.value],f.arm.value)){
    f.task.value='';
    autoCollectionName();
  }
  renderTaskListbox();
  updateTaskSummary();
  pollCameras();
  if(typeof renderArmCards==='function')renderArmCards();
  if(typeof renderParamsPanel==='function')renderParamsPanel();
  validateStart();
}

function selectArm(arm){
  if(!arm||![...f.arm.options].some(o=>o.value===arm))return;
  const want=arm==='arm_ab'?new Set(['arm_a','arm_b']):new Set([arm]);
  for(const cb of $('arm-checks').querySelectorAll('input[type="checkbox"]')){
    cb.checked=want.has(cb.value);
  }
  syncArmSelection();
}

function selectTask(val,opts){
  window.zoneSwapped=false;
  if(!(opts&&opts.keepMapZone)){
    window.shipHold=null;
    window.mapZone=null;
  }
  if(typeof window.clearMapNote==='function')window.clearMapNote();
  f.task.value=val||'';
  renderTaskListbox();
  updateTaskSummary();
  renderConfigMeta();
  autoCollectionName();
  validateStart();
  const sbScroll=$('bench-sidebar-scroll');
  if(sbScroll)sbScroll.scrollTop=0;
  if(typeof window.closeDrawer==='function')window.closeDrawer(true);
}

let taskFilter='all';
function taskMatchesFilter(v,c){
  if(taskFilter==='all')return true;
  const hay=(v+' '+(c.origin||'')+' '+(c.target_slot||'')+' '+(c.single_task||'')+' '+(c.raw||'')).toLowerCase();
  if(taskFilter==='pinky')return /pinky|belt|conveyor|supply/.test(hay);
  return typeof window.taskFitsArm==='function'?window.taskFitsArm(v,c,f.arm.value):true;
}
function stepTask(delta){
  const opts=[...($('task-listbox')?.querySelectorAll('.task-opt:not(:disabled)')||[])];
  if(!opts.length)return;
  const cur=opts.findIndex(o=>o.getAttribute('aria-selected')==='true');
  const next=cur<0?(delta>0?0:opts.length-1):(cur+delta+opts.length)%opts.length;
  opts[next].click();
  $('task-listbox')?.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'});
}
function setTaskListOpen(open){
  const box=$('task-listbox'),btn=$('task-toggle-btn');
  if(box&&btn){box.hidden=!open;btn.setAttribute('aria-expanded',String(open));btn.textContent=open?'목록 접기':'목록 펼치기';}
}

function renderTaskListbox(){
  const box=$('task-listbox');
  if(!box)return;
  const q=($('task-search')?.value||'').trim().toLowerCase();
  const cards=(choices&&choices.task_cards)?choices.task_cards:{};
  const tasks=choices&&Array.isArray(choices.tasks)?choices.tasks:[];
  box.innerHTML='';
  const addOpt=(val,title,sub,disabled)=>{
    const btn=document.createElement('button');
    btn.type='button';
    btn.className='task-opt';
    btn.setAttribute('role','option');
    btn.setAttribute('aria-selected',f.task.value===val?'true':'false');
    btn.disabled=Boolean(disabled);
    const top=document.createElement('div');top.className='task-opt-top';
    const sp1=document.createElement('span');sp1.className='mono';sp1.style.fontWeight='700';sp1.textContent=title;
    const sp2=document.createElement('span');sp2.className='quiet';sp2.style.fontSize='.78rem';sp2.textContent=disabled?'검증 실패':(f.task.value===val?'선택됨':'');
    top.append(sp1,sp2);
    btn.append(top);
    if(sub){
      const sb=document.createElement('div');sb.className='task-opt-sub';sb.textContent=sub;btn.append(sb);
    }
    if(!disabled)btn.addEventListener('click',()=>selectTask(val));
    box.append(btn);
  };
  if(!q)addOpt('','없음 (미지정)','과제 카드 없이 자유 녹화',false);
  for(const v of tasks){
    const c=cards[v]||{};
    if(!taskMatchesFilter(v,c))continue;
    const bad=c.valid===false;
    const meta=[c.origin,c.target_slot].filter(Boolean).join(' -> ');
    const hay=(v+' '+meta+' '+(c.single_task||'')).toLowerCase();
    if(q&&!hay.includes(q))continue;
    const sc=(lastStatus&&lastStatus.scenario_counts&&c.task_id)?lastStatus.scenario_counts[c.task_id]:null;
    const doneEp=sc?sc.episodes:0;
    const goalEp=c.num_episodes!=null?c.num_episodes:'?';
    const qInfo=typeof epQuota==='function'?epQuota(c):null;
    const prog=qInfo?('수집 '+qInfo.done+'/'+qInfo.goal+'회 · 남은 '+qInfo.rem+'회 · '):(c.task_id?('수집 '+doneEp+'/'+goalEp+'회 · '):'');
    const sub=prog+(meta?meta+' · ':'')+(c.single_task||(bad?(c.error||'형식 오류'):''));
    addOpt(v,v,sub,bad);
  }
}

async function loadChoices(){
  try{
    choices=await api('/choices.json');
    if(armContractValid()){
      for(const a of choices.arms)f.arm.append(new Option(a,a));
      const singles=choices.arms.filter(a=>a!=='arm_ab');
      const connMap=choices.arm_connectivity||{};
      const defaultArm=singles.find(a=>connMap[a]?.connected===true)||singles[0]||'';
      $('arm-checks').innerHTML='';
      for(const a of singles){
        const lbl=document.createElement('label');lbl.className='check-row';lbl.style.flex='1 1 110px';
        const cb=document.createElement('input');cb.type='checkbox';cb.value=a;cb.checked=(a===defaultArm);
        const sp=document.createElement('span');sp.className='mono';sp.textContent=a;
        lbl.append(cb,sp);$('arm-checks').append(lbl);
      }
      $('rail-arm-pills').innerHTML='';
      for(const a of choices.arms){
        const btn=document.createElement('button');btn.type='button';btn.className='pill-btn mono';btn.dataset.arm=a;
        btn.textContent=a==='arm_ab'?'arm_a+b':a;
        btn.addEventListener('click',()=>selectArm(a));
        $('rail-arm-pills').append(btn);
      }
      if(defaultArm)f.arm.value=defaultArm;
      syncArmPillsUI();
      if(typeof renderArmCards==='function')renderArmCards();
    }else{
      f.arm.append(new Option('미확인 (서버 계약 없음)',''));
      f.arm.disabled=true;
    }
    f.config.append(new Option('선택하세요',''));
    for(const v of (choices.configs||[]))f.config.append(new Option(v,v));
    f.caps.append(new Option('선택하세요',''));
    for(const v of (choices.caps||[]))f.caps.append(new Option(v,v));
    for(const v of (choices.tasks||[])){
      const c=choices.task_cards&&choices.task_cards[v];
      const bad=Boolean(c&&c.valid===false);
      const opt=new Option(v+(bad?' (검증 실패)':''),v);
      opt.disabled=bad;
      f.task.append(opt);
    }
    $('cal-robot-list').innerHTML='';
    $('cal-leader-list').innerHTML='';
    const meta=choices.cal_meta||{};
    for(const v of (choices.calibrations||[])){
      const lbl=document.createElement('label');lbl.className='check-row';
      const cb=document.createElement('input');cb.type='checkbox';cb.value=v;
      const p=v.split('/');
      const m=meta[v];
      const info=m?(' — '+m.role+' · '+m.joints+'관절 · '+m.updated):'';
      const sp=document.createElement('span');sp.className='mono';sp.textContent=p.slice(-2).join('/')+info;
      lbl.append(cb,sp);
      if(p[p.length-3]==='robots')$('cal-robot-list').append(lbl);
      else $('cal-leader-list').append(lbl);
    }
    applyArmRules(true);
    applyPresetOrRecommended(false);
    renderTaskListbox();
    updateTaskSummary();
    if(typeof renderArmCards==='function')renderArmCards();
    if(typeof renderParamsPanel==='function')renderParamsPanel();
    validateStart();
  }catch(err){
    setReqError('선택 목록을 불러오지 못했습니다: '+err.message);
  }
}

function init(){
  pollStatus();
  setInterval(pollStatus,2000);
  pollArms();
  if(typeof loadGripMaps==='function')loadGripMaps();
  pollCameras();
  setInterval(pollCameras,1500);
  setInterval(tickCameraFrames,150);
  loadChoices();
}

function renderConfigMeta(){
  const m=choices&&choices.config_meta?choices.config_meta[f.config.value]:null;
  const el=$('config-meta-note');
  if(!m){el.textContent='';return;}
  const parts=[];
  if(m.fps!=null)parts.push('기록 '+m.fps+' fps');
  if(m.use_degrees!=null)parts.push(m.use_degrees?'단위: degree':'단위: normalized (-100~100)');
  if(m.max_relative_target!=null)parts.push('스텝 제한: '+m.max_relative_target);
  if(Array.isArray(m.cameras)&&m.cameras.length)parts.push('카메라: '+m.cameras.join(', '));
  el.textContent=parts.join(' · ');
  const tc=(choices&&choices.task_cards&&f.task.value)?choices.task_cards[f.task.value]:null;
  const ep=tc&&tc.num_episodes!=null?tc.num_episodes:m.num_episodes;
  const et=tc&&tc.episode_time_s!=null?tc.episode_time_s:m.episode_time_s;
  const rt=tc&&tc.reset_time_s!=null?tc.reset_time_s:m.reset_time_s;
  if($('lp-episodes')&&ep!=null)$('lp-episodes').value=String(ep);
  if($('lp-ep-time')&&et!=null)$('lp-ep-time').value=String(et);
  if($('lp-reset-time')&&rt!=null)$('lp-reset-time').value=String(rt);
}

$('apply-rec-btn').addEventListener('click',()=>{
  for(const cb of document.querySelectorAll('#cal-robot-list input, #cal-leader-list input'))cb.checked=false;
  applyArmRules(true);
  applyPresetOrRecommended(true);
});

$('save-preset-btn').addEventListener('click',()=>{
  saveArmPreset();
  $('save-preset-btn').textContent='저장됨!';
  setTimeout(()=>{$('save-preset-btn').textContent='현재 설정 저장';},1500);
});

$('arm-checks').addEventListener('change',syncArmSelection);
let poseInFlight=false;
let poseFeedbackMsg='';
let poseFeedbackUntil=0;
let lastArmsStatus=null;
