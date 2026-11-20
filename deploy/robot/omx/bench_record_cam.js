function epQuota(c){
  if(!c||c.valid===false||c.num_episodes==null)return null;
  const goal=Number(c.num_episodes)||0;
  const sc=(typeof lastStatus!=='undefined'&&lastStatus&&lastStatus.scenario_counts&&c.task_id)?lastStatus.scenario_counts[c.task_id]:null;
  const done=sc?Number(sc.episodes)||0:0;
  const rem=Math.max(0,goal-done);
  const pct=goal>0?Math.min(100,Math.round(done/goal*100)):0;
  return {done,goal,rem,pct};
}
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
    try{
      setReqError('');
      await api('/api/camera_baseline',{arm:f.arm.value,at_bench:f.at_bench.checked});
      await checkCameraDrift();
    }catch(err){setReqError(err.message);}
    finally{btn.disabled=false;btn.textContent='기준 카메라 저장';}
  });
}
setInterval(checkCameraDrift,8000);
setTimeout(checkCameraDrift,800);

$('stop-btn').addEventListener('click',async()=>{
  if(stopInFlight)return;
  stopInFlight=true;
  setReqError('');
  validateStart();
  const seq=++latestStatusSeq;
  try{
    const st=await api('/stop',{});
    if(seq!==latestStatusSeq)return;
    renderStatus(st);
  }catch(err){
    setReqError(err.message);
  }finally{
    stopInFlight=false;
    validateStart();
  }
});

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
init();
pollArms();
setInterval(pollArms,10000);
