window.zoneSwapped=false;
let reverseMode=false;
let recStartMs=null;
let lastEpDurationMs=Number(localStorage.getItem('omx_last_ep_ms')||0)||null;

function mapConfigCamToLabel(rawKey,arm){
  const parts=String(rawKey||'').trim().split('.');
  const prefix=parts.length===2?parts[0]:arm;
  const role=(parts.length===2?parts[1]:parts[0]).toLowerCase();
  if(!role)return [];
  if(role==='top')return [prefix==='arm_s'?'arm_s_top':'top'];
  if(role==='side')return ['side'];
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
    if(missing.length)parts.push('8767 미수신: '+missing.join(', '));
    note.textContent=parts.join(' · ');
  }
  const rch=$('rail-cam-health');
  if(rch&&lastCamState&&camLabels.length){
    const missing=recSet?[...recSet].filter(l=>!camLabels.includes(l)):[];
    const rows=camLabels.map(l=>{
      const ok=lastCamState[l]?.fresh!==false;
      const isRec=!recSet||recSet.has(l);
      const tag=recSet?(isRec?' (녹화)':' (미녹화)'):'';
      return '<div class="mono" style="display:flex;justify-content:space-between;gap:6px;opacity:'+(isRec?'1':'0.42')+'"><span>'+l+tag+'</span><span style="color:'+(ok?'var(--good)':'var(--warn)')+'">'+(ok?'수신':'지연')+'</span></div>';
    });
    for(const m of missing){
      rows.push('<div class="mono" style="display:flex;justify-content:space-between;gap:6px"><span>'+m+' (녹화)</span><span style="color:var(--crit)">미수신</span></div>');
    }
    rch.innerHTML=rows.join('');
  }
}
window.updateCameraRecordingMask=updateCameraRecordingMask;

function initRailToggle(){
  const body=document.querySelector('.app-body'), btn=$('rail-toggle-btn');
  if(!body||!btn)return;
  const open=localStorage.getItem('omx_sb_open')==='1';
  body.classList.toggle('sb-expanded',open);
  btn.setAttribute('aria-expanded',open?'true':'false');
  btn.addEventListener('click',()=>{
    const nxt=!body.classList.contains('sb-expanded');
    body.classList.toggle('sb-expanded',nxt);
    btn.setAttribute('aria-expanded',nxt?'true':'false');
    try{localStorage.setItem('omx_sb_open',nxt?'1':'0');}catch(_){}
  });
  for(const a of document.querySelectorAll('.app-sidebar a.sb-link[href^="#"]')){
    a.addEventListener('click',()=>{
      const t=document.querySelector(a.getAttribute('href'));
      if(t&&t.tagName==='DETAILS')t.open=true;
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

function fmtElapsed(ms){
  const sec=Math.max(0,ms/1000);
  const mm=String(Math.floor(sec/60)).padStart(2,'0');
  const ss=(sec%60).toFixed(1).padStart(4,'0');
  return mm+':'+ss+'s';
}

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
  const st=typeof lastStatus!=='undefined'?lastStatus:null;
  const code=st?st.status:'idle';
  const busyNow=Boolean(st&&BUSY.has(code));
  const arm=f&&f.arm?f.arm.value:'';
  const rep=$('replay')?$('replay').value:'';
  const armPill=$('hdr-arm-pill');
  if(armPill){
    armPill.textContent=(arm||'미선택')+' · '+(rep?'리플레이':'수동')+(reverseMode?' · 역방향':'');
    armPill.dataset.tone=busyNow?'live':'';
  }
  const hRec=$('hdr-record-btn');
  if(hRec){
    if(code==='recording'||code==='handing_over'){
      hRec.textContent='녹화 중지';
      hRec.className='btn-stop';
      hRec.style.minHeight='40px';
      hRec.disabled=Boolean(stopInFlight);
    }else if(busyNow){
      hRec.textContent=(STATUS_MAP[code]?.[0])||'진행 중';
      hRec.className='btn-tool';
      hRec.style.minHeight='40px';
      hRec.disabled=true;
    }else{
      hRec.textContent='녹화 시작';
      hRec.className='btn-primary';
      hRec.style.minHeight='40px';
      hRec.disabled=!window.benchStartReady;
    }
  }

  const t=f&&f.task?f.task.value:'';
  const c=choices&&choices.task_cards&&t?choices.task_cards[t]:null;
  const q=epQuota(c);
  const done=st&&st.episodes_done!=null?st.episodes_done:(q?q.done:null);
  const goal=st&&st.target_episodes!=null?st.target_episodes:(q?q.goal:null);
  const rem=(done!=null&&goal!=null)?Math.max(0,goal-done):(q?q.rem:null);
  const pct=(done!=null&&goal>0)?Math.min(100,Math.round(done/goal*100)):(q?q.pct:0);
  if($('sp-quota'))$('sp-quota').textContent=(done!=null&&goal!=null)?(done+' / '+goal+'회'):'— / —';
  if($('sp-rem'))$('sp-rem').textContent=rem!=null?('잔여 '+rem+'회'):'';
  if($('sp-fill'))$('sp-fill').style.width=pct+'%';
  if($('sp-mode')){
    $('sp-mode').textContent=reverseMode?('역방향('+$('reverse-mode')?.value+')'):'정방향';
    $('sp-mode').dataset.tone=reverseMode?'live':'';
  }
  if($('sp-status-text'))$('sp-status-text').textContent=$('top-badge')?.textContent||'대기 중';

  if(code==='recording'){
    if(recStartMs===null){
      recStartMs=st.recording_started?(st.recording_started*1000):(st.recording_elapsed_s!=null?(Date.now()-st.recording_elapsed_s*1000):Date.now());
    }
    if($('sp-timer'))$('sp-timer').textContent=fmtElapsed(Date.now()-recStartMs);
  }else{
    if(recStartMs!==null&&(code==='restoring'||code==='sealing'||code==='sealed'||code==='stopped_not_sealed')){
      lastEpDurationMs=st&&st.recording_elapsed_s!=null?(st.recording_elapsed_s*1000):(Date.now()-recStartMs);
      try{localStorage.setItem('omx_last_ep_ms',String(lastEpDurationMs));}catch(_){}
      recStartMs=null;
    }else if(!busyNow){recStartMs=null;}
    if($('sp-timer'))$('sp-timer').textContent=st&&st.recording_elapsed_s!=null?fmtElapsed(st.recording_elapsed_s*1000):'00:00.0s';
  }
  const lastSec=st&&st.last_episode_s!=null?st.last_episode_s:(lastEpDurationMs!=null?(lastEpDurationMs/1000):null);
  if($('sp-last'))$('sp-last').textContent=lastSec!=null?(Number(lastSec).toFixed(1)+'s'):'—';

  const locks=st&&Array.isArray(st.active_locks)?st.active_locks:[];
  if($('ftr-server')){
    const ok=Boolean(statusLoaded);
    $('ftr-server').textContent=ok?'서버 정상':'연결 끊김';
    $('ftr-server').dataset.tone=ok?'good':'crit';
  }
  if($('ftr-lock')){
    $('ftr-lock').textContent=locks.length?('락 '+locks.length+'건'):'락 없음';
    $('ftr-lock').dataset.tone=locks.length?'warn':'';
  }
  if($('rail-tel-lat')&&$('tel-lat'))$('rail-tel-lat').textContent=$('tel-lat').textContent;
  if($('rail-tel-track')&&$('tel-track'))$('rail-tel-track').textContent=$('tel-track').textContent;
}

if($('hdr-record-btn')){
  $('hdr-record-btn').addEventListener('click',async()=>{
    const code=lastStatus?lastStatus.status:'';
    if(code==='recording'||code==='handing_over'){
      if(stopInFlight)return;
      stopInFlight=true;setReqError('');syncHeaderAndSlimBar();
      const seq=++latestStatusSeq;
      try{const st=await api('/stop',{});if(seq===latestStatusSeq)renderStatus(st);}
      catch(err){setReqError(err.message);}
      finally{stopInFlight=false;validateStart();}
    }else if(window.benchStartReady){
      f.requestSubmit();
    }
  });
}
if($('hdr-estop-btn')){
  $('hdr-estop-btn').addEventListener('click',async()=>{
    if(stopInFlight)return;
    stopInFlight=true;setReqError('');
    try{renderStatus(await api('/stop',{}));}
    catch(err){setReqError('비상정지 요청: '+err.message);}
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
initRailToggle();

async function checkCameraDrift(){
  const note=$('cam-drift-note');
  if(!note)return;
  try{
    const arm=f&&f.arm?f.arm.value:'';
    const d=await api('/api/camera_check?arm='+encodeURIComponent(arm));
    if(!d||!d.cameras){note.hidden=true;return;}
    const bad=Object.entries(d.cameras).filter(([,v])=>v.status!=='ok'&&v.status!=='no_baseline');
    const noBase=Object.entries(d.cameras).filter(([,v])=>v.status==='no_baseline');
    note.hidden=false;
    if(bad.length){
      note.className='alert warn';
      note.textContent='카메라 변화 감지: '+bad.map(([k,v])=>k+'('+v.status+(v.max_px!=null?' '+v.max_px+'px':'')+(v.delta_mean!=null?' Δ밝기'+v.delta_mean:'')+')').join(', ')+' — 각도/조명을 맞추거나 기준 재저장하세요.';
    }else if(noBase.length){
      note.className='alert';
      note.textContent='카메라 기준 미저장 ('+noBase.map(([k])=>k).join(', ')+') — 현재 구도·조명이 맞으면 "기준 카메라 저장"을 누르세요.';
    }else{
      note.className='alert good';
      note.textContent='카메라 기준 일치 (이전 에피소드와 구도·조명 정상)';
    }
  }catch(_){}
}
if($('save-cam-base-btn')){
  $('save-cam-base-btn').addEventListener('click',async()=>{
    const btn=$('save-cam-base-btn');
    btn.disabled=true;btn.textContent='저장 중...';
    try{setReqError('');await api('/api/camera_baseline',{arm:f.arm.value,at_bench:f.at_bench.checked});await checkCameraDrift();}
    catch(err){setReqError(err.message);}
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
setInterval(syncHeaderAndSlimBar,150);
setTimeout(syncReplayUI,600);

const HF_AUTO_KEY='omx_hf_auto_upload';
const HF_STATE_MAP={idle:['대기','warn'],encoding:['인코딩 중','live'],uploading:['업로드 중','live'],done:['업로드 완료','good'],failed:['업로드 실패','crit']};
let hfUploadInFlight=false, lastHfAutoSealKey='';

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
  if(!ul||!empty)return;
  if(!rows.length){ul.innerHTML='';empty.hidden=false;return;}
  empty.hidden=true;ul.innerHTML='';
  const busyAll=hfUploadInFlight||state==='encoding'||state==='uploading';
  for(const r of rows){
    const li=document.createElement('li');li.className='sess-item hf-ds-row';
    const top=document.createElement('div');top.className='hf-ds-top';
    const left=document.createElement('span');left.className='mono';left.textContent=r.name||'';
    const act=document.createElement('div');act.style.cssText='display:flex;align-items:center;gap:6px';
    if(r.hf_uploaded){const tag=document.createElement('span');tag.className='ui-tag';tag.dataset.tone='good';tag.textContent='업로드 완료';act.append(tag);}
    const btn=document.createElement('button');btn.type='button';btn.className='btn-tool btn-xs';
    btn.textContent=(busyAll&&up.dataset===r.name)?sTxt:'HF(LeRobot) 업로드';
    btn.disabled=Boolean(!hfOk||busyAll||r.do_not_train);
    btn.addEventListener('click',()=>triggerHfUpload(r.name||''));
    act.append(btn);top.append(left,act);
    const meta=document.createElement('div');meta.className='hf-ds-meta quiet';
    const info=document.createElement('span');
    info.textContent=r.episodes+'회(parquet) · '+r.videos+'개(MP4)'+(r.do_not_train?' · 정지회차(DO_NOT_TRAIN)':'');
    meta.append(info);
    if(r.hf_repo_url){const a=document.createElement('a');a.href=r.hf_repo_url;a.target='_blank';a.rel='noopener';a.className='mono';a.textContent=r.hf_repo_id||'Repo';meta.append(a);}
    li.append(top,meta);ul.append(li);
  }
}
window.renderLeRobotPanel=renderLeRobotPanel;

if($('hf-auto-upload')){
  const saved=localStorage.getItem(HF_AUTO_KEY)==='1';
  $('hf-auto-upload').checked=saved;
  if(saved){api('/api/hf/config',{auto_upload:true}).catch(()=>{});}
  $('hf-auto-upload').addEventListener('change',async()=>{
    const on=$('hf-auto-upload').checked;
    try{localStorage.setItem(HF_AUTO_KEY,on?'1':'0');}catch(_){}
    try{await api('/api/hf/config',{auto_upload:on});}catch(_){}
  });
}
setInterval(()=>{
  const cur=typeof lastStatus!=='undefined'&&lastStatus?lastStatus.status:'';
  const sk=typeof sessionKey==='function'&&lastStatus?sessionKey(lastStatus):'';
  if(cur==='sealed'&&sk&&sk!==lastHfAutoSealKey&&$('hf-auto-upload')?.checked){
    lastHfAutoSealKey=sk;
    triggerHfUpload(lastStatus.name||lastStatus.folder||'');
  }
},1000);
init();
pollArms();
setInterval(pollArms,10000);
