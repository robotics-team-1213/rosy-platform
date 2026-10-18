// Requests always use the saved revision; completion never reloads the editor.
let generation=0,timer=null,updateButtons=()=>{};
const actions={object_draft:'AI 객체 초안 만들기',pixel_draft:'AI 픽셀 보완 초안 만들기',mask_check:'AI 마스크 확인 실행'};
const states={queued:'대기',running:'실행 중',succeeded:'완료',failed:'실패',cancelled:'취소됨',stale:'입력 변경 · 결과 미등록'};
const active=job=>['queued','running'].includes(job.state);
export const actorName=actor=>actor==='local-unidentified'?'미인증 로컬 작업자':actor||'작업자 미기록';
export function candidateOrigin(origin){
  try{const value=JSON.parse(origin);if(value.model&&value.requested_by)return `${value.model} · 요청 ${actorName(value.requested_by)}`;}catch{}
  return origin||'출처 미기록';
}
function element(tag,text){const node=document.createElement(tag);if(tag==='ui-button')node.setAttribute('kind','quiet');if(text)node.textContent=text;return node;}
export function resetAI(){generation++;clearTimeout(timer);updateButtons=()=>{};document.getElementById('review-ai-jobs')?.remove();}
export function updateAI(){updateButtons();}
export function showAI(lane,index,request,context,results){
  resetAI();const ticket=generation,panel=element('section'),title=element('h3','AI 초안과 확인'),controls=element('div'),message=element('p'),jobs=element('ul');
  panel.id='review-ai-jobs';panel.className='review-history';panel.setAttribute('aria-label','AI 실행');controls.className='review-ai-actions';message.setAttribute('role','status');
  panel.append(title,element('p','저장된 버전으로 요청합니다. 결과는 후보·참고 의견이며 사람이 확인한 뒤 적용·승인합니다.'),controls,message,jobs);
  document.querySelector(lane==='object'?'#save-status':'.pixel-vlm-feedback').after(panel);
  const allowed=lane==='object'?['object_draft']:['pixel_draft','mask_check'],buttons=[];
  let status=null,pending=false;
  for(const action of allowed){const button=element('ui-button',actions[action]);button.id=`review-ai-${action}`;controls.append(button);buttons.push([button,action]);button.onclick=()=>run(action);}
  const refresh=element('ui-button','AI 실행 상태 다시 조회'),result=element('ui-button','AI 결과 목록 조회');controls.append(refresh,result);
  updateButtons=()=>{
    const current=context(),blocked=!current||current.blocked;
    for(const [button,action] of buttons){const reason=pending?'요청 중입니다.':blocked?'현재 편집을 저장하거나 마친 뒤 요청하세요.':!status?'실행 설정 확인 중입니다.':status.jobs.some(active)?'현재 작업이 끝난 뒤 요청하세요.':status.actions[action].reason;button.disabled=!!reason;button.setAttribute('reason',reason||'');}
    refresh.disabled=pending;result.disabled=pending||blocked;
    result.setAttribute('reason',blocked?'현재 편집을 저장하거나 마친 뒤 조회하세요.':'');
  };
  function render(){
    jobs.replaceChildren();
    for(const job of status.jobs.filter(row=>allowed.includes(row.action))){
      const row=element('li'),summary=element('p',`${actions[job.action]} · ${states[job.state]||job.state} · v${job.version} · 요청 ${actorName(job.actor)} · ${job.created_at}`);
      row.append(summary,element('p',`모델 ${job.model} · ${job.model_digest}`));
      if(job.error)row.append(element('p',job.error));
      if(job.state==='succeeded')row.append(element('p',job.action==='mask_check'?'참고 의견 저장됨 · AI 결과 목록 조회에서 확인하세요.':job.result?.added_pixels===0?'보완할 픽셀 없음 · 새 후보를 만들지 않았습니다.':'초안 후보 저장됨 · AI 결과 목록 조회에서 선택하세요.'));
      if(active(job)){const cancel=element('ui-button','이 AI 작업 취소');cancel.disabled=pending;cancel.onclick=()=>send(`/api/review-ai-cancel/${job.id}`,{});row.append(cancel);}
      jobs.append(row);
    }
    message.textContent=status.reason||(!jobs.children.length?'이 사진에서 실행한 AI 작업이 없습니다.':'결과를 조회해도 현재 라벨은 자동 변경되지 않습니다.');updateAI();
  }
  async function load(){
    clearTimeout(timer);
    try{const value=await request(`/api/review-ai/${index}`);if(ticket!==generation)return;status=value;render();if(status.jobs.some(active))timer=setTimeout(load,1500);}
    catch(error){if(ticket===generation){status=null;message.textContent=error.message;updateAI();}}
  }
  async function send(path,body){
    if(pending||ticket!==generation)return;pending=true;updateAI();
    try{await request(path,body);if(ticket===generation)await load();}
    catch(error){if(ticket===generation)message.textContent=error.message;}
    finally{if(ticket===generation){pending=false;updateAI();}}
  }
  function run(action){const current=context();if(!current||current.blocked||buttons.find(([,id])=>id===action)[0].disabled)return;void send(`/api/review-ai/${index}`,{action,version:current.version});}
  refresh.onclick=load;
  result.onclick=async()=>{if(result.disabled)return;pending=true;updateAI();try{await results();if(ticket===generation)message.textContent='AI 결과 목록을 조회했습니다. 후보와 참고 의견을 확인하세요.';}catch(error){if(ticket===generation)message.textContent=error.message;}finally{if(ticket===generation){pending=false;updateAI();}}};
  updateAI();void load();
}
