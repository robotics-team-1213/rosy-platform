import {accountFetch} from '/account-session.js';
import '/common/ui.js';
const $=id=>document.getElementById(id);
$('theme').value=document.documentElement.dataset.theme||'dark';$('theme').onchange=()=>{document.documentElement.dataset.theme=$('theme').value;try{localStorage.setItem('rosy.theme',$('theme').value);}catch{}document.dispatchEvent(new CustomEvent('rosy:theme'));};
const DOMAINS={lane:'Pinky 차로·픽셀',object:'Pinky 객체',omx:'OMX 모방학습',sim:'Isaac SIM',vlm:'VLM 판단',decision:'판단 모델'};
const requested=new URLSearchParams(location.search).get('domain');
const domain=DOMAINS[requested]?requested:null;
const stageStates={done:'완료',active:'진행',blocked:'막힘',waiting:'대기',not_available:'없음'};
async function read(path){
  const response=await accountFetch(path,{cache:'no-store'});
  const value=await response.json();
  if(!response.ok)throw new Error(value.error||'평가 근거를 읽지 못했습니다.');
  return value;
}
function text(parent,tag,value,cls){const node=document.createElement(tag);node.textContent=value;if(cls)node.className=cls;parent.append(node);return node;}
function source(key){
  const found=$('evaluate-sources').querySelector(`[data-domain="${key}"]`);
  if(found)return found;
  const block=text($('evaluate-sources'),'article','','evaluate-source');block.dataset.domain=key;
  text(block,'h3',DOMAINS[key]);
  return block;
}
function go(parent,label,href){const anchor=text(parent,'a',label,'workspace-link');anchor.href=href;return anchor;}
function stages(workspace){
  // The 평가 and 승격 기록 stages of every domain from /api/learning; unknown stays 없음 with its reason.
  for(const row of workspace.domains||[]){
    if(domain&&row.id!==domain)continue;
    const block=source(row.id);
    for(const stage of row.stages.filter(stage=>['evaluate','promote'].includes(stage.stage))){
      const line=text(block,'p',`${stage.label} · ${stageStates[stage.state]||stage.state} · ${stage.evidence}`);line.dataset.state=stage.state;
      if(stage.next&&!stage.next.href.startsWith('/learning/evaluate'))go(block,stage.next.label,stage.next.href);
    }
    if(row.id==='lane')go(block,'평가 근거 펼쳐 보기','/learning#pipeline-evidence');
  }
}
async function vlm(workspace){
  const block=source('vlm');text(block,'h4','모델 대 확정 정답');
  if(workspace.vlm_eval_url)go(block,'VLM 평가 state 열기',workspace.vlm_eval_url);
  const summary=await read('/api/learning/vlm/summary');
  if(!summary.total){text(block,'p',workspace.vlm_eval_url?'이 작업대에는 VLM 질문 자료가 없습니다. 별도 평가 state에서 확인하세요.':'VLM 질문 자료가 없습니다.');return;}
  const data=await read('/api/learning/vlm/evaluation');
  text(block,'p',`확정 정답 ${data.labelled}장 기준 · 모델 ${data.models.length}개`);
  if(data.models.length){
    const table=text(block,'table','','evaluate-table');const head=table.createTHead().insertRow();
    for(const name of ['모델','런타임','질문','n','일치율'])text(head,'th',name);
    const body=table.createTBody();
    for(const model of data.models)for(const row of model.questions){
      const line=body.insertRow();
      for(const value of [model.model,model.runtime,row.question,String(row.n),row.agreement==null?'—':`${(row.agreement*100).toFixed(1)}%`])line.insertCell().textContent=value;
    }
  }
  go(block,'VLM 평가 자세히','/learning/vlm#eval');
}
async function sim(){
  // Recent SIM runs, only fields sim_web.public() sends; each opens its run on /learning/sim.
  const block=source('sim');text(block,'h4','최근 SIM 실험');
  text(block,'p','SIM 판정과 과제 성공은 실험 근거일 뿐 승인·승격이 아닙니다(D-793, D-857).','quiet');
  let runs;
  try{runs=(await read('/api/learning/sim/runs')).runs;}catch(error){text(block,'p',`없음 · ${error.message}`).dataset.state='not_available';return;}
  if(!runs.length){text(block,'p','SIM 실험 기록이 없습니다.');return;}
  const when=run=>String(run.updated_at||run.created_at||'');
  const success={true:'성공',false:'실패'};
  const list=text(block,'ul','','evaluate-runs');
  for(const run of [...runs].sort((a,b)=>when(b).localeCompare(when(a))).slice(0,10)){
    const result=run.result||{};
    go(text(list,'li',''),`${run.run_id.slice(0,12)} · ${run.status} · 단계 ${result.stage||'없음'} · 과제 성공 ${success[result.task_success]||'기록 없음'} · 판정 ${result.status||'없음'}`,
      '/learning/sim?run='+encodeURIComponent(run.run_id));
  }
}
let token='';
async function promotion(){
  // Only the server decides who qualifies; this page shows its reasons and never calls Fleet (D-874).
  const data=await read('/api/learning/promotion-requests');
  $('promote-candidates').replaceChildren();$('promote-requests').replaceChildren();
  for(const row of data.candidates)text($('promote-candidates'),'li',`${row.name} · ${row.qualified?'요청 가능 · '+row.model_revision:row.reason}`).dataset.state=row.qualified?'done':'blocked';
  const ready=data.candidates.filter(row=>row.qualified);
  $('promote-candidate').replaceChildren(...ready.map(row=>{const option=document.createElement('option');option.value=row.id;option.textContent=`${row.name} · ${row.model_revision}`;return option;}));
  const reason=ready.length?'':data.candidates.length?'확정 정답 평가를 통과한 후보가 없습니다. 위 거절 이유를 확인하세요.':'등록된 인식 학습 결과가 없습니다. 홈에서 결과 폴더를 등록하세요.';
  $('promote-pick').hidden=!ready.length;$('promote-request').disabled=!!reason;$('promote-request').setAttribute('reason',reason);
  $('promote-status').textContent=reason||`요청 가능한 후보 ${ready.length}개`;
  for(const row of data.requests)text($('promote-requests'),'li',`${row.sha256} · ${row.model_revision} · ${row.requester} · ${row.created_at}`);
  if(!data.requests.length)text($('promote-requests'),'li','아직 없습니다.');
}
$('promote-request').onclick=async()=>{
  $('promote-request').disabled=true;
  try{
    const response=await accountFetch('/api/learning/promotion-requests',{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':token},body:JSON.stringify({id:$('promote-candidate').value})});
    const value=await response.json();
    if(!response.ok)throw new Error(value.error||'승격 요청을 만들지 못했습니다.');
    $('promote-result').textContent=`요청 해시 ${value.sha256} · Fleet에서 승인권자가 이 해시로 제안을 만든다(D-793).`;$('promote-result').hidden=false;
  }catch(error){$('evaluate-error').textContent=error.message;$('evaluate-error').hidden=false;}
  await promotion();
};
async function load(){
  $('evaluate-filter').textContent=domain?`${DOMAINS[domain]}만 보는 중`:'모든 도메인';
  if(domain){const all=go($('evaluate-filter'),' · 전체 보기','/learning/evaluate');all.classList.remove('workspace-link');}
  const workspace=await read('/api/learning');
  token=workspace.token;  // the server swaps in the account CSRF token in collaboration mode
  await promotion();
  stages(workspace);
  if(!domain||domain==='vlm')await vlm(workspace);
  if(!domain||domain==='sim')await sim();
  if(!$('evaluate-sources').children.length)text($('evaluate-sources'),'p','이 도메인에는 아직 Learning에 연결된 평가 근거가 없습니다.');
}
load().catch(error=>{$('evaluate-error').textContent=error.message;$('evaluate-error').hidden=false;$('evaluate-filter').textContent='';});
