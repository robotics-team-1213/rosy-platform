// Requests always use the saved revision; completion never reloads the editor.
let generation=0,timer=null,autoTimer=null,updateButtons=()=>{};
const autoAttempts=new Set();
const actions={object_draft:'AI 객체 초안 만들기',pixel_draft:'AI 픽셀 보완 초안 만들기',mask_check:'AI 마스크 확인 실행'};
const states={queued:'대기',running:'실행 중',succeeded:'완료',failed:'실패',cancelled:'취소됨',stale:'입력 변경 · 결과 미등록'};
const active=job=>['queued','running'].includes(job.state);
export const actorName=actor=>actor==='local-unidentified'?'미인증 로컬 작업자':actor||'작업자 미기록';
export function candidateOrigin(origin){
  try{const value=JSON.parse(origin);if(value.model&&value.requested_by)return `${value.model} · 요청 ${actorName(value.requested_by)}`;}catch{}
  return origin||'출처 미기록';
}
function element(tag,text){const node=document.createElement(tag);if(tag==='ui-button')node.setAttribute('kind','quiet');if(text)node.textContent=text;return node;}
export function resetAI(){generation++;clearTimeout(timer);clearTimeout(autoTimer);autoTimer=null;updateButtons=()=>{};document.getElementById('review-ai-jobs')?.remove();for(const id of ['pixel-mask-check-controls','pixel-draft-create-controls'])document.getElementById(id)?.replaceChildren();const state=document.getElementById('pixel-ai-generation-state');if(state){state.textContent='';state.hidden=true;}}
export function updateAI(){updateButtons();}
export function showAI(lane,index,request,context,results){
  resetAI();const ticket=generation,panel=element('section'),title=element('h3','AI 초안과 확인'),controls=element('div'),message=element('p'),jobs=element('ul'),provenance=element('details'),provenanceRows=element('div');
  panel.id='review-ai-jobs';panel.className='review-history';panel.setAttribute('aria-label','AI 실행');controls.className='review-ai-actions';message.setAttribute('role','status');
  provenance.id='review-ai-provenance';provenance.append(element('summary','AI 요청·모델 정보'),provenanceRows);
  panel.append(title,element('p','저장된 버전으로 요청합니다. 결과는 후보·참고 의견이며 사람이 확인한 뒤 적용·승인합니다.'),controls,message,jobs,provenance);
  if(lane==='object')document.querySelector('#save-status').after(panel);
  else document.querySelector('.pixel-vlm-feedback').append(panel);
  const allowed=lane==='object'?['object_draft']:['pixel_draft','mask_check'],buttons=[];
  let status=null,pending=false,loaded=false,autoScheduledKey='';
  const seenStates=new Map(),changedJobs=new Map(),noticedDrafts=new Set();
  const generationState=lane==='pixel'?document.getElementById('pixel-ai-generation-state'):null;
  for(const action of allowed){const button=element('ui-button',lane==='pixel'?(action==='mask_check'?'현재 사진 AI 검사':'현재 사진 AI 초안'):actions[action]);button.id=`review-ai-${action}`;const host=lane==='pixel'?document.getElementById(action==='mask_check'?'pixel-mask-check-controls':'pixel-draft-create-controls'):null;(host||controls).append(button);buttons.push([button,action]);button.onclick=()=>run(action);}
  const refresh=element('ui-button','AI 실행 상태 다시 조회'),result=element('ui-button','AI 결과 목록 조회');controls.append(refresh,result);
  updateButtons=()=>{
    const current=context(),blocked=!current||current.blocked;
    for(const [button,action] of buttons){const capability=status?.actions?.[action];const reason=pending?'요청 중입니다.':blocked?'현재 편집을 저장하거나 마친 뒤 요청하세요.':!status?'실행 설정 확인 중입니다.':status.can_request===false?'AI 실행 권한이 없는 읽기 전용 계정입니다.':status.busy||status.jobs.some(active)?'현재 작업이 끝난 뒤 요청하세요.':!capability?.available?capability?.reason||'AI 실행 설정을 확인하세요.':capability.reason;button.disabled=!!reason;button.setAttribute('reason',reason||'');}
    refresh.disabled=pending;result.disabled=pending||blocked;
    result.setAttribute('reason',blocked?'현재 편집을 저장하거나 마친 뒤 조회하세요.':'');
    if(lane==='pixel'){updateAuto();void deliverChanges();}
  };
  function generationMessage(text){if(generationState){generationState.textContent=text;generationState.hidden=!text;}}
  function clearAuto(){clearTimeout(autoTimer);autoTimer=null;autoScheduledKey='';}
  function pollLater(){if(ticket===generation&&!timer)timer=setTimeout(load,1500);}
  function draftAttempt(current){return status?.jobs.find(job=>job.action==='pixel_draft'&&job.version===current.version&&(!job.image_sha256||job.image_sha256===current.image_sha256)&&(!job.classes_sha256||job.classes_sha256===current.classes_sha256));}
  function jobMessage(job){return active(job)?job.state==='queued'?'AI 초안 준비 대기 중…':'현재 사진 AI 초안 생성 중…':job.state==='succeeded'?job.result?.added_pixels===0?'보완할 새 픽셀이 없습니다. 필요하면 직접 수정하세요.':'AI 초안 준비 완료 · 사진에서 확인하세요.':`AI 초안 ${states[job.state]||job.state} · ${job.error||'현재 사진 AI 초안으로 다시 요청할 수 있습니다.'}`;}
  let lastAutoMessage='';
  function updateAuto(){
    if(ticket!==generation)return;
    const current=context(),attempt=current?draftAttempt(current):null;
    if(attempt){if(current.autoDraft&&current.autoKey)autoAttempts.add(current.autoKey);clearAuto();generationMessage(current.autoDraft||noticedDrafts.has(attempt.id)?current.blocked&&attempt.state==='succeeded'&&changedJobs.has(attempt.id)?'AI 초안 준비됨 · 현재 수정을 마치면 자동 표시합니다.':jobMessage(attempt):'');if(active(attempt))pollLater();return;}
    if(!current?.autoDraft||!current.autoKey){clearAuto();generationMessage('');return;}
    if(autoAttempts.has(current.autoKey)){clearAuto();generationMessage(lastAutoMessage||'이 사진은 이미 AI 초안을 요청했습니다. 필요하면 다시 요청하세요.');return;}
    if(!status){clearAuto();generationMessage('AI 초안 실행 설정 확인 중…');return;}
    if(status.can_request!==true){clearAuto();generationMessage(status.can_request===false?'읽기 전용 계정 · AI 초안을 요청할 수 없습니다.':'자동 준비 권한을 확인할 수 없습니다.');return;}
    const capability=status.actions?.pixel_draft;
    if(!capability?.available){clearAuto();generationMessage(capability?.reason||'AI 초안 실행 설정이 필요합니다.');return;}
    if(status.busy||status.jobs.some(active)){clearAuto();generationMessage('AI 자원 대기 중 · 현재 사진은 앞선 작업이 끝나면 준비합니다.');pollLater();return;}
    if(current.blocked||pending){clearAuto();generationMessage(pending?'AI 요청을 처리하는 중…':'편집을 마치면 현재 사진의 AI 초안을 준비합니다.');return;}
    generationMessage('현재 사진 AI 초안 준비 대기 중…');
    if(autoTimer&&autoScheduledKey===current.autoKey)return;
    clearAuto();autoScheduledKey=current.autoKey;const key=current.autoKey;
    autoTimer=setTimeout(()=>{
      autoTimer=null;autoScheduledKey='';const latest=context();
      if(ticket!==generation||pending||!latest?.autoDraft||latest.blocked||latest.autoKey!==key||status?.can_request!==true||status.busy||!status.actions?.pixel_draft?.available||status.jobs.some(active)||draftAttempt(latest)||autoAttempts.has(key))return;
      autoAttempts.add(key);lastAutoMessage='현재 사진 AI 초안 요청 중…';void send(`/api/review-ai/${index}`,{action:'pixel_draft',version:latest.version});
    },700);
  }
  async function deliverChanges(){
    const current=context();if(ticket!==generation||pending||!changedJobs.size||!current||current.blocked)return;
    const changes=[...changedJobs.values()];changedJobs.clear();pending=true;updateAI();
    try{await results(changes);if(ticket===generation)message.textContent='현재 사진의 AI 결과를 확인했습니다. 라벨은 자동 저장하지 않습니다.';}
    catch(error){if(ticket===generation)message.textContent=error.message;}
    finally{if(ticket===generation){pending=false;updateAI();}}
  }
  function render(){
    jobs.replaceChildren();provenanceRows.replaceChildren();
    const visibleJobs=status.jobs.filter(row=>allowed.includes(row.action));provenance.hidden=!visibleJobs.length;
    for(const job of visibleJobs){
      const row=element('li'),summary=element('p',`${actions[job.action]} · ${states[job.state]||job.state} · v${job.version}`),details=element('section');
      details.dataset.job=job.id;
      details.append(element('h4',`${actions[job.action]} · v${job.version}`),element('p',`요청 ${actorName(job.actor)} · ${job.created_at}`),element('p',`모델 ${job.model} · ${job.model_digest}`));
      row.append(summary);provenanceRows.append(details);
      if(job.error)row.append(element('p',job.error));
      if(job.state==='succeeded')row.append(element('p',job.action==='mask_check'?'참고 의견 저장됨 · AI 의견에 자동 표시됩니다.':job.result?.added_pixels===0?'보완할 픽셀 없음 · 새 후보를 만들지 않았습니다.':'초안 후보 저장됨 · AI 결과 목록 조회에서 선택하세요.'));
      if(active(job)){const cancel=element('ui-button','이 AI 작업 취소');cancel.disabled=pending;cancel.onclick=()=>send(`/api/review-ai-cancel/${job.id}`,{});row.append(cancel);}
      jobs.append(row);
    }
    message.textContent=status.reason||(!jobs.children.length?'이 사진에서 실행한 AI 작업이 없습니다.':'결과를 조회해도 현재 라벨은 자동 변경되지 않습니다.');updateAI();
  }
  async function load(){
    clearTimeout(timer);timer=null;
    try{const value=await request(`/api/review-ai/${index}`);if(ticket!==generation)return;status=value;
      if(lane==='pixel')for(const job of status.jobs.filter(row=>allowed.includes(row.action))){if(loaded&&seenStates.get(job.id)!==job.state){changedJobs.set(job.id,job);if(job.action==='pixel_draft')noticedDrafts.add(job.id);}seenStates.set(job.id,job.state);}
      loaded=true;render();if(status.jobs.some(active))pollLater();}
    catch(error){if(ticket===generation){status=null;message.textContent=error.message;updateAI();}}
  }
  async function send(path,body){
    if(pending||ticket!==generation)return;pending=true;updateAI();
    try{await request(path,body);if(ticket===generation)await load();}
    catch(error){if(ticket===generation){message.textContent=error.message;if(body.action==='pixel_draft'){lastAutoMessage=`AI 초안 요청 실패 · ${error.message} · 현재 사진 AI 초안으로 다시 요청하세요.`;generationMessage(lastAutoMessage);}}}
    finally{if(ticket===generation){pending=false;updateAI();}}
  }
  function run(action){const current=context();if(!current||current.blocked||buttons.find(([,id])=>id===action)[0].disabled)return;if(action==='pixel_draft'&&current.autoKey){clearAuto();autoAttempts.add(current.autoKey);lastAutoMessage='현재 사진 AI 초안 요청 중…';}void send(`/api/review-ai/${index}`,{action,version:current.version});}
  refresh.onclick=load;
  result.onclick=async()=>{if(result.disabled)return;pending=true;updateAI();try{await results();if(ticket===generation)message.textContent='AI 결과 목록을 조회했습니다. 후보와 참고 의견을 확인하세요.';}catch(error){if(ticket===generation)message.textContent=error.message;}finally{if(ticket===generation){pending=false;updateAI();}}};
  updateAI();void load();
}
