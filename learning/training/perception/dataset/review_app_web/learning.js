import '/common/ui.js';
const $=id=>document.getElementById(id);
let workspace, busy=false;
const labels={unchanged:'등록한 파일과 일치',changed:'등록 후 변경됨',missing:'파일 없음',invalid:'읽기 실패'};
const states={running:'진행 중',reading:'자료 읽는 중',training:'학습 중',failed:'실패',rejected:'품질 거절',reject:'품질 거절',
  ready:'자료 준비 완료',done:'완료',pass:'보고서 통과',research_only:'연구 결과',research_exported:'연구 결과 저장됨',
  offline_only:'오프라인 평가 결과',not_eligible:'승격 대상 아님'};
function text(parent,tag,value,cls) {
  const node=document.createElement(tag);node.textContent=value;
  if(cls) node.className=cls;parent.append(node);return node;
}
function setBusy(value) {
  busy=value;
  for(const button of document.querySelectorAll('ui-button')) {
    button.reason=value?'결과를 확인하는 중입니다':'';button.disabled=value;
  }
}
async function request(path,body) {
  const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':workspace.token},body:JSON.stringify(body)}:{});
  const value=await response.json();if(!response.ok) throw new Error(value.error||'요청 실패');return value;
}
function fileHint() {
  const kind=workspace.workflows.find(row=>row.id===$('kind').value);
  $('expected-files').textContent=`지원 결과 파일: ${kind.files.join(', ')} 중 하나 이상`;
}
function render() {
  const filtered=workspace.items.filter(row=>$('kind-filter').value==='all'||row.kind===$('kind-filter').value);
  $('jobs').replaceChildren();
  if(!filtered.length) text($('jobs'),'p','연결한 작업이 없습니다. 위에서 기존 결과 폴더를 연결하세요.','quiet');
  for(const item of filtered) {
    const card=text($('jobs'),'article','', 'learning-job');card.dataset.job=item.id;
    text(card,'h3',item.name);
    text(card,'p',workspace.workflows.find(row=>row.id===item.kind).name);
    for(const report of item.reports) {
      if(report.status==='missing' && item.reports.some(r=>r.status!=='missing')) continue;
      text(card,'p',`${report.name} · ${labels[report.status]}`);
      if(report.declared) {
        const values=Object.entries(report.declared).filter(([key])=>!['schema','revision'].includes(key)).map(([,value])=>states[value]||value);
        if(values.length) text(card,'p',`보고서 상태: ${values.join(' · ')}`,'quiet');
      }
      for(const step of report.steps||[]) text(card,'p',`${step.name}: ${states[step.status]||step.status}${step.error?' · '+step.error:''}`);
      for(const reason of report.reasons||[]) text(card,'p',reason);
      if(report.error) text(card,'p',report.error);
    }
    text(card,'p',item.next);
    const details=text(card,'details','');text(details,'summary','결과 파일 상세');
    text(details,'pre',JSON.stringify({path:item.path,version:item.version,reports:item.reports},null,2));
    text(details,'p','현재 파일을 읽은 결과입니다. 원본 검증·학습 수용·정책 승격 상태는 해당 도구와 담당자가 확인합니다.');
    const remove=text(card,'ui-button','연결 해제');remove.setAttribute('kind','quiet');
    remove.onclick=async()=> {
      if(busy) return;
      setBusy(true);$('learning-error').textContent='';
      try {await request('/api/learning/remove',{id:item.id,version:item.version});await load();$('notice').textContent='연결을 해제했습니다. 원래 결과 파일은 유지됩니다.';}
      catch(error) {$('learning-error').textContent=error.message;}
      finally {setBusy(false);}
    };
  }
  setBusy(busy);
}
async function load() {
  workspace=await request('/api/learning');
  const {approved,pending,excluded}=workspace.counts;
  $('review-counts').textContent=`승인 ${approved}장 · 검수 대기 ${pending}장 · 제외 ${excluded}장`;
  if(!$('kind').options.length) {
    for(const row of workspace.workflows) {
      text($('capabilities'),'h3',row.name);text($('capabilities'),'p',row.support);text($('capabilities'),'p',row.next);
      if(row.files) for(const select of [$('kind'),$('kind-filter')]) {
        const option=text(select,'option',row.name);option.value=row.id;
      }
    }
    fileHint();
  }
  $('updated').textContent=`확인 시각 ${new Date().toLocaleString('ko-KR')} · 보고서 선언과 파일 변경 여부를 표시합니다.`;
  render();
}
async function register(event) {
  event.preventDefault();if(busy||!$('register').reportValidity()) return;
  setBusy(true);$('learning-error').textContent='';
  try {
    await request('/api/learning/register',{kind:$('kind').value,name:$('name').value,path:$('path').value});
    await load();$('notice').textContent='연결을 저장했습니다. 학습 작업을 시작하지 않습니다.';
    $('name').value='';$('path').value='';
  } catch(error) {$('learning-error').textContent=error.message;} finally {setBusy(false);}
}
$('register').onsubmit=register;$('connect').onclick=register;
$('kind').onchange=fileHint;$('kind-filter').onchange=render;
$('refresh').onclick=async()=> {if(busy) return;setBusy(true);$('learning-error').textContent='';try {await load();}catch(error){$('learning-error').textContent=error.message;}finally{setBusy(false);}};
$('theme').value=document.documentElement.dataset.theme||'dark';
$('theme').onchange=()=> {document.documentElement.dataset.theme=$('theme').value;try{localStorage.setItem('rosy.theme',$('theme').value);}catch{} document.dispatchEvent(new CustomEvent('rosy:theme'));};
load().catch(error=>$('learning-error').textContent=error.message);
