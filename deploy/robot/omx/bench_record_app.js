function updateCameraRecordingMaskHook(){if(typeof updateCameraRecordingMask==='function')updateCameraRecordingMask();}
let camLabels=[];
let lastCamState=null;
async function pollCameras(){
  const grid=$('cam-grid'), note=$('cam-note');
  if(lastStatus&&(lastStatus.status==='handing_over'||lastStatus.status==='recording')){
    note.textContent='녹화 중에는 녹화기가 카메라를 직접 점유하므로 미리보기가 일시 중지됩니다.';
    grid.innerHTML='';camLabels=[];
    return;
  }
  try{
    const st=await api('/cameras.json');
    lastCamState=st||{};
    const labels=Object.keys(lastCamState);
    const hdrCam=$('hdr-cam-health');
    if(!labels.length){
      note.textContent='카메라 뷰어(8767)가 대기 중이거나 연결된 카메라가 없습니다.';
      if(hdrCam){hdrCam.textContent='카메라 0대';hdrCam.dataset.tone='warn';}
      grid.innerHTML='';camLabels=[];
      return;
    }
    const freshCnt=labels.filter(l=>lastCamState[l]?.fresh!==false).length;
    if(hdrCam){hdrCam.textContent='카메라 '+freshCnt+'/'+labels.length+'대';hdrCam.dataset.tone=freshCnt===labels.length?'good':'warn';}
    note.textContent='실시간 미리보기 ('+labels.join(', ')+')';
    if(labels.join(',')!==camLabels.join(',')){
      camLabels=labels;
      grid.innerHTML='';
      for(const lbl of labels){
        const box=document.createElement('div');box.className='cam-box';box.dataset.camBox=lbl;
        const title=document.createElement('div');title.className='mono quiet';title.textContent=lbl+' ('+(st[lbl]?.quality?.condition||'확인 중')+')';
        const rec=document.createElement('span');rec.className='cam-rec-badge on';rec.textContent='● 녹화';
        const tag=document.createElement('span');tag.className='cam-tag';tag.hidden=true;
        const img=document.createElement('img');img.alt=lbl+' 카메라 (프레임 대기 중)';img.dataset.cam=lbl;
        img.onerror=()=>{img.style.display='none';};img.onload=()=>{img.style.display='block';};
        box.append(title,rec,tag,img);grid.append(box);
      }
    }
    updateCameraRecordingMask();
    const ts=Date.now();
    for(const img of grid.querySelectorAll('img[data-cam]')){
      const camInfo=lastCamState[img.dataset.cam];
      if(camInfo&&camInfo.fresh===false){
        img.style.display='none';
        continue;
      }
      img.src='/camera/'+encodeURIComponent(img.dataset.cam)+'.jpg?t='+ts;
    }
  }catch(_){
    note.textContent='카메라 미리보기를 불러오지 못했습니다.';
  }
}

async function pollStatus(){
  const seq=++latestStatusSeq;
  try{
    const st=await api('/status.json');
    if(seq!==latestStatusSeq)return;
    $('conn-error').hidden=true;
    renderStatus(st);
  }catch(err){
    if(seq!==latestStatusSeq)return;
    const ce=$('conn-error');
    const inActive=Boolean(lastStatus&&(lastStatus.status==='handing_over'||lastStatus.status==='recording'));
    ce.textContent='상태 조회 오류: '+(err.message||'네트워크 오류')+(inActive?' (중지 버튼 접근은 유지됩니다)':'');
    ce.hidden=false;
    if(!inActive){
      statusLoaded=false;
      $('top-badge').textContent='연결 끊김';
      $('top-badge').dataset.tone='crit';
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

function applyPresetOrRecommended(preferRec){
  const arm=f.arm.value;
  if(!arm||!choices)return;
  let preset=null;
  if(!preferRec){
    try{preset=JSON.parse(localStorage.getItem('omx_bench_preset_'+arm)||'null');}catch(_){}
  }
  const rec=choices.recommended?choices.recommended[arm]:null;
  const src=preset||rec;
  if(!src)return;
  if(src.task&&[...f.task.options].some(o=>o.value===src.task&&!o.disabled)){f.task.value=src.task;renderTaskListbox();updateTaskSummary();}
  if(src.rig_revision)f.rig_revision.value=src.rig_revision;
  if(src.config&&[...f.config.options].some(o=>o.value===src.config&&!o.disabled))f.config.value=src.config;
  if(src.caps&&[...f.caps.options].some(o=>o.value===src.caps&&!o.disabled))f.caps.value=src.caps;
  if(Array.isArray(src.calibrations)){
    const want=new Set(src.calibrations);
    for(const cb of document.querySelectorAll('#cal-robot-list input:not(:disabled), #cal-leader-list input:not(:disabled)')){
      cb.checked=want.has(cb.value);
    }
  }
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
}

function syncArmSelection(){
  const picked=[...$('arm-checks').querySelectorAll('input:checked')].map(i=>i.value).sort();
  let mapped='';
  if(picked.length===1)mapped=picked[0];
  else if(picked.length===2&&picked[0]==='arm_a'&&picked[1]==='arm_b')mapped='arm_ab';
  else if(picked.length>1)mapped='__unsupported__';
  if(mapped&&mapped!=='__unsupported__'&&[...f.arm.options].some(o=>o.value===mapped))f.arm.value=mapped;
  else f.arm.value='';
  syncArmPillsUI();
  if(mapped==='__unsupported__'){
    $('arm-note').textContent='다중 선택은 현재 arm_a + arm_b(양팔 동시)만 지원합니다. arm_s는 단독으로 선택하세요.';
  }
  for(const cb of document.querySelectorAll('#cal-robot-list input, #cal-leader-list input'))cb.checked=false;
  f.at_bench.checked=false;
  applyArmRules(true);
  applyPresetOrRecommended(false);
  if(taskFilter==='arm')renderTaskListbox();
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

function selectTask(val){
  window.zoneSwapped=false;
  f.task.value=val||'';
  renderTaskListbox();
  updateTaskSummary();
  renderConfigMeta();
  const c=choices&&choices.task_cards?choices.task_cards[f.task.value]:null;
  const curName=f.name.value.trim();
  if(c&&c.valid&&c.task_id&&(!curName||/-01$/.test(curName))){
    f.name.value=String(c.task_id).toLowerCase().replace(/[^a-z0-9-]+/g,'-')+'-01';
  }
  validateStart();
}

let taskFilter='all';
function taskMatchesFilter(v,c){
  if(taskFilter==='all')return true;
  const hay=(v+' '+(c.origin||'')+' '+(c.target_slot||'')+' '+(c.single_task||'')+' '+(c.raw||'')).toLowerCase();
  if(taskFilter==='pinky')return /pinky|belt|conveyor|supply/.test(hay);
  const arm=f.arm.value, blk={arm_a:/arm[_ -]?[bs]\b|tmp-b|belt-in|conveyor|supply/,arm_b:/arm[_ -]?[as]\b|tmp-a|belt-in|conveyor|supply/,arm_ab:/arm[_ -]?s\b|belt-in|conveyor|supply/};
  if(arm==='arm_s')return /arm[_ -]?s\b|belt-in|conveyor|supply|pinky/.test(hay);
  return blk[arm]?!blk[arm].test(hay):true;
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
      $('arm-checks').innerHTML='';
      for(const a of singles){
        const lbl=document.createElement('label');lbl.className='check-row';lbl.style.flex='1 1 110px';
        const cb=document.createElement('input');cb.type='checkbox';cb.value=a;cb.checked=(a===singles[0]);
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
      if(singles.length)f.arm.value=singles[0];
      syncArmPillsUI();
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
    validateStart();
  }catch(err){
    setReqError('선택 목록을 불러오지 못했습니다: '+err.message);
  }
}

function init(){
  pollStatus();
  setInterval(pollStatus,2000);
  pollCameras();
  setInterval(pollCameras,1000);
  loadChoices();
}

const JOINT_LABELS={'11':'11 · 어깨 회전(pan)','12':'12 · 어깨 들기(lift)','13':'13 · 팔꿈치(elbow)','14':'14 · 손목 굽힘(flex)','15':'15 · 손목 회전(roll)','16':'16 · 그리퍼(gripper)'};
const PARAM_LABELS={'pwm':'최대 토크(PWM)','current':'최대 전류(mA)','p':'추적 강성(P)','i':'오차 보정(I)','acc':'가속도(acc)','vel':'속도(vel)'};

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

function renderCapsSummary(){
  const wrap=$('caps-summary-chart');
  const inputs=[...$('caps-fields').querySelectorAll('input[data-mid][data-key="pwm"]')];
  if(!inputs.length){wrap.innerHTML='';return;}
  let html='<div style="display:grid;grid-template-columns:repeat('+inputs.length+',minmax(0,1fr));gap:6px;align-items:end;height:68px;padding:8px;background:var(--ground-deep);border:1px solid var(--bd);border-radius:6px">';
  for(const inp of inputs){
    const v=Math.max(0,Math.min(2000,Number(inp.value)||0));
    const h=Math.max(6,Math.round((v/2000)*46));
    const col=v>=1000?'#ffc53d':'#58a6ff';
    html+='<div style="display:flex;flex-direction:column;align-items:center;gap:2px"><div style="width:100%;max-width:34px;height:'+h+'px;background:'+col+';border-radius:4px 4px 0 0"></div><span class="mono" style="font-size:.7rem;color:var(--ink-q)">M'+inp.dataset.mid+'</span></div>';
  }
  wrap.innerHTML=html+'</div>';
}

function renderCapsEditor(){
  renderConfigMeta();
  const name=f.caps.value;
  const data=choices&&choices.caps_data?choices.caps_data[name]:null;
  const box=$('caps-editor'), fields=$('caps-fields');
  if(!name||!data||typeof data!=='object'){box.hidden=true;fields.innerHTML='';$('caps-summary-chart').innerHTML='';return;}
  box.hidden=false;fields.innerHTML='';
  for(const [mid,obj] of Object.entries(data)){
    if(!obj||typeof obj!=='object')continue;
    const card=document.createElement('div');card.style.cssText='background:var(--ground-deep);border:1px solid var(--bd);border-radius:6px;padding:10px';
    const h=document.createElement('div');h.className='mono';h.style.cssText='font-weight:700;margin-bottom:6px;font-size:.9rem';h.textContent=JOINT_LABELS[mid]||('모터 ID '+mid);card.append(h);
    for(const [k,val] of Object.entries(obj)){
      const row=document.createElement('div');row.style.cssText='display:flex;align-items:center;gap:8px;margin-top:6px';
      const lbl=document.createElement('span');lbl.style.cssText='flex:0 0 118px;font-size:.82rem;color:var(--ink-q)';lbl.textContent=PARAM_LABELS[k]||k;
      const track=document.createElement('div');track.className='bar-track';
      const fill=document.createElement('div');fill.className='bar-fill';
      const vtxt=document.createElement('span');vtxt.className='bar-val';
      track.append(fill,vtxt);
      const inp=document.createElement('input');inp.type='number';inp.min='0';inp.max='2000';inp.value=String(val);
      inp.dataset.mid=mid;inp.dataset.key=k;
      inp.style.cssText='width:68px;min-height:30px;padding:2px 6px;background:var(--ground-soft);color:var(--ink);border:1px solid var(--bd);border-radius:4px;font-family:ui-monospace,monospace';
      const sync=(n)=>{
        const c=Math.max(0,Math.min(2000,Math.round(n)));
        inp.value=String(c);
        fill.style.width=(c/2000*100)+'%';
        fill.className='bar-fill'+(c>=1000?' high':'');
        vtxt.textContent=String(c);
        renderCapsSummary();
      };
      const onPtr=(e)=>{
        const r=track.getBoundingClientRect();
        const ratio=Math.max(0,Math.min(1,(e.clientX-r.left)/Math.max(1,r.width)));
        sync(Math.round((ratio*2000)/10)*10);
      };
      let dragging=false;
      track.addEventListener('pointerdown',e=>{dragging=true;track.setPointerCapture(e.pointerId);onPtr(e);});
      track.addEventListener('pointermove',e=>{if(dragging)onPtr(e);});
      track.addEventListener('pointerup',()=>{dragging=false;});
      track.addEventListener('pointercancel',()=>{dragging=false;});
      inp.addEventListener('input',()=>sync(Number(inp.value)||0));
      row.append(lbl,track,inp);card.append(row);
      sync(Number(val)||0);
    }
    fields.append(card);
  }
  renderCapsSummary();
}

$('save-caps-btn').addEventListener('click',async()=>{
  const values={};
  for(const inp of $('caps-fields').querySelectorAll('input[data-mid]')){
    const m=inp.dataset.mid, k=inp.dataset.key, v=Number(inp.value);
    if(!Number.isInteger(v)||v<0||v>2000){setReqError('모터 '+m+'.'+k+' 값은 0~2000 정수여야 합니다');return;}
    (values[m]=values[m]||{})[k]=v;
  }
  try{
    setReqError('');
    const res=await api('/save_caps',{arm:f.arm.value,values});
    choices=res.choices;
    f.caps.innerHTML='';f.caps.append(new Option('선택하세요',''));
    for(const v of (choices.caps||[]))f.caps.append(new Option(v,v));
    applyArmRules(false);
    f.caps.value=res.saved;
    renderCapsEditor();
    validateStart();
  }catch(err){setReqError(err.message);}
});

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
async function pollArms(){
  try{const res=await api('/api/arms');if(res&&res.arms){lastArmsStatus=res.arms;validateStart();}}catch(_){}
}
if($('hdr-home-btn')){
  $('hdr-home-btn').addEventListener('click',async()=>{
    const btn=$('hdr-home-btn');
    const incL=Boolean(lastArmsStatus&&f.arm.value&&lastArmsStatus[f.arm.value]?.has_leader_pose);
    poseInFlight=true;btn.disabled=true;btn.textContent='홈 이동 중...';validateStart();
    try{
      setReqError('');
      const st=await api('/home',{arm:f.arm.value,at_bench:f.at_bench.checked,include_leader:incL,hands_off_leader:incL});
      renderStatus(st);
      poseFeedbackMsg='홈(이니셜) 위치 이동 완료: '+((st.home_moved||[]).join(', ')||f.arm.value)+(incL?' (리더 토크 OFF 복구됨)':'');
      poseFeedbackUntil=Date.now()+6000;
    }catch(err){setReqError(err.message);}
    finally{poseInFlight=false;btn.textContent='홈 이동';validateStart();}
  });
}
if($('save-leader-pose-btn')){
  $('save-leader-pose-btn').addEventListener('click',async()=>{
    const btn=$('save-leader-pose-btn');
    poseInFlight=true;btn.disabled=true;btn.textContent='읽는 중...';validateStart();
    try{
      setReqError('');
      const st=await api('/save_leader_pose',{arm:f.arm.value,at_bench:f.at_bench.checked});
      renderStatus(st);
      poseFeedbackMsg='리더 홈 포즈 저장 완료 ('+Object.keys(st.leader_pose_saved||{}).join(', ')+')';
      poseFeedbackUntil=Date.now()+6000;
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
      const st=await api('/save_initial_pose',{arm:f.arm.value,at_bench:f.at_bench.checked});
      renderStatus(st);
      const sv=st.initial_pose_saved||{};
      const txt=Object.entries(sv).map(([k,v])=>k+': ['+v.join(', ')+']').join(' / ');
      poseFeedbackMsg='이니셜 포즈 저장 완료: '+txt;
      poseFeedbackUntil=Date.now()+6000;
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
if($('hdr-refresh-btn'))$('hdr-refresh-btn').addEventListener('click',()=>{pollStatus();pollCameras();});
f.arm.addEventListener('change',()=>{
  for(const cb of document.querySelectorAll('#cal-robot-list input, #cal-leader-list input'))cb.checked=false;
  f.at_bench.checked=false;
  applyArmRules(true);
  updateCameraRecordingMask();
  validateStart();
});
f.caps.addEventListener('change',()=>{renderCapsEditor();validateStart();});
f.task.addEventListener('change',()=>{
  window.zoneSwapped=false;
  renderTaskListbox();
  updateTaskSummary();
  renderConfigMeta();
  const c=choices&&choices.task_cards?choices.task_cards[f.task.value]:null;
  if(c&&c.valid&&c.task_id&&!f.name.value.trim()){
    f.name.value=String(c.task_id).toLowerCase().replace(/[^a-z0-9-]+/g,'-')+'-01';
  }
  validateStart();
});
for(const el of [f.name,f.rig_revision,f.at_bench]){
  el.addEventListener('input',validateStart);
  el.addEventListener('change',validateStart);
}
f.config.addEventListener('change',()=>{renderConfigMeta();updateCameraRecordingMask();validateStart();});
$('cal-robot-list').addEventListener('change',validateStart);
$('cal-leader-list').addEventListener('change',validateStart);

document.addEventListener('keydown',e=>{
  if(e.repeat)return;
  if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName||'')){
    const ts=$('task-search');if(ts){e.preventDefault();ts.focus();ts.select();}
  }else if((e.ctrlKey&&e.key==='Enter')||(e.altKey&&e.key.toLowerCase()==='s')){
    if(window.benchStartReady&&!BUSY.has(lastStatus?.status)){e.preventDefault();f.requestSubmit();}
  }else if(e.key==='Escape'||(e.altKey&&e.key.toLowerCase()==='x')){
    if((lastStatus?.status==='recording'||lastStatus?.status==='handing_over')&&!$('hdr-record-btn')?.disabled){e.preventDefault();$('hdr-record-btn').click();}
  }else if(e.altKey&&e.key.toLowerCase()==='c'){
    e.preventDefault();f.at_bench.checked=!f.at_bench.checked;validateStart();
  }else if(e.altKey&&e.key.toLowerCase()==='r'){
    const rb=$('toggle-reverse-btn');if(rb&&!rb.disabled){e.preventDefault();rb.click();}
  }else if(e.altKey&&e.key.toLowerCase()==='w'){
    const sb=$('swap-zones-btn');if(sb&&!sb.disabled){e.preventDefault();sb.click();}
  }
});

$('next-ep-btn').addEventListener('click',()=>{
  const cur=f.name.value.trim();
  const m=cur.match(/^(.*?)(\d+)$/);
  if(m)f.name.value=m[1]+String(Number(m[2])+1).padStart(m[2].length,'0');
  else if(cur)f.name.value=cur+'-02';
  f.at_bench.checked=false;
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
    at_bench:f.at_bench.checked,
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
    f.at_bench.checked=false;
    setReqError(err.message);
  }finally{
    startInFlight=false;
    validateStart();
  }
});
