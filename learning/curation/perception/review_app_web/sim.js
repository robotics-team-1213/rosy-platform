import {accountFetch} from '/account-session.js';
import '/commands.js';
const $=id=>document.getElementById(id);
let token='', manager=false, busy=false, source='', checked=null, selected=null, pending=null;
const terminal=new Set(['SUCCEEDED','FAILED','STOPPED']);
const labels={PENDING:'준비 중',RUNNING:'실행 중',STOP_REQUESTED:'종료 확인 중',UNKNOWN:'확인 필요',SUCCEEDED:'모델 검사 통과',FAILED:'실패',STOPPED:'중단'};
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
  $('sim-artifacts').replaceChildren();
  for(const file of row.artifacts?.files||[]){
    if(file.id!=='import-report')continue;
    const link=document.createElement('a');link.textContent='모델 검사 보고서 열기';
    link.href=`/api/learning/sim/runs/${row.run_id}/artifacts/${file.id}`;$('sim-artifacts').append(link);
  }
  controls();
}
async function refresh(){
  const data=await api('runs');$('sim-runs').replaceChildren();
  for(const row of data.runs){
    const button=document.createElement('button');button.type='button';button.className='ui-field';
    button.textContent=`${labels[row.status]||row.status} · ${row.run_id.slice(0,12)}`;
    button.addEventListener('click',()=>work(async()=>detail(await api('runs/'+row.run_id))));
    $('sim-runs').append(button);
    if(selected?.run_id===row.run_id)detail(row);
  }
  if(!data.runs.length)$('sim-runs').textContent='아직 실행 기록이 없습니다.';
}
async function check(){
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
$('theme').value=window.RosyTheme.get();$('theme').addEventListener('change',()=>window.RosyTheme.set($('theme').value));
$('sim-check').addEventListener('click',()=>work(check));
$('sim-start').addEventListener('click',()=>work(()=>start()));
$('sim-refresh').addEventListener('click',()=>work(refresh));
$('sim-stop').addEventListener('click',()=>work(async()=>{detail(await api('stop',{run_id:selected.run_id,expected_revision:selected.revision}));await refresh();}));
$('sim-replay').addEventListener('click',()=>work(async()=>{
  const parent=selected.run_id;$('sim-seed').value=selected.input.config.seed;pending=null;
  await check();await start(parent);
}));
work(async()=>{
  const session=await accountFetch('/api/accounts/session',{cache:'no-store'});
  if(session.ok){const account=await session.json();token=account.token;manager=account.capabilities.includes('manage');}
  const data=await api('catalog');source=data.source_sha;$('sim-source').textContent='실행 소스: '+source;
  for(const entry of data.scenarios){
    const option=document.createElement('option');option.value=entry.id;option.textContent=entry.name||entry.id;option.disabled=!entry.implemented;
    $('sim-scenario').append(option);
    const item=document.createElement('li');item.textContent=(entry.name||entry.id)+' · '+(entry.reason||'조건 확인 필요');$('sim-prerequisites').append(item);
  }
  const saved=sessionStorage.getItem('rosy.sim.pending.'+source);
  if(saved){pending=JSON.parse(saved);$('sim-seed').value=pending.config.seed;notice('sim-checked','이전 요청이 보존되었습니다. 조건 확인 후 같은 요청을 재전송할 수 있습니다.');}
  await refresh();notice('sim-notice',manager?'조건을 확인한 뒤 실험을 시작하세요.':'조회 화면입니다. 실행·중지는 프로젝트 관리 권한이 필요합니다.');
});
