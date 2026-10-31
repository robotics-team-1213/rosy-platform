import {accountFetch} from '/account-session.js';
import '/commands.js';
const $=id=>document.getElementById(id);
let token='', manager=false, busy=false, source='', checked=null, selected=null, pending=null;
const terminal=new Set(['SUCCEEDED','FAILED','STOPPED']);
const labels={PENDING:'준비 중',RUNNING:'실행 중',STOP_REQUESTED:'종료 확인 중',UNKNOWN:'확인 필요',SUCCEEDED:'실행 완료',FAILED:'실패',STOPPED:'중단'};
const artifactLabels={'import-report':'모델 검사 보고서 열기','contact-report':'접촉 왕복 보고서 열기',pinky_initial:'Pinky 초기 위치',out_lift:'첫 파지·들기',conveyor_settle:'컨베이어 안착',back_lift:'복귀 파지·들기',pinky_settle:'Pinky 원위치 안착',
  'mapped-stack-report':'적층 보고서 열기','mapped-video':'연속 영상','mapped-overview':'전체','mapped-initial':'처음 배치','mapped-top':'위','mapped-side':'옆','mapped-grasp-failed':'파지 실패 순간'};
const numbered={layer:'번째 놓기 후',trial:'번째 시도 끝',leveling:'번째 고르기'};
const simStatus={reflected:'반영',stand_in:'대용',none:'없음'};
let inventory=null;
function artifactLabel(id){
  const match=/^mapped-(layer|trial|leveling)-([0-9]{1,2})$/.exec(id);
  return match?match[2]+numbered[match[1]]:artifactLabels[id];
}
function el(tag,text){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;}
function notice(id,value){$(id).textContent=value;$(id).hidden=!value;}
async function api(action,body){
  const response=await accountFetch('/api/learning/sim/'+action,body===undefined?{cache:'no-store'}:
    {method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':token},body:JSON.stringify(body)});
  const value=await response.json();
  if(!response.ok)throw new Error(value.error||'실험 연결을 확인하세요.');
  return value;
}
function controls(){
  $('sim-check').disabled=busy||!manager;
  $('sim-start').disabled=busy||!manager||!checked;
  $('sim-stop').disabled=busy||!manager||!selected||terminal.has(selected.status)||selected.status==='PENDING';
  $('sim-replay').disabled=busy||!manager||!selected||!terminal.has(selected.status)||selected.input?.source_sha!==source;
  $('sim-seed').disabled=busy; $('sim-scenario').disabled=busy;
}
async function work(operation){
  if(busy)return;
  busy=true;controls();notice('sim-error','');
  try{await operation();}catch(error){notice('sim-error',error.message);}
  finally{busy=false;controls();}
}
function config(){
  const seed=Number($('sim-seed').value);
  if(!Number.isInteger(seed)||seed<0||seed>2147483647||!$('sim-seed').value)throw new Error('Seed 범위를 확인하세요.');
  return {scenario_id:$('sim-scenario').value,config:{seed}};
}
function invalidate(){checked=null;pending=null;notice('sim-checked','조건을 다시 확인하세요.');controls();}
function detail(row){
  selected=row;
  $('sim-selected').textContent=`${row.run_id} · ${labels[row.status]||row.status} · ${row.input_sha256||'입력 확인 필요'}`;
  $('sim-result').textContent=JSON.stringify(row.result||{status:row.status,error:row.error||null,snapshot:row.snapshot},null,2);
  $('sim-artifacts').replaceChildren();notice('sim-summary','');
  const ids=new Set();
  for(const file of row.artifacts?.files||[]){
    const label=artifactLabel(file.id);
    if(!label)continue;
    ids.add(file.id);
    const href=`/api/learning/sim/runs/${row.run_id}/artifacts/${file.id}`;
    const link=el('a',label);link.href=href;
    const item=el(/report$/.test(file.id)?'p':'figure');
    if(file.id==='mapped-video'){const video=el('video');video.controls=true;video.preload='metadata';video.src=href;video.style.maxWidth='100%';item.append(video);}
    else if(item.tagName==='FIGURE'){const image=el('img');image.loading='lazy';image.alt=label;image.src=href;item.append(image);}
    if(item.tagName==='FIGURE'){const caption=el('figcaption');caption.append(link);item.append(caption);}else item.append(link);
    $('sim-artifacts').append(item);
  }
  if(ids.has('mapped-stack-report'))api('runs/'+row.run_id+'/summary').then(value=>{
    if(selected?.run_id!==row.run_id)return;
    const gaps=value.row_gaps_mm?` · 줄 간격 ${value.row_gaps_mm.join(', ')} mm`:'';
    notice('sim-summary',`놓은 상자 ${value.placed}/${value.planned}${gaps} · 불안정 상자 ${value.unstable.length}개${value.error?' · 멈춘 이유 '+value.error:''}`);
  },error=>notice('sim-summary',error.message));
  compare(row.run_id,ids);
  controls();
}
function compare(runId,ids){
  if(!inventory)return;
  $('sim-compare').replaceChildren();
  for(const photo of inventory.photos){
    const real=el('figure'),image=el('img');image.alt='실물 '+photo.camera;image.src='/api/learning/sim/photos/'+photo.id;
    image.addEventListener('error',()=>image.replaceWith(el('p','실물 사진이 아직 등록되지 않았습니다.')),{once:true});
    real.append(image,el('figcaption',`실물 · ${photo.camera} · ${photo.captured_at}`));
    const sim=el('figure');
    if(runId&&photo.sim_view&&ids.has(photo.sim_view)){
      const view=el('img');view.alt='시뮬레이션 '+artifactLabel(photo.sim_view);
      view.src=`/api/learning/sim/runs/${runId}/artifacts/${photo.sim_view}`;sim.append(view);
    }else sim.append(el('p',runId?'이 실행에는 같은 방향 시뮬레이션 그림이 없습니다.':'실행 기록을 선택하면 같은 방향 시뮬레이션 그림을 놓습니다.'));
    sim.append(el('figcaption','시뮬레이션 · '+(photo.sim_view?artifactLabel(photo.sim_view):'같은 방향 없음')));
    $('sim-compare').append(real,sim);
  }
}
function ledger(value){
  inventory=value;
  const table=el('table'),head=el('tr');
  for(const name of ['항목','CAD 출처','시뮬레이션','잰 값·출처','실물과 다른 점'])head.append(el('th',name));
  const thead=el('thead');thead.append(head);const body=el('tbody');
  for(const model of value.models){
    const tr=el('tr');
    const cad=model.cad.file?model.cad.file+(model.cad.sha256?' · sha256 '+model.cad.sha256.slice(0,12):''):'없음';
    for(const text of [model.name,cad,simStatus[model.sim]||model.sim,model.measured||'—',model.differs||'—'])tr.append(el('td',text));
    body.append(tr);
  }
  table.append(thead,body);const wrap=el('div');wrap.className='omx-table-wrap';wrap.append(table);
  $('sim-inventory').replaceChildren(el('p',`확인 ${value.checked_at}`),wrap);
  $('sim-tasks').replaceChildren(...value.person_tasks.map(task=>el('li',`${task.status==='done'?'완료':'할 일'} · ${task.task} — ${task.why}`)));
  compare(selected?.run_id,new Set((selected?.artifacts?.files||[]).map(file=>file.id)));
}
async function refresh(){
  const data=await api('runs');$('sim-runs').replaceChildren();
  for(const row of data.runs){
    const button=document.createElement('ui-button');button.setAttribute('kind','quiet');
    button.textContent=`${labels[row.status]||row.status} · ${row.run_id.slice(0,12)}`;
    button.addEventListener('click',()=>work(async()=>detail(await api('runs/'+row.run_id))));
    $('sim-runs').append(button);
    if(selected?.run_id===row.run_id)detail(row);
  }
  if(!data.runs.length)$('sim-runs').textContent='아직 실행 기록이 없습니다.';
}
async function check(){
  checked=null;
  const value=await api('check',config());
  if(value.ready!==true)throw new Error(value.reason||'실행 준비가 되지 않았습니다.');
  checked=value;notice('sim-checked','확인한 입력 지문: '+value.input_sha256);
}
async function start(parent){
  if(!checked)throw new Error('조건을 먼저 확인하세요.');
  pending??={...config(),request_id:crypto.randomUUID().replaceAll('-',''),expected_input_sha256:checked.input_sha256};
  if(parent)pending.parent_run_id=parent;
  // Keep the same request after a lost response; a new experiment gets a new ID.
  sessionStorage.setItem('rosy.sim.pending.'+source,JSON.stringify(pending));
  const row=await api('start',pending);detail(row);await refresh();
  notice('sim-notice','같은 요청 재전송은 이 실행을 다시 조회합니다.');
}
$('sim-seed').addEventListener('input',invalidate);$('sim-scenario').addEventListener('change',invalidate);
$('sim-check').addEventListener('click',()=>work(check));
$('sim-start').addEventListener('click',()=>work(()=>start()));
$('sim-refresh').addEventListener('click',()=>work(refresh));
$('sim-stop').addEventListener('click',()=>work(async()=>{detail(await api('stop',{run_id:selected.run_id,expected_revision:selected.revision}));await refresh();}));
$('sim-replay').addEventListener('click',()=>work(async()=>{
  const parent=selected.run_id;$('sim-scenario').value=selected.input.scenario_id;$('sim-seed').value=selected.input.config.seed;pending=null;
  await check();await start(parent);
}));
work(async()=>{
  const session=await accountFetch('/api/accounts/session',{cache:'no-store'});
  if(session.ok){const account=await session.json();token=account.token;manager=account.capabilities.includes('manage');}
  // The ledger is a repository file, so it shows even when the SIM connection is down.
  ledger(await api('inventory'));
  const data=await api('catalog');source=data.source_sha;$('sim-source').textContent='실행 소스: '+source;
  for(const entry of data.scenarios){
    const option=document.createElement('option');option.value=entry.id;option.textContent=entry.name||entry.id;option.disabled=!entry.implemented;
    $('sim-scenario').append(option);
    const item=document.createElement('li');item.textContent=(entry.name||entry.id)+' · '+(entry.reason||'조건 확인 필요');$('sim-prerequisites').append(item);
  }
  const saved=sessionStorage.getItem('rosy.sim.pending.'+source);
  if(saved){pending=JSON.parse(saved);$('sim-seed').value=pending.config.seed;notice('sim-checked','이전 요청이 보존되었습니다. 조건 확인 후 같은 요청을 재전송할 수 있습니다.');}
  await refresh();
  // /learning/sim?run=<id> (home row, 평가·승격 list) opens that run the same way a click does.
  const wanted=new URLSearchParams(location.search).get('run');
  if(/^[0-9a-f]{32}$/.test(wanted||''))detail(await api('runs/'+wanted));
  notice('sim-notice',manager?'조건을 확인한 뒤 실험을 시작하세요.':'조회 화면입니다. 실행·중지는 프로젝트 관리 권한이 필요합니다.');
});
