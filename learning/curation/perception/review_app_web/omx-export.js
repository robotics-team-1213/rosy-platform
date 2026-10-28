// Conversion progress belongs beside its source selection, before learning starts.
let lastRuns;
const stopStates=new Map();
export function renderExportRuns(container,runs,options){
  const encoded=JSON.stringify(runs);if(encoded===lastRuns)return;lastRuns=encoded;
  const active=document.activeElement,row=active?.closest('[data-export-run]');
  const focused=container.contains(row)?row.dataset.exportRun:null,action=active?.dataset.exportAction;
  const nodes=runs.map(run=>renderExportRun(run,options));
  for(const id of stopStates.keys())if(!runs.some(run=>run.id===id))stopStates.delete(id);
  if(!nodes.length){const empty=document.createElement('p');empty.className='quiet';empty.textContent='변환 기록이 없습니다. 검수할 시연과 프로필을 선택하세요.';nodes.push(empty);}
  container.replaceChildren(...nodes);
  if(focused){
    const replacement=[...container.children].find(node=>node.dataset.exportRun===focused);
    const control=replacement&&[...replacement.querySelectorAll('[data-export-action]')].find(node=>node.dataset.exportAction===action);
    (control||replacement?.querySelector('h3')||container).focus({preventScroll:true});
  }
}
function renderExportRun(run,{states,request,refresh,selectDataset}){
  const el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;};
  const section=el('section');section.className='learning-section';section.dataset.exportRun=run.id;
  const heading=el('h3',`시연 → ACT 데이터 변환 · ${states[run.status]||run.status}`);heading.tabIndex=-1;section.append(heading);
  section.append(el('p',`${run.name} · 작업 ${run.id} · 준비 자료 ${run.prepared_id}`));
  const phase={verifying:'시연 자료 검증 중',exporting:'데이터 변환 중',completed:'데이터 등록 완료'};
  section.append(el('p',phase[run.progress?.phase]||'변환 상태 확인 중'));
  if(run.error)section.append(el('p',typeof run.error==='string'?run.error:JSON.stringify(run.error)));
  if(run.status==='succeeded'&&run.result){
    const {dataset_id:id,dataset_revision:revision}=run.result;
    section.append(el('p',`데이터 ${id} · revision ${revision}`));
    section.append(el('p',run.result.act_only?'ACT 전용 데이터 · 정책 학습은 별도로 시작하세요.':'정책 학습은 별도로 시작하세요.'));
    const actions=el('div');actions.className='learning-next-actions';
    const learn=el('a','이 데이터로 학습 준비');learn.dataset.exportAction='learn';learn.className='workspace-link';learn.href='#train-section';learn.onclick=()=>selectDataset(id);
    const archive=el('a','이 데이터 HF 보관 준비');archive.dataset.exportAction='archive';archive.className='workspace-link';
    archive.href=`/learning?archive=omx&dataset=${encodeURIComponent(id)}&revision=${encodeURIComponent(revision)}#storage-preparation`;
    actions.append(learn,archive);section.append(actions);
    section.append(el('p','HF 보관은 파일 사본과 바이트를 검증합니다. LeRobot 형식 게시·reader 검증과 학습·현장 수용은 별도입니다.'));
  }
  if(['queued','running'].includes(run.status)){
    const stop=el('ui-button','이 변환 중지');stop.dataset.exportAction='stop';stop.type='button';stop.setAttribute('kind','quiet');
    const status=el('p');status.setAttribute('role','alert');
    const operation=stopStates.get(run.id)||{pending:false,error:''};stopStates.set(run.id,operation);
    operation.render=()=>{stop.disabled=operation.pending;status.textContent=operation.error;};operation.render();
    stop.onclick=async()=>{
      if(operation.pending)return;operation.pending=true;operation.error='';operation.render();
      try{await request('/api/learning/omx/center/stop',{id:run.id});await refresh();}
      catch(error){operation.error=error.message;}
      finally{operation.pending=false;operation.render();}
    };
    section.append(stop,status);
  }
  return section;
}
