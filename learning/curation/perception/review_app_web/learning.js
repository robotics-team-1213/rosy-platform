import {accountFetch} from '/account-session.js';
import { taskRow } from '/common/workspace.js';
import '/commands.js';
import { loadStorage, clearStorage } from '/storage.js';
const $=id=>document.getElementById(id);
let workspace, busy=false, checkedAt=0, readSequence=0;
const trainingView=new URL(location.href).searchParams.get('view')==='training';
$('workspace-title').textContent=trainingView?'학습·결과':'작업';
document.title=`${trainingView?'학습·결과':'작업'} · Rosy Learning`;
$('workspace-review').hidden=trainingView;
if(trainingView)$('training-controls').open=true;
const labels={unchanged:'등록한 파일과 일치',changed:'등록 후 변경됨',missing:'파일 없음',invalid:'읽기 실패'};
const states={running:'진행 중',reading:'자료 읽는 중',training:'학습 중',failed:'실패',rejected:'품질 거절',reject:'품질 거절',
  ready:'자료 준비 완료',done:'완료',candidate:'학습 후보 저장됨',pass:'보고서 통과',research_only:'연구 결과',research_exported:'연구 결과 저장됨',
  offline_only:'오프라인 평가 결과',not_eligible:'승격 대상 아님',candidate_evaluated:'후보 평가 완료',HOLD:'적용 보류',held:'승인·입력 조건 대기',request_published:'학습 요청 준비됨',already_completed:'같은 자료 처리 완료'};
const nextActions={perception:'보고서 상태와 단계별 근거를 확인하고 학습 담당자에게 전달하세요. 로봇 실행 수용은 별도입니다.',
  raw:'원본 검증 보고서와 학습·평가 세션 분리를 확인하세요.',
  pinky:'이동 속도와 회전 속도 평가를 각각 확인하세요. 로봇 실행 수용은 별도입니다.',
  omx:'시연 단위 분리와 관절 평가 결과를 확인하세요. 장치 수용은 별도입니다.',
  policy:'산출물 파일과 승격 증거를 정책 원장에서 확인하세요.',
  isaac:'환경과 과제 설정이 맞는지 독립 시뮬레이션에서 확인하세요.',
  segmentation:'픽셀 검수 결과를 확인하세요. 객체 박스 승인과 별개입니다.'};
const reasons={does_not_beat_constant_target_baseline:'오프라인 평가가 상수 목표 기준을 넘지 못했습니다.',no_approved_masks:'아직 사람이 승인한 픽셀 마스크가 없습니다.',
  'work busy: GPU compute job':'다른 GPU 작업이 끝나면 자동으로 다시 확인합니다.',
  'work busy: GPU utilization':'GPU 사용 중입니다. 자동으로 다시 확인합니다.'};
function readableError(error) {
  const message=error.message||String(error);
  if(message.includes('no supported report')) return '선택한 작업 종류에 맞는 결과 파일이 없습니다.';
  if(message.includes('already registered')) return '이 결과 폴더는 이미 연결되어 있습니다.';
  if(message.includes('does not exist')) return '결과 폴더를 찾을 수 없습니다.';
  if(message.includes('version conflict')) return '다른 화면에서 연결이 변경되었습니다.';
  return message;
}
function text(parent,tag,value,cls) {
  const node=document.createElement(tag);node.textContent=value;
  if(cls) node.className=cls;parent.append(node);return node;
}
function message(id,value) {$(id).textContent=value;$(id).hidden=!value;}
function setBusy(value) {
  busy=value;
  for(const button of $('learning-main').querySelectorAll('ui-button')) {
    button.reason=value?'결과를 확인하는 중입니다':!workspace&&button.id!=='refresh'?'작업 결과를 다시 확인한 뒤 사용하세요.':'';
    button.disabled=value||(!workspace&&button.id!=='refresh');
  }
  for(const id of ['search','kind-filter','state-filter','kind','name','path'])$(id).disabled=value||!workspace;
  updateControls();
  updatePipelineAction();
}
const stageStates={waiting:'대기',running:'진행 중',done:'완료',attention:'확인 필요',connection:'연결 필요'};
function updatePipelineAction() {
  const next=workspace?.pipeline?.next,button=$('pipeline-action');
  const action=next?.action;
  button.disabled=busy||!workspace||!action||
    (['start','retry'].includes(action)&&!workspace.control?.[`can_${action}`]);
  button.reason=busy?'요청을 처리하고 있습니다.':!workspace?'최신 결과를 확인하세요.':'';
  $('pipeline-link').hidden=!workspace||!next?.href;
}
function renderPipeline() {
  const pipeline=workspace?.pipeline;
  $('pipeline-stages').replaceChildren();$('pipeline-records').replaceChildren();
  $('pipeline').setAttribute('aria-busy', 'false');
  if(!pipeline) {
    $('pipeline-title').textContent='작업 상태를 확인하지 못했습니다';
    $('pipeline-status').textContent='현재 자료의 상태를 확인할 수 없습니다. 최신 결과 확인으로 다시 시도하세요.';
    $('pipeline-action').hidden=false;$('pipeline-action').textContent='진행 상태 확인 불가';
    updatePipelineAction();return;
  }
  const next=pipeline.next;
  const headline=next.href==='/catalog'?'첫 자료를 등록하세요':next.href?.startsWith('/pixels')?'검수할 자료가 있습니다':
    next.action==='prepare'?'승인한 자료를 학습에 준비하세요':next.action==='start'?'학습을 시작할 수 있습니다':
    next.action==='retry'?'학습을 다시 진행할 수 있습니다':workspace.control?.active?'학습이 진행 중입니다':
    pipeline.stages.find(row=>row.id==='training')?.state==='done'?'모델과 평가 결과를 확인하세요':'현재 작업을 이어가세요';
  $('pipeline-title').textContent=headline;
  $('pipeline-status').textContent=pipeline.stages.find(row=>row.state!=='done')?.detail||'현재 자료의 처리 결과를 확인하세요.';
  let current=false;
  for(const step of pipeline.stages) {
    const row=text($('pipeline-stages'),'li','','pipeline-stage');
    row.dataset.stage=step.id;row.dataset.state=step.state;
    if(!current&&step.state!=='done'){row.setAttribute('aria-current','step');current=true;}
    const heading=text(row,'div','','pipeline-stage-heading');
    text(heading,'h3',step.label);text(heading,'span',stageStates[step.state]||'확인 필요');
    text(row,'p',step.detail);
  }
  $('pipeline-action').hidden=!!next.href;$('pipeline-action').textContent=next.label;
  if(next.href) {
    $('pipeline-link').href=new URL(next.href,location.href).href;
    $('pipeline-link').textContent=next.label;
  }
  const records=$('pipeline-records'),identity=pipeline.identity;
  for(const step of pipeline.stages)text(records,'p',`${step.label} · ${step.detail}`);
  text(records,'p',`검수 버전 ${identity.generation} · 작업대 ${identity.workspace_id}`);
  text(records,'p',`검수 결정 ${identity.decision_sha256}`,'quiet');
  if(pipeline.dataset)text(records,'p',`현재 데이터셋 · ${pipeline.dataset}`);
  if(!pipeline.current)text(records,'p','현재 검수 결정과 연결된 학습 결과가 아직 없습니다.');
  for(const [index,row] of pipeline.cycles.entries()) {
    const phase={ready:'평가·READY 기록 확인',candidate:'후보 생성 · 독립 평가 대기'}[row.status]||states[row.status]||row.status;
    text(records,'p',`학습 ${index+1} · ${phase}${row.revision?' · 모델 '+row.revision:''}`);
    if(row.error)text(records,'p',reasons[row.error]||row.error,'job-reason');
  }
  for(const reason of pipeline.blockers)text(records,'p',reasons[reason]||reason,'job-reason');
  if(pipeline.cycles.length)text(records,'p','표시한 모델의 실행 기록입니다. 비교 지표와 장치 적용 근거는 별도로 검토하세요.','quiet');
  updatePipelineAction();
}
async function prepareCurrent() {
  if(busy||workspace?.pipeline?.next?.action!=='prepare')return;
  setBusy(true);message('learning-error','');
  try {await request('/api/prepare',{});await load();message('notice','승인 자료를 준비했습니다. 다음 작업을 확인하세요.');}
  catch(error){message('learning-error',readableError(error));}
  finally {setBusy(false);}
}
function updateControls() {
  const control=workspace?.control,status=$('owner-control-status');
  if(!status)return;
  status.textContent=control?.available
    ? ({running:'실행기 처리 중',stopping:'중지 요청 처리 중',waiting:'자동 확인 켜짐 · 조건 대기',stopped:'자동 확인 중지됨'}[control.state]||control.state)
    : '학습 실행기 연결 필요';
  if(control?.error)status.textContent+=` · ${control.error}`;
  if(control?.available)$('training-controls').open=true;
  for(const action of ['start','stop','retry']) {
    const button=$(`owner-control-${action}`);
    button.disabled=busy||!control?.available||!control[`can_${action}`];
    button.reason=busy?'요청 처리 중입니다':button.disabled?control?.reasons?.[action]||control?.error||'학습 실행기를 연결하세요.':'';
  }
}
async function controlAction(action) {
  if(busy)return;
  const version=workspace.control.version;setBusy(true);message('learning-error','');
  try {
    await request('/api/learning/control',{action,version});
    await load();message('notice','실행기 요청을 접수했습니다. 아래 상태와 학습 결과를 확인하세요.');
    $('owner-control-status')?.focus();
  } catch(error) {
    if(error.status===409)await load().catch(()=>{});
    message('learning-error',readableError(error));
  } finally {setBusy(false);}
}
let polling=false, pendingReportRefresh=false;
setInterval(async()=> {
  if(busy||polling||!workspace||document.hidden)return;
  polling=true;
  const sequence=readSequence;
  try {
    const value=await request('/api/learning');
    if(busy||sequence!==readSequence)return;
    pendingReportRefresh ||= JSON.stringify(workspace.items)!==JSON.stringify(value.items);
    workspace=value;renderReview();renderPipeline();updateControls();
    if(pendingReportRefresh&&!document.querySelector('dialog[open]')&&!$('connection-panel').open
        &&!$('jobs').contains(document.activeElement)) {
      checkedAt=Date.now();render();pendingReportRefresh=false;
    }
  } catch(error) {
    if(!busy&&sequence===readSequence){showUnavailable(error);setBusy(false);}
  } finally {polling=false;}
},5000);
async function request(path,body) {
  const response=await accountFetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':workspace.token},body:JSON.stringify(body)}:{});
  if(response.status>=500){const error=new Error('학습 작업 서비스를 사용할 수 없습니다. 잠시 후 다시 시도하세요.');error.status=response.status;throw error;}
  const value=await response.json();if(!response.ok){const error=new Error(response.status===403?'이 작업대의 학습 작업 접근 권한이 거부되었습니다.':'요청 실패 · '+(value.error||'원인을 확인할 수 없습니다.'));error.status=response.status;if(response.status===401||response.status===403)showUnavailable(error);throw error;}return value;
}
function showUnavailable(error){clearStorage();workspace=undefined;checkedAt=0;renderPipeline();updateControls();$('jobs').replaceChildren();$('jobs').hidden=true;$('empty-jobs').hidden=false;$('learning-status').setAttribute('state','error');$('learning-status').textContent=error.status===403?'학습 작업 권한이 거부되었습니다. 접근 권한을 확인한 뒤 최신 결과 확인을 누르세요.':error.status>=500?'학습 작업 서비스를 사용할 수 없습니다. 서비스가 복구되면 최신 결과 확인을 누르세요.':'작업 결과를 확인할 수 없습니다. 연결을 확인한 뒤 최신 결과 확인을 누르세요.';$('review-counts').textContent='검수 상태 확인 불가';$('pixel-counts').textContent='검수 상태 확인 불가';$('review-stage-summary').textContent='등록·승인 상태 확인 불가';$('training-data-state').textContent='학습 데이터 수용 여부 확인 불가';$('preparation-status').textContent='상태 확인 불가';$('empty-title').textContent='작업 결과를 확인할 수 없습니다';$('empty-description').textContent='최신 결과 확인으로 다시 시도하세요.';$('updated').textContent='';}
function updateReadAge(){
  if(!checkedAt)return;
  const minutes=Math.floor(Math.max(0,Date.now()-checkedAt)/60000);
  const age=minutes===0?'방금':minutes<60?`${minutes}분 전`:`${Math.floor(minutes/60)}시간 전`;
  for(const node of document.querySelectorAll('[data-report-age]'))node.textContent=`결과 파일 ${age} 확인 · 최신 결과 확인으로 다시 읽기`;
}
setInterval(updateReadAge,30000);
function fileHint() {
  const kind=workspace.workflows.find(row=>row.id===$('kind').value);
  $('expected-files').textContent=`지원 결과 파일: ${kind.files.join(', ')} 중 하나 이상`;
}
function summary(item) {
  const reports=item.reports.filter(row=>row.status!=='missing');
  if(!reports.length) return {label:'파일 확인 필요',attention:true};
  if(reports.some(row=>row.status==='invalid')) return {label:'읽기 실패',attention:true};
  if(reports.some(row=>row.declared?.verdict==='HOLD'||row.declared?.promotion?.startsWith('HOLD'))) return {label:'적용 보류',attention:true};
  if(item.path!==workspace.control?.out_path&&reports.some(row=>row.status==='changed')&&!reports.some(row=>row.declared?.status==='held')) return {label:'결과 변경',attention:true};
  if(reports.some(row=>['reject','rejected','failed'].includes(row.declared?.verdict)||['failed','rejected'].includes(row.declared?.outcome)||['failed','rejected'].includes(row.declared?.status)||row.steps?.some(step=>['failed','rejected'].includes(step.status)))) return {label:'실패·거절 확인',attention:true};
  if(reports.some(row=>row.declared?.status==='held')) return {label:states.held,attention:true};
  const status=reports.flatMap(row=>[row.declared?.outcome,row.declared?.status,row.declared?.verdict]).find(value=>states[value]);
  return {label:states[status]||'보고서 확인',attention:false};
}
function saveFilters() {
  const url=new URL(location.href);
  for(const [id,key] of [['search','q'],['kind-filter','kind'],['state-filter','state']]) {
    const value=$(id).value;if(value&&value!=='all') url.searchParams.set(key,value);else url.searchParams.delete(key);
  }
  history.replaceState(null,'',url);
}
function render() {
  if(!workspace) return;
  const query=$('search').value.trim().toLocaleLowerCase();
  const filtered=workspace.items.filter(row=> {
    const kind=workspace.workflows.find(kind=>kind.id===row.kind);
    return ($('kind-filter').value==='all'||row.kind===$('kind-filter').value)
      &&($('state-filter').value==='all'||summary(row).attention)
      &&(!query||`${row.name} ${kind.name}`.toLocaleLowerCase().includes(query));
  }).sort((a,b)=>Number(summary(b).attention)-Number(summary(a).attention));
  const attention=workspace.items.filter(row=>summary(row).attention).length;
  $('learning-status').setAttribute('state',attention?'warning':workspace.items.length?'ready':'empty');
  $('learning-status').textContent=`연결 ${workspace.items.length}개 · 확인 필요 ${attention}개 · 보고서 상태를 확인합니다.`;
  $('jobs').replaceChildren();$('jobs').hidden=!filtered.length;$('empty-jobs').hidden=!!filtered.length;
  const active=query||$('kind-filter').value!=='all'||$('state-filter').value!=='all';
  $('work-filters').hidden=workspace.items.length<=1&&!active;
  $('updated').textContent=`${new Date(checkedAt).toLocaleString('ko-KR')} 확인 · ${active ? `${workspace.items.length}개 중 ${filtered.length}개 표시` : `${filtered.length}개 작업`}`;
  $('empty-title').textContent=active?'조건에 맞는 결과가 없습니다':'아직 실행 결과가 없습니다';
  $('empty-description').textContent=active?'검색어나 필터를 바꿔 다시 확인하세요.':'자료 검수를 마치면 현재 작업에서 학습을 이어갈 수 있습니다.';
  $('empty-data-link').hidden=!!active;
  $('reset-filters').hidden=!active;
  for(const item of filtered) {
    const status=summary(item),kind=workspace.workflows.find(row=>row.id===item.kind);
    const candidate=item.reports.some(row=>row.declared?.schema==='rosy.pidnet-candidate-evaluation/1');
    const card=taskRow({title:item.name,subtitle:kind.name,status:status.label,attention:status.attention,
      description:candidate?'독립 시험 결과를 확인하세요. 로봇 적용은 별도 검증이 필요합니다.':nextActions[item.kind]||item.next});
    card.dataset.job=item.id;
    text(card,'p','','ui-task-meta').dataset.reportAge='';
    for(const report of item.reports) {
      if(report.metrics?.length) {
        const group=text(card,'div','','job-metrics');group.setAttribute('aria-label','평가 지표');
        for(const metric of report.metrics) {
          const value=text(group,'div','','job-metric');
          text(value,'strong',`${Number(metric.value).toLocaleString('ko-KR',{maximumFractionDigits:4})}${metric.unit||''}`);
          text(value,'span',metric.label);
        }
      }
      if(report.images?.length) {
        const group=text(card,'div','','job-images');
        for(const image of report.images) {
          const link=text(group,'a',`결과 JPG 열기 · ${image.name}`,'workspace-link');
          link.href=`/api/learning/images/${encodeURIComponent(item.id)}/${encodeURIComponent(image.name)}`;
          link.target='_blank';link.rel='noopener';
        }
      }
    }
    for(const reason of new Set(item.reports.flatMap(report=>report.reasons||[]))) text(card,'p',reasons[reason]||reason,'job-reason');
    for(const report of item.reports) {
      for(const step of report.steps||[]) if(step.error) text(card,'p',`${step.name}: ${step.error}`,'job-reason');
      if(report.error) text(card,'p',report.error,'job-reason');
    }
    const details=text(card,'details','');text(details,'summary','단계·결과 파일 및 연결 관리');
    for(const report of item.reports) {
      if(report.status==='missing'&&item.reports.some(row=>row.status!=='missing')) continue;
      text(details,'p',`${report.name} · ${labels[report.status]}`);
      for(const step of report.steps||[]) text(details,'p',`${step.name}: ${states[step.status]||step.status}${step.error?' · '+step.error:''}`);
    }
    text(details,'pre',JSON.stringify({path:item.path,version:item.version,reports:item.reports},null,2));
    text(details,'p','현재 파일을 읽은 결과입니다. 원본 검증·학습 수용·정책 승격은 해당 도구와 담당자가 확인합니다.');
    const remove=text(details,'ui-button','이 작업 연결 해제');remove.setAttribute('kind','quiet');
    remove.onclick=async()=> {
      if(busy) return;setBusy(true);message('learning-error','');
      try {await request('/api/learning/remove',{id:item.id,version:item.version});await load();message('notice','연결을 해제했습니다. 원래 결과 파일은 유지됩니다.');}
      catch(error) {if(error.status===403)$('learning-status').scrollIntoView({block:'center'});else if(workspace)message('learning-error',`${readableError(error)} · 최신 결과 확인 후 다시 시도하세요.`);}
      finally {setBusy(false);}
    };
    $('jobs').append(card);
  }
  updateReadAge();setBusy(busy);saveFilters();
}
async function load() {
  ++readSequence;
  workspace=undefined;setBusy(true);$('learning-status').setAttribute('state','pending');$('learning-status').textContent='작업 결과를 확인하는 중입니다.';$('review-counts').textContent='불러오는 중';$('pixel-counts').textContent='불러오는 중';$('review-stage-summary').textContent='등록·승인 상태를 확인하는 중입니다.';$('training-data-state').textContent='학습 데이터 수용 여부를 확인하는 중입니다.';$('jobs').replaceChildren();$('jobs').hidden=true;$('empty-jobs').hidden=true;$('updated').textContent='';
  $('pipeline').setAttribute('aria-busy','true');$('pipeline-stages').replaceChildren();$('pipeline-records').replaceChildren();$('pipeline-status').textContent='현재 자료와 학습 결과를 연결하는 중입니다.';
  const started=performance.now();const timer=setInterval(()=>{const seconds=Math.floor((performance.now()-started)/1000);if(seconds>=3)$('learning-status').textContent=`서버 응답 대기 ${seconds}초 · 현재 작업과 보고서 상태를 확인하고 있습니다.`;},1000);
  try {workspace=await request('/api/learning');checkedAt=Date.now();
  renderReview();renderPipeline();
  if(!$('kind').options.length) {
    for(const row of workspace.workflows) {
      text($('capabilities'),'h3',row.name);text($('capabilities'),'p',row.support);text($('capabilities'),'p',row.next);
      if(row.files) for(const select of [$('kind'),$('kind-filter')]) {const option=text(select,'option',row.name);option.value=row.id;}
    }
    $('kind').value='perception';fileHint();
    const params=new URLSearchParams(location.search);
    $('search').value=params.get('q')||'';
    for(const [id,key] of [['kind-filter','kind'],['state-filter','state']]) {$(id).value=params.get(key)||'all';if(!$(id).value) $(id).value='all';}
  }
  render();
  await loadStorage(request);
  } catch(error) {showUnavailable(error);throw error;} finally {clearInterval(timer);setBusy(false);}
}
function renderReview() {
  const {approved,pending,excluded}=workspace.counts;
  const total=approved+pending+excluded;
  $('work-summary').textContent=total?`자료 ${total}장 · 픽셀 검수 대기 ${workspace.pixel_counts.pending}장 · 승인 ${workspace.pixel_counts.approved}장`:'';
  $('work-preview').hidden=!total;
  if(total) {
    const frame=workspace.pixel_draft_first??workspace.object_draft_first??0;
    const preview=$('work-preview-image'),src=`/api/images/${frame}`;
    if(preview.getAttribute('src')!==src)preview.src=src;
  }
  $('review-stage-summary').textContent=`등록 ${total}장 · 객체 승인 ${approved}장 · 픽셀 승인 ${workspace.pixel_counts.approved}장`;
  $('training-data-state').textContent=workspace.pixel_counts.approved===0?'현재 검수분의 픽셀 승인 0장 · 픽셀 학습 데이터 입력 전입니다.':'승인 자료 준비 후 세션 분리·고정 평가 제외·최신 결정 대조를 거쳐야 학습 데이터로 수용됩니다.';
  if(workspace.source_video_unverified>0)$('training-data-state').textContent+=` 원본 영상 ${workspace.source_video_unverified}장의 출처 검증이 필요합니다.`;
  const prepared=workspace.preparation;
  if(workspace.pipeline?.dataset)$('training-data-state').textContent='현재 검수 자료가 데이터셋에 연결됐습니다. 학습·평가 상태는 위 흐름에서 확인하세요.';
  $('preparation-status').textContent=prepared?.pixel_frames===0
    ? '최신 준비본 · 픽셀 승인 0장 · 학습 입력 없음. 승인된 픽셀 검수가 필요합니다.'
    : prepared
    ? `${prepared.current_decisions_match?'최신 준비본':'이전 준비본'} · 객체 ${prepared.object_frames}장 · 픽셀 ${prepared.pixel_frames}장 · ${prepared.current_decisions_match?'현재 결정 일치':'현재 결정과 다름 · 다시 준비 필요'}${workspace.pipeline?.dataset?'':'. 학습 수용은 별도 검증 대기입니다.'}`
    : '준비본 없음 · 승인 자료 준비를 실행하세요. 학습 수용은 별도 검증 대기입니다.';
  $('review-counts').textContent=`검수 대기 ${pending}장 · 객체 초안 ${workspace.object_drafts}장 · 승인 ${approved}장`;
  $('pixel-counts').textContent=`승인 ${workspace.pixel_counts.approved}장 · 검수 대기 ${workspace.pixel_counts.pending}장 · 선택 가능한 초안 ${workspace.pixel_counts.candidates}장 · 라벨이 있는 대기 자료 ${workspace.pixel_counts.drafted}장`;
  $('object-review-link').href=workspace.object_draft_first==null?'/?filter=pending':`/?filter=pending&frame=${workspace.object_draft_first}`;
  $('pixel-review-link').href=workspace.pixel_draft_first==null?'/pixels?filter=pending':`/pixels?filter=pending&frame=${workspace.pixel_draft_first}`;
  ($('object-review-link').querySelector('span')||$('object-review-link')).textContent=workspace.object_draft_first==null?'객체 검수 열기':'객체 초안 확인';
  ($('pixel-review-link').querySelector('span')||$('pixel-review-link')).textContent=workspace.pixel_draft_first==null?'픽셀 검수 열기':'픽셀 초안 확인';
}
async function register(event) {
  event.preventDefault();if(busy||!workspace||!$('register').reportValidity()) return;setBusy(true);message('learning-error','');
  try {
    await request('/api/learning/register',{kind:$('kind').value,name:$('name').value,path:$('path').value});
    $('search').value='';$('kind-filter').value='all';$('state-filter').value='all';
    await load();message('notice','작업 연결을 저장했습니다. 학습 실행과 승인 상태는 바뀌지 않습니다.');
    $('name').value='';$('path').value='';$('connection-panel').open=false;$('job-heading').tabIndex=-1;$('job-heading').focus();
  } catch(error) {if(error.status===403){message('learning-error',error.message);$('learning-error').scrollIntoView({block:'center'});}else if(workspace)message('learning-error',`${readableError(error)} · 작업 종류와 결과 폴더를 확인하세요.`);} finally {setBusy(false);}
}
$('register').onsubmit=register;$('connect').onclick=register;
$('new-task').onclick=()=> {if(!workspace)return;$('connection-panel').open=true;$('name').focus();};
$('kind').onchange=fileHint;
for(const id of ['search','kind-filter','state-filter']) $(id).addEventListener(id==='search'?'input':'change',render);
$('reset-filters').onclick=()=> {$('search').value='';$('kind-filter').value='all';$('state-filter').value='all';render();$('search').focus();};
$('refresh').onclick=()=> {if(busy) return;message('learning-error','');load().catch(()=>{});};
for(const action of ['start','stop','retry'])$(`owner-control-${action}`).onclick=()=>controlAction(action);
$('pipeline-action').onclick=()=> {
  const action=workspace?.pipeline?.next?.action;
  if(action==='prepare')prepareCurrent();
  else if(action==='refresh')$('refresh').click();
  else if(['start','retry'].includes(action))controlAction(action);
};
$('pipeline-link').addEventListener('click',()=> {
  const target=$('pipeline-link').getAttribute('href');
  if(!target)return;
  const hash=new URL(target,location.href).hash;
  if(hash==='#pipeline-setup'){$('training-controls').open=true;$('pipeline-setup').open=true;}
  if(hash==='#pipeline-evidence')$('pipeline-evidence').open=true;
});
$('work-preview-image').addEventListener('error',()=>{$('work-preview').hidden=true;});
load().catch(()=>{});
