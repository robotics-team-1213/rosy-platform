import {accountFetch} from '/account-session.js';
import '/commands.js';
const $=id=>document.getElementById(id),API='/api/learning/omx/center';
const statusLabels={launching:'시작 준비 중',running:'실행 중',stopping:'중지 처리 중',failed:'실패',interrupted:'실행 중단됨',cancelled:'취소됨',succeeded:'학습 완료'};
const phaseLabels={downloading:'원본 자료 내려받는 중',preparing:'학습 자료 준비 중',training:'ACT 학습 중',evaluating:'남겨 둔 자료 평가 중',finished:'학습·평가 완료'};
const active=new Set(['launching','running','stopping']);
let source=null,token='',connected=false,busy=false,refreshing=false,polling=false,pending=null;
const runNodes=new Map();
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function error(message){$('public-error').hidden=!message;$('public-error').textContent=message||'';}
function uuid(){const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;const h=Array.from(b,v=>v.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
async function request(path,body){
  const options={cache:'no-store',signal:AbortSignal.timeout(path===API+'/public-source'?60000:30000)};
  if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-Pinky-Token':token};options.body=JSON.stringify(body);}
  const response=await accountFetch(path,options),value=await response.json();
  if(!response.ok)throw new Error(response.status===401?'로그인·계정에서 접속한 뒤 다시 확인하세요.':response.status===403?'프로젝트의 학습 실행 권한을 확인하세요.':value.error||`요청 실패 (${response.status})`);
  return value;
}
function facts(target,rows){target.replaceChildren(...rows.flatMap(([label,value])=>[node('dt',label),node('dd',value)]));}
function selection(){
  const reason=refreshing?'출처와 학습 호스트를 확인하는 중입니다.':!source?'출처를 다시 확인하세요.':!source.available?source.reason||'현재 호스트에서 공개 자료 학습을 사용할 수 없습니다.':!source.recipe?'학습 설정을 확인할 수 없습니다.':!connected?'학습 기록 연결을 다시 확인하세요.':!token?'로그인·계정에서 학습 권한을 확인하세요.':!$('public-confirm').checked?'원본·이용 조건과 분할의 한계를 확인하세요.':'';
  $('public-start-reason').textContent=reason||'SO100 공개 자료로 오프라인 학습을 시작할 수 있습니다.';
  $('public-start').disabled=busy||!!reason;$('public-start').reason=reason;
  $('public-start').textContent=busy?'요청 처리 중':pending?'같은 학습 요청 다시 확인':'공개 시연으로 학습 시작';
  for(const view of runNodes.values()){
    view.stop.disabled=busy||!connected||!token||view.run.status==='stopping';
    view.stop.reason=!connected?'연결을 다시 확인하세요.':!token?'학습 실행 권한을 확인하세요.':view.run.status==='stopping'?'중지 처리 결과를 기다리세요.':'';
  }
  return !reason;
}
function renderSource(){
  $('public-source-status').textContent=source.available?'고정한 공개 자료를 확인했습니다.':source.reason||'공개 자료를 사용할 수 없습니다. 다시 확인하세요.';
  const recipe=source.recipe;
  facts($('public-source-facts'),[['자료',source.repo_id||'미확인'],['원본 로봇',source.robot_type||'미확인'],['이용 조건',source.license||'미확인'],['원본 에피소드',source.episodes??'미확인']]);
  $('public-revision').textContent=`고정 버전: ${source.revision||'미확인'}`;
  const episodes=key=>Array.isArray(recipe?.[key])?recipe[key].join(', '):'미확인';
  facts($('public-recipe'),[['학습 에피소드',episodes('train_episodes')],['검증 에피소드',episodes('validation_episodes')],['평가 에피소드',episodes('eval_episodes')],['학습 단계',recipe?.steps??'미확인'],['배치 크기',recipe?.batch_size??'미확인']]);
}
function finite(value){return Number.isFinite(value)?Number(value.toPrecision(5)).toString():'미확인';}
function resultTable(evaluation){
  const table=node('table',null,'public-table'),thead=node('thead'),head=node('tr'),body=node('tbody');
  table.append(node('caption','원본 자료의 단위로 비교한 관절별 평균 절대 오차 · 물리 단위 미확인'));
  for(const label of ['원본 관절','모델 MAE','학습 평균 기준 MAE']){const th=node('th',label);th.scope='col';head.append(th);}thead.append(head);
  evaluation.mae_per_joint.forEach((value,i)=>{const row=node('tr'),name=node('th',evaluation.joint_names?.[i]||`관절 ${i+1}`);name.scope='row';row.append(name,node('td',finite(value)),node('td',finite(evaluation.train_mean_baseline_mae_per_joint?.[i])));body.append(row);});
  table.append(thead,body);return table;
}
function renderRun(run){
  let view=runNodes.get(run.id);
  if(!view){
    const section=node('article',null,'public-run'),header=node('div',null,'public-run-header'),title=node('h3'),progress=node('p'),failure=node('p'),evaluation=node('div'),download=node('a','모델·입력·평가 내려받기','workspace-link'),details=node('details'),record=node('pre');
    const stop=node('ui-button','이 학습 중지');
    stop.setAttribute('kind','quiet');stop.dataset.alwaysLive='';stop.onclick=()=>stopRun(run.id);
    download.href=API+'/artifact/'+encodeURIComponent(run.id);details.append(node('summary','실행 식별·설정 기록'),record);header.append(title,stop);section.append(header,progress,failure,evaluation,download,details);$('public-runs').append(section);
    view={section,title,stop,progress,failure,evaluation,download,record,signature:''};runNodes.set(run.id,view);
  }
  view.run=run;
  view.title.textContent=statusLabels[run.status]||'상태 확인 필요';view.title.title=run.status;
  view.stop.hidden=!active.has(run.status);view.stop.disabled=busy||!connected||!token||run.status==='stopping';view.stop.reason=!connected?'연결을 다시 확인하세요.':!token?'학습 실행 권한을 확인하세요.':run.status==='stopping'?'중지 처리 결과를 기다리세요.':'';
  const progress=run.progress||{};
  view.progress.textContent=phaseLabels[progress.phase]||'세부 진행 정보 없음';
  if(Number.isFinite(progress.step)&&Number.isFinite(progress.steps))view.progress.textContent+=` · ${progress.step} / ${progress.steps}단계`;
  view.failure.hidden=!run.error;view.failure.textContent=typeof run.error==='string'?run.error:run.error?.message||'';
  const evaluation=run.result?.evaluation,signature=JSON.stringify(evaluation||null);
  if(view.signature!==signature){
    view.signature=signature;view.evaluation.replaceChildren();
    if(Array.isArray(evaluation?.mae_per_joint)&&evaluation.mae_per_joint.length){
      view.evaluation.append(node('p',`평가 표본 ${evaluation.samples??'미확인'}개 · 별도 프로세스 모델 재적재 ${evaluation.model_reloaded_in_new_process===true?'확인됨':'미확인'}`));
      const wrap=node('div',null,'public-table-wrap');wrap.append(resultTable(evaluation));view.evaluation.append(wrap);
    }else view.evaluation.append(node('p','오프라인 평가 결과가 아직 없습니다.'));
    view.evaluation.append(node('p','실물 학습 성능 미검증 · 정책 적용 없음','public-note'));
  }
  view.download.hidden=run.status!=='succeeded';
  const record=JSON.stringify(run,null,2);if(view.record.textContent!==record)view.record.textContent=record;
}
async function snapshot(){
  if(polling)return;polling=true;
  try{
    const data=await request(API);connected=true;
    const runs=(data.runs||[]).filter(run=>run.execution_mode==='public_train');
    const ids=new Set(runs.map(run=>run.id));for(const [id,view] of runNodes)if(!ids.has(id)){view.section.remove();runNodes.delete(id);}
    runs.forEach(renderRun);$('public-empty').hidden=!!runs.length;$('public-runs-status').textContent='저장한 공개 데이터 학습 기록을 확인했습니다.';
  }catch(exc){connected=false;$('public-runs-status').textContent=`학습 기록 연결 실패: ${exc.message} 다시 확인하세요.`;for(const view of runNodes.values()){view.stop.disabled=true;view.stop.reason='연결을 다시 확인하세요.';}}
  finally{polling=false;selection();}
}
async function refresh(){
  if(refreshing)return;refreshing=true;$('public-refresh').disabled=true;error('');selection();
  const results=await Promise.allSettled([request('/api/workspace'),request(API+'/public-source'),snapshot()]);
  if(results[0].status==='fulfilled')token=results[0].value.token||'';else{token='';error(results[0].reason.message);}
  if(results[1].status==='fulfilled'){source=results[1].value;renderSource();}else{source=null;$('public-source-status').textContent=`출처 확인 실패: ${results[1].reason.message} 다시 확인하세요.`;}
  refreshing=false;$('public-refresh').disabled=false;selection();
}
$('public-confirm').onchange=selection;
$('public-refresh').onclick=refresh;
$('public-start').onclick=async()=>{
  if(busy||!selection())return;
  pending??={request_id:uuid(),repo_id:source.repo_id,revision:source.revision,steps:source.recipe.steps,batch_size:source.recipe.batch_size,confirmed_source:true};
  busy=true;error('');selection();
  try{const run=await request(API+'/public-run',pending);pending=null;$('public-submit-status').textContent=`학습 접수 확인: ${run.id}`;await snapshot();}
  catch(exc){error(`${exc.message} 같은 학습 요청 다시 확인을 누르면 동일한 요청으로 접수 여부를 확인합니다.`);}
  finally{busy=false;selection();}
};
async function stopRun(id){
  if(busy||!connected||!token)return;busy=true;error('');selection();
  try{await request(API+'/stop',{id});$('public-submit-status').textContent='중지를 요청했습니다. 실행 상태에서 처리 결과를 확인하세요.';await snapshot();}
  catch(exc){error(`${exc.message} 실행 상태를 다시 확인하고 중지를 재시도하세요.`);}
  finally{busy=false;selection();}
}
refresh();setInterval(()=>{if(!document.hidden&&!busy)snapshot();},5000);
