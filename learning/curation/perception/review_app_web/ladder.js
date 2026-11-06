import {accountFetch} from '/account-session.js';
import '/commands.js';
const $=id=>document.getElementById(id);
let token='', manager=false, busy=false, configured=false, running=false, selected=null, bestId=null;
const STATUS={passed:'✓ 통과',failed:'✕ 실패',blocked:'⊘ 막힘',not_run:'– 실행 안 함',pending:'… 대기',running:'▶ 실행 중',unknown:'? 알 수 없음'};
const STAGE={mujoco:'MuJoCo',gazebo:'Gazebo',isaac:'Isaac'};
const COMPARE={better:'더 좋음 (평가 구간이 겹치지 않고 위쪽)',worse:'더 나쁨 (평가 구간이 겹치지 않고 아래쪽)',
  unclear:'차이 불명확 — 아직 정할 수 없습니다',current:'현재 비교 기준입니다'};
const SCENE={robot:'팔',jaw:'집게',wrist_camera:'손목 카메라',revision:'셀 개정'};
const RECIPE={policy:'정책',steps:'학습 단계',batch_size:'묶음 크기',chunk_size:'청크',n_action_steps:'행동 단계',optimizer_lr:'학습률'};
const DATA={episodes:'에피소드',from_failures:'실패에서 가져온 수'};
function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function notice(id,value){$(id).textContent=value;$(id).hidden=!value;}
function pairs(names,values){const out=Object.keys(names).filter(key=>values?.[key]!=null).map(key=>`${names[key]} ${values[key]}`);return out.length?out.join(' · '):'기록 없음';}
function pct(value){return (value*100).toFixed(1)+'%';}
async function api(path,body){
  const response=await accountFetch('/api/learning/ladder/'+path,body===undefined?{cache:'no-store'}:
    {method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':token},body:JSON.stringify(body)});
  const value=await response.json();
  if(!response.ok)throw new Error(value.error||'사다리 연결을 확인하세요.');
  return value;
}
function controls(){
  const passed=selected?.stages?.mujoco?.status==='passed';
  $('ladder-decide').disabled=busy||!manager||!configured||!passed;
  $('ladder-start').disabled=busy||!manager||!configured||running;
  $('ladder-decide-round').textContent=selected?.round_id||'없음';
  $('ladder-start-state').textContent=!configured?'학습 사다리가 연결되지 않았습니다. 라운드를 시작할 수 없습니다.':
    running?'다른 라운드가 실행 중입니다. 끝난 뒤 시작할 수 있습니다.':
    manager?'값은 서버에서 한 번 더 확인합니다.':'조회 화면입니다. 시작·판단은 프로젝트 관리 권한이 필요합니다.';
}
async function work(operation){
  if(busy)return;
  busy=true;controls();notice('ladder-error','');
  try{await operation();}catch(error){notice('ladder-error',error.message);}
  finally{busy=false;controls();}
}
function stageLine(name,stage){
  const line=el('div',undefined,'ladder-stage');line.dataset.status=stage.status;
  const head=el('div');head.append(el('b',STAGE[name]+' '),el('span',STATUS[stage.status]||STATUS.unknown));line.append(head);
  line.append(el('small','말할 수 있는 범위: '+(stage.claim||'기록 없음')));
  if(stage.status==='blocked'||stage.status==='not_run')line.append(el('small','이유: '+(stage.reason||'이유가 기록되지 않았습니다.')));
  return line;
}
function card(row){
  const item=el('article',undefined,'ladder-card');
  if(row.unreadable){
    item.append(el('h3',row.round_id),el('p','이 라운드 기록을 읽을 수 없습니다. 기록 파일이 깨졌거나 형식이 다릅니다.'));
    return item;
  }
  const open=document.createElement('ui-button');open.setAttribute('kind','quiet');open.textContent=row.round_id;
  open.addEventListener('click',()=>work(()=>show(row.round_id)));
  const h=el('h3');h.append(open);
  item.append(h,el('p',row.created_at||'시각 기록 없음','quiet'),
    el('p','장면: '+pairs(SCENE,row.scene)),el('p','레시피: '+pairs(RECIPE,row.recipe)),el('p','데이터: '+pairs(DATA,row.data)));
  for(const name of Object.keys(STAGE))item.append(stageLine(name,row.stages[name]));
  if(row.comparison)item.append(el('p','기준과 비교: '+COMPARE[row.comparison]));
  if(row.round_id===bestId)item.append(el('p','★ 현재 비교 기준','ladder-best'));
  return item;
}
async function refresh(){
  const data=await api('rounds');
  configured=data.configured;running=data.running;bestId=data.best_round_id;
  $('ladder-rounds').replaceChildren(...data.rounds.map(card));
  const parent=$('ladder-parent'),keep=parent.value;
  parent.replaceChildren(new Option('없음 (처음부터)',''),...data.rounds.filter(row=>!row.unreadable).map(row=>new Option(row.round_id,row.round_id)));
  parent.value=[...parent.options].some(option=>option.value===keep)?keep:'';
  if(!configured){$('ladder-rounds').textContent='학습 사다리가 연결되지 않았습니다.';notice('ladder-notice','학습 사다리가 연결되지 않았습니다. 운영자 설정이 필요합니다.');}
  else if(!data.rounds.length){$('ladder-rounds').textContent='아직 라운드가 없습니다.';notice('ladder-notice',manager?'새 라운드를 시작할 수 있습니다.':'조회 화면입니다.');}
  else notice('ladder-notice',running?'라운드가 실행 중입니다.':manager?'라운드를 고르거나 새로 시작하세요.':'조회 화면입니다.');
  controls();
}
function list(items){const ul=el('ul');for(const text of items)ul.append(el('li',text));return ul;}
function evaluation(stage){
  const ev=stage.eval;
  if(!ev)return el('p','MuJoCo 평가 기록이 없습니다.');
  const strict=ev.strict||{},loose=ev.loose||{};
  const rate=ev.n>0&&strict.placed!=null?` (${pct(strict.placed/ev.n)})`:'';
  const band=strict.wilson_low!=null?` · 95% 신뢰구간 하한 ${pct(strict.wilson_low)}`:'';
  return list([`엄격 성공 ${strict.placed ?? '?'} / ${ev.n ?? '?'}${rate}${band}`,
    `느슨한 성공 ${loose.placed ?? '?'} / ${ev.n ?? '?'}`,`들어올림 ${ev.lifted ?? '?'} / ${ev.n ?? '?'}`,
    `위치 오차 중앙값 ${ev.xy_err_mm_median ?? '?'} mm`,`방향 오차 중앙값 ${ev.yaw_err_deg_median ?? '?'}도`,`평가 시드 시작값 ${ev.seed_base ?? '?'}`]);
}
function images(round){
  const gallery=el('div',undefined,'omx-review-gallery');
  for(const name of Object.keys(STAGE))for(const art of round.stages[name].artifacts){
    const fig=el('figure'),img=el('img');img.loading='lazy';img.alt=`${STAGE[name]} ${art.name||art.path}`;
    img.src=`/api/learning/ladder/rounds/${round.round_id}/${art.path}`;
    fig.append(img,el('figcaption',`${STAGE[name]} · ${art.name||art.path}`));gallery.append(fig);
  }
  return gallery.children.length?gallery:el('p','저장된 그림이 없습니다.','quiet');
}
function detail(data){
  const round=data.round,box=$('ladder-detail');
  selected=round.unreadable?null:round;
  if(round.unreadable){box.replaceChildren(el('p','이 라운드 기록을 읽을 수 없습니다.'));controls();return;}
  const {mujoco,gazebo,isaac}=round.stages;
  const note=el('p','이 화면의 결과는 시뮬레이션 근거입니다. 실제 팔이 성공했다는 뜻이 아닙니다(D-947).','ladder-note');
  const compare=el('p','기준과 비교: '+COMPARE[round.comparison||'unclear']);
  box.replaceChildren(note,el('h3',round.round_id),...Object.keys(STAGE).map(name=>stageLine(name,round.stages[name])),
    el('h3','MuJoCo 평가'),evaluation(mujoco),
    el('h3','현재 기준과 비교'),
    data.best_round_id?compare:el('p','아직 비교 기준이 없습니다. 첫 판단이 기준이 됩니다.'),
    ...(round.same_seeds===false?[el('p','평가 시드가 달라 숫자 비교가 거칠 수 있습니다. 같은 시드로 다시 평가한 값이 필요합니다.','quiet')]:[]),
    el('h3','Gazebo 계약 점검'),
    gazebo.contract?list([`백엔드 ${gazebo.contract.backend ?? '?'} · ${gazebo.contract.passed?'통과':'통과하지 못함'}`,
      ...Object.entries(gazebo.contract.checks||{}).map(([key,value])=>`${key}: ${value}`)]):el('p','계약 점검 기록이 없습니다.'),
    el('h3','Isaac 실행 참조'),
    el('p',isaac.run_id?`실행 ${isaac.run_id} · 결과 ${isaac.result ?? '기록 없음'}`:'연결된 Isaac 실행이 없습니다.'),
    el('h3','그림'),images(round),
    ...(data.decisions.length?[el('h3','이 라운드의 판단 기록'),list(data.decisions.map(row=>
      `${row.at} · ${row.by} · ${row.verdict==='replace'?'기준으로 바꿈':'기준 유지'} · ${row.note}`))]:[]));
  controls();
}
async function show(roundId){detail(await api('rounds/'+roundId));}
$('ladder-refresh').addEventListener('click',()=>work(refresh));
$('ladder-decision').addEventListener('submit',event=>{
  event.preventDefault();
  work(async()=>{
    if(!selected)throw new Error('라운드를 먼저 고르세요.');
    const result=await api('decision',{round_id:selected.round_id,verdict:$('ladder-verdict').value,note:$('ladder-note').value});
    $('ladder-note').value='';
    $('ladder-decided').textContent=`기록했습니다 (${result.verdict==='replace'?'기준으로 바꿈':'기준 유지'}). 현재 비교 기준: ${result.best_round_id||'없음'}`;
    await refresh();await show(selected.round_id);
  });
});
$('ladder-start-form').addEventListener('submit',event=>{
  event.preventDefault();
  work(async()=>{
    await api('start',{episodes:Number($('ladder-episodes').value),eval_episodes:Number($('ladder-eval').value),
      steps:Number($('ladder-steps').value),lr:Number($('ladder-lr').value),parent:$('ladder-parent').value||null});
    notice('ladder-notice','라운드를 시작했습니다. 새로고침하면 진행을 볼 수 있습니다.');
    await refresh();
  });
});
work(async()=>{
  const session=await accountFetch('/api/accounts/session',{cache:'no-store'});
  if(session.ok){const account=await session.json();token=account.token;manager=account.capabilities.includes('manage');}
  await refresh();
  const wanted=new URLSearchParams(location.search).get('round');
  if(/^[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$/.test(wanted||''))await show(wanted);
});
