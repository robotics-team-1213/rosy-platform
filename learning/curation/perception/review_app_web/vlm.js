import {accountFetch} from '/account-session.js';
import '/common/ui.js';
const $=id=>document.getElementById(id);
$('theme').value=document.documentElement.dataset.theme||'dark';$('theme').onchange=()=>{document.documentElement.dataset.theme=$('theme').value;try{localStorage.setItem('rosy.theme',$('theme').value);}catch{}document.dispatchEvent(new CustomEvent('rosy:theme'));};
const API='/api/learning/vlm/';
let token='', editor=true, manager=true, busy=false, list=[], current=null, choices={}, focus=0, imageReady=false, summary=null, revising=false;
const KINDS={eval:'평가셋',disputed:'의견 갈림',audit:'점검'};
// D-857 §5: an audit shows the model consensus with 맞음/고침; 고침 reveals the normal options.
const auditing=()=>current?.kind==='audit'&&!revising;
function notice(id,value){$(id).textContent=value;$(id).hidden=!value;}
async function api(path,body){
  const response=await accountFetch(API+path,body===undefined?{cache:'no-store'}:
    {method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':token},body:JSON.stringify(body)});
  const value=await response.json();
  if(!response.ok)throw new Error(value.error||'VLM 판단 연결을 확인하세요.');
  return value;
}
async function work(operation){
  if(busy)return;
  busy=true;controls();notice('vlm-error','');
  try{await operation();}catch(error){notice('vlm-error',error.message);}
  finally{busy=false;controls();}
}
function complete(){return current&&current.questions.every(q=>choices[q.id]!=null);}
function controls(){
  const position=current?list.findIndex(row=>row.id===current.id):-1;
  $('vlm-confirm').hidden=$('vlm-fix').hidden=!auditing();$('vlm-save').hidden=auditing();
  $('vlm-confirm').disabled=busy||!editor||!imageReady||!complete();$('vlm-fix').disabled=busy||!editor;
  $('vlm-save').disabled=busy||!editor||!imageReady||!complete();
  $('vlm-save').setAttribute('reason',!editor?'정답 편집 권한이 필요합니다.':!complete()?'모든 질문에 답하세요.':'');
  $('vlm-exclude').disabled=busy||!editor||!current;
  $('vlm-prev').disabled=busy||position<=0;
  $('vlm-next').disabled=busy||!list.length||position>=list.length-1;
  $('vlm-next-pending').disabled=busy;
  for(const button of $('vlm-questions').querySelectorAll('ui-button'))button.disabled=busy||!editor;
  $('vlm-import').disabled=busy||!manager;
}
function progress(){
  const done=summary?Object.values(summary.views).reduce((sum,v)=>sum+v.labelled+v.excluded,0):0;
  const position=current?list.findIndex(row=>row.id===current.id)+1:0;
  $('vlm-progress').textContent=`완료 ${done} / ${summary?.total??0} · 목록 ${position} / ${list.length}`;
}
function renderQuestions(){
  const box=$('vlm-questions');box.replaceChildren();
  current.questions.forEach((question,index)=>{
    const block=document.createElement('div');block.className='vlm-question';block.dataset.focus=String(index===focus);
    const title=document.createElement('p');const head=document.createElement('b');head.textContent=`질문 ${index+1} `;
    const english=document.createElement('span');english.className='vlm-en';english.lang='en';english.textContent=question.text;
    title.id=`vlm-q-${index}`;title.append(head,english);
    if(auditing()){
      const shown=document.createElement('p');shown.className='vlm-provisional';shown.textContent=`임시 정답 ${current.provisional[question.id]}`;
      block.append(title,shown);box.append(block);return;
    }
    const options=document.createElement('div');options.className='vlm-options';options.setAttribute('role','group');
    options.setAttribute('aria-labelledby',title.id);
    question.options.forEach((option,number)=>{
      const button=document.createElement('ui-button');button.setAttribute('kind','toggle');
      button.setAttribute('aria-pressed',String(choices[question.id]===option));button.dataset.option=option;
      button.setAttribute('aria-keyshortcuts',String(number+1));
      const name=document.createElement('span');name.textContent=option;
      const key=document.createElement('small');key.textContent=`키 ${number+1}`;key.setAttribute('aria-hidden','true');
      button.append(name,key);
      button.addEventListener('click',()=>pick(index,option));
      options.append(button);
    });
    block.append(title,options);box.append(block);
  });
}
function pick(index,option){
  if(busy||!editor||!current||auditing())return;
  focus=index;choices[current.questions[index].id]=option;
  notice('vlm-save-status','저장 전 · 바뀐 답이 있습니다.');renderQuestions();controls();
}
async function open(id){
  current=await api('items/'+id);revising=false;choices={...(current.kind==='audit'?current.provisional:current.answers)};focus=0;imageReady=false;
  $('vlm-audit-note').hidden=current.kind!=='audit';
  const image=$('vlm-image');image.hidden=false;
  notice('vlm-image-message','사진을 불러오는 중입니다.');
  image.onload=()=>{imageReady=true;notice('vlm-image-message','');controls();};
  image.onerror=()=>{imageReady=false;notice('vlm-image-message','사진을 확인할 수 없습니다. 원본이 바뀌었을 수 있습니다.');controls();};
  image.src=`${API}images/${current.id}`;
  if(image.complete&&image.naturalWidth){imageReady=true;notice('vlm-image-message','');}  // same photo reopened: no new load event
  $('vlm-name').textContent=`${current.view} · ${current.image_name} · ${KINDS[current.kind]||{pending:'대기',labelled:'정답 있음',excluded:'제외'}[current.status]}`;
  notice('vlm-save-status',current.version?`서버 저장됨 · v${current.version}${current.actor?' · '+current.actor:''}`:'아직 정답이 없습니다.');
  renderQuestions();progress();
}
function showQueue(queue){
  const total=kind=>Object.values(queue.counts).reduce((sum,row)=>sum+row[kind],0);
  $('vlm-queue').textContent=`평가셋 ${total('eval_done')}/${total('eval_size')} · 의견 갈림 ${total('disputed')}${total('disputed_waiting')?` (대기 ${total('disputed_waiting')})`:''} · 점검 ${total('audit')} · 의견 갈림·점검은 보기당 최대 ${queue.cap}건`;
  $('vlm-paused').textContent=queue.paused.length?`점검 오류가 많아 임시 정답을 멈춘 질문: ${queue.paused.join(', ')}`:'';
  $('vlm-paused').hidden=!queue.paused.length;
}
async function load(after){
  summary=await api('summary');token=summary.token;
  const view=$('vlm-view').value,kind=$('vlm-kind').value;
  const queue=await api('queue?'+new URLSearchParams({view}));showQueue(queue);
  // Only the queue is labelled; provisional photos outside it are not shown (D-857 §5).
  list=kind==='labelled'?(await api('items?'+new URLSearchParams({view,status:'labelled'}))).items:queue.items.filter(row=>!kind||row.kind===kind);
  const next=list.find(row=>after!=null&&row.id>after)||list[0];
  if(next)await open(next.id);
  else{current=null;$('vlm-audit-note').hidden=true;$('vlm-questions').replaceChildren();$('vlm-image').hidden=true;$('vlm-name').textContent='';
    notice('vlm-image-message',summary.total?'이 조건의 사진이 없습니다.':'사진이 없습니다. 가져오기에서 벤치 결과를 등록하세요.');progress();}
}
async function save(status){
  const saved=current.id;
  try{await api('items/'+saved,{version:current.version,status,answers:choices});}
  catch(error){notice('vlm-save-status','저장되지 않았습니다.');throw error;}
  await load(saved);
  if(current&&current.id!==saved)notice('vlm-save-status',`앞 사진 저장됨 · ${status==='labelled'?'정답':'제외'}`);
}
function fix(){
  if(!auditing()||busy||!editor)return;
  revising=true;renderQuestions();controls();notice('vlm-save-status','고칠 답을 고른 뒤 저장하세요. 저장하면 확정 정답이 됩니다.');
}
function move(step){
  const position=list.findIndex(row=>row.id===current?.id)+step;
  if(list[position])work(()=>open(list[position].id));
}
function table(head,rows){
  const element=document.createElement('table');const top=element.createTHead().insertRow();
  for(const name of head){const cell=document.createElement('th');cell.textContent=name;top.append(cell);}
  const body=element.createTBody();
  for(const row of rows){const line=body.insertRow();for(const value of row){const cell=line.insertCell();cell.append(value);}}
  return element;
}
const percent=value=>value==null?'—':`${(value*100).toFixed(1)}%`;
async function evaluate(){
  const data=await api('evaluation');const box=$('vlm-eval');box.replaceChildren();$('vlm-confusion').hidden=true;
  const count=document.createElement('p');count.textContent=`정답 있는 사진 ${data.labelled}장 기준`;box.append(count);
  const tiers=document.createElement('h2');tiers.textContent='임시 정답 범위(대기 사진)';box.append(tiers);
  box.append(table(['질문','대기','임시 정답','토론으로 합의','범위'],data.provisional.map(row=>[row.question,String(row.pending),String(row.provisional),String(row.debate),percent(row.coverage)])));
  const audit=document.createElement('h2');audit.textContent='임시 정답 점검';box.append(audit);
  if(data.audits.length)box.append(table(['질문','점검','틀림','오류율','상태'],data.audits.map(row=>[row.question,String(row.n),String(row.errors),percent(row.rate),row.paused?'멈춤':'사용'])));
  else{const none=document.createElement('p');none.textContent='아직 점검한 임시 정답이 없습니다.';box.append(none);}
  const caption=document.createElement('h2');caption.textContent='사람 정답의 unclear 비율';box.append(caption);
  box.append(table(['질문','n','unclear'],data.human.map(row=>[row.question,String(row.n),percent(row.unclear_rate)])));
  for(const model of data.models){
    const title=document.createElement('h2');title.textContent=`${model.model} · ${model.runtime} · 모순 답(물체 쥠=yes·빈 집게=yes) ${model.contradictions}장`;
    box.append(title,table(['질문','n','일치율','balanced accuracy','혼동표'],model.questions.map(row=>{
      const button=document.createElement('ui-button');button.setAttribute('kind','quiet');button.textContent='보기';
      button.addEventListener('click',()=>{
        const width=Math.max(8,...row.options.map(o=>o.length+2));
        const lines=[`${model.model} · ${model.runtime} · ${row.question} (행: 사람, 열: 모델)`,
          ''.padEnd(width)+row.options.map(o=>o.padEnd(width)).join(''),
          ...row.options.map(h=>h.padEnd(width)+row.options.map(m=>String(row.confusion[h][m]).padEnd(width)).join(''))];
        if(row.missing)lines.push(`모델 답 없음 ${row.missing}`);
        $('vlm-confusion').textContent=lines.join('\n');$('vlm-confusion').hidden=false;
      });
      return [row.question,String(row.n),percent(row.agreement),percent(row.balanced_accuracy),button];
    })));
  }
  if(!data.models.length){const empty=document.createElement('p');empty.textContent='비교할 모델 답이 없거나 정답 있는 사진이 없습니다.';box.append(empty);}
}
async function exportLabels(){
  const data=await api('export');
  const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([data.jsonl],{type:'application/jsonl'}));
  link.download=`vlm-labels-${data.sha256.slice(0,12)}.jsonl`;link.click();URL.revokeObjectURL(link.href);
  notice('vlm-export-status',`${data.count}줄 · sha256 ${data.sha256}`);
}
async function importRows(){
  const file=$('vlm-questions-file').files[0];
  if(!file)throw new Error('질문 파일을 고르세요.');
  const dumped=JSON.parse(await file.text());
  const result=await api('import',{rows_path:$('vlm-rows').value.trim(),model:$('vlm-model').value.trim(),
    question_set:dumped.question_set,questions:dumped.questions});
  notice('vlm-import-status',`새 사진 ${result.items_added} · 기존 사진 ${result.items_existing} · 새 모델 답 ${result.answers_added} · rows sha256 ${result.rows_sha256}`);
  const views=new Set([...$('vlm-view').options].map(o=>o.value));
  await load(null);
  for(const view of Object.keys(summary.views))if(!views.has(view))$('vlm-view').append(new Option(view,view));
}
function tab(name){
  for(const button of document.querySelectorAll('.vlm-tabs ui-button'))button.setAttribute('aria-pressed',String(button.dataset.tab===name));
  for(const key of ['label','eval','import'])$('panel-'+key).hidden=key!==name;
  if(name==='eval')work(evaluate);
}
for(const button of document.querySelectorAll('.vlm-tabs ui-button'))button.addEventListener('click',()=>tab(button.dataset.tab));
$('vlm-prev').addEventListener('click',()=>move(-1));
$('vlm-next').addEventListener('click',()=>move(1));
$('vlm-next-pending').addEventListener('click',()=>work(async()=>{const after=current?.id??null;$('vlm-kind').value='';await load(after);}));
$('vlm-save').addEventListener('click',()=>work(()=>save('labelled')));
$('vlm-confirm').addEventListener('click',()=>work(()=>save('labelled')));
$('vlm-fix').addEventListener('click',fix);
$('vlm-exclude').addEventListener('click',()=>work(()=>save('excluded')));
$('vlm-view').addEventListener('change',()=>work(()=>load(null)));
$('vlm-kind').addEventListener('change',()=>work(()=>load(null)));
$('vlm-help-open').addEventListener('click',()=>{$('vlm-help').hidden=!$('vlm-help').hidden;});
$('vlm-eval-refresh').addEventListener('click',()=>work(evaluate));
$('vlm-export').addEventListener('click',()=>work(exportLabels));
$('vlm-import').addEventListener('click',()=>work(importRows));
document.addEventListener('keydown',event=>{
  // D-538 §5: no shortcuts while typing, composing or holding Ctrl/Alt/Meta.
  if(event.isComposing||event.keyCode===229||event.ctrlKey||event.altKey||event.metaKey)return;
  if(event.target.closest?.('input, select, textarea, [contenteditable="true"], dialog'))return;
  if(event.key==='?'){event.preventDefault();$('vlm-help').hidden=!$('vlm-help').hidden;return;}
  if($('panel-label').hidden||!current&&event.code!=='KeyN')return;
  const digit=/^(?:Digit|Numpad)([1-9])$/.exec(event.code);
  if(event.key==='ArrowLeft')move(-1);
  else if(event.key==='ArrowRight')move(1);
  else if(event.code==='KeyN')$('vlm-next-pending').click();
  else if(auditing()&&(event.code==='KeyA'||event.key==='Enter')&&!event.target.closest?.('ui-button, a, button')){if(!$('vlm-confirm').disabled)$('vlm-confirm').click();}
  else if(auditing()&&event.code==='KeyE')fix();
  else if(event.key==='ArrowUp'||event.key==='ArrowDown'){
    focus=Math.max(0,Math.min(current.questions.length-1,focus+(event.key==='ArrowUp'?-1:1)));renderQuestions();controls();
  }else if(digit){const option=current.questions[focus].options[Number(digit[1])-1];if(option)pick(focus,option);}
  else if(event.key==='Enter'&&!event.target.closest?.('ui-button, a, button')){if(!$('vlm-save').disabled)$('vlm-save').click();}
  else return;
  event.preventDefault();
});
work(async()=>{
  const session=await accountFetch('/api/accounts/session',{cache:'no-store'});
  // Collaboration refuses server-path imports (as /api/import); managers use the CLI on the server.
  const account=await session.json();  // read the local-mode 404 too; an unread body stays an open request
  if(session.ok){editor=account.capabilities.includes('edit');manager=false;}
  $('tab-import').hidden=!manager;
  await load(null);
  if(location.hash==='#eval')tab('eval');  // the 평가·승격 page links here
  for(const view of Object.keys(summary.views).sort())$('vlm-view').append(new Option(view,view));
  if(!editor)notice('vlm-save-status','조회 화면입니다. 정답 저장은 편집 권한이 필요합니다.');
});
