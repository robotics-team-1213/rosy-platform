import {accountFetch} from '/account-session.js';
import '/commands.js';
const $=id=>document.getElementById(id);
let token='', manager=false, busy=false, configured=false, running=false, twoArmRunning=false, selected=null, bestId=null;
const STATUS={passed:'✓ 통과',failed:'✕ 실패',blocked:'⊘ 막힘',not_run:'– 실행 안 함',pending:'… 대기',running:'▶ 실행 중',unknown:'? 알 수 없음'};
const STAGE={mujoco:'MuJoCo',gazebo:'Gazebo',isaac:'Isaac'};
const COMPARE={better:'더 좋음 (평가 구간이 겹치지 않고 위쪽)',worse:'더 나쁨 (평가 구간이 겹치지 않고 아래쪽)',
  unclear:'차이 불명확 — 아직 정할 수 없습니다',current:'현재 비교 기준입니다'};
const TWO_ARM={stack:'3×3×3 적층',rehandle:'임시 칸 재취급'};
const TWO_ARM_STAGE={collect:'시연 수집',train:'학습',evaluate:'평가'};
const COMPARE_SCENARIO={stack:'컨베이어에서 장치(9개)',outbound:'재취급을 동반한 반출(2건)'};
const COMPARE_MODE={'one-arm-A':'한 팔 A','one-arm-B':'한 팔 B','two-arm':'두 팔 동시'};
const HOLD_REASON={NO_STAND_IN_REACH:'반출대로 옮길 팔 없음',NO_TEMPORARY_SPACE_IN_REACH:'임시 자리에 닿는 팔 없음',NO_ARM_FOR_RESTORE:'되돌릴 팔 없음',NO_FREE_STAND:'반출대가 비지 않음'};
const TWO_ARM_VIEW={'top.png':'위쪽 D435','side.png':'옆 Jieli','a_wrist.png':'손목 arm_a','b_wrist.png':'손목 arm_b'};
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
  $('ladder-two-arm-start').disabled=busy||!manager||!configured||twoArmRunning;
  $('ladder-compare-start').disabled=busy||!manager||!configured||twoArmRunning;
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
function pairedLine(row){
  const here=row.stages.mujoco.eval?.strict?.placed;
  return el('p',`이전 라운드와 같은 위치 비교: ${here ?? '?'} 대 ${row.paired.placed ?? '?'} / ${row.paired.n ?? '?'} — ${COMPARE[row.paired.result]}`);
}
function twoArmCard(row){
  const item=el('article',undefined,'ladder-card');
  if(row.unreadable){item.append(el('h3',row.run_id),el('p','이 실행 기록을 읽을 수 없습니다.'));return item;}
  const line=el('div',undefined,'ladder-stage');line.dataset.status=row.status;line.append(el('span',STATUS[row.status]||STATUS.unknown));
  item.append(el('h3',`${TWO_ARM[row.task]||row.task} · 시드 ${row.seed ?? '?'}`),el('p',row.created_at||'시각 기록 없음','quiet'),line);
  if(row.steps!=null)item.append(el('p',`단계 통과 ${row.steps_pass ?? '?'} / ${row.steps} · 최종 위치 ${row.final_ok ?? '?'} / ${row.final_total ?? '?'}`));
  if(row.reason)item.append(el('p','이유: '+row.reason));
  for(const step of row.failed_steps)item.append(el('p',`실패 ${step.step} (${step.arm}): ${step.reason||step.result}`));
  if(row.roll_below_floor_steps.length)item.append(el('p','실물 손목 하한 아래로 가는 단계(실물에서 그대로 실행할 수 없음): '+row.roll_below_floor_steps.join(', ')));
  if(row.views.length){
    const gallery=el('div',undefined,'omx-review-gallery');
    for(const name of row.views){
      const fig=el('figure'),img=el('img'),label=TWO_ARM_VIEW[name]||name;
      img.loading='lazy';img.alt=`마지막 장면 · ${label}`;img.src=`/api/learning/ladder/two-arm/${row.run_id}/artifacts/${name}`;
      fig.append(img,el('figcaption',label));gallery.append(fig);
    }
    item.append(gallery);
  }
  return item;
}
function compareCard(row){
  const item=el('article',undefined,'ladder-card');
  if(row.unreadable){item.append(el('h3',row.run_id),el('p','이 비교 기록을 읽을 수 없습니다.'));return item;}
  const line=el('div',undefined,'ladder-stage');line.dataset.status=row.status;line.append(el('span',STATUS[row.status]||STATUS.unknown));
  item.append(el('h3',`한 팔·두 팔 비교 · 시드 ${row.seed ?? '?'}`),el('p',row.created_at||'시각 기록 없음','quiet'),line);
  if(row.reason)item.append(el('p','이유: '+row.reason));
  for(const scenario of Object.keys(COMPARE_SCENARIO)){
    const runs=row.runs.filter(run=>run.scenario===scenario);
    if(!runs.length)continue;
    item.append(el('h4',COMPARE_SCENARIO[scenario]));
    const scroll=el('div',undefined,'ui-table-scroll'),table=el('table',undefined,'ui-data-table'),head=el('tr'),body=el('tbody');
    scroll.tabIndex=0;table.setAttribute('aria-label',`${COMPARE_SCENARIO[scenario]} 모드별 결과`);
    for(const name of ['모드','결과','보류(사람·추가 이송)','걸린 시간','겹쳐 움직인 시간','팔별 이동'])head.append(el('th',name));
    table.append(el('thead'),body);table.tHead.append(head);
    for(const run of runs){
      const tr=el('tr');
      const result=run.steps==null?(run.reason||'결과 없음'):`단계 ${run.steps_pass ?? '?'} / ${run.steps}${run.completed?' 완료':' 멈춤'}`;
      const holds=run.holds.length?run.holds.map(h=>`${h.request}: ${HOLD_REASON[h.reason]||h.reason}`).join(', '):'없음';
      const time=run.makespan_s==null?'—':`${run.makespan_s}초 (계획 ${run.planned_makespan_s ?? '?'}초)`;
      const moves=Object.entries(run.moves_per_arm||{}).map(([arm,n])=>`${arm} ${n}`).join(' · ')||'—';
      for(const text of [COMPARE_MODE[run.mode]||run.mode,result,holds,time,run.concurrent?`${run.overlap_s ?? '?'}초`:'—',moves])tr.append(el('td',text));
      body.append(tr);
    }
    scroll.append(table);item.append(scroll);
    for(const run of runs.filter(run=>run.video)){
      const fig=el('figure'),video=el('video');
      video.controls=true;video.preload='none';video.src=`/api/learning/ladder/two-arm-compare/${row.run_id}/artifacts/${run.video}`;
      video.setAttribute('aria-label',`${COMPARE_SCENARIO[scenario]} ${COMPARE_MODE[run.mode]||run.mode} 영상`);
      fig.append(video,el('figcaption',`${COMPARE_MODE[run.mode]||run.mode} · 네 카메라`));item.append(fig);
    }
  }
  return item;
}
function twoArmRoundCard(row){
  const item=el('article',undefined,'ladder-card');
  if(row.unreadable){item.append(el('h3',row.round_id),el('p','이 라운드 기록을 읽을 수 없습니다.'));return item;}
  const line=el('div',undefined,'ladder-stage');line.dataset.status=row.status;line.append(el('span',STATUS[row.status]||STATUS.unknown));
  item.append(el('h3',`학습 모델 · ${row.round_id}`),el('p',row.created_at||'시각 기록 없음','quiet'),line);
  if(row.status==='running')item.append(el('p',`진행 중: ${TWO_ARM_STAGE[row.stage]||row.stage}`));
  if(row.reason)item.append(el('p','이유: '+row.reason));
  if(row.data.episodes!=null)item.append(el('p',`시연 ${row.data.episodes}단계 · ${row.data.frames}프레임 · 학습 ${row.recipe.steps}스텝`));
  const score=row.eval;
  if(score){
    item.append(el('p',`단계별 통과 ${score.passed ?? '?'} / ${score.n ?? '?'} (95% 구간 ${score.wilson_low ?? '?'}~${score.wilson_high ?? '?'}) · 컨테이너를 든 단계 ${score.lifted ?? '?'}`));
    for(const run of score.whole)item.append(el('p',`${TWO_ARM[run.task]||run.task} 전체 · 시드 ${run.seed}: ${run.passed} / ${run.total} 단계${run.completed?' 완료':'에서 멈춤'}`));
    const zero=Object.entries(score.per_step).filter(([,count])=>count===0).map(([key])=>key);
    if(zero.length)item.append(el('p','한 번도 통과하지 못한 단계: '+zero.join(', ')));
  }
  for(const name of row.videos){
    const fig=el('figure'),video=el('video');
    video.controls=true;video.preload='none';video.src=`/api/learning/ladder/two-arm-rounds/${row.round_id}/artifacts/${name}`;video.setAttribute('aria-label',`학습 모델 실행 영상 ${name}`);
    fig.append(video,el('figcaption',`네 카메라 ${name}`));item.append(fig);
  }
  return item;
}
async function refreshTwoArm(){
  const compared=await api('two-arm-compare');
  const compareBox=$('ladder-compare');
  if(compared.runs?.length)compareBox.replaceChildren(...compared.runs.map(compareCard));
  else compareBox.textContent=configured?'아직 한 팔·두 팔 비교 기록이 없습니다.':'학습 사다리가 연결되지 않았습니다.';
  const learned=await api('two-arm-rounds');
  $('ladder-two-arm-rounds').replaceChildren(...(learned.rounds||[]).map(twoArmRoundCard));
  const data=await api('two-arm');
  twoArmRunning=!!data.running;
  const box=$('ladder-two-arm');
  if(data.runs?.length)box.replaceChildren(...data.runs.map(twoArmCard));
  else box.textContent=configured?'아직 양팔 태스크 실행 기록이 없습니다.':'학습 사다리가 연결되지 않았습니다.';
  controls();
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
  if(row.paired)item.append(pairedLine(row));
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
    ...(round.paired?[pairedLine(round)]:[]),
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
$('ladder-refresh').addEventListener('click',()=>work(async()=>{await refresh();await refreshTwoArm();}));
$('ladder-two-arm-form').addEventListener('submit',event=>{
  event.preventDefault();
  work(async()=>{
    await api('two-arm',{task:$('ladder-two-arm-task').value,seed:Number($('ladder-two-arm-seed').value)});
    await refreshTwoArm();
    notice('ladder-notice','양팔 태스크를 시작했습니다. 몇 분 뒤 새로고침하면 결과를 볼 수 있습니다.');
  });
});
$('ladder-compare-form').addEventListener('submit',event=>{
  event.preventDefault();
  work(async()=>{
    await api('two-arm-compare',{seed:Number($('ladder-compare-seed').value)});
    await refreshTwoArm();
    notice('ladder-notice','한 팔·두 팔 비교를 시작했습니다. 여섯 번을 돌리므로 수십 분 뒤 새로고침하면 결과를 볼 수 있습니다.');
  });
});
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
    await refresh();
    notice('ladder-notice','라운드를 시작했습니다. 새로고침하면 진행을 볼 수 있습니다.');
  });
});
work(async()=>{
  const session=await accountFetch('/api/accounts/session',{cache:'no-store'});
  if(session.ok){const account=await session.json();token=account.token;manager=account.capabilities.includes('manage');}
  await refresh();await refreshTwoArm();
  const wanted=new URLSearchParams(location.search).get('round');
  if(/^[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$/.test(wanted||''))await show(wanted);
});
