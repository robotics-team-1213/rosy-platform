import {accountFetch} from '/account-session.js';
import {taskRow} from '/common/workspace.js';
import '/commands.js';
const $=id=>document.getElementById(id),API='/api/learning/tasks',CENTER='/api/learning/omx/center';
const stages=[['prepare','준비'],['record','직접 조종·녹화'],['review','시연 확인'],['learn','학습'],['results','결과 확인']];
const statuses={queued:'접수됨',launching:'시작 준비 중',running:'학습 중',stopping:'중지 처리 중',succeeded:'학습 완료',failed:'실패',cancelled:'취소됨'};
let state={tasks:[],native_inputs:[],workflows:{}},connected=false,busy=false,loading=false;
const pending=new Map();
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function sourceId(row){return row?.prepared_id||row?.id;}
function current(){return state.tasks.find(t=>t.id===new URL(location.href).searchParams.get('task'));}
function flow(){return state.workflows?.[current()?.id];}
function sources(){return flow()?.inputs||[];}
function selectedSource(){return sources().find(row=>sourceId(row)===$('workflow-train-source').value);}
function error(message){$('workflow-error').hidden=!message;$('workflow-error').textContent=message||'';}
function uuid(){const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;const h=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
async function request(path,body){
  const options={cache:'no-store'};
  if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-Pinky-Token':state.token};options.body=JSON.stringify(body);}
  const response=await accountFetch(path,options),value=await response.json();
  if(!response.ok)throw new Error(response.status===401?'로그인·계정에서 접속한 뒤 다시 확인하세요.':response.status===403?'이 작업에 필요한 프로젝트 권한을 확인하세요.':value.error||`요청 실패 (${response.status})`);
  return value;
}
function options(select,rows,label){
  const old=select.value,signature=JSON.stringify(rows);
  if(select.dataset.options===signature)return;
  select.dataset.options=signature;select.replaceChildren(...[['',label],...rows].map(([value,text])=>{const option=node('option',text);option.value=value;return option;}));
  if(rows.some(([value])=>value===old))select.value=old;
}
function linkHref(href){try{const url=new URL(href,location.href);return url.origin===location.origin?url.pathname+url.search+url.hash:'#';}catch{return '#';}}
function showStage(key,write=false,focus=false){
  if(!stages.some(([stage])=>stage===key))return;
  $('workflow-detail').dataset.panel=key;
  for(const [stage] of stages){
    const selected=stage===key,tab=$('workflow-tab-'+stage);
    if(!tab)continue;
    tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;
    $('workflow-'+stage).hidden=!selected;
  }
  if(write)history.replaceState(null,'','#workflow-'+key);
  if(focus)$('workflow-tab-'+key).focus();
}
function readout(rows){
  const list=node('dl',null,'workflow-readout');
  for(const [label,value] of rows)list.append(node('dt',label),node('dd',value));
  return list;
}
function selection(){
  const source=selectedSource(),mode=$('workflow-review-selection').value;
  const review=mode==='episodes'?source?.latest_review_id:mode==='segments'?source?.segment_review?.version:null;
  const methods=flow()?.methods||[],act=methods.find(m=>m.id==='act');
  const reviewReady=mode==='segments'?source?.segments_trainable?.ok:source?.trainable?.ok;
  const reason=!connected?'연결을 다시 확인하세요.':!state.token?'로그인·계정에서 권한을 확인하세요.':!['model','ai'].includes(state.host_id)?'학습 호스트 식별 설정을 확인하세요.':
    !source?'이 과제에 연결한 시연을 선택하세요.':source.error||source.fixture_only?'학습 가능한 원본 시연을 선택하세요.':!review?'학습에 사용할 저장 검수를 명시적으로 선택하세요.':
    !reviewReady?(mode==='segments'?source.segments_trainable?.reason:source.trainable?.reason)||'검수 자료의 학습·평가 분할을 확인하세요.':act?.state!=='available'?act?.reason||'현재 호스트의 ACT 실행 준비를 확인하세요.':'';
  $('workflow-train-reason').textContent=reason||'저장 검수와 원본·과제 구성을 서버가 다시 검증합니다.';
  $('workflow-train-start').disabled=busy||!!reason;
  $('workflow-train-start').reason=reason;
  const candidate=(state.native_inputs||[]).find(row=>sourceId(row)===$('workflow-native-source').value);
  const attachReason=!connected?'연결을 다시 확인하세요.':!state.token?'로그인·계정에서 권한을 확인하세요.':!candidate?'연결할 등록 시연을 선택하세요.':!candidate.source_revision?'원본 버전을 확인할 수 없습니다.':sources().some(row=>sourceId(row)===sourceId(candidate))?'이미 이 과제에 연결한 시연입니다.':'';
  $('workflow-attach').disabled=busy||!!attachReason;$('workflow-attach').reason=attachReason;
  $('workflow-card-export').disabled=busy||!connected||!state.token||!flow()?.recording?.task_card_export;
  $('workflow-card-export').reason=!flow()?.recording?.task_card_export?'이 과제의 녹화 준비서 생성이 준비되지 않았습니다.':!connected?'연결을 다시 확인하세요.':!state.token?'로그인·계정에서 권한을 확인하세요.':'';
  const prepared=sourceId(source);
  $('workflow-review-link').hidden=!prepared;
  $('workflow-review-link').href=prepared?`/learning/omx?task=${encodeURIComponent(current()?.id)}&prepared=${encodeURIComponent(prepared)}#dataset-section`:'#';
  $('workflow-review-status').textContent=!source?'위에서 검수할 시연을 선택하세요.':source.latest_review_id?'전체 시연의 저장 검수가 있습니다. 학습 전에 사용할 검수를 선택하세요.':'시연을 열어 검수·분할을 저장하세요.';
  $('workflow-source-status').textContent=source?source.error||`전체 검수 ${source.latest_review_id?'저장됨':'미저장'} · 구간 검수 ${source.segment_review?.version?'v'+source.segment_review.version:'미저장'}`:sources().length?'검수·학습할 시연을 직접 선택하세요.':'녹화 탭에서 시연을 연결하세요.';
  const reviewed=source,counts=reviewed?.trainable?.counts;
  $('workflow-review-summary').replaceChildren(readout([['시연',reviewed?.name||'연결한 시연 없음'],['학습 시연',counts?.train??'미확인'],['평가 시연',counts?.eval??'미확인'],['전체 검수',reviewed?.latest_review_id?'저장됨':'미저장'],['구간 검수',reviewed?.segment_review?.version?`v${reviewed.segment_review.version}`:'미저장']]));
  return !reason?{prepared_id:sourceId(source),...(mode==='episodes'?{review_id:review}:{segment_version:review})}:null;
}
function renderRuns(){
  const runs=flow()?.runs||[];
  const signature=JSON.stringify([runs,busy,connected,!!state.token]);
  if($('workflow-runs').dataset.content===signature)return;
  $('workflow-runs').dataset.content=signature;
  $('workflow-runs').replaceChildren(...runs.map(run=>{
    const section=node('section',null,'workflow-card'),heading=node('header',null,'workflow-run-heading'),title=node('div');
    title.append(node('h4',statuses[run.status]||'상태 확인 필요'),node('p',run.native?'ACT · 원본 시연 학습':'학습 실행'));
    heading.append(title);section.append(heading);
    if(run.error)section.append(node('p',typeof run.error==='string'?run.error:run.error.message||'학습 실행 기록에서 오류를 확인하세요.'));
    const evaluation=run.result?.evaluation,values=evaluation?.mae_per_joint;
    if(Array.isArray(values)&&values.length&&values.every(Number.isFinite)){
      section.append(readout([['평균 관절 오차 (MAE)',(values.reduce((a,b)=>a+b,0)/values.length).toPrecision(4)],['독립 평가 자료',`${evaluation.samples??'미확인'}개`],['모델 재로딩',evaluation.model_reloaded_in_new_process?'확인됨':'확인 필요']]));
      const details=node('details');details.append(node('summary','관절별 오차·평가 근거'));
      const table=node('table',null,'workflow-table'),head=node('thead'),labels=node('tr'),body=node('tbody');
      table.append(node('caption','관절별 오프라인 평가'));
      for(const label of ['관절','모델 오차','학습 평균 기준']){const th=node('th',label);th.scope='col';labels.append(th);}head.append(labels);
      values.forEach((value,index)=>{const row=node('tr');row.append(node('th',evaluation.joint_names?.[index]||`관절 ${index+1}`),node('td',Number(value.toPrecision(5))),node('td',evaluation.train_mean_baseline_mae_per_joint?.[index]??'미확인'));row.firstChild.scope='row';body.append(row);});
      table.append(head,body);const wrap=node('div',null,'workflow-table-wrap');wrap.append(table);details.append(wrap);
      details.append(node('p',evaluation.model_reloaded_in_new_process?'별도 프로세스 모델 재적재 확인됨':'별도 프로세스 모델 재적재 확인 필요'));section.append(details);
    }
    if(['queued','launching','running','stopping'].includes(run.status)){
      const stop=node('ui-button',run.status==='stopping'?'중지 처리 중':'이 학습 중지');stop.setAttribute('kind','quiet');stop.dataset.alwaysLive='';stop.disabled=busy||!connected||!state.token||run.status==='stopping';
      stop.onclick=()=>mutate(async()=>{await request(CENTER+'/stop',{id:run.id});});section.append(stop);
    }
    if(run.status==='succeeded'){
      const download=node('a','모델·입력·평가 내려받기','workspace-link');download.href=CENTER+'/artifact/'+encodeURIComponent(run.id);section.append(download);
    }
    const details=node('details');details.append(node('summary','실행 식별·설정 기록'),node('pre',JSON.stringify(run,null,2)));section.append(details);return section;
  }));
  if(!runs.length)$('workflow-runs').append(node('ui-empty','이 과제에 연결된 학습 기록이 없습니다.'));
}
function render(){
  const task=current(),journey=flow(),queryTask=new URL(location.href).searchParams.get('task');
  $('workflow-empty').hidden=state.tasks.length>0;$('workflow-tasks').hidden=state.tasks.length===0;
  $('workflow-tasks').replaceChildren(...state.tasks.map(task=>{
    const journey=state.workflows?.[task.id],row=taskRow({title:task.name,subtitle:task.objective||'',status:stages.find(([key])=>key===journey?.stage)?.[1]||'준비 확인',description:journey?.blocked_reason||''});
    const link=node('a',`${task.name} · 이어서 하기`,'workspace-link');link.href=`/learning/tasks?task=${encodeURIComponent(task.id)}`;row.append(link);return row;
  }));
  $('workflow-list').hidden=!!task;$('workflow-detail').hidden=!task;
  if(!task){if(queryTask)$('workflow-status').textContent='선택한 과제를 찾을 수 없습니다. 목록에서 다시 선택하세요.';return;}
  const expert=new URL('/learning/tasks/manage'+location.search,location.origin);
  expert.searchParams.set('task',task.id);if(task.profile_id)expert.searchParams.set('profile',task.profile_id);expert.hash='run-title';
  $('workflow-expert-link').href=expert.pathname+expert.search+expert.hash;
  $('workflow-task-title').textContent=task.name;$('workflow-objective').textContent=task.objective||'';
  if(!journey){$('workflow-detail').hidden=true;$('workflow-list').hidden=false;$('workflow-status').textContent='과제 진행 근거를 읽을 수 없습니다. 다시 확인하세요.';return;}
  if($('workflow-detail').dataset.task!==task.id){
    $('workflow-detail').dataset.task=task.id;delete $('workflow-detail').dataset.panel;
    $('workflow-stage-track').replaceChildren(...stages.map(([key,label],index)=>{
      const item=node('li',null,'ui-stage'),tab=node('button',key==='record'?'녹화':key==='review'?'검수':key==='results'?'결과':label);
      item.setAttribute('role','presentation');tab.id='workflow-tab-'+key;tab.type='button';tab.setAttribute('role','tab');tab.setAttribute('aria-controls','workflow-'+key);
      tab.onclick=()=>showStage(key,true);
      tab.onkeydown=event=>{const offset=event.key==='ArrowRight'?1:event.key==='ArrowLeft'?-1:null;
        const next=event.key==='Home'?0:event.key==='End'?stages.length-1:offset===null?null:(index+offset+stages.length)%stages.length;
        if(next!==null){event.preventDefault();showStage(stages[next][0],true,true);}};
      item.append(tab);return item;
    }));
  }
  for(const [key] of stages){
    const item=$('workflow-tab-'+key).parentElement;
    const complete={prepare:false,record:journey.completion?.recording_complete,review:journey.completion?.review_complete,learn:journey.completion?.training_complete,results:journey.completion?.offline_evaluation_complete}[key];
    item.dataset.state=key===journey.stage?(journey.blocked_reason?'blocked':'now'):complete?'done':'todo';
  }
  const stage=stages.some(([key])=>key===journey.stage)?journey.stage:'prepare';
  const hash=location.hash.replace('#workflow-','');
  const hasActiveRun=(journey.runs||[]).some(run=>['queued','launching','running','stopping'].includes(run.status));
  showStage(stages.some(([key])=>key===hash)?hash:$('workflow-detail').dataset.panel||(hasActiveRun?'results':stage));
  $('workflow-current').textContent=`현재 단계 · ${stages.find(([key])=>key===stage)[1]}`;
  $('workflow-blocker').textContent=journey.blocked_reason||'저장된 근거를 확인하고 다음 작업으로 진행하세요.';
  const next=journey.next_action;$('workflow-next').hidden=!next;$('workflow-next').textContent=next?.label||'';$('workflow-next').href=linkHref(next?.href||'#');
  $('workflow-next').onclick=()=>{const id=$('workflow-next').hash.replace('#workflow-','');showStage(id,true);};
  const setup=journey.setup||{},profile=state.profiles?.find(p=>p.id===setup.profile_id);
  $('workflow-setup').replaceChildren(node('h4',profile?.profile?.name||profile?.name||'이 과제에 고정한 구성'),readout([['장치 확인',setup.device_verified?'확인 기록 있음':'미확인']]));
  for(const arm of setup.arms||[])$('workflow-setup').append(node('h4',`팔 ${arm.id}`),readout([['관절',(arm.joint_names||[]).join(', ')||'미기록'],['행동 단위',arm.units||'미기록']]));
  for(const camera of setup.cameras||[])$('workflow-setup').append(readout([[`카메라 ${camera.id}`,camera.role||'역할 미기록']]));
  $('workflow-record-reason').textContent=journey.recording?.reason||'실물 조종·녹화 연결이 준비되지 않았습니다.';
  options($('workflow-native-source'),(state.native_inputs||[]).map(row=>[sourceId(row),row.name||'등록 시연']),'연결할 시연 선택');
  options($('workflow-train-source'),sources().map(row=>[sourceId(row),row.name||'연결한 시연']),'학습할 시연 선택');
  if(sources().length===1&&!$('workflow-train-source').value)$('workflow-train-source').value=sourceId(sources()[0]);
  $('workflow-inputs').replaceChildren(...sources().map(row=>node('p',`${row.name||'연결한 시연'} · 과제 연결됨`)));
  $('workflow-host').textContent=`저장할 실행 호스트: ${state.host_id==='model'?'Model PC':state.host_id==='ai'?'AI PC':'미설정'} · CPU · LeRobot ${state.capabilities?.lerobot_version||'버전 확인 필요'}`;
  const methodTable=node('table',null,'workflow-table'),methodHead=node('thead'),methodLabels=node('tr'),methodBody=node('tbody');
  methodTable.append(node('caption','학습 방법별 준비 상태'));
  for(const label of ['학습 방법','실행 상태','필요한 준비']){const th=node('th',label);th.scope='col';methodLabels.append(th);}methodHead.append(methodLabels);
  for(const method of journey.methods||[]){const row=node('tr'),name=node('th',method.label||method.id),status=node('td',method.state==='available'?'실행 준비됨':'준비 필요');name.scope='row';if(method.reason)status.append(node('p',method.reason));row.append(name,status,node('td',(method.requirements||[]).join(', ')||'검수된 시연·독립 평가 분할'));methodBody.append(row);}
  methodTable.append(methodHead,methodBody);const methodsWrap=node('div',null,'workflow-table-wrap');methodsWrap.append(methodTable);$('workflow-methods').replaceChildren(methodsWrap);
  const completion=journey.completion||{};
  const groups=[['시연 준비',[['recording_complete','녹화'],['review_complete','검수']]],['오프라인 검증',[['training_complete','학습'],['offline_evaluation_complete','오프라인 평가']]],['실물 적용',[['physical_evaluation_complete','실물 평가'],['application_approved','적용 승인']]]];
  $('workflow-completion').replaceChildren(...groups.map(([title,rows])=>{
    const card=node('section',null,'workflow-card');card.append(node('h4',title));
    const list=node('dl',null,'workflow-readout');for(const [key,label] of rows){const term=node('dt',label),value=node('dd',completion[key]?'완료 근거 있음':'미확인');value.dataset.evidence=key;list.append(term,value);}card.append(list);return card;
  }));
  selection();renderRuns();
}
async function refresh(checkSources=false){
  if(loading)return;loading=true;$('workflow-refresh').disabled=true;
  try{
    if(checkSources)await request(API+'/native-inputs');
    state=await request(API);connected=true;
    const checked=new Date(state.native_inputs_checked_at);
    const checkedAt=state.native_inputs_checked_at&&!Number.isNaN(checked.getTime())?checked.toLocaleString('ko-KR'):'미확인';
    $('workflow-status').textContent=`저장한 과제·학습 상태를 읽었습니다. 자료 확인 시각: ${checkedAt} · 다시 확인으로 갱신`;
    render();
  }
  catch(exc){connected=false;error(exc.message);if(current()){selection();renderRuns();}}
  finally{loading=false;$('workflow-refresh').disabled=false;}
}
async function mutate(action){
  if(busy)return;busy=true;error('');selection();renderRuns();
  try{await action();await refresh();}
  catch(exc){error(`${exc.message} 입력을 바꾸지 않고 다시 누르면 같은 요청으로 확인합니다.`);}
  finally{busy=false;selection();renderRuns();}
}
$('workflow-attach-form').onsubmit=event=>{event.preventDefault();if($('workflow-attach').disabled)return;mutate(async()=>{
  const source=(state.native_inputs||[]).find(row=>sourceId(row)===$('workflow-native-source').value);
  if(!pending.has('attach'))pending.set('attach',{task_id:current().id,prepared_id:sourceId(source),source_revision:source.source_revision,request_id:uuid()});
  await request(API+'/native-input',pending.get('attach'));pending.delete('attach');
});};
$('workflow-train-form').onsubmit=event=>{event.preventDefault();const chosen=selection();if(!chosen||busy)return;mutate(async()=>{
  if(!pending.has('train'))pending.set('train',{...chosen,task_id:current().id,compute_host:state.host_id,steps:Number($('workflow-steps').value),batch_size:Number($('workflow-batch').value),request_id:uuid()});
  await request(CENTER+'/native-run',pending.get('train'));pending.delete('train');showStage('results',true);
});};
$('workflow-card-form').onsubmit=event=>{event.preventDefault();if($('workflow-card-export').disabled)return;mutate(async()=>{
  const value=await request(API+'/recording-card',{task_id:current().id,record:{root_prefix:$('workflow-card-root').value.trim(),episode_time_s:Number($('workflow-card-episode').value),reset_time_s:Number($('workflow-card-reset').value),num_episodes:Number($('workflow-card-count').value)}});
  if(!value.card||value.device_execution!==false||value.requires_owner_preflight!==true)throw new Error('녹화 준비서의 실행 경계를 확인할 수 없습니다. 담당자에게 확인하세요.');
  const url=URL.createObjectURL(new Blob([JSON.stringify(value.card,null,2)],{type:'application/json'})),download=node('a');download.href=url;download.download=value.filename||'recording-task-card.json';download.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  $('workflow-card-status').textContent='녹화 준비서를 만들었습니다. 현장 담당자가 OMX owner의 장치 확인을 마친 뒤 사용하세요. 녹화나 장치 동작은 시작되지 않았습니다.';
});};
$('workflow-native-source').onchange=()=>{pending.delete('attach');selection();};
for(const id of ['workflow-train-source','workflow-review-selection','workflow-steps','workflow-batch'])$(id).addEventListener('input',()=>{pending.delete('train');selection();});
$('workflow-refresh').onclick=()=>{error('');refresh(true);};
addEventListener('hashchange',()=>showStage(location.hash.replace('#workflow-','')));
refresh(true);setInterval(()=>{if(!document.hidden&&!busy)refresh();},5000);
