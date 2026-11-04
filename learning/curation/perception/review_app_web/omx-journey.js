// Explicit task context connects the workbench to the existing task/run owner.
const $=id=>document.getElementById(id);
const keys=['task','profile','dataset'];
const params=new URLSearchParams(location.search);
const requested=Object.fromEntries(keys.map(key=>[key,params.get(key)||'']));
let invalid=keys.some(key=>params.getAll(key).length>1||params.has(key)&&!requested[key]||requested[key].length>128);
let tasks=null,contextError='',loading=false,profileKey='',latest=null,planSaved=false;
export const journeyContext={task:null,blocked:keys.some(key=>requested[key])||invalid};
export function contextUrl(hash='run-title',path='/learning/tasks/manage'){
  const url=new URL(path,location.origin);
  for(const key of keys){const value=key==='dataset'?requested.dataset||$('dataset').value:requested[key];if(value)url.searchParams.set(key,value);}
  if(journeyContext.task?.profile_id)url.searchParams.set('profile',journeyContext.task.profile_id);
  url.hash=hash;return url.pathname+url.search+url.hash;
}
export function initJourney(refresh){
  $('journey-context-reset').onclick=()=>{
    for(const key of keys){requested[key]='';params.delete(key);}
    tasks=null;contextError='';invalid=false;journeyContext.task=null;journeyContext.blocked=false;
    const url=new URL(location.href);for(const key of keys)url.searchParams.delete(key);
    history.replaceState(null,'',url.pathname+url.search+url.hash);profileKey='';refresh();
    document.dispatchEvent(new Event('omx-journey-context-changed'));
  };
  $('dataset').addEventListener('change',()=>{
    requested.dataset=$('dataset').value;
    const url=new URL(location.href);
    if(requested.dataset)url.searchParams.set('dataset',requested.dataset);else url.searchParams.delete('dataset');
    history.replaceState(null,'',url.pathname+url.search+url.hash);
    document.dispatchEvent(new Event('omx-journey-context-changed'));
  });
  $('followup-form').addEventListener('input',()=>{planSaved=false;});
  window.addEventListener('beforeunload',event=>{
    if(!planSaved&&($('followup-observation').value||$('followup-next').value)){event.preventDefault();event.returnValue='';}
  });
  $('followup-form').onsubmit=event=>{
    event.preventDefault();if($('followup-download').disabled)return;
    const run=latest?.runs.find(row=>row.id===$('followup-run').value);
    if(!run)return;
    const binding=run.learning_task;
    const plan={kind:'collection_plan',evidence_status:'operator_plan_only',created_at:new Date().toISOString(),
      task_id:binding?.task_id||journeyContext.task?.id||null,task_revision:binding?.task_revision||journeyContext.task?.revision||null,
      task_profile_revision:binding?.profile_revision||journeyContext.task?.profile_revision||null,
      run_id:run.id,dataset_id:run.dataset_id,dataset_revision:run.dataset_revision||binding?.dataset_revision||null,
      policy_version:run.result?.version??run.progress?.latest_version??null,
      training_scope:run.result?.training_scope||run.training_scope||null,
      observation:$('followup-observation').value.trim(),next_demonstration:$('followup-next').value.trim()};
    const url=URL.createObjectURL(new Blob([JSON.stringify(plan,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='collection-plan.json';link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    planSaved=true;
    $('followup-status').textContent='수집 계획을 내려받았습니다. 검수 정답·평가 결과·실물 성공 기록으로 등록되지 않습니다.';
  };
}
export async function refreshJourneyContext(request){
  if(!requested.task&&!requested.profile&&!invalid)return;
  loading=true;
  try{tasks=await request('/api/learning/tasks');contextError='';}
  catch{contextError='과제 연결을 확인할 수 없습니다. 다시 확인하거나 연결 선택을 해제하세요.';}
  finally{loading=false;}
}
export function applyJourneyContext(snapshot){
  latest=snapshot;let message=contextError,task=null,profile=null;
  if(invalid)message='중복되거나 너무 긴 연결 선택입니다. 연결 선택을 해제하고 다시 고르세요.';
  if(!message&&loading)message='과제와 입력 설정을 확인하는 중입니다.';
  if(!message&&requested.task){
    task=tasks?.tasks?.find(row=>row.id===requested.task);
    if(!task)message='연결한 과제를 찾을 수 없습니다. 과제 화면에서 다시 선택하세요.';
    else if(requested.profile&&task.profile_id!==requested.profile)message='과제와 연결한 프로필이 다릅니다. 과제 화면에서 입력 설정을 다시 선택하세요.';
  }
  const profileId=requested.profile||task?.profile_id;
  if(!message&&profileId){
    profile=tasks?.profiles?.find(row=>row.id===profileId);
    if(!profile)message='연결한 프로필을 찾을 수 없습니다. 과제 화면에서 다시 선택하세요.';
    else if(task?.profile_revision&&task.profile_revision!==profile.revision)message='과제에 고정한 프로필 버전과 현재 선택이 다릅니다. 과제 화면에서 확인하세요.';
  }
  if(!message&&requested.dataset&&!snapshot.datasets.some(row=>row.id===requested.dataset))message='연결한 학습 데이터를 찾을 수 없습니다. 자료를 다시 등록하거나 연결 선택을 해제하세요.';
  journeyContext.task=message?null:task;journeyContext.blocked=!!message;
  $('journey-context-status').textContent=message;
  $('journey-context-reset').hidden=!message;
  $('journey-task-status').textContent=task&&!message?`학습 과제: ${task.name}`:'학습 과제를 선택해 목표와 성공 조건을 정하세요.';
  $('journey-task-link').href=contextUrl();
  $('journey-task-link').textContent=task&&!message?'이 과제에서 자료 선택·학습 실행':'학습 과제 선택·만들기';
  document.dispatchEvent(new Event('omx-journey-context-changed'));
  if(message)return;
  if(requested.dataset&&$('dataset').dataset.journeySelection!==requested.dataset){
    $('dataset').value=requested.dataset;$('dataset').dataset.journeySelection=requested.dataset;
  }
  if(profile&&profileKey!==profile.id+profile.revision){
    profileKey=profile.id+profile.revision;
    document.dispatchEvent(new CustomEvent('omx-profile-selected',{detail:profile}));
  }
}
export function selectJourneyProfile(profile){
  profileKey=profile.id+profile.revision;
  requested.profile=profile.id;
  const url=new URL(location.href);url.searchParams.set('profile',profile.id);
  history.replaceState(null,'',url.pathname+url.search+url.hash);
  const task=requested.task&&tasks?.tasks?.find(row=>row.id===requested.task);
  if(task&&(task.profile_id!==profile.id||task.profile_revision!==profile.revision)){
    journeyContext.blocked=true;$('journey-context-status').textContent='선택한 프로필이 과제에 고정된 설정과 다릅니다. 과제 화면에서 다시 선택하세요.';
    $('journey-context-reset').hidden=false;
  }
  document.dispatchEvent(new Event('omx-journey-context-changed'));
}
export function clearJourneyProfile(){
  if(requested.task)return;
  requested.profile='';profileKey='';
  const url=new URL(location.href);url.searchParams.delete('profile');
  history.replaceState(null,'',url.pathname+url.search+url.hash);
  document.dispatchEvent(new Event('omx-journey-context-changed'));
}
export function updateJourneyEvidence({snapshot,preparedSets,preparedReady,centerReady}){
  latest=snapshot;
  const available=preparedReady?`연결된 준비 시연 ${preparedSets.length}세트`:'준비 시연 연결 확인 필요';
  $('capture-handoff-status').textContent=`${available} · ${centerReady&&snapshot.status!=='not_configured'?'학습 자료 목록 확인됨':'학습 실행기 연결 필요'}. 원격 작업대 녹화·전송 상태는 이 화면에서 확인하지 못했습니다.`;
  $('journey-task-link').href=contextUrl();
  $('task-training-action').href=contextUrl();
  $('task-training-action').hidden=!journeyContext.task;
  $('legacy-training-note').hidden=!!journeyContext.task;
  const selected=$('followup-run').value;
  const runs=snapshot.runs.filter(row=>row.dataset_id===$('dataset').value&&row.result?.evaluation&&
    (!journeyContext.task||row.learning_task?.task_id===journeyContext.task.id));
  const signature=JSON.stringify(runs.map(row=>[row.id,row.status]));
  if($('followup-run').dataset.options!==signature){
    $('followup-run').dataset.options=signature;
    $('followup-run').replaceChildren(...(runs.length?runs.map(row=>new Option(`${row.method} · ${row.id}`,row.id)):[new Option('선택 자료의 평가 결과 없음','')]));
    if(runs.some(row=>row.id===selected))$('followup-run').value=selected;
  }
  $('followup-download').disabled=!runs.length||!centerReady||journeyContext.blocked;
  $('followup-run').disabled=!runs.length||!centerReady;
}
export function renderJourneyComparison(dataset,{allRuns,needsArm,matchingTarget,targetLabel,states}){
  const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;};
  const area=$('comparison');area.replaceChildren();
  if(!dataset){area.append(el('p','초기 학습 데이터를 선택하면 같은 자료에서 시작한 작업의 평가를 볼 수 있습니다.','quiet'));return;}
  if(needsArm(dataset)&&!$('arm-target').value){area.append(el('p','학습 팔을 선택하면 같은 팔의 입력 범위가 기록된 평가만 비교합니다.','quiet'));return;}
  const runs=allRuns.filter(run=>run.execution_mode!=='native_export'&&run.dataset_id===dataset.id&&run.result?.evaluation&&matchingTarget(run,dataset)&&(!journeyContext.task||run.learning_task?.task_id===journeyContext.task.id));
  if(!runs.length){area.append(el('p','선택한 초기 데이터에 저장된 평가 결과가 없습니다. 정책과 평가가 저장되면 표시됩니다.','quiet'));return;}
  const table=el('table',null,'omx-episodes');
  table.append(el('caption',`동일 초기 데이터: ${dataset.name}${needsArm(dataset)?' · 개별 팔 '+$('arm-target').value:''} · 저장된 평가 ${runs.length}개`));
  const head=el('thead'),headers=el('tr');
  for(const text of ['방법·작업','학습 입력 범위','자료 출처','상태','학습 단계','누적 입력','평가 프레임','행동 MAE','학습 평균 기준 MAE','시범 프레임','롤아웃 프레임','현장 성공','사람 개입 시간','초기화 횟수','낙하 횟수','사이클 시간']){
    const cell=el('th',text);cell.scope='col';headers.append(cell);
  }
  head.append(headers);table.append(head);
  const body=el('tbody');
  for(const run of runs){
    const result=run.result,evaluation=result.evaluation,replay=result.replay||{};
    const online=run.execution_mode==='online_experience',version=result.version??run.progress?.latest_version;
    const label=online?`지속 SAC · 정책 버전 ${version??'미수집'}`:run.method==='act'?'ACT 시범/교정':'SAC 오프라인 재학습';
    const row=el('tr'),method=el('th');method.scope='row';method.append(el('span',label),el('p',run.id,'quiet'));row.append(method);
    const total=result.total_steps??result.steps??run.steps,inputs=result.inputs??run.progress?.consumed_inputs;
    const values=[targetLabel(run),result.source??dataset.source,states[run.status]||run.status,
      online?`${total??'미수집'} (입력당 ${run.steps})`:total,
      online?(Array.isArray(inputs)?`초기 포함 ${inputs.length}개`:'미수집'):'초기 자료만',
      evaluation.frames,evaluation.action_mae,evaluation.constant_train_mean_mae,
      replay.demonstration_frames,replay.rollout_frames,'미검증','미수집','미수집','미수집','미수집'];
    for(const value of values)row.append(el('td',value==null?'미수집':String(value)));
    body.append(row);
  }
  table.append(body);
  const wrap=el('div',null,'omx-table-wrap');wrap.append(table);area.append(wrap);
  if(runs.length===1)area.append(el('p','평가 기록이 1개입니다. 같은 초기 자료의 다른 학습 결과가 저장되면 함께 표시됩니다.','quiet'));
}
