// D-943 §4: preview a finished model's files, then upload them with the project's HF connection.
const $=id=>document.getElementById(id);
const STATE={prepared:'미리보기 완료 · 업로드 전',uploading:'업로드 중',uploaded:'업로드 완료',failed:'업로드 실패'};
let request,uuid,pending=null,busy=false;
function el(tag,text){const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;}
export function initHub(options){
  ({request,uuid}=options);
  $('hub-form').oninput=()=>{pending=null;};
  $('hub-form').onsubmit=async event=>{
    event.preventDefault();if(busy)return;busy=true;$('hub-preview').disabled=true;$('hub-status').textContent='묶음을 만드는 중입니다.';
    pending??={run_id:$('hub-run').value,repo_id:$('hub-repo').value.trim(),request_id:uuid()};
    try{await request('/api/learning/omx/center/hub-prepare',pending);pending=null;$('hub-status').textContent='미리보기를 만들었습니다. 파일을 확인한 뒤 업로드하세요.';await refreshHub();}
    catch(exc){$('hub-status').textContent=`미리보기 실패: ${exc.message}`;}
    finally{busy=false;$('hub-preview').disabled=false;}
  };
  loadConnections();
}
async function loadConnections(){
  let connections=[];
  try{connections=(await request('/api/accounts/session')).connections||[];}catch{}
  const usable=connections.filter(item=>(item.scopes||[]).includes('write-repos'));
  $('hub-connection').replaceChildren(...(usable.length?usable.map(item=>{const option=el('option',`${item.username} · ${item.sharing==='project'?'팀 공유':'개인'}`);option.value=item.connection_id;return option;})
    :[el('option','쓰기 권한(write-repos)이 있는 HF 연결이 없습니다')]));
  $('hub-connection').disabled=!usable.length;
}
export function updateHubRuns(runs){
  const done=runs.filter(run=>run.status==='succeeded'&&run.execution_mode!=='native_export'),chosen=$('hub-run').value;
  $('hub-run').replaceChildren(...(done.length?done.map(run=>{const option=el('option',`${run.method==='act'?'ACT':'SAC'} · ${run.id.slice(0,8)} · 데이터 ${run.dataset_id.slice(0,8)}`);option.value=run.id;return option;})
    :[el('option','끝난 학습 결과가 없습니다')]));
  if(done.some(run=>run.id===chosen))$('hub-run').value=chosen;
  $('hub-preview').disabled=busy||!done.length;
  refreshHub();
}
async function refreshHub(){
  let bundles=[];
  try{bundles=(await request('/api/learning/omx/center/hub')).bundles;}catch(exc){$('hub-bundles').replaceChildren(el('p',`업로드 기록을 읽지 못했습니다: ${exc.message}`));return;}
  $('hub-bundles').replaceChildren(...(bundles.length?bundles.map(renderBundle):[el('p','미리보기한 묶음이 없습니다.')]));
}
function renderBundle(bundle){
  const section=el('section');section.className='learning-section';
  section.append(el('h3',`${bundle.repo_id} · ${STATE[bundle.state]||bundle.state}`),el('p',`학습 결과 ${bundle.run_id}`));
  const details=el('details');details.append(el('summary',`올릴 파일 ${Object.keys(bundle.files).length}개와 SHA-256`),el('pre',Object.entries(bundle.files).map(([name,sha])=>`${name}  ${sha}`).join('\n')));section.append(details);
  if(bundle.error)section.append(el('p',`실패 사유: ${bundle.error}`));
  if(bundle.receipt)section.append(el('p',`커밋 ${bundle.receipt.revision} · 다시 내려받아 해시 일치 확인됨`));
  if(['prepared','failed'].includes(bundle.state)){
    const upload=el('ui-button','이 파일들을 HF에 업로드');upload.type='button';upload.setAttribute('kind','quiet');upload.disabled=$('hub-connection').disabled;
    upload.onclick=async()=>{upload.disabled=true;
      try{await request('/api/learning/omx/center/hub-upload',{bundle_id:bundle.bundle_id,connection_id:$('hub-connection').value});await refreshHub();}
      catch(exc){section.append(el('p',`업로드 요청 실패: ${exc.message}`));upload.disabled=false;}};
    section.append(upload);
  }
  if(bundle.state==='uploading')setTimeout(refreshHub,3000);
  return section;
}
