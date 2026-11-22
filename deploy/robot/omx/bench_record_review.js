// Manual hold diagnosis/recovery panel and per-episode evaluation, playback, DO_NOT_TRAIN, and deletion.
(function(){
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function renderManualHoldCard(st){
  const card=$('manual-hold-card');
  if(!card)return;
  const mh=st&&st.manual_hold&&st.manual_hold.active?st.manual_hold:null;
  if(!mh){card.hidden=true;return;}
  card.hidden=false;
  if($('mh-reason'))$('mh-reason').textContent=mh.reason||'사람 확인 필요';
  const badge=$('mh-torque-badge');
  if(badge){
    badge.textContent=mh.runner_alive?'토크 ON 유지 중 (PID '+mh.runner_pid+')':(mh.lease_hold?'임대 hold 확인 필요':'러너 종료됨 (복원 대기)');
    badge.dataset.tone=mh.runner_alive?'crit':(mh.lease_hold?'warn':'good');
  }
  const facts=$('mh-facts');
  if(facts){
    const parts=[];
    if(mh.arm)parts.push('팔: '+mh.arm);
    if(mh.runner_pid)parts.push('PID: '+mh.runner_pid+(mh.runner_alive?' (실행 중)':' (종료)'));
    if(Array.isArray(mh.live_pose))parts.push('관절: ['+mh.live_pose.join(', ')+']');
    if(Array.isArray(mh.pending_units)&&mh.pending_units.length)parts.push('중지 유닛: '+mh.pending_units.length+'개');
    facts.textContent=parts.join(' · ');
  }
  const hint=$('mh-cause-hint');
  if(hint){
    if(mh.worker_human_hold){
      hint.textContent='원인 추정: cell-task-worker 또는 안전 워치독이 홈 이동 중 human-hold를 보냈습니다. 새 버전에서는 홈 이동 시 cell-task-worker를 잠시 중지해 재발을 막습니다.';
      hint.hidden=false;
    }else if(mh.detail){
      hint.textContent='세부 사유: '+mh.detail;
      hint.hidden=false;
    }else{hint.hidden=true;}
  }
  const tailEl=$('mh-log-tail');
  if(tailEl){
    const txt=Array.isArray(mh.log_tail)?mh.log_tail.join('\n'):'';
    tailEl.textContent=txt;tailEl.hidden=!txt;
  }
  const relBox=$('mh-release-box'), clearBtn=$('mh-clear-btn'), relBtn=$('mh-release-btn');
  if(relBox)relBox.hidden=!mh.runner_alive;
  if(relBtn&&!relBtn.dataset.busy)relBtn.disabled=!($('mh-support-check')?.checked);
  if(clearBtn)clearBtn.disabled=Boolean(mh.runner_alive);
}
window.renderManualHoldCard=renderManualHoldCard;

if($('mh-support-check')&&$('mh-release-btn')){
  $('mh-support-check').addEventListener('change',()=>{
    $('mh-release-btn').disabled=!$('mh-support-check').checked||Boolean($('mh-release-btn').dataset.busy);
  });
  $('mh-release-btn').addEventListener('click',async()=>{
    const btn=$('mh-release-btn'), mh=lastStatus?.manual_hold;
    if(!mh||!$('mh-support-check').checked)return;
    btn.dataset.busy='1';btn.disabled=true;setReqError('');
    try{
      const res=await api('/api/manual_hold/release_runner',{arm:mh.arm,pid:mh.runner_pid,arm_supported_confirmed:true});
      $('mh-support-check').checked=false;
      if(typeof window.pushBenchLog==='function')window.pushBenchLog('pose','warn','HOLD 러너(PID '+mh.runner_pid+') SIGUSR2 해제 요청 완료');
      if(res&&res.status)renderStatus(res.status);else await pollStatus();
    }catch(e){setReqError(e.message||String(e));}
    finally{delete btn.dataset.busy;btn.disabled=!$('mh-support-check').checked;}
  });
}
if($('mh-clear-btn')&&$('mh-clear-confirm')){
  $('mh-clear-btn').addEventListener('click',()=>{$('mh-clear-confirm').hidden=false;});
  $('mh-clear-no')?.addEventListener('click',()=>{$('mh-clear-confirm').hidden=true;});
  $('mh-clear-yes')?.addEventListener('click',async()=>{
    $('mh-clear-confirm').hidden=true;setReqError('');
    try{
      const st=await api('/api/manual_hold/clear',{confirmed:true});
      if(typeof window.pushBenchLog==='function')window.pushBenchLog('bench','good','수동 확인 보류 해제 및 대기 복귀 완료');
      renderStatus(st);
    }catch(e){setReqError(e.message||String(e));await pollStatus();}
  });
}
$('mh-log-btn')?.addEventListener('click',()=>{$('sec-live-log')?.scrollIntoView({block:'nearest'});});

const openTrays=new Map();
const RATING_LABELS={good:'합격',bad:'불량',retry:'재녹화',unrated:'미평가'};

async function renderEpisodeReviewPanel(host,dsName){
  if(!host||!dsName)return;
  host.innerHTML='<div class="quiet mono" style="padding:6px">에피소드 평가 정보를 불러오는 중...</div>';
  let data;
  try{data=await api('/api/dataset/episodes?dataset='+encodeURIComponent(dsName));}
  catch(e){host.innerHTML='<div class="alert crit">'+esc(e.message||String(e))+'</div>';return;}

  const eps=Array.isArray(data.episodes)?data.episodes:[];
  const cams=Array.isArray(data.cameras)?data.cameras:[];
  let selCam=host.dataset.selCam||(cams.includes('top')?'top':(cams[0]||''));
  const sum=data.summary||{};
  const badIndices=eps.filter(e=>e.rating==='bad').map(e=>e.index);
  const busy=(typeof benchSessionActive==='function'&&benchSessionActive());

  let h='<div class="ep-review-box">';
  h+='<div class="ep-review-head"><div class="mono" style="font-size:.78rem"><b>'+esc(dsName)+'</b> · '+eps.length+'회 · 합격 '+(sum.good||0)+' · 불량 '+(sum.bad||0)+' · 미평가 '+(sum.unrated||0)+'</div>';
  h+='<div class="ep-review-bulk">';
  if(badIndices.length)h+='<button type="button" class="btn-tool btn-xs" data-tone="warn" data-ep-del-bad="1"'+(busy?' disabled':'')+'>불량 '+badIndices.length+'개 일괄 삭제</button>';
  h+='<button type="button" class="btn-tool btn-xs" data-ds-dnt="'+(data.do_not_train?'0':'1')+'"'+(busy?' disabled':'')+'>'+(data.do_not_train?'학습제외 해제':'학습제외(DO_NOT_TRAIN)')+'</button>';
  h+='<button type="button" class="btn-tool btn-xs" data-tone="warn" data-ds-trash="1"'+(busy?' disabled':'')+'>데이터셋 삭제</button>';
  h+='</div></div>';
  h+='<div class="reset-confirm-bar" data-confirm-box hidden><span class="quiet" data-confirm-msg></span><div style="display:flex;gap:6px"><button type="button" class="btn-primary btn-xs" data-confirm-yes>삭제 확인</button><button type="button" class="btn-tool btn-xs" data-confirm-no>취소</button></div></div>';

  if(cams.length){
    h+='<div class="ep-video-wrap" data-video-wrap hidden><div class="ep-video-bar"><div class="dir-toggle">';
    for(const c of cams)h+='<button type="button" class="pill-btn'+(c===selCam?' active':'')+'" data-ep-cam="'+esc(c)+'">'+esc(c)+'</button>';
    h+='</div><span class="mono quiet" data-ep-play-lbl></span></div><video class="ep-video-el" controls preload="metadata" playsinline></video></div>';
  }

  h+='<ul class="ep-list">';
  for(const ep of eps){
    const rCls=ep.rating||'unrated';
    const meta=[ep.length?(ep.length+'프레임'):'',ep.duration_s!=null?(ep.duration_s+'s'):'',ep.static?'정지 의심':''].filter(Boolean).join(' · ');
    h+='<li class="ep-row" data-ep-rating="'+esc(rCls)+'">';
    h+='<div class="ep-row-top"><span class="mono"><b>#'+ep.index+'</b>'+(meta?' <span class="quiet">('+esc(meta)+')</span>':'')+'</span>';
    h+='<div class="ep-row-btns">';
    if(cams.length)h+='<button type="button" class="btn-tool btn-xs" data-ep-play="'+ep.index+'">재생</button>';
    for(const k of ['good','bad','retry']){
      h+='<button type="button" class="pill-btn'+(rCls===k?' active':'')+'" data-ep-rate="'+ep.index+'" data-rate-val="'+k+'" data-rate-tone="'+k+'">'+RATING_LABELS[k]+'</button>';
    }
    h+='<button type="button" class="btn-tool btn-xs" data-tone="warn" data-ep-del="'+ep.index+'"'+(busy?' disabled':'')+'>삭제</button>';
    h+='</div></div>';
    h+='<input type="text" class="ep-note-inp" data-ep-note="'+ep.index+'" value="'+esc(ep.note||'')+'" data-rate-cur="'+esc(rCls)+'" placeholder="메모 (불량 사유 등 · Enter 저장)">';
    h+='</li>';
  }
  if(!eps.length)h+='<li class="quiet" style="padding:6px">에피소드가 없습니다.</li>';
  host.innerHTML=h+'</ul></div>';

  const confirmBox=host.querySelector('[data-confirm-box]'), confirmMsg=host.querySelector('[data-confirm-msg]');
  let pendingAct=null;
  const askConfirm=(msg,fn)=>{if(!confirmBox)return;confirmMsg.textContent=msg;pendingAct=fn;confirmBox.hidden=false;};
  host.querySelector('[data-confirm-no]')?.addEventListener('click',()=>{confirmBox.hidden=true;pendingAct=null;});
  host.querySelector('[data-confirm-yes]')?.addEventListener('click',async()=>{
    const fn=pendingAct;confirmBox.hidden=true;pendingAct=null;if(fn)await fn();
  });

  const vidWrap=host.querySelector('[data-video-wrap]'), vid=host.querySelector('.ep-video-el'), playLbl=host.querySelector('[data-ep-play-lbl]');
  let activeEpIdx=null;
  const playEpisode=(idx)=>{
    const epObj=eps.find(x=>x.index===idx);
    if(!vid||!epObj)return;
    const vInfo=(epObj.videos&&epObj.videos[selCam])||{chunk:0,file:0,from_s:0,to_s:0};
    const tFrag=(vInfo.to_s>vInfo.from_s)?('#t='+vInfo.from_s+','+vInfo.to_s):'#t=0';
    const src='/api/dataset/video?dataset='+encodeURIComponent(dsName)+'&cam='+encodeURIComponent(selCam)+'&chunk='+(vInfo.chunk||0)+'&file='+(vInfo.file||0)+tFrag;
    vidWrap.hidden=false;activeEpIdx=idx;
    if(playLbl)playLbl.textContent='ep#'+idx+' · '+selCam+(vInfo.to_s>vInfo.from_s?(' ('+vInfo.from_s+'~'+vInfo.to_s+'s)'):'');
    vid.src=src;vid.play().catch(()=>{});
  };
  for(const b of host.querySelectorAll('[data-ep-cam]'))b.addEventListener('click',()=>{
    selCam=b.dataset.epCam;host.dataset.selCam=selCam;
    for(const x of host.querySelectorAll('[data-ep-cam]'))x.classList.toggle('active',x===b);
    if(activeEpIdx!=null)playEpisode(activeEpIdx);
  });
  for(const b of host.querySelectorAll('[data-ep-play]'))b.addEventListener('click',()=>playEpisode(Number(b.dataset.epPlay)));

  for(const b of host.querySelectorAll('[data-ep-rate]'))b.addEventListener('click',async()=>{
    const epIdx=Number(b.dataset.epRate), nextR=b.dataset.rateVal;
    const cur=eps.find(x=>x.index===epIdx);
    const val=(cur&&cur.rating===nextR)?'unrated':nextR;
    const note=(host.querySelector('[data-ep-note="'+epIdx+'"]')?.value||'').trim();
    try{
      await api('/api/dataset/episode/rate',{dataset:dsName,episode:epIdx,rating:val,note});
      await renderEpisodeReviewPanel(host,dsName);
      if(typeof pollStatus==='function')pollStatus();
    }catch(e){setReqError(e.message||String(e));}
  });
  for(const inp of host.querySelectorAll('[data-ep-note]')){
    const saveNote=async()=>{
      const epIdx=Number(inp.dataset.epNote), rating=inp.dataset.rateCur||'unrated';
      try{await api('/api/dataset/episode/rate',{dataset:dsName,episode:epIdx,rating,note:inp.value.trim()});}catch(e){setReqError(e.message||String(e));}
    };
    inp.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();saveNote();}});
    inp.addEventListener('blur',saveNote);
  }
  const runDeleteEps=(indices)=>askConfirm(dsName+' 에피소드 '+indices.map(i=>'#'+i).join(', ')+'를 삭제하고 재인덱싱할까요? (원본은 .trash/로 백업)',async()=>{
    try{
      const res=await api('/api/dataset/episode/delete',{dataset:dsName,episodes:indices,confirm:true});
      if(typeof window.pushBenchLog==='function')window.pushBenchLog('review','warn',dsName+' 에피소드 삭제: '+indices.join(', '));
      if(res.deleted_all){openTrays.delete(dsName);host.remove();}
      else await renderEpisodeReviewPanel(host,dsName);
      if(typeof pollStatus==='function')await pollStatus();
    }catch(e){setReqError(e.message||String(e));}
  });
  for(const b of host.querySelectorAll('[data-ep-del]'))b.addEventListener('click',()=>runDeleteEps([Number(b.dataset.epDel)]));
  host.querySelector('[data-ep-del-bad]')?.addEventListener('click',()=>runDeleteEps(badIndices));
  host.querySelector('[data-ds-dnt]')?.addEventListener('click',async e=>{
    const dnt=e.currentTarget.dataset.dsDnt==='1';
    try{
      await api('/api/dataset/do_not_train',{dataset:dsName,do_not_train:dnt,reason:'bench_review'});
      await renderEpisodeReviewPanel(host,dsName);
      if(typeof pollStatus==='function')await pollStatus();
    }catch(err){setReqError(err.message||String(err));}
  });
  host.querySelector('[data-ds-trash]')?.addEventListener('click',()=>askConfirm('데이터셋 '+dsName+' 전체를 폐기(.trash/로 이동)할까요?',async()=>{
    try{
      await api('/api/dataset/delete',{dataset:dsName,confirm_nonempty:true});
      openTrays.delete(dsName);host.remove();
      if(typeof window.pushBenchLog==='function')window.pushBenchLog('review','warn','데이터셋 폐기: '+dsName);
      if(typeof pollStatus==='function')await pollStatus();
    }catch(e){setReqError(e.message||String(e));}
  }));
}

window.toggleDatasetReviewTray=(li,dsName)=>{
  if(!li||!dsName)return;
  const ex=li.querySelector('.ep-review-tray');
  if(ex){openTrays.delete(dsName);ex.remove();return;}
  const tray=document.createElement('div');
  tray.className='ep-review-tray';
  openTrays.set(dsName,true);
  li.append(tray);
  renderEpisodeReviewPanel(tray,dsName);
};

window.syncResultEpisodeReview=(st)=>{
  const host=$('ev-episode-review');
  if(!host)return;
  if(!st||(typeof currentBenchPhase==='function'&&currentBenchPhase()!=='result')){host.hidden=true;return;}
  const dsRows=Array.isArray(st.lerobot_datasets)?st.lerobot_datasets:[];
  const fBase=st.folder?String(st.folder).split('/').pop():'';
  const hit=dsRows.find(r=>r&&st.name&&(r.name===st.name||(fBase&&r.name===fBase)||r.name.endsWith('-'+st.name)));
  if(!hit||(hit.episodes||0)<1){host.hidden=true;host.innerHTML='';return;}
  host.hidden=false;
  if(host.dataset.loadedDs!==hit.name){
    host.dataset.loadedDs=hit.name;
    renderEpisodeReviewPanel(host,hit.name);
  }
};
window.renderEpisodeReviewPanel=renderEpisodeReviewPanel;
})();