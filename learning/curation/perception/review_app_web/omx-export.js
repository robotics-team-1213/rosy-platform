// Conversion progress belongs beside its source selection, before learning starts.
export function renderExportRun(run,{states,request,refresh,selectDataset}){
  const el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;};
  const section=el('section');section.className='learning-section';
  section.append(el('h3',`시연 → ACT 데이터 변환 · ${states[run.status]||run.status}`));
  section.append(el('p',`${run.name} · 작업 ${run.id} · 준비 자료 ${run.prepared_id}`));
  const phase={verifying:'시연 자료 검증 중',exporting:'데이터 변환 중',completed:'데이터 등록 완료'};
  section.append(el('p',phase[run.progress?.phase]||'변환 상태 확인 중'));
  if(run.error)section.append(el('p',typeof run.error==='string'?run.error:JSON.stringify(run.error)));
  if(run.status==='succeeded'&&run.result){
    const {dataset_id:id,dataset_revision:revision}=run.result;
    section.append(el('p',`데이터 ${id} · revision ${revision}`));
    section.append(el('p',run.result.act_only?'ACT 전용 데이터 · 정책 학습은 별도로 시작하세요.':'정책 학습은 별도로 시작하세요.'));
    const actions=el('div');actions.className='learning-next-actions';
    const learn=el('a','이 데이터로 학습 준비');learn.className='workspace-link';learn.href='#train-section';learn.onclick=()=>selectDataset(id);
    const archive=el('a','이 데이터 HF 보관 준비');archive.className='workspace-link';
    archive.href=`/learning?archive=omx&dataset=${encodeURIComponent(id)}&revision=${encodeURIComponent(revision)}#storage-preparation`;
    actions.append(learn,archive);section.append(actions);
    section.append(el('p','HF 보관은 파일 사본과 바이트를 검증합니다. LeRobot 형식 게시·reader 검증과 학습·현장 수용은 별도입니다.'));
  }
  if(['queued','running'].includes(run.status)){
    const stop=el('ui-button','이 변환 중지');stop.type='button';stop.setAttribute('kind','quiet');
    const status=el('p');status.setAttribute('role','alert');
    stop.onclick=async()=>{stop.disabled=true;try{await request('/api/learning/omx/center/stop',{id:run.id});await refresh();}catch(error){status.textContent=error.message;stop.disabled=false;}};
    section.append(stop,status);
  }
  return section;
}
