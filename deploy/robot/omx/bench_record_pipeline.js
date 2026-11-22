(function(){
const JOB_MAP={idle:['대기','warn'],running:['실행 중','live'],blocked:['설정 필요','warn'],transferred:['전송 완료','good'],done:['전달 완료','good'],failed:['실패','crit']};
let lastPreviewReplay='';
let pipeInFlight=false;

function setBadge(el,state,label){
  if(!el)return;
  const [txt,tone]=JOB_MAP[state]||[label||state||'대기','warn'];
  el.textContent=label||txt;
  el.dataset.tone=tone;
}

function renderPipeline(p){
  if(!p||typeof p!=='object')return;
  const jobState=p.state||'idle';
  setBadge($('pipe-job-badge'),jobState);
  const rp=$('rail-pipe');
  if(rp){
    const [txt]=JOB_MAP[jobState]||['대기'];
    rp.textContent=txt;
    rp.className='rail-step'+(jobState==='done'||jobState==='transferred'?' ok':'');
  }
  const sp=$('sum-pipe-drawer');
  if(sp){
    const [txt]=JOB_MAP[jobState]||['대기'];
    const qLen=Array.isArray(p.pending_queue)?p.pending_queue.filter(r=>r.status!=='done').length:0;
    sp.textContent=txt+' · 전달 '+(p.loop_count||0)+'회'+(p.last_dataset?' · '+p.last_dataset:'')+(qLen?' (대기 '+qLen+')':'');
  }
  const stCode=typeof lastStatus!=='undefined'&&lastStatus?lastStatus.status:'idle';
  const collectState=(stCode==='recording'||stCode==='handing_over')?'running':(stCode==='sealed'?'done':(stCode==='failed'||stCode==='unsafe_or_failed'?'failed':'idle'));
  const stages=p.stages||{};
  for(const li of document.querySelectorAll('#pipe-stepper .pipe-step')){
    const k=li.dataset.stage;
    const raw=(k==='collect'&&(!stages.collect||stages.collect==='idle'))?collectState:(stages[k]||'idle');
    li.dataset.state=(raw==='unconfigured')?'warn':raw;
  }
  const toggle=$('pipe-auto-toggle');
  if(toggle&&document.activeElement!==toggle){
    toggle.checked=Boolean(p.auto_loop);
  }
  const loopEl=$('pipe-loop-badge'), metaEl=$('pipe-loop-meta');
  if(loopEl){
    loopEl.textContent='전달 '+(p.loop_count||0)+'회';
    loopEl.dataset.tone=(jobState==='done')?'good':(jobState==='failed'?'crit':'');
  }
  if(metaEl){
    const parts=[];
    if(p.last_dataset)parts.push('컬렉션: '+p.last_dataset);
    if(p.manifest_sha256)parts.push('sha256='+String(p.manifest_sha256).slice(0,10));
    if(p.remote_path)parts.push('모델PC: '+p.remote_path);
    if(!p.model_target&&!p.error)parts.push('모델PC 미설정');
    if(p.intake_job_id)parts.push('job='+p.intake_job_id.slice(0,8));
    if(p.error)parts.push('상태: '+p.error);
    metaEl.textContent=parts.length?parts.join(' · '):'모델 PC 전달 및 Canonical 인입 대기 중';
  }
  const logEl=$('pipe-log');
  if(logEl){
    const txt=Array.isArray(p.logs)?p.logs.join('\n'):String(p.log_tail||'');
    logEl.textContent=txt;
    logEl.hidden=!txt;
    if(txt)logEl.scrollTop=logEl.scrollHeight;
  }
  const runBtn=$('pipe-run-btn');
  if(runBtn)runBtn.disabled=pipeInFlight||jobState==='running';
}

async function pollPipeline(){
  try{renderPipeline(await api('/api/pipeline/status'));}catch(_){}
}

async function triggerPipelineRun(reason){
  if(pipeInFlight)return;
  pipeInFlight=true;
  setReqError('');
  try{
    const st=await api('/api/pipeline/run',{
      source_type:$('pipe-source-type')?.value||'isaac_sim',
      source_ref:$('pipe-source-ref')?.value?.trim()||'',
      dataset_folder:lastStatus?.name||lastStatus?.folder||'',
      task:f?.task?.value||'',
      arm:f?.arm?.value||'',
      trigger:reason||'manual'
    });
    renderPipeline(st);
  }catch(err){setReqError('파이프라인 실행 오류: '+err.message);}
  finally{pipeInFlight=false;}
}

if($('pipe-auto-toggle')){
  $('pipe-auto-toggle').addEventListener('change',async()=>{
    const on=$('pipe-auto-toggle').checked;
    try{renderPipeline(await api('/api/pipeline/config',{auto_loop:on}));}catch(err){setReqError('자동 전달 설정 오류: '+err.message);}
  });
}

if($('pipe-gen-btn')){
  $('pipe-gen-btn').addEventListener('click',async()=>{
    const btn=$('pipe-gen-btn'), box=$('pipe-preview-box'), appBtn=$('pipe-apply-replay-btn');
    btn.disabled=true;btn.textContent='생성 중...';setReqError('');
    try{
      const revOn=$('toggle-reverse-btn')?.getAttribute('aria-pressed')==='true';
      const swOn=Boolean(window.zoneSwapped);
      const res=await api('/api/pipeline/generate_replay',{
        source_type:$('pipe-source-type')?.value||'isaac_sim',
        source_ref:$('pipe-source-ref')?.value?.trim()||'',
        arm:f?.arm?.value||'',
        task:f?.task?.value||'',
        origin:swOn?'belt-in':'',
        target_slot:swOn?'pinky':'',
        replay_mode:revOn?($('reverse-mode')?.value||'swap_ab'):'none',
        invert_gripper:Boolean($('invert-gripper')?.checked)
      });
      lastPreviewReplay=res.replay_id||'';
      if(box){
        box.textContent=(res.summary||'궤적 생성 완료')+(lastPreviewReplay?' · replay='+lastPreviewReplay:'');
        box.hidden=false;
      }
      if(appBtn)appBtn.disabled=!lastPreviewReplay;
      if(res.pipeline)renderPipeline(res.pipeline);
    }catch(err){setReqError('궤적 생성 오류: '+err.message);}
    finally{btn.disabled=false;btn.textContent='궤적 생성 · 미리보기';}
  });
}

if($('pipe-apply-replay-btn')){
  $('pipe-apply-replay-btn').addEventListener('click',()=>{
    const rSel=$('replay');
    if(!rSel||!lastPreviewReplay)return;
    if(![...rSel.options].some(o=>o.value===lastPreviewReplay)){
      rSel.append(new Option(lastPreviewReplay+' (시뮬/모델)',lastPreviewReplay));
    }
    rSel.value=lastPreviewReplay;
    rSel.dispatchEvent(new Event('change'));
  });
}

if($('pipe-run-btn')){
  $('pipe-run-btn').addEventListener('click',()=>triggerPipelineRun('manual'));
}

pollPipeline();
setInterval(pollPipeline,2500);
})();
