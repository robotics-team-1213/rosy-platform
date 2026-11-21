(function(){
const JOB_MAP={idle:['대기','warn'],running:['실행 중','live'],done:['완료','good'],failed:['실패','crit']};
const AUTO_KEY='omx_pipe_auto_loop';
let lastPreviewReplay='';
let lastAutoSealKey='';
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
    rp.className='rail-step'+(jobState==='done'?' ok':'');
  }
  const stCode=typeof lastStatus!=='undefined'&&lastStatus?lastStatus.status:'idle';
  const collectState=(stCode==='recording'||stCode==='handing_over')?'running':(stCode==='sealed'?'done':(stCode==='failed'||stCode==='unsafe_or_failed'?'failed':'idle'));
  const stages=p.stages||{};
  for(const li of document.querySelectorAll('#pipe-stepper .pipe-step')){
    const k=li.dataset.stage;
    li.dataset.state=(k==='collect'&&(!stages.collect||stages.collect==='idle'))?collectState:(stages[k]||'idle');
  }
  const loopEl=$('pipe-loop-badge'), metaEl=$('pipe-loop-meta');
  if(loopEl){
    loopEl.textContent='루프 '+(p.loop_count||0)+'회';
    loopEl.dataset.tone=p.next_checkpoint?'good':'';
  }
  if(metaEl){
    const parts=[];
    if(p.last_dataset)parts.push('데이터셋: '+p.last_dataset);
    if(p.augmented_dataset)parts.push('증강: '+p.augmented_dataset);
    if(p.next_checkpoint)parts.push('다음 RL 체크포인트: '+p.next_checkpoint);
    metaEl.textContent=parts.length?parts.join(' → '):'데이터셋 · 증강 · RL 체크포인트 피드백 대기 중';
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
  const saved=localStorage.getItem(AUTO_KEY)==='1';
  $('pipe-auto-toggle').checked=saved;
  if(saved){api('/api/pipeline/config',{auto_loop:true}).catch(()=>{});}
  $('pipe-auto-toggle').addEventListener('change',async()=>{
    const on=$('pipe-auto-toggle').checked;
    try{localStorage.setItem(AUTO_KEY,on?'1':'0');}catch(_){}
    try{await api('/api/pipeline/config',{auto_loop:on});}catch(_){}
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

setInterval(()=>{
  const cur=typeof lastStatus!=='undefined'&&lastStatus?lastStatus.status:'';
  const sk=typeof sessionKey==='function'&&lastStatus?sessionKey(lastStatus):'';
  if(cur==='sealed'&&sk&&sk!==lastAutoSealKey&&$('pipe-auto-toggle')?.checked){
    lastAutoSealKey=sk;
    triggerPipelineRun('auto_after_seal');
  }
},1000);

pollPipeline();
setInterval(pollPipeline,2500);
})();
