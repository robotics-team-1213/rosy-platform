import {accountFetch} from '/account-session.js';
import '/common/ui.js';
import '/commands.js';
const $=id=>document.getElementById(id),API='/api/learning/tasks';
let state={robots:[],tasks:[],profiles:[],datasets:[],runs:[],methods:{}},token='',loading=false,busy=false,connected=false;
const pending=new Map();
const experienceDrafts=new Map();
let actionError='',refreshError='';
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function error(message,owner='action'){
  if(owner==='refresh')refreshError=message||'';else actionError=message||'';
  const text=[refreshError,actionError].filter(Boolean).join('\n');$('tasks-error').hidden=!text;$('tasks-error').textContent=text;
}
function uuid(){const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;const h=Array.from(b,x=>x.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
async function request(path,body){
  const options={cache:'no-store'};
  if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-Pinky-Token':token};options.body=JSON.stringify(body);}
  const response=await accountFetch(path,options);
  if(response.status===401){$('tasks-login').hidden=false;throw new Error('로그인이 필요합니다. 로그인·계정에서 접속한 뒤 다시 확인하세요.');}
  if(response.status===403){$('tasks-login').hidden=false;throw new Error('이 작업에 필요한 권한이 없습니다. 계정의 프로젝트 권한을 확인하세요.');}
  const value=await response.json();if(!response.ok)throw new Error(value.error||`요청 실패 (${response.status})`);return value;
}
function options(select,rows,placeholder){
  const signature=JSON.stringify(rows),old=select.value;
  if(select.dataset.options===signature)return;
  select.dataset.options=signature;
  const entries=placeholder==null?rows:[['',placeholder],...rows];
  select.replaceChildren(...entries.map(([id,label])=>{const option=node('option',label);option.value=id;return option;}));
  if(entries.some(([id])=>id===old))select.value=old;
}
function task(){return state.tasks.find(row=>row.id===$('task-select').value);}
function selectedProfile(){return state.profiles.find(row=>row.id===$('task-profile').value);}
function participant(component='',role='',locked=false){
  const row=node('fieldset',null,'task-participant');row.append(node('legend','참여 요소'));
  function field(label,tag,key,value){const wrapper=node('label',label,'ui-field-label'),input=node(tag);input.className='ui-field';input.dataset[key]='';input.required=true;if(tag==='input'){input.value=value;input.maxLength=128;}wrapper.append(input);row.append(wrapper);return input;}
  const robot=field('등록 로봇','select','robot');options(robot,state.robots.map(r=>[r.id,`${r.name} · ${r.kind}`]),null);
  field('구성 요소 ID','input','component',component).readOnly=locked;field('역할','input','role',role||component||'primary');
  const remove=node('ui-button','참여 요소 제거');remove.setAttribute('kind','quiet');remove.hidden=locked;remove.onclick=()=>{row.remove();pending.delete('task');};row.append(remove);
  $('task-participants').append(row);
}
function configureParticipants(){
  const profile=selectedProfile()?.profile,omx=$('task-adapter').value.trim()==='omx';
  $('task-profile-field').hidden=!omx;$('participant-add').hidden=!!(omx&&profile);
  if(omx&&profile){$('task-mode').value=profile.mode;$('task-mode').disabled=true;$('task-participants').replaceChildren();for(const arm of profile.arms)participant(arm.id,arm.id,true);}
  else{$('task-mode').disabled=false;for(const input of $('task-participants').querySelectorAll('[data-component]'))input.readOnly=false;for(const button of $('task-participants').querySelectorAll('ui-button'))button.hidden=false;}
  pending.delete('task');
}
function readiness(){
  const current=task(),dataset=state.datasets.find(row=>row.id===$('run-dataset').value),online=$('run-execution').value==='online';
  if(online)$('run-method').value='hilserl';
  for(const option of $('run-method').options)option.disabled=!state.methods[option.value]?.available||(online&&option.value==='act');
  const method=state.methods[$('run-method').value];
  const multi=current?.mode==='independent'&&current.participants.length>1;
  $('run-arm-field').hidden=!multi;$('run-arm').required=!!multi;
  options($('run-arm'),multi?current.participants.map(p=>[p.component_id,p.component_id]):[],'참여 요소 선택');
  let reason=!connected?'연결을 다시 확인하세요.':!current?'과제를 저장하거나 선택하세요.':!current.runnable?`어댑터 준비 필요: ${current.blocked_reason||'지원되는 OMX 종류와 프로필을 확인하세요.'}`:
    !state.host_id?'운영 담당자에게 이 호스트의 Model·AI 식별 설정을 요청하세요.':!state.center_configured?'운영 담당자에게 이 호스트의 학습 실행기 연결을 요청하세요.':
    !dataset?'시범 자료를 등록하고 선택하세요.':!method?.available?`실행기 준비 필요: ${method?.reason||method?.error||'선택 방법의 실행기를 설정하세요.'}`:
    online&&dataset.profile?.schema!=='rosy.omx.learning-profile/2'?'지속 경험 학습에는 action_limits를 포함한 schema 2 자료가 필요합니다.':
    multi&&!$('run-arm').value?'개별 학습할 참여 요소를 선택하세요.':'';
  $('run-host').textContent=`실행 호스트: ${state.host_id==='model'?'Model PC':state.host_id==='ai'?'AI PC':'미설정'} · 현재 접속한 호스트에서 CPU 학습합니다. 계산 호스트는 실행마다 기록됩니다.`;
  $('run-readiness').textContent=reason||'자료·과제 결속을 검증한 뒤 학습을 시작할 수 있습니다.';
  $('run-data-status').textContent=dataset?`자료 revision ${dataset.revision||'미기록'} · 출처 ${dataset.source||'미기록'}${/synthetic|smoke/i.test(dataset.source||'')?' · 합성 시험 자료이며 실제 수집·성공 증거가 아닙니다.':''}`:'';
  $('run-start').disabled=busy||!token||!!reason;
  $('robot-save').disabled=$('task-import').disabled=busy||!connected||!token;
  $('task-save').disabled=busy||!connected||!token||!state.robots.length;
  $('task-export').disabled=busy||!connected||!current;
  for(const panel of $('task-runs').querySelectorAll('[data-continuous-run]')){
    const select=panel.querySelector('select'),unavailable=busy||!connected||!token;
    select.disabled=unavailable||select.options.length===0;
    panel.querySelector('[data-experience-submit]').disabled=unavailable||!select.value;
    panel.querySelector('[data-run-stop]').disabled=unavailable;
  }
}
function continuousControls(run){
  const panel=node('div');panel.dataset.continuousRun=run.id;
  const draft=experienceDrafts.get(run.id)||{datasetId:'',message:''};experienceDrafts.set(run.id,draft);
  const key='experience:'+run.id,retry=pending.get(key)?.payload;
  const used=new Set([run.dataset_id,...(run.inputs||[]).map(input=>input.dataset_id)]);
  const usedRevisions=new Set(state.datasets.filter(dataset=>used.has(dataset.id)).map(dataset=>dataset.revision).filter(Boolean));
  const datasets=state.datasets.filter(dataset=>(!used.has(dataset.id)&&!usedRevisions.has(dataset.revision))||retry?.dataset_id===dataset.id);
  const form=node('form',null,'ui-form learning-form'),label=node('label','추가 경험 자료','ui-field-label'),select=node('select');select.className='ui-field';select.required=true;
  select.dataset.taskRunAction='experience';
  options(select,datasets.map(dataset=>[dataset.id,`${dataset.name||dataset.id}${retry?.dataset_id===dataset.id?' · 응답 재확인':''}`]),null);
  if(datasets.some(dataset=>dataset.id===draft.datasetId))select.value=draft.datasetId;
  select.onchange=()=>{draft.datasetId=select.value;draft.message='';pending.delete(key);readiness();};
  label.append(select);form.append(label);
  const feed=node('ui-button','추가 경험 입력');feed.setAttribute('kind','primary');feed.type='submit';feed.dataset.experienceSubmit='';feed.dataset.taskRunAction='submit';form.append(feed);
  form.onsubmit=event=>{event.preventDefault();if(feed.disabled)return;action(async()=>{
    draft.datasetId=select.value;
    await save(key,'/api/learning/omx/center/experience',{id:run.id,dataset_id:select.value});
    draft.datasetId='';draft.message='입력 대기열에 추가했습니다.';$('task-runs').dataset.value='';await refresh();
  });};
  const status=node('p',draft.message||`${run.inputs?.length||0}개 추가 입력 기록 · ${datasets.length?'초기 자료와 이미 입력한 자료는 제외합니다.':'새 경험 자료를 먼저 등록하세요.'}`);status.setAttribute('role','status');
  const stop=node('ui-button','이 지속 학습 중지');stop.setAttribute('kind','quiet');stop.dataset.runStop='';stop.dataset.taskRunAction='stop';
  stop.onclick=()=>action(async()=>{await request('/api/learning/omx/center/stop',{id:run.id});await refresh();});
  panel.append(node('p','지속 학습은 새 경험을 기다립니다. 추가 입력도 같은 과제·참여 범위를 서버가 검증합니다. 이 호스트의 학습을 중지해도 저장된 모델·평가 파일은 유지됩니다.'),form,status,stop);
  return panel;
}
function renderTask(){
  const current=task(),area=$('selected-task'),signature=JSON.stringify(current);
  if(area.dataset.value!==signature){area.dataset.value=signature;area.replaceChildren();if(current){
    area.append(node('h3',current.name),node('p',current.objective),node('p',`성공: ${current.success} · 실패: ${current.failure} · 초기화: ${current.reset}`),node('p',`${current.mode==='cooperative'?'협동':'개별'} · ${current.participants.map(p=>`${state.robots.find(r=>r.id===p.robot_id)?.name||p.robot_id}/${p.component_id} (${p.role})`).join(' · ')}`),node('p',`과제 ${current.id} · revision ${current.revision}`,'quiet'));
  }else area.append(node('p','아직 선택한 과제가 없습니다. 먼저 로봇과 과제를 등록하세요.'));}
  const runs=current?state.runs.filter(run=>run.learning_task?.task_id===current.id):[],runSignature=JSON.stringify([runs,state.datasets]),list=$('task-runs');
  const active=document.activeElement,row=active?.closest('[data-task-run]'),focused=list.contains(row)?row.dataset.taskRun:null,focusAction=active?.dataset.taskRunAction;
  const changed=list.dataset.value!==runSignature;
  if(changed){list.dataset.value=runSignature;list.replaceChildren();
    if(!runs.length)list.append(node('p','이 과제의 실행 기록이 없습니다. 자료와 방법을 선택해 학습을 시작하세요.'));
    for(const run of runs){const section=node('article',null,'learning-panel'),result=run.result,evaluation=result?.evaluation;
      section.dataset.taskRun=run.id;
      const statuses={queued:'대기 중',running:'진행 중',stopping:'중지 중',succeeded:'완료',failed:'실패',cancelled:'취소됨'};
      const heading=node('h3',`${run.method||'학습'} · ${statuses[run.status]||run.status}`);heading.tabIndex=-1;
      section.append(heading,node('p',run.id),node('p',`자료 ${run.dataset_id||'미기록'} · 계산 호스트 ${run.learning_task?.compute_host||run.compute_host||'미기록'}`));
      if(evaluation)section.append(node('p',`평가 프레임 ${evaluation.frames??'미기록'} · action MAE ${evaluation.action_mae??'미기록'} · 기준 MAE ${evaluation.constant_train_mean_mae??'미기록'}`));
      else section.append(node('p','저장된 평가 결과가 없습니다. 완료 상태만으로 품질을 판단하지 마세요.'));
      if(run.error)section.append(node('p',typeof run.error==='string'?run.error:JSON.stringify(run.error)));
      if(run.status==='succeeded'||run.progress?.latest_version!=null){const link=node('a','모델·평가·과제 근거 ZIP 내려받기','workspace-link');link.href='/api/learning/omx/center/artifact/'+encodeURIComponent(run.id);link.download='';section.append(link);}
      if(result?.source)section.append(node('p',`출처: ${result.source}`,'quiet'));
      if(run.execution_mode==='online_experience'&&run.status==='running')section.append(continuousControls(run));
      list.append(section);
    }
  }
  readiness();
  if(changed&&focused){
    const replacement=[...list.children].find(node=>node.dataset.taskRun===focused);
    const control=replacement&&[...replacement.querySelectorAll('[data-task-run-action]')].find(node=>node.dataset.taskRunAction===focusAction);
    if(!replacement)list.tabIndex=-1;
    (control&&!control.disabled?control:replacement?.querySelector('h3')||list).focus({preventScroll:true});
  }
}
async function refresh(){
  if(loading)return;loading=true;
  try{state=await request(API);token=state.token||token;connected=true;$('tasks-login').hidden=true;
    error('','refresh');
    options($('task-select'),state.tasks.map(t=>[t.id,t.name]),'과제 선택');
    options($('task-profile'),state.profiles.map(p=>[p.id,`${p.profile.name||p.id} · ${p.revision.slice(0,12)}`]),'저장 프로필 선택');
    options($('run-dataset'),state.datasets.map(d=>[d.id,d.name||d.id]),'자료 선택');
    for(const select of $('task-participants').querySelectorAll('[data-robot]'))options(select,state.robots.map(r=>[r.id,`${r.name} · ${r.kind}`]),null);
    const robots=$('robots'),signature=JSON.stringify(state.robots);
    if(robots.dataset.value!==signature){robots.dataset.value=signature;robots.replaceChildren(...(state.robots.length?state.robots.map(r=>node('li',`${r.name} · ${r.kind} · device ${r.device_id} · 연결 미검증`)):[node('li','등록된 로봇이 없습니다. 이름과 기존 device ID를 입력하세요.')]));}
    $('tasks-status').textContent=`프로젝트 ${state.project_id} · 과제 ${state.tasks.length}개 · 최신 기록 확인됨`;
    renderTask();
  }catch(exc){connected=false;error(exc.message,'refresh');$('tasks-status').textContent='연결 실패 · 입력을 유지했습니다. 다시 확인을 누르세요.';readiness();}
  finally{loading=false;}
}
async function save(kind,path,body){
  const signature=JSON.stringify(body),previous=pending.get(kind);
  const payload=previous?.signature===signature?previous.payload:{...body,request_id:uuid()};pending.set(kind,{signature,payload});
  const result=await request(path,payload);pending.delete(kind);return result;
}
async function action(callback){if(busy)return;busy=true;error('');readiness();try{await callback();}catch(exc){error(exc.message);}finally{busy=false;readiness();}}
$('robot-form').onsubmit=event=>{event.preventDefault();action(async()=>{
  const body={name:$('robot-name').value.trim(),kind:$('robot-kind').value.trim(),model_revision:$('robot-model').value.trim(),device_id:$('robot-device').value.trim()};
  await save('robot','/api/learning/robots',body);await refresh();
});};
$('task-form').onsubmit=event=>{event.preventDefault();action(async()=>{
  const body=Object.fromEntries(['name','objective','success','failure','reset','mode','adapter'].map(key=>[key,$('task-'+key).value.trim()]));
  body.participants=[...$('task-participants').children].map(row=>({robot_id:row.querySelector('[data-robot]').value,component_id:row.querySelector('[data-component]').value.trim(),role:row.querySelector('[data-role]').value.trim()}));
  if(body.adapter==='omx'&&$('task-profile').value)body.profile_id=$('task-profile').value;
  const row=await save('task',API,body);await refresh();$('task-select').value=row.id;renderTask();
});};
$('run-form').onsubmit=event=>{event.preventDefault();if($('run-start').disabled)return;action(async()=>{
  const body={task_id:task().id,compute_host:state.host_id,dataset_id:$('run-dataset').value,method:$('run-method').value,steps:Number($('run-steps').value),batch_size:Number($('run-batch').value),device:'cpu',seed:0};
  if(task().mode==='independent'&&task().participants.length>1)body.arm_id=$('run-arm').value;
  await save('run','/api/learning/omx/center/'+($('run-execution').value==='online'?'online-run':'run'),body);await refresh();
});};
$('import-form').onsubmit=event=>{event.preventDefault();action(async()=>{
  const file=$('task-import-file').files[0];if(!file||file.size>1024*1024)throw new Error('1 MiB 이하의 과제 JSON 파일을 선택하세요.');
  const row=await request(API+'/import',JSON.parse(await file.text()));await refresh();$('task-select').value=row.id;renderTask();
});};
$('task-export').onclick=()=>action(async()=>{
  const value=await request(API+'/export?id='+encodeURIComponent(task().id));
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),link=node('a');link.href=url;link.download=`learning-task-${task().id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$('participant-add').onclick=()=>participant();
$('task-profile').onchange=configureParticipants;$('task-adapter').oninput=configureParticipants;
$('task-select').onchange=()=>{pending.delete('run');renderTask();};
for(const id of ['run-dataset','run-method','run-execution','run-arm'])$(id).onchange=()=>{pending.delete('run');readiness();};
$('tasks-refresh').onclick=()=>{error('');refresh();};
participant();refresh();setInterval(()=>{if(!busy&&!document.hidden)refresh();},5000);
