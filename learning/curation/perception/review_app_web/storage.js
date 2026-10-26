import {clearStorageSetup,loadStorageSetup,storageSetupDirty} from '/storage-settings.js';
const $=id=>document.getElementById(id);
const bytes=value=>value==null?'미확인':`${(value/1024**3).toLocaleString('ko-KR',{maximumFractionDigits:3})} GiB`;
const roles={raw:'수집 원본',derived:'파생 자료',cache:'작업 캐시',pending:'전송 대기'};
let send, busy=false, epoch=0;
function line(parent,value){const p=document.createElement('p');p.textContent=value;parent.append(p);}
function fail(error){$('storage-error').textContent=error.message||'저장 현황을 확인할 수 없습니다.';$('storage-error').hidden=false;}
export function clearStorage(){
  clearStorageSetup();
  clearTimeout(poolTimer);lastJobs='';confirmJob=null;reconcileJob=null;
  $('storage-pool').hidden=true;$('storage-targets').replaceChildren();$('storage-jobs').replaceChildren();
  $('storage-source').replaceChildren();$('storage-artifact').value='';
  $('storage-confirmation').hidden=true;$('storage-pool-error').hidden=true;
  $('storage-reconciliation').hidden=true;$('storage-existing-revision').value='';
  epoch+=1;
  $('storage-status').textContent='저장 현황 미확인';
  $('storage-roots').replaceChildren();$('storage-destination').replaceChildren();
  $('storage-preflight').hidden=true;$('storage-result').textContent='';
}
export async function loadStorage(request){
  if(busy)return;
  if(storageSetupDirty()&&!confirm('저장하지 않은 설정이 있습니다. 입력을 버리고 저장 현황을 다시 불러올까요?'))return;
  send=request;busy=true;$('storage-refresh').disabled=true;$('storage-error').hidden=true;
  clearStorage();
  const current=epoch;
  await loadStorageSetup(send,()=>loadStorage(send));
  $('storage-status').textContent='저장 현황을 확인하는 중입니다.';
  try{
    const data=await send('/api/learning/storage');
    if(current!==epoch)return;
    if(data.status==='not_configured'){
      $('storage-status').textContent='저장 경로 미설정 · 관리자가 프로젝트의 수집·저장 폴더를 등록해야 합니다.';return;
    }
    $('storage-status').textContent=`${new Date(data.measured_at*1000).toLocaleString('ko-KR')} 측정 · 전송 대기 ${bytes(data.pending_bytes)} · 최대 60초 캐시`;
    for(const row of data.roots){
      const article=document.createElement('article');$('storage-roots').append(article);
      const heading=document.createElement('h3');heading.textContent=`${row.label} · ${roles[row.role]}`;article.append(heading);
      line(article,row.status==='ready'?`파일 ${row.files}개 · 논리 크기 ${bytes(row.logical_bytes)} · 하드링크 중복 제외 ${bytes(row.file_bytes)} · 할당 ${bytes(row.allocated_bytes)}`:
        row.status==='partial'?'일부 항목을 집계하지 못했습니다. 합계 미확인.':'등록 폴더를 읽을 수 없습니다. 합계 미확인.');
      line(article,`미완료 이름의 파일 ${bytes(row.incomplete_bytes)} · 볼륨 잔여 ${bytes(row.free_bytes)}`);
      line(article,`하루 증가량 ${bytes(row.growth_bytes_per_day)} · 예상 잔여 ${row.estimated_days==null?'미확인':row.estimated_days.toFixed(1)+'일'} (최근 30일의 이 폴더 증가율 기준)`);
      const option=document.createElement('option');option.value=row.id;option.textContent=row.label;$('storage-destination').append(option);
    }
    $('storage-preflight').hidden=false;
    await refreshPool(current);
  }catch(error){if(current!==epoch)return;clearStorage();$('storage-status').textContent='저장 현황 확인 실패 · 다시 확인으로 재시도하세요.';fail(error);}
  finally{busy=false;$('storage-refresh').disabled=false;}
}
$('storage-refresh').onclick=()=>{if(send)loadStorage(send);};
$('storage-preflight').onsubmit=async event=>{
  event.preventDefault();if(busy||!send)return;
  busy=true;const button=event.target.querySelector('button');button.disabled=true;
  $('storage-error').hidden=true;$('storage-result').textContent='공간을 점검하는 중입니다.';
  const current=epoch;
  try{
    const body={destination_id:$('storage-destination').value};
    for(const key of ['download','staging','transform','upload']) body[`${key}_bytes`]=Math.ceil(Number($(`storage-${key}`).value)*1024**3);
    const result=await send('/api/learning/storage/preflight',body);
    if(current!==epoch)return;
    const states={ready:'공간 추정 충족',hold:'공간 확인 보류',blocked:'공간 부족'};
    const remote={not_required:'업로드 없음',unknown:'미확인 또는 유효기간 만료',sufficient:'추정 충족',insufficient:'부족'};
    $('storage-result').textContent=`${states[result.status]} · 로컬 필요 ${bytes(result.local_required_bytes)} (여유분 ${bytes(result.reserve_bytes)} 포함) / 잔여 ${bytes(result.local_available_bytes)} · 원격 ${remote[result.remote_status]} · 공간 예약·전송은 하지 않았습니다.`;
    if(result.remote_quota) $('storage-result').textContent+=` 원격 근거: ${result.remote_quota.source}, ${new Date(result.remote_quota.measured_at*1000).toLocaleString('ko-KR')} 측정.`;
  }catch(error){if(current!==epoch)return;$('storage-result').textContent='공간 점검 실패';if(error.status===401||error.status===403)clearStorage();fail(error);}
  finally{busy=false;button.disabled=false;}
};

let poolTimer, poolBusy=false, lastJobs='', confirmJob=null, reconcileJob=null, capabilities={};
const jobStates={queued:'전송 대기',uploading:'업로드 중',uploaded:'원격 커밋 기록됨',verifying:'원격 검증 중',
  verified:'원격 검증 완료',failed:'전송·검증 실패',hold:'원격 결과 확인 필요',reclaiming:'로컬 정리 확인 필요',cancelled:'취소됨'};
const operations={run:'전송·검증 중',restore:'복원 중',reclaim:'로컬 정리 중',cache_reclaim:'캐시 공간 확보 중'};
function poolError(error){
  $('storage-pool-error').textContent=error.message||'보관 작업을 확인하지 못했습니다. 다시 확인하세요.';
  $('storage-pool-error').hidden=false;
}
function actionButton(parent,label,action,disabled=false){
  const button=document.createElement('ui-button');button.setAttribute('kind','quiet');button.textContent=label;
  button.toggleAttribute('disabled',disabled);button.addEventListener('click',action);parent.append(button);
}
function showJobs(rows){
  const encoded=JSON.stringify(rows);if(encoded===lastJobs)return;lastJobs=encoded;
  const active=document.activeElement, focused=active?.closest('[data-job]')?.dataset.job;
  const label=focused?active.textContent:null;
  $('storage-jobs').replaceChildren();
  if(!rows.length){line($('storage-jobs'),'아직 보관 작업이 없습니다. 완료된 자료 폴더를 등록하세요.');return;}
  for(const job of rows){
    const article=document.createElement('article');article.className='storage-job';article.dataset.job=job.id;
    const heading=document.createElement('h4');heading.textContent=job.provenance?.run_id||job.id;article.append(heading);
    line(article,`${jobStates[job.status]||'상태 확인 필요'} · ${bytes(job.upload_bytes)} · ${job.local_present===true?'로컬 사본 있음':job.local_present===false?'로컬 사본 없음':'로컬 사본 확인 필요'}${job.pinned?' · 고정 보관':''}`);
    line(article,`${job.repo_id||'저장소 미확인'}${job.revision?' · 버전 '+job.revision.slice(0,12):''}`);
    if(job.files_total>32)line(article,`전송 기록 ${job.files_uploaded}/${job.files_total}개 · 전체 검증 후 로컬 정리 가능`);
    if(job.operation)line(article,operations[job.operation]||'작업 중');
    if(job.error==='upload_outcome_unknown')line(article,'원격 커밋 결과를 확인해야 합니다. 계정을 바꾸거나 다시 업로드하지 않습니다.');
    else if(job.error||job.operation_error)line(article,'작업을 마치지 못했습니다. 원격 권한·공간과 현재 자료 상태를 확인한 뒤 같은 작업으로 재시도하세요.');
    const actions=document.createElement('div');actions.className='storage-actions';article.append(actions);
    const pending=Boolean(job.operation);
    if(capabilities.publish&&!job.bytes_verified&&['queued','failed','uploading','uploaded','verifying'].includes(job.status))
      actionButton(actions,'전송·검증',()=>operate(job.id,'run'),pending);
    if(capabilities.publish&&['queued','failed'].includes(job.status)&&!job.revision)
      actionButton(actions,'대기 취소',()=>operate(job.id,'cancel'),pending);
    if(capabilities.publish&&job.status==='hold')actionButton(actions,'기존 커밋 확인',()=>{
      reconcileJob=job;$('storage-reconciliation').hidden=false;$('storage-confirmation').hidden=true;confirmJob=null;
      $('storage-reconcile-description').textContent=`${job.repo_id} · 작업 ID ${job.id}`;
      $('storage-existing-revision').value='';$('storage-existing-revision').focus();
    },pending);
    if(capabilities.publish&&job.bytes_verified&&job.local_present===false&&job.status==='verified')
      actionButton(actions,'필요 자료 복원',()=>operate(job.id,'restore'),pending);
    if(capabilities.manage&&job.bytes_verified){
      actionButton(actions,job.pinned?'고정 보관 해제':'고정 보관',()=>operate(job.id,'pin',{pinned:!job.pinned}),pending);
      if(job.reclaimable||job.status==='reclaiming')actionButton(actions,'로컬 정리',()=>{
        confirmJob=job;$('storage-confirmation').hidden=false;
        $('storage-reconciliation').hidden=true;reconcileJob=null;
        $('storage-confirm-description').textContent=`정리할 자료: ${job.provenance?.run_id||job.id} · ${bytes(job.upload_bytes)}. 아래에 작업 ID ${job.id}를 입력하세요.`;
        $('storage-confirm-id').value='';$('storage-confirm-submit').disabled=true;$('storage-confirm-id').focus();
      },pending);
    }
    $('storage-jobs').append(article);
  }
  if(focused){
    const replacement=[...$('storage-jobs').querySelectorAll(`[data-job="${focused}"] ui-button`)].find(b=>b.textContent===label);
    if(replacement)replacement.focus({preventScroll:true});
  }
}
async function refreshPool(current=epoch){
  clearTimeout(poolTimer);
  try{
    const [pool,listing]=await Promise.all([send('/api/learning/storage/pool'),send('/api/learning/storage/jobs')]);
    if(current!==epoch)return;
    $('storage-pool').hidden=false;$('storage-pool-error').hidden=true;
    if(pool.status==='not_configured'){
      $('storage-pool-status').textContent='원격 보관 미설정 · 관리자가 계정 연결과 저장 대상을 등록하면 사용할 수 있습니다.';
      $('storage-archive').hidden=true;$('storage-cache-reclaim').hidden=true;return;
    }
    capabilities=pool.capabilities;
    $('storage-pool-status').textContent=(pool.enabled===false?'새 보관 배정 중지 · 위 설정에서 활성화하세요. ':'')+'같은 계정·조직의 저장소는 용량을 공유합니다. 표시한 잔여량은 예약과 여유분을 뺀 추정입니다.';
    $('storage-targets').replaceChildren();
    for(const target of pool.targets){
      const row=document.createElement('p');row.className='storage-target';
      const state={ready:'배정 가능',unknown:'용량 미확인 · 측정값 갱신 필요',unavailable:'연결·권한 확인 필요',disabled:'배정 중지'};
      row.textContent=`${target.id}${target.repo_id?' · '+target.repo_id:''} · ${state[target.status]||'확인 필요'} · 잔여 ${bytes(target.available_bytes)}`;
      $('storage-targets').append(row);
    }
    const selected=$('storage-source').value;$('storage-source').replaceChildren();
    for(const root of pool.sources){const option=document.createElement('option');option.value=root.id;option.textContent=root.label;$('storage-source').append(option);}
    if(pool.sources.some(root=>root.id===selected))$('storage-source').value=selected;
    $('storage-archive').hidden=!capabilities.publish||pool.enabled===false;$('storage-cache-reclaim').hidden=!capabilities.manage;
    if(!capabilities.publish)line($('storage-targets'),'자료 게시 권한이 필요합니다. 계정 관리자에게 요청하세요.');
    showJobs(listing.jobs);
    if(pool.cache_operation)$('storage-pool-message').textContent=operations[pool.cache_operation];
    else if(pool.cache_error)poolError(new Error('캐시 공간을 확보하지 못했습니다. 사용 중인 자료와 연결 권한을 확인하세요.'));
    else if(pool.cache_result)$('storage-pool-message').textContent=pool.cache_result.status==='disabled'?'자동 캐시 회수 정책이 꺼져 있습니다.':
      `${pool.cache_result.status==='blocked'?'공간 부족 · 다른 사용자의 자료나 고정·사용 중인 자료를 확인하세요. ':''}회수한 캐시 ${bytes(pool.cache_result.reclaimed_bytes)}`;
    if(pool.cache_operation||listing.jobs.some(job=>job.operation))poolTimer=setTimeout(()=>refreshPool(current),1000);
  }catch(error){
    if(current!==epoch)return;
    if(error.status===401||error.status===403)clearStorage();
    poolError(error);
  }
}
async function operate(id,action,body={}){
  if(poolBusy||!send)return;poolBusy=true;const current=epoch;
  $('storage-pool-error').hidden=true;$('storage-pool-message').textContent='작업을 접수하는 중입니다.';
  try{
    await send(id?`/api/learning/storage/jobs/${id}/${action}`:'/api/learning/storage/cache/reclaim',body);
    if(current!==epoch)return;
    $('storage-pool-message').textContent='작업을 접수했습니다. 아래에서 결과를 확인하세요.';
    if(action==='reclaim'){$('storage-confirmation').hidden=true;confirmJob=null;}
    if(action==='reconcile'){$('storage-reconciliation').hidden=true;reconcileJob=null;}
    await refreshPool(current);
  }catch(error){if(current===epoch)poolError(error);}
  finally{poolBusy=false;}
}
$('storage-archive').onsubmit=async event=>{
  event.preventDefault();if(poolBusy||!send)return;poolBusy=true;const current=epoch;
  const button=event.target.querySelector('[type="submit"]');button.disabled=true;
  $('storage-pool-error').hidden=true;$('storage-pool-message').textContent='완료된 자료 목록과 해시를 확인하는 중입니다.';
  try{
    await send('/api/learning/storage/jobs',{source_id:$('storage-source').value,artifact_id:$('storage-artifact').value,profile:$('storage-profile').value});
    if(current!==epoch)return;$('storage-pool-message').textContent='보관 작업을 등록했습니다. 전송·검증을 선택하세요.';
    await refreshPool(current);
  }catch(error){if(current===epoch)poolError(error);}
  finally{poolBusy=false;button.disabled=false;}
};
$('storage-cache-reclaim').addEventListener('click',()=>operate(null,'cache_reclaim'));
$('storage-confirm-id').oninput=()=>{$('storage-confirm-submit').disabled=!confirmJob||$('storage-confirm-id').value!==confirmJob.id;};
$('storage-confirm-cancel').addEventListener('click',()=>{$('storage-confirmation').hidden=true;confirmJob=null;});
$('storage-confirmation').onsubmit=event=>{
  event.preventDefault();if(confirmJob&&$('storage-confirm-id').value===confirmJob.id)operate(confirmJob.id,'reclaim',{confirm:confirmJob.id});
};
$('storage-reconcile-cancel').addEventListener('click',()=>{$('storage-reconciliation').hidden=true;reconcileJob=null;});
$('storage-reconciliation').onsubmit=event=>{
  event.preventDefault();if(reconcileJob)operate(reconcileJob.id,'reconcile',{revision:$('storage-existing-revision').value});
};
