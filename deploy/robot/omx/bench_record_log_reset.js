// Bottom live log console, custom ("기타") goal picker, and factory/recommended defaults reset.
(function(){
const LOG_COLLAPSE_KEY='omx_bench_log_collapsed';
const MAX_CLIENT_LOGS=200;
const clientLogs=[];
let serverLogs=[];
let logFileLabel='';
let logFilter='all';
let logPollTimer=null;
let resetBusy=false;

window.goalMode='card';
window.customClickTarget='target';
window.customGoal={origin:'belt',target_slot:'ship-h1r0-l0',single_task:''};

function normLevel(lv){
  const t=String(lv||'info').toLowerCase();
  if(t==='crit'||t==='error')return 'crit';
  if(t==='warn'||t==='warning')return 'warn';
  if(t==='good')return 'good';
  return 'info';
}

function logMatches(row){
  if(logFilter==='all')return true;
  if(logFilter==='error')return row.level==='crit'||row.level==='warn';
  if(logFilter==='session')return row.source==='session'||row.source==='bench'||row.source==='pose';
  if(logFilter==='config')return row.source==='config'||row.source==='map';
  if(logFilter==='pipeline')return row.source==='pipeline'||row.source==='hf';
  return true;
}

function mergedLogs(){
  const seen=new Set();
  const out=[];
  for(const row of [...serverLogs,...clientLogs]){
    if(!row||!row.text)continue;
    const key=(row.ts||'')+'|'+row.source+'|'+row.text;
    if(seen.has(key))continue;
    seen.add(key);
    out.push(row);
  }
  return out.slice(-MAX_CLIENT_LOGS);
}

function renderLiveLogs(){
  const body=$('live-log-body'), cntEl=$('live-log-count'), fileEl=$('live-log-file');
  if(!body)return;
  const rows=mergedLogs().filter(logMatches);
  if(cntEl)cntEl.textContent=rows.length+'줄';
  if(fileEl){fileEl.textContent=logFileLabel;fileEl.hidden=!logFileLabel;}
  if(!rows.length){
    body.innerHTML='<div class="quiet">표시할 로그가 없습니다.</div>';
    return;
  }
  body.innerHTML='';
  for(const r of rows){
    const div=document.createElement('div');
    div.className='log-row';
    div.dataset.level=normLevel(r.level);
    const ts=document.createElement('span');ts.className='log-ts';ts.textContent=r.ts||'--:--:--';
    const src=document.createElement('span');src.className='log-src';src.textContent=r.source||'bench';
    const msg=document.createElement('span');msg.className='log-msg';msg.textContent=r.text||'';
    div.append(ts,src,msg);
    body.append(div);
  }
  if($('live-log-autoscroll')?.checked){
    body.scrollTop=body.scrollHeight;
  }
}

function pushBenchLog(source,level,text){
  const clean=String(text||'').trim();
  if(!clean)return;
  const ts=typeof nowText==='function'?nowText():'';
  const prev=clientLogs[clientLogs.length-1];
  if(prev&&prev.source===source&&prev.text===clean&&prev.ts===ts)return;
  clientLogs.push({ts,source:String(source||'bench'),level:normLevel(level),text:clean});
  if(clientLogs.length>MAX_CLIENT_LOGS)clientLogs.splice(0,clientLogs.length-MAX_CLIENT_LOGS);
  renderLiveLogs();
}
window.pushBenchLog=pushBenchLog;

async function pollLiveLogs(){
  try{
    const d=await api('/api/logs?limit=100');
    if(d&&Array.isArray(d.entries)){
      serverLogs=d.entries;
      logFileLabel=d.log_file||'';
      renderLiveLogs();
    }
  }catch(_){}
}
window.pollLiveLogs=pollLiveLogs;

function scheduleLogPoll(){
  if(logPollTimer)clearInterval(logPollTimer);
  const collapsed=$('sec-live-log')?.classList.contains('collapsed');
  logPollTimer=setInterval(pollLiveLogs,collapsed?5000:2000);
}

function setLiveLogCollapsed(collapsed){
  const sec=$('sec-live-log'), btn=$('live-log-toggle');
  if(!sec)return;
  sec.classList.toggle('collapsed',Boolean(collapsed));
  if(btn){
    btn.setAttribute('aria-expanded',collapsed?'false':'true');
    btn.textContent=collapsed?'펼치기':'접기';
  }
  try{localStorage.setItem(LOG_COLLAPSE_KEY,collapsed?'1':'0');}catch(_){}
  scheduleLogPoll();
}

function populateCustomSpotSelects(){
  const oSel=$('custom-origin-sel'), tSel=$('custom-target-sel');
  if(!oSel||!tSel)return;
  const spots=(window.cellMapData&&Array.isArray(window.cellMapData.spot_catalog)&&window.cellMapData.spot_catalog.length)
    ?window.cellMapData.spot_catalog
    :[
      {code:'belt',label:'벨트 인출단 (belt)'},
      {code:'belt-in',label:'벨트 공급단 (belt-in)'},
      {code:'pinky',label:'핑키 로봇 (pinky)'},
      {code:'stand:r1-s1-t1',label:'반출대 (stand)'},
      {code:'tmp-a-1',label:'임시대 A · 1번 1층 (tmp-a-1)'},
      {code:'tmp-b-2',label:'임시대 B · 2번 1층 (tmp-b-2)'},
      {code:'ship-h1r0-l0',label:'화물칸 h1 · A쪽 줄 · 1층 (ship-h1r0-l0)'},
      {code:'ship-h1r1-l0',label:'화물칸 h1 · 가운데 줄 · 1층 (ship-h1r1-l0)'},
      {code:'ship-h1r2-l0',label:'화물칸 h1 · B쪽 줄 · 1층 (ship-h1r2-l0)'},
    ];
  for(const [sel,cur] of [[oSel,window.customGoal.origin],[tSel,window.customGoal.target_slot]]){
    const prev=sel.value||cur;
    sel.innerHTML='';
    for(const s of spots)sel.append(new Option(s.label,s.code));
    sel.append(new Option('기타 직접 입력...','__other__'));
    if([...sel.options].some(o=>o.value===prev))sel.value=prev;
    else if(prev){sel.value='__other__';}
  }
  syncCustomInputsVisibility();
}
window.populateCustomSpotSelects=populateCustomSpotSelects;

function syncCustomInputsVisibility(){
  const oSel=$('custom-origin-sel'), oTxt=$('custom-origin-text');
  const tSel=$('custom-target-sel'), tTxt=$('custom-target-text');
  if(oSel&&oTxt){
    const customO=oSel.value==='__other__';
    oTxt.hidden=!customO;
    if(customO&&!oTxt.value)oTxt.value=window.customGoal.origin||'';
  }
  if(tSel&&tTxt){
    const customT=tSel.value==='__other__';
    tTxt.hidden=!customT;
    if(customT&&!tTxt.value)tTxt.value=window.customGoal.target_slot||'';
  }
}

function readCustomGoalFromUI(){
  const oSel=$('custom-origin-sel'), oTxt=$('custom-origin-text');
  const tSel=$('custom-target-sel'), tTxt=$('custom-target-text');
  const orig=(oSel&&oSel.value==='__other__'?(oTxt?.value||''):(oSel?.value||window.customGoal.origin)).trim();
  const tgt=(tSel&&tSel.value==='__other__'?(tTxt?.value||''):(tSel?.value||window.customGoal.target_slot)).trim();
  const instr=($('custom-task-text')?.value||'').trim();
  window.customGoal={origin:orig,target_slot:tgt,single_task:instr};
  return window.customGoal;
}

function setGoalMode(mode){
  const m=mode==='custom'?'custom':'card';
  window.goalMode=m;
  for(const b of document.querySelectorAll('#goal-mode-pills button[data-goal-mode]')){
    const on=b.dataset.goalMode===m;
    b.classList.toggle('active',on);
    b.setAttribute('aria-pressed',on?'true':'false');
  }
  const box=$('goal-custom-panel');
  if(box)box.hidden=(m!=='custom');
  if(m==='custom')populateCustomSpotSelects();
  if(typeof renderCamGuide==='function')renderCamGuide();
  if(typeof autoCollectionName==='function')autoCollectionName();
  if(typeof validateStart==='function')validateStart();
}
window.setGoalMode=setGoalMode;

function applyCustomMapSpot(spot){
  const role=window.customClickTarget==='origin'?'origin':'target';
  const clean=String(spot||'').trim();
  if(!clean)return;
  if(role==='origin')window.customGoal.origin=clean;
  else window.customGoal.target_slot=clean;
  const sel=$(role==='origin'?'custom-origin-sel':'custom-target-sel');
  const txt=$(role==='origin'?'custom-origin-text':'custom-target-text');
  if(sel){
    if([...sel.options].some(o=>o.value===clean)){
      sel.value=clean;
      if(txt)txt.hidden=true;
    }else{
      sel.value='__other__';
      if(txt){txt.value=clean;txt.hidden=false;}
    }
  }
  pushBenchLog('map','info','직접 목표 '+(role==='origin'?'① 출발':'② 도착')+' 선택: '+clean);
  if(typeof renderCamGuide==='function')renderCamGuide();
  if(typeof autoCollectionName==='function')autoCollectionName();
  if(typeof validateStart==='function')validateStart();
}
window.applyCustomMapSpot=applyCustomMapSpot;

window.getCustomTaskOverride=()=>{
  if(window.goalMode!=='custom')return null;
  const g=readCustomGoalFromUI();
  if(!g.origin||!g.target_slot)return null;
  return {custom:true,origin:g.origin,target_slot:g.target_slot,single_task:g.single_task||''};
};

function clearClientOverrides(){
  window.zoneSwapped=false;
  setGoalMode('card');
  window.customGoal={origin:'belt',target_slot:'ship-h1r0-l0',single_task:''};
  if($('custom-task-text'))$('custom-task-text').value='';
  if($('replay'))$('replay').value='';
  if($('invert-gripper'))$('invert-gripper').checked=false;
  if($('toggle-reverse-btn')?.getAttribute('aria-pressed')==='true')$('toggle-reverse-btn').click();
  if($('lp-episodes'))$('lp-episodes').value='';
  if($('lp-ep-time'))$('lp-ep-time').value='';
  if($('lp-reset-time'))$('lp-reset-time').value='';
}

async function runDefaultsReset(preset,scope){
  if(resetBusy)return;
  resetBusy=true;
  setReqError('');
  const arm=f&&f.arm?f.arm.value:'';
  pushBenchLog('config','info','기본값 초기화 요청 ('+preset+' / '+scope+' · '+(arm||'all')+')');
  try{
    if(scope==='all'&&preset==='factory'){
      try{
        for(const k of Object.keys(localStorage)){
          if(k.startsWith('omx_bench_preset_'))localStorage.removeItem(k);
        }
      }catch(_){}
    }
    const res=await api('/api/defaults/reset',{preset,scope,arm});
    if(res.choices)choices=res.choices;
    if(res.grip_maps&&res.grip_maps.arms)gripMapsData=res.grip_maps.arms;
    if(scope==='all')clearClientOverrides();
    if(res.status)renderStatus(res.status);
    if(typeof applyArmRules==='function')applyArmRules(true);
    if(typeof applyPresetOrRecommended==='function')applyPresetOrRecommended(true);
    if(typeof loadGripMaps==='function')await loadGripMaps();
    if(typeof renderParamsPanel==='function')renderParamsPanel();
    const summary=(res.reset_items||[]).join(', ')||'완료';
    const skipped=(res.skipped_items||[]).length?(' · 유지: '+res.skipped_items.join(', ')):'';
    if(typeof setActivity==='function')setActivity('기본값 복원 완료 ('+preset+')','good',summary+skipped);
    setNotice('defaults-reset','good','복원 완료: '+summary+skipped,{ttlMs:6000});
  }catch(err){
    setReqError('기본값 복원 오류: '+err.message);
    pushBenchLog('config','crit','기본값 복원 실패: '+err.message);
  }finally{
    resetBusy=false;
    if(typeof validateStart==='function')validateStart();
  }
}

async function runResetAndRetry(){
  if(benchSessionActive()||resetBusy||poseInFlight||startInFlight)return;
  const armNow=(f&&f.arm?f.arm.value:'')||lastStatus?.arm||'arm_a';
  const prevSt=lastStatus;
  const rhBlocked=Boolean(prevSt?.manual_attention)||prevSt?.error_kind==='needs_person'||prevSt?.status==='unsafe_or_failed'||prevSt?.status==='leader_manual_check'||prevSt?.status==='failed'||prevSt?.safe_end===false;
  await runDefaultsReset('recommended','params');
  if(typeof bumpCollectionName==='function')bumpCollectionName(prevSt?.name||'');
  if(typeof setManualBenchPhase==='function')setManualBenchPhase('setup');
  if(!rhBlocked){
    try{
      pushBenchLog('pose','info','초기화 후 안전 홈 이동 실행 ('+armNow+')');
      const st=await api('/home',{arm:armNow,include_leader:false,fold_unfolded:true});
      renderStatus(st);
    }catch(err){
      pushBenchLog('pose','warn','홈 이동 건너뜀/실패: '+err.message);
    }
  }
}

function wireConfirmReset(triggerId,barId,yesId,noId,preset,scope){
  const trig=$(triggerId), bar=$(barId), yes=$(yesId), no=$(noId);
  if(!trig||!bar||!yes||!no)return;
  trig.addEventListener('click',()=>{bar.hidden=false;});
  no.addEventListener('click',()=>{bar.hidden=true;});
  yes.addEventListener('click',()=>{bar.hidden=true;runDefaultsReset(preset,scope);});
}

// Wire live log console
if($('live-log-filters')){
  $('live-log-filters').addEventListener('click',e=>{
    const btn=e.target.closest('button[data-log-filter]');if(!btn)return;
    logFilter=btn.dataset.logFilter||'all';
    for(const b of $('live-log-filters').querySelectorAll('button[data-log-filter]')){
      const on=b===btn;
      b.classList.toggle('active',on);
      b.setAttribute('aria-pressed',on?'true':'false');
    }
    renderLiveLogs();
  });
}
if($('live-log-toggle')){
  try{if(localStorage.getItem(LOG_COLLAPSE_KEY)==='1')setLiveLogCollapsed(true);}catch(_){}
  $('live-log-toggle').addEventListener('click',()=>{
    const collapsed=$('sec-live-log')?.classList.contains('collapsed');
    setLiveLogCollapsed(!collapsed);
  });
}
if($('live-log-copy-btn')){
  $('live-log-copy-btn').addEventListener('click',async()=>{
    const txt=mergedLogs().filter(logMatches).map(r=>`[${r.ts||'--:--:--'}] [${r.source}] ${r.text}`).join('\n');
    try{await navigator.clipboard.writeText(txt);$('live-log-copy-btn').textContent='복사됨';setTimeout(()=>{$('live-log-copy-btn').textContent='복사';},1200);}catch(_){}
  });
}
if($('live-log-clear-btn')){
  $('live-log-clear-btn').addEventListener('click',()=>{clientLogs.length=0;renderLiveLogs();});
}
if($('activity-log-bar')){
  $('activity-log-bar').addEventListener('click',()=>{
    setLiveLogCollapsed(false);
    $('sec-live-log')?.scrollIntoView({block:'nearest'});
  });
}

// Wire custom goal controls
for(const b of document.querySelectorAll('#goal-mode-pills button[data-goal-mode]')){
  b.addEventListener('click',()=>setGoalMode(b.dataset.goalMode));
}
for(const b of document.querySelectorAll('#goal-custom-panel button[data-custom-pick]')){
  b.addEventListener('click',()=>{
    window.customClickTarget=b.dataset.customPick||'target';
    for(const x of document.querySelectorAll('#goal-custom-panel button[data-custom-pick]')){
      const on=x===b;
      x.classList.toggle('active',on);
      x.setAttribute('aria-pressed',on?'true':'false');
    }
  });
}
for(const id of ['custom-origin-sel','custom-target-sel','custom-origin-text','custom-target-text','custom-task-text']){
  if($(id)){
    $(id).addEventListener('change',()=>{
      syncCustomInputsVisibility();
      readCustomGoalFromUI();
      if(typeof renderCamGuide==='function')renderCamGuide();
      if(typeof autoCollectionName==='function')autoCollectionName();
      if(typeof validateStart==='function')validateStart();
    });
    if(id.endsWith('-text')){
      $(id).addEventListener('input',()=>{
        readCustomGoalFromUI();
        if(typeof renderCamGuide==='function')renderCamGuide();
      });
    }
  }
}
if($('custom-goal-reset-btn')){
  $('custom-goal-reset-btn').addEventListener('click',()=>{
    window.customGoal={origin:'belt',target_slot:'ship-h1r0-l0',single_task:''};
    if($('custom-task-text'))$('custom-task-text').value='';
    populateCustomSpotSelects();
    if(typeof renderCamGuide==='function')renderCamGuide();
    pushBenchLog('config','info','목표 입력을 기본값(belt → ship-h1r0-l0)으로 복원');
  });
}

// Wire factory reset & retry controls
wireConfirmReset('sb-factory-reset-btn','sb-reset-confirm','sb-reset-confirm-yes','sb-reset-confirm-no','factory','all');
wireConfirmReset('factory-reset-btn','drawer-reset-confirm','drawer-reset-confirm-yes','drawer-reset-confirm-no','factory','all');
if($('sb-apply-rec-defaults-btn'))$('sb-apply-rec-defaults-btn').addEventListener('click',()=>runDefaultsReset('recommended','params'));
if($('sb-grip-reset-btn'))$('sb-grip-reset-btn').addEventListener('click',()=>runDefaultsReset('factory','grip'));
if($('hdr-reset-retry-btn'))$('hdr-reset-retry-btn').addEventListener('click',runResetAndRetry);

populateCustomSpotSelects();
pollLiveLogs();
scheduleLogPoll();
})();
