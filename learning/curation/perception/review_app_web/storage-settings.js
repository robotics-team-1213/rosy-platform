const $=id=>document.getElementById(id), GiB=1024**3;
let send, changed, state, draft=[], quotas={}, generation=0, timer, busy=false, dirty=false, formRevision=0;
const text=(parent,tag,value)=>{const node=document.createElement(tag);node.textContent=value;parent.append(node);return node;};
const localDate=seconds=>{const date=new Date(seconds*1000);return new Date(date-date.getTimezoneOffset()*60000).toISOString().slice(0,16);};
const bytes=input=>Math.ceil(Number(input.value)*GiB);
function error(message){$('storage-setup-error').textContent=message;$('storage-setup-error').hidden=false;}
function failureMessage(failure){
  if(failure.status===401)return '로그인이 만료되었습니다. 계정 화면에서 다시 로그인한 뒤 확인하세요.';
  if(failure.status===403)return '이 프로젝트의 게시·관리 권한과 계정 연결의 허용 범위를 확인하세요.';
  if(/revision|settings changed/.test(failure.message||''))return '저장 설정이 바뀌었습니다. 현재 입력을 확인한 뒤 저장 현황을 다시 불러오세요.';
  if(/quota|capacity|space/.test(failure.message||''))return '잔여 용량·측정 시각·유효기간과 로컬 여유 공간을 확인하세요.';
  if(/verification|private/.test(failure.message||''))return '연결의 쓰기·읽기 권한과 저장소 비공개 설정을 확인하고 소량 전송 검증을 다시 실행하세요.';
  return '설정 또는 자료를 확인하지 못했습니다. 입력과 서버 연결을 확인한 뒤 다시 시도하세요.';
}
function field(parent,label,key,value,type='text'){
  const holder=text(parent,'label',label);holder.className='ui-field-label';
  const input=document.createElement('input');input.className='ui-field';input.type=type;input.dataset.field=key;
  input.value=value??'';input.required=true;
  if(type==='number'){input.min='0';input.max='8000000';input.step='any';}
  holder.append(input);return input;
}
function select(parent,label,key,choices,value){
  const holder=text(parent,'label',label);holder.className='ui-field-label';
  const input=document.createElement('select');input.className='ui-field';input.dataset.field=key;
  for(const [key,title] of choices){const option=text(input,'option',title);option.value=key;}
  input.value=value;holder.append(input);return input;
}
function button(parent,label,call){
  const element=text(parent,'ui-button',label);element.setAttribute('kind','quiet');element.addEventListener('click',call);return element;
}
function readTargets(){
  return [...$('storage-settings-targets').children].map((row,index)=>{
    const previous=draft[index];
    if(!previous.connection_id)return {id:previous.id,enabled:row.querySelector('[data-field=enabled]').checked,status:'unavailable'};
    const result={id:previous.id,priority:index};
    for(const key of ['connection_id','repo_type','repo_id'])result[key]=row.querySelector(`[data-field=${key}]`).value.trim();
    result.enabled=row.querySelector('[data-field=enabled]').checked;
    result.quota_owner=result.repo_id.split('/')[0].toLowerCase();return result;
  });
}
function readQuotas(){
  const result={};
  for(const row of $('storage-settings-quotas').children){
    const get=key=>row.querySelector(`[data-field=${key}]`);
    result[row.dataset.owner]={remaining_bytes:bytes(get('remaining_bytes')),reserve_bytes:bytes(get('reserve_bytes')),
      source:get('source').value.trim(),measured_at:Math.floor(new Date(get('measured_at').value).getTime()/1000),
      expires_at:Math.floor(new Date(get('expires_at').value).getTime()/1000)};
  }
  return result;
}
function showQuotas(){
  const previous=readQuotas();Object.assign(quotas,previous);
  $('storage-settings-quotas').replaceChildren();
  const owners=[...new Set(readTargets().filter(row=>row.connection_id&&row.repo_id.includes('/')).map(row=>row.quota_owner))];
  for(const owner of owners){
    const now=Math.floor(Date.now()/1000), quota=quotas[owner]||{remaining_bytes:0,reserve_bytes:GiB,
      source:'HF 설정 화면에서 확인',measured_at:now,expires_at:now+3600};
    const row=document.createElement('fieldset');row.className='storage-quota';row.dataset.owner=owner;
    text(row,'legend',owner);const fields=document.createElement('div');fields.className='ui-form learning-form';row.append(fields);
    field(fields,'실제 잔여량 GiB','remaining_bytes',quota.remaining_bytes/GiB,'number');
    field(fields,'원격 여유분 GiB','reserve_bytes',quota.reserve_bytes/GiB,'number');
    field(fields,'측정 근거','source',quota.source).maxLength=160;
    field(fields,'측정 시각','measured_at',localDate(quota.measured_at),'datetime-local');
    field(fields,'유효기간 끝','expires_at',localDate(quota.expires_at),'datetime-local');
    $('storage-settings-quotas').append(row);
  }
}
function renderTargets(){
  $('storage-settings-targets').replaceChildren();
  for(const [index,target] of draft.entries()){
    const row=document.createElement('fieldset');row.className='storage-settings-target';
    text(row,'legend',`저장 대상 ${index+1}`);
    if(!target.connection_id){
      text(row,'p','연결에 접근할 수 없습니다. 기존 설정을 보존하며 원하면 이 대상의 새 배정만 중지할 수 있습니다.');
      const holder=text(row,'label','기존 새 배정 설정 유지');holder.className='ui-check';
      const enabled=document.createElement('input');enabled.className='ui-field';enabled.type='checkbox';enabled.dataset.field='enabled';enabled.checked=target.enabled;holder.prepend(enabled);
      $('storage-settings-targets').append(row);continue;
    }
    const fields=document.createElement('div');fields.className='ui-form learning-form';row.append(fields);
    select(fields,'HF 계정 연결','connection_id',state.connections.map(item=>[item.connection_id,
      `${item.username||'HF 계정'} · ${item.sharing==='project'?'프로젝트 연결':'개인 연결'}`]),target.connection_id);
    select(fields,'저장소 종류','repo_type',[['dataset','데이터셋'],['model','모델']],target.repo_type);
    field(fields,'비공개 저장소 이름','repo_id',target.repo_id).placeholder='계정 또는 조직/저장소';
    const holder=text(fields,'label','새 자료 배정에 사용');holder.className='ui-check';
    const enabled=document.createElement('input');enabled.className='ui-field';enabled.type='checkbox';enabled.dataset.field='enabled';enabled.checked=target.enabled;holder.prepend(enabled);
    const status={verified:'소량 전송·읽기 검증 완료',needs_verification:'소량 전송·읽기 검증 필요',unavailable:'연결 권한 확인 필요'};
    text(row,'p',status[target.status]||'저장 후 연결을 검증하세요.');
    const actions=document.createElement('ui-actions');row.append(actions);
    button(actions,'대상 제거',()=>{draft=readTargets();quotas=readQuotas();draft.splice(index,1);renderTargets();showQuotas();edited();});
    if(index>0)button(actions,'우선순위 올리기',()=>{draft=readTargets();quotas=readQuotas();[draft[index-1],draft[index]]=[draft[index],draft[index-1]];renderTargets();showQuotas();edited();});
    row.addEventListener('change',event=>{if(event.target.dataset.field==='repo_id')showQuotas();});
    $('storage-settings-targets').append(row);
  }
}
function controls(){
  const pending=busy||state?.busy, enabled=Boolean(state?.enabled), saved=state?.revision>0;
  const targets=(state?.targets||[]).filter(row=>row.enabled);
  const verified=targets.length>0&&targets.every(row=>row.status==='verified');
  $('storage-settings-save').disabled=Boolean(pending);
  $('storage-target-add').disabled=Boolean(pending)||!state?.connections?.length;
  $('storage-verify').disabled=Boolean(pending)||dirty||state?.upload_available===false||!saved||!targets.length||!$('storage-check-consent').checked;
  $('storage-activate').disabled=Boolean(pending)||dirty||enabled||!verified;
  $('storage-prepare-submit').disabled=Boolean(pending)||dirty||!enabled||!$('storage-completed-consent').checked;
  $('storage-check-reason').textContent=pending?'보관 작업 처리 중입니다. 끝나면 다음 작업을 할 수 있습니다.':
    dirty?'저장하지 않은 변경이 있습니다. 저장 설정 저장을 눌러 반영한 뒤 다음 작업을 하세요.':
    state?.upload_available===false?'보관 서버의 전송 기능이 아직 준비되지 않았습니다. 운영자에게 서버 구성을 요청하세요.':
    !saved?'계정 연결과 실제 용량을 선택하고 저장 설정을 저장하세요.':!targets.length?'새 자료를 받을 저장 대상을 하나 이상 선택하세요.':
      enabled?'새 보관이 활성화되어 있습니다. 아래에서 완료 자료를 준비하고 보관하세요.':
      !verified?'소량 전송과 읽기 검증 후 새 보관을 활성화할 수 있습니다.':'연결 검증을 마쳤습니다. 새 보관 활성화 후 완료 자료를 준비하세요.';
}
function result(data){
  if(data.error){error('작업을 마치지 못했습니다. 계정의 쓰기·읽기 권한, 비공개 설정, 측정 용량과 서버 연결을 확인한 뒤 재시도하세요.');return;}
  if(data.operation){$('storage-setup-result').textContent=data.operation==='verify'?'비공개 저장소에 소량 전송하고 실제 내용을 다시 확인하는 중입니다.':'완료 자료를 준비하고 보관하는 중입니다.';return;}
  if(data.result){
    const value=data.result;
    $('storage-setup-result').textContent=value.bytes_verified?'원격 검증 완료 · 아래 보관 작업에서 고정·회수·복원을 이어갈 수 있습니다.':
      value.status==='verified'?'저장 대상 연결 검증 완료 · 새 보관을 활성화하세요.':
        value.status==='prepared'?'완료 자료 준비됨 · 보관 작업에 등록할 수 있습니다.':'검증을 마치지 못했습니다. 아래 작업의 실패·보류 이유와 기존 커밋 확인을 살펴보세요.';
  }
}
async function refresh(current){
  const data=await send('/api/learning/storage/settings');if(current!==generation)return;
  const redraw=!state||state.revision!==data.revision;
  if(data.enabled&&!state?.enabled){$('storage-settings').open=false;$('storage-preparation').open=true;}
  state=data;$('storage-setup').hidden=false;$('storage-manager').hidden=!data.can_manage;
  $('storage-setup-status').textContent=!data.can_manage?'저장 대상 설정은 프로젝트의 게시·관리 권한이 필요합니다.':
    data.enabled?'새 보관 활성화됨 · 완료 자료를 준비하거나 기존 자료를 복원하세요.':
      !data.connections.length?'먼저 HF 계정을 연결하고 비공개 저장소를 준비하세요.':'저장 설정과 연결 검증을 마친 뒤 새 보관을 활성화하세요.';
  if(data.can_manage){
    if(redraw&&!dirty){draft=data.targets;quotas=data.quotas;formRevision=data.revision;$('storage-settings-quotas').replaceChildren();renderTargets();showQuotas();
      $('storage-local-reserve').value=data.reserve_bytes/GiB;$('storage-cache-limit').value=data.cache_policy.max_bytes/GiB;
      $('storage-cache-enabled').checked=data.cache_policy.enabled;}
    else if(dirty&&formRevision!==data.revision)error('다른 관리자가 저장 설정을 바꿨습니다. 입력을 확인한 뒤 저장 현황을 다시 불러오세요.');
    controls();result(data);
    if(data.operation)timer=setTimeout(()=>poll(current),700);
  }
  return data;
}
async function poll(current){
  try{const before=state?.operation;await refresh(current);if(current===generation&&before&&!state.operation)changed?.();}
  catch(failure){if(current===generation)error(failureMessage(failure));}
}
export function storageSetupDirty(){return dirty;}
export function clearStorageSetup(){generation++;clearTimeout(timer);state=null;draft=[];quotas={};dirty=false;$('storage-setup').hidden=true;}
export async function loadStorageSetup(request,onChanged){
  send=request;changed=onChanged;const current=generation;
  try{await refresh(current);}catch(failure){if(current===generation){$('storage-setup').hidden=false;error(failureMessage(failure));}}
}
async function action(path,body){
  if(busy||!send)return;busy=true;controls();$('storage-setup-error').hidden=true;
  const current=generation;
  try{
    await send('/api/learning/storage/'+path,body);if(current!==generation)return;
    if(path==='settings')dirty=false;
    await refresh(current);if(!state.operation)changed?.();
  }catch(failure){if(current===generation)error(failureMessage(failure));}
  finally{busy=false;if(current===generation)controls();}
}
$('storage-target-add').addEventListener('click',()=>{
  draft=readTargets();quotas=readQuotas();draft.push({id:'target-'+crypto.randomUUID().slice(0,8),
    connection_id:state.connections[0].connection_id,repo_type:'dataset',repo_id:'',enabled:true});renderTargets();showQuotas();
  edited();
  $('storage-settings-targets').lastElementChild.querySelector('[data-field=repo_id]').focus();
});
function edited(){dirty=true;controls();}
$('storage-settings-form').addEventListener('input',edited);
$('storage-settings-form').addEventListener('change',edited);
$('storage-settings-form').onsubmit=event=>{event.preventDefault();action('settings',{revision:formRevision,
  targets:readTargets().filter(row=>row.connection_id||!row.enabled).map(row=>row.connection_id?row:{id:row.id,enabled:false}),
  quotas:readQuotas(),reserve_bytes:bytes($('storage-local-reserve')),
  cache_policy:{enabled:$('storage-cache-enabled').checked,max_bytes:bytes($('storage-cache-limit'))}});};
$('storage-check-consent').onchange=controls;$('storage-completed-consent').onchange=controls;
$('storage-verify').addEventListener('click',()=>action('settings/verify',{revision:state.revision,confirm:true}));
$('storage-activate').addEventListener('click',()=>action('settings/activate',{revision:state.revision}));
async function sources(){
  if(!send||!state?.can_manage)return;
  const current=generation, isaac=$('storage-prepare-kind').value==='isaac';
  try{
    const data=await send('/api/learning/storage/'+(isaac?'sim-sources':'sources'));if(current!==generation)return;
    $('storage-folder-fields').hidden=isaac;$('storage-isaac-fields').hidden=!isaac;
    const input=$(isaac?'storage-prepare-run':'storage-prepare-folder');input.replaceChildren();
    const rows=isaac?data.runs:data.folders.filter(row=>row.can_prepare);
    for(const row of rows){const option=text(input,'option',isaac?`${row.scenario_id||'Isaac 결과'} · ${row.run_id}`:row.artifact_id);option.value=isaac?row.run_id:row.artifact_id;}
    $('storage-source-help').textContent=isaac&&!data.configured?'SIM 실행 연결이 필요합니다. SIM 실험 화면에서 실행기 상태를 확인하세요.':
      !rows.length?'준비할 완료 자료가 없습니다. 등록된 완료 자료 위치 또는 SIM 실험의 종료 결과를 확인하세요.':
        '파일의 쓰기가 끝난 자료만 선택하세요. 이미 준비한 목록은 다시 작성하지 않습니다.';
  }catch(failure){if(current===generation)error(failureMessage(failure));}
}
$('storage-sources-refresh').addEventListener('click',sources);$('storage-prepare-kind').onchange=sources;
$('storage-prepare-form').onsubmit=event=>{
  event.preventDefault();const kind=$('storage-prepare-kind').value;
  const body={kind,archive:true,confirm_completed:$('storage-completed-consent').checked};
  if(kind==='isaac')body.run_id=$('storage-prepare-run').value;
  else{body.artifact_id=$('storage-prepare-folder').value;body.profile=$('storage-prepare-profile').value;
    body.provenance={source_revision:$('storage-source-revision').value.trim()};
    if(!body.provenance.source_revision){error('자료의 출처 버전을 입력하세요.');return;}}
  action('sources/prepare',body);
};
