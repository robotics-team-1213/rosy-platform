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
const BENCH_PHASES=['setup','prepare','recording','result'];
const ENDED=new Set(['sealed','stopped_safe','stopped_not_sealed','unsafe_or_failed','seal_failed','failed','leader_manual_check']);
const NAME_RE=/^[a-z0-9][a-z0-9-]{2,63}$/;

let choices=null;
let lastStatus=null;
let statusLoaded=false;
let startInFlight=false;
let stopInFlight=false;
let stopRequestVersion=0;
let latestStatusSeq=0;
let lastStartMeta=null;
let lastTelemetryActive=false;
let lastAutoPhase='setup';
let manualPhase=null;

function benchSessionActive(st=lastStatus){
  if(st?.status==='homing'&&(st?.error||st?.manual_hold?.active))return false;
  return BUSY.has(st?.status)||st?.phase==='prepare'||st?.phase==='recording';
}

// only the recording phase with the server's recording status is an active take; setup/prepare/result/idle are standby
function isActivelyRecording(){
  return currentBenchPhase()==='recording'&&lastStatus?.status==='recording';
}
window.isActivelyRecording=isActivelyRecording;

function resolveBenchPhase(statusCode,telemetryActive,phase){
  if(BENCH_PHASES.includes(phase))return phase;
  if(statusCode==='recording')return 'recording';
  if(statusCode==='restoring'||statusCode==='sealing'||ENDED.has(statusCode))return 'result';
  if(BUSY.has(statusCode)||telemetryActive)return 'prepare';
  return 'setup';
}

function currentBenchPhase(){
  return manualPhase||lastAutoPhase;
}

function applyBenchPhase(phase){
  const p=BENCH_PHASES.includes(phase)?phase:'setup';
  const shell=document.querySelector('.app-shell');
  if(shell)shell.dataset.phase=p;
  for(const step of document.querySelectorAll('#phase-tabs [data-phase-tab]')){
    const index=BENCH_PHASES.indexOf(step.dataset.phaseTab);
    const current=BENCH_PHASES.indexOf(p);
    const completed=index<current&&(p!=='result'||index===0||lastStatus?.status==='sealed'||
      (index===1&&Boolean(lastStatus?.recording_started)));
    step.classList.toggle('is-complete',completed);
    if(index===current)step.setAttribute('aria-current','step');
    else step.removeAttribute('aria-current');
  }
  for(const el of document.querySelectorAll('[data-tabs]')){
    const tabs=String(el.dataset.tabs||'').split(/\s+/).filter(Boolean);
    el.hidden=!tabs.includes(p);
  }
  const camBaseBtn=$('save-cam-base-btn');
  if(camBaseBtn)camBaseBtn.hidden=benchSessionActive();
  if(p==='prepare'||p==='recording'){const secSt=$('sec-status');if(secSt)secSt.open=true;}
  if(benchSessionActive()&&typeof window.closeDrawer==='function'&&window.activeDrawerName?.()!=='records')window.closeDrawer(false);
  if(p!=='result')renderCamGuide();
  if(typeof updateCameraRecordingMask==='function')updateCameraRecordingMask();
  if(typeof updateGoalSummaryRows==='function')updateGoalSummaryRows();
}

function syncBenchPhase(){
  const errHome=(lastStatus?.status==='homing'&&(lastStatus?.error||lastStatus?.manual_hold?.active));
  const nextAuto=errHome?'setup':resolveBenchPhase(lastStatus?.status,lastTelemetryActive,lastStatus?.phase);
  if(nextAuto!==lastAutoPhase){
    lastAutoPhase=nextAuto;
    manualPhase=null;
  }
  applyBenchPhase(currentBenchPhase());
}

window.resolveBenchPhase=resolveBenchPhase;
window.applyBenchPhase=applyBenchPhase;
window.setManualBenchPhase=p=>{
  if(benchSessionActive())return;
  manualPhase=p;
  applyBenchPhase(currentBenchPhase());
  validateStart();
};

async function api(path,body){
  const res=await fetch(path,body?{method:'POST',headers:H,body:JSON.stringify(body)}:{cache:'no-store'});
  let data={};
  try{data=await res.json();}catch(_){}
  if(!res.ok)throw Object.assign(new Error(data.error||('HTTP '+res.status)),{status:res.status});
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
  aligning:'가드 정렬 중',
  saving:'에피소드 저장 중',
  fold_unfolded:'펼쳐진 팔 안전 접기 중',
  baseline_restore:'기준 상태 복원 중'
};
const NOTICE_PRIO={crit:4,warn:3,good:2,muted:1};
const NOTICE_TONE_LABEL={crit:'오류',warn:'주의',good:'완료',live:'진행',muted:'안내'};
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
const statusBar=$('status-bar');
new ResizeObserver(()=>{
  document.documentElement.style.setProperty('--status-h',statusBar.offsetHeight+'px');
}).observe(statusBar);

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

let activeNoticeAction=null;
function renderNoticeBar(){
  const now=Date.now();
  for(const [k,v] of activeNotices.entries()){
    if(v.expiresAt&&now>=v.expiresAt)activeNotices.delete(k);
  }
  const reasonBar=$('start-reason-bar'), hdrReasons=$('hdr-start-reasons');
  const actBtn=$('reason-action-btn'), moreBtn=$('reason-more-btn'), expBtn=$('reason-expand-btn'), closeBtn=$('reason-close-btn');
  if(!reasonBar||!hdrReasons)return;
  const list=[...activeNotices.values()].sort((a,b)=>(NOTICE_PRIO[b.tone]||0)-(NOTICE_PRIO[a.tone]||0));
  if(!list.length){
    hdrReasons.textContent='';
    reasonBar.hidden=true;
    reasonBar.classList.remove('expanded','muted','crit','good');
    activeNoticeAction=null;
    if(actBtn){actBtn.hidden=true;actBtn.textContent='';}
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
  hdrReasons.title=hdrReasons.textContent;
  activeNoticeAction=top.action||null;
  if(actBtn){
    if(!actBtn.dataset.bound){
      actBtn.dataset.bound='1';
      actBtn.addEventListener('click',async()=>{
        const fn=activeNoticeAction?.run;
        if(typeof fn!=='function'||actBtn.disabled)return;
        actBtn.disabled=true;
        try{await fn();}finally{actBtn.disabled=false;}
      });
    }
    actBtn.hidden=!activeNoticeAction;
    if(activeNoticeAction)actBtn.textContent=activeNoticeAction.label||'조치';
  }
  if(moreBtn){
    const extra=list.length-1;
    moreBtn.hidden=expanded||extra<=0;
    moreBtn.textContent=extra>0?('(+'+extra+'건)'):'';
  }
  if(expBtn){
    const needExp=list.length>1||top.msg.length>72||expanded||hdrReasons.scrollWidth>hdrReasons.clientWidth;
    expBtn.hidden=!needExp;
    expBtn.setAttribute('aria-expanded',expanded?'true':'false');
    expBtn.textContent=expanded?'접기':'자세히';
  }
  if(closeBtn){
    closeBtn.hidden=!(top.persistent||top.tone==='crit'||top.tone==='good');
    closeBtn.dataset.noticeKey=top.key;
  }
}

function setNotice(key,tone,msg,opts){
  const text=String(msg||'').trim();
  if(!text){clearNotice(key);return;}
  const sig=(opts&&opts.sig)||text;
  if(dismissedNoticeMsg.get(key)===sig)return;
  dismissedNoticeMsg.delete(key);
  const prev=activeNotices.get(key);
  const ts=nowText();
  const persistent=Boolean(opts&&opts.persistent)||tone==='crit';
  const expiresAt=(tone==='good')?(Date.now()+((opts&&opts.ttlMs)||6000)):0;
  const action=(opts&&opts.action&&typeof opts.action.run==='function')?opts.action:null;
  activeNotices.set(key,{key,tone,msg:text,sig,action,ts,persistent,expiresAt});
  if(!prev||(prev.sig||prev.msg)!==sig||prev.tone!==tone){
    noticeHistory.unshift({ts,key,tone,msg:text});
    if(noticeHistory.length>20)noticeHistory.length=20;
    renderNoticeHistory();
    if(typeof window.pushBenchLog==='function'&&(tone==='crit'||tone==='warn'||tone==='good')){
      window.pushBenchLog('notice',tone==='crit'?'crit':(tone==='warn'?'warn':'good'),text);
    }
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
  dismissedNoticeMsg.set(top.key,top.sig||top.msg);
  activeNotices.delete(top.key);
  renderNoticeBar();
}

function setActivity(action,tone='muted',detail=''){
  const ts=nowText();
  const head=String(action||'').trim();
  const extra=String(detail||'').trim();
  const line=extra?(head+' — '+extra):head;
  if(!line)return;
  const t=(tone==='good'||tone==='warn'||tone==='crit'||tone==='live')?tone:'muted';
  const el=$('activity-log-text');
  if(el){
    el.textContent='['+ts+'] '+line;
    el.title=el.textContent;
    el.dataset.tone=t;
  }
  const prev=noticeHistory[0];
  if(!prev||prev.key!=='activity'||prev.msg!==line||prev.tone!==t){
    noticeHistory.unshift({ts,key:'activity',tone:t,msg:line});
    if(noticeHistory.length>20)noticeHistory.length=20;
    renderNoticeHistory();
  }
  if(typeof window.pushBenchLog==='function'){
    window.pushBenchLog('bench',t==='crit'?'crit':(t==='warn'?'warn':(t==='good'?'good':'info')),line);
  }
}

window.setNotice=setNotice;
window.clearNotice=clearNotice;
window.dismissTopNotice=dismissTopNotice;
window.setActivity=setActivity;
setInterval(()=>{if(activeNotices.size)renderNoticeBar();},1000);

function initSidebarSections(){
  for(const el of document.querySelectorAll('#bench-sidebar details.sb-sec[id]')){
    const k='omx_sb_sec_'+el.id;
    try{
      const saved=localStorage.getItem(k);
      if(saved==='1')el.open=true;
      else if(saved==='0')el.open=false;
    }catch(_){}
    el.addEventListener('toggle',()=>{
      try{localStorage.setItem(k,el.open?'1':'0');}catch(_){}
    });
  }
}
initSidebarSections();

const SOUND_KEY='omx_bench_sound';
const BEEP_PATTERNS={
  ready:[[660,0.08,0],[880,0.13,0.09]],
  rec_start:[[1046.5,0.14,0]],
  countdown:[[740,0.045,0]],
  saved:[[784,0.08,0],[1046.5,0.14,0.09]],
  rerecord:[[622.25,0.08,0],[440,0.12,0.09]],
  done:[[523.25,0.08,0],[659.25,0.08,0.09],[784,0.16,0.18]],
  warn:[[330,0.11,0],[277.18,0.16,0.13]]
};
let benchAudioCtx=null;
function ensureAudioCtx(){
  try{
    const AC=window.AudioContext||window.webkitAudioContext;
    if(!AC)return null;
    if(!benchAudioCtx)benchAudioCtx=new AC();
    if(benchAudioCtx.state==='suspended')benchAudioCtx.resume().catch(()=>{});
    return benchAudioCtx;
  }catch(_){return null;}
}
function soundEnabled(){
  try{return localStorage.getItem(SOUND_KEY)!=='0';}catch(_){return true;}
}
function syncSoundBtn(){
  const btn=$('hdr-sound-btn');
  if(!btn)return;
  const on=soundEnabled();
  btn.setAttribute('aria-pressed',on?'true':'false');
  btn.textContent=on?'신호음 ON':'신호음 OFF';
}
function benchBeep(kind){
  if(!soundEnabled())return;
  const notes=BEEP_PATTERNS[kind];
  if(!notes)return;
  const ctx=ensureAudioCtx();
  if(!ctx)return;
  try{
    const base=ctx.currentTime+0.01;
    const wave=kind==='warn'?'triangle':'sine';
    for(const [freq,dur,off] of notes){
      const osc=ctx.createOscillator(), gain=ctx.createGain();
      osc.type=wave;osc.frequency.setValueAtTime(freq,base+off);
      gain.gain.setValueAtTime(0.001,base+off);
      gain.gain.linearRampToValueAtTime(0.14,base+off+0.01);
      gain.gain.exponentialRampToValueAtTime(0.001,base+off+Math.max(0.025,dur));
      osc.connect(gain);gain.connect(ctx.destination);
      osc.start(base+off);osc.stop(base+off+Math.max(0.03,dur)+0.015);
    }
  }catch(_){}
}
function setSoundEnabled(on,announce){
  const enabled=Boolean(on);
  try{localStorage.setItem(SOUND_KEY,enabled?'1':'0');}catch(_){}
  syncSoundBtn();
  if(announce){
    if(typeof setActivity==='function')setActivity(enabled?'신호음 켜짐':'신호음 꺼짐',enabled?'good':'muted','Web Audio');
    if(enabled)benchBeep('ready');
  }
}
if($('hdr-sound-btn')){
  syncSoundBtn();
  $('hdr-sound-btn').addEventListener('click',()=>setSoundEnabled(!soundEnabled(),true));
}
const unlockBenchAudio=()=>{if(soundEnabled())ensureAudioCtx();};
document.addEventListener('pointerdown',unlockBenchAudio,{once:true});
document.addEventListener('keydown',unlockBenchAudio,{once:true});
window.benchBeep=benchBeep;
window.soundEnabled=soundEnabled;
window.setSoundEnabled=setSoundEnabled;

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

function updateGoalSummaryRows(){
  const phase=currentBenchPhase();
  const st=lastStatus;
  const t=f&&f.task?f.task.value:(st&&st.task?st.task:'');
  const c=choices&&choices.task_cards&&t?choices.task_cards[t]:null;
  const busyRun=benchSessionActive(st);
  const showSession=busyRun||phase==='result';
  const meta=lastStartMeta&&sessionKey(st)===lastStartMeta.key?lastStartMeta:null;
  const nm=(showSession&&(st?.name||meta?.name))||f.name.value.trim()||'수집명 미정';
  const armCode=st?.arm||(f&&f.arm?f.arm.value:'');
  const armDisp=armCode==='arm_ab'?'arm_a+b':armCode;
  const customTask=(window.goalMode==='custom'&&window.customGoal?.origin&&window.customGoal?.target_slot)
    ?(window.customGoal.origin+'→'+window.customGoal.target_slot):'';
  const rawTid=(showSession&&(st?.task||meta?.task))||(c&&c.valid!==false&&c.task_id)||customTask||t||'과제 미선택';
  const hdrTask=[armDisp,rawTid].filter(Boolean).join(' · ');
  for(const [id,value,label] of [['hdr-task-summary',hdrTask,'과제'],['goal-name-btn',nm,'수집명']]){
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

