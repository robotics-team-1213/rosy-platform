import {accountFetch} from '/account-session.js';
import '/common/ui.js';
import {taskRow} from '/common/workspace.js';
import '/commands.js';
const $ = id => document.getElementById(id);
let token, session, active = false, pending = false;
const states = {queued:'대기',running:'가져오는 중',completed:'가져옴 · 검수 대기',failed:'실패',
  interrupted:'중단됨',cancelled:'취소됨',rights_hold:'이용 권한 확인 필요',blocked:'접근 차단'};
const failures = {insufficient_space:'저장 공간이 부족합니다. 여유 공간을 확보한 뒤 재시도하세요.',
  storage_unavailable:'저장 공간을 확인할 수 없습니다. 저장소 연결을 확인하세요.',
  verification_failed:'파일 크기 또는 해시가 일치하지 않습니다. 같은 버전으로 다시 받으세요.',
  access_revoked:'계정 접근 권한이 철회됐습니다.', worker_interrupted:'실행기가 중단됐습니다. 같은 버전으로 재시도하세요.',
  import_failed:'가져오기에 실패했습니다. 연결과 자료 접근을 확인한 뒤 재시도하세요.'};
const size = n=>`${Number(n || 0).toLocaleString('ko-KR')} bytes`;
const scopeLabel={'read-repos':'읽기','gated-repos':'제한 자료 읽기','write-repos':'쓰기','manage-repos':'저장소 생성·삭제'};
function error(message) { $('account-error').textContent=message || ''; $('account-error').hidden=!message; }
function status(text, state) {
  $('account-status').textContent=text; $('account-status').setAttribute('state',state);
}
function empty(parent, text) {
  const node=document.createElement('ui-empty'); node.textContent=text; parent.append(node);
}
function signedOut() {
  token=null; session=null; active=false;
  $('login-panel').hidden=false; $('signed-in').hidden=true;
  status('프로젝트에 로그인하세요.', 'empty');
  for(const id of ['identity','connections','connection','imports','repos','repo-connection']) $(id).replaceChildren();
  for(const id of ['login-form','connect-form','import-form','repo-list-form','repo-create-form','repo-delete-form']) $(id).reset();
}
async function api(path, body) {
  const response=await accountFetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',
    headers:body===undefined?{}:{'Content-Type':'application/json','X-Pinky-Token':token || ''},
    body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();
  if (!response.ok) {
    if(response.status===401) signedOut();
    throw Object.assign(new Error(data.error || '요청을 처리하지 못했습니다.'), {status:response.status});
  }
  return data;
}
function line(parent,text) { const p=document.createElement('p'); p.textContent=text; parent.append(p); return p; }
function button(parent,label,action) {
  const b=document.createElement('ui-button'); b.setAttribute('kind','quiet'); b.textContent=label;
  b.addEventListener('click',()=>perform(action)); parent.append(b);
}
async function perform(action) {
  if(pending)return;
  pending=true; error('');
  $('accounts-main').setAttribute('aria-busy','true');
  try { await action(); } catch(e) { error(e.message); }
  finally { pending=false; $('accounts-main').setAttribute('aria-busy','false'); }
}
async function refresh() {
  const options=await api('/api/accounts/options');
  $('hf-login').hidden=!options.oauth;
  if(options.rosy_account) $('hf-login').hidden=true;
  if(!options.enabled) {
    signedOut();
    status('협업 계정이 설정되지 않았습니다. 관리자에게 프로젝트 설정을 요청하세요.', 'unavailable');
    $('login-panel').hidden=$('signed-in').hidden=true; active=false; return;
  }
  try { session=await api('/api/accounts/session'); }
  catch(e) {
    if (e.status !== 401 && e.status !== 403) {
      throw e;
    }
    if(options.rosy_account) {
      $('login-panel').hidden=true; $('signed-in').hidden=true;
      status('Rosy Account로 연결 중…', 'pending');
      window.location.assign('/api/account/login?return=/accounts'); return;
    }
    token=null; active=false; $('login-panel').hidden=false; $('signed-in').hidden=true;
    status('프로젝트에 로그인하세요.', 'empty'); return;
  }
  token=session.token; active=true; $('login-panel').hidden=true; $('signed-in').hidden=false;
  status('로그인됨', 'ready');
  $('identity').textContent=`프로젝트 ${session.project_id} · 작업자 ${session.user_id} · 권한 ${session.capabilities.join(', ')}`;
  const canPublish=session.capabilities.includes('publish');
  $('import-panel').hidden=!session.capabilities.includes('import');
  $('connect-panel').hidden=!session.capabilities.includes('import');
  $('hf-link').hidden=!options.oauth || !session.capabilities.includes('import');
  $('repo-panel').hidden=!canPublish;
  $('hf-manage').hidden=!options.oauth || !canPublish;
  $('sharing').querySelector('[value=project]').disabled=!session.capabilities.includes('manage');
  if(!session.capabilities.includes('manage')) $('sharing').value='personal';
  const list=$('connections'), select=$('connection'), managed=$('repo-connection');
  list.replaceChildren(); select.replaceChildren(); managed.replaceChildren(); $('repos').replaceChildren();
  for(const account of session.connections) {
    const names=(account.scopes||[]).map(scope=>scopeLabel[scope]).filter(Boolean);
    const row=taskRow({title:account.username || account.subject,
      status:account.sharing==='project'?'프로젝트 연결':'개인 연결',
      subtitle:names.length?names.join(' · '):'기록된 저장소 권한 없음'}); list.append(row);
    if(account.sharing==='project' ? session.capabilities.includes('manage') : account.owner_id===session.user_id) button(row,'연결 해제',async()=>{
      if(!confirm('연결을 해제하면 이 계정을 사용하는 새 가져오기가 중단됩니다. 해제할까요?'))return;
      await api('/api/accounts/disconnect',{connection_id:account.connection_id}); await refresh();
    });
    const option=document.createElement('option'); option.value=account.connection_id;
    option.textContent=account.username || account.subject; select.append(option);
    managed.append(option.cloneNode(true));
  }
  if(!session.connections.length) empty(list,'연결된 계정이 없습니다. 외부 자료를 가져오려면 계정을 연결하세요.');
  await jobs();
}
async function jobs() {
  if(!active)return;
  const identity=session;
  const result=await api('/api/learning/imports'), root=$('imports');
  if(!active||session!==identity)return;
  const opened=new Set([...root.querySelectorAll('details[open]')].map(node=>node.dataset.job));
  const focused=document.activeElement, focusId=focused.closest('article')?.dataset.job;
  const focusText=root.contains(focused)?focused.textContent:null;
  root.replaceChildren();
  if(!result.jobs.length) empty(root,'가져오기 작업이 없습니다. 위에서 계정과 자료를 선택해 등록하세요.');
  for(const job of result.jobs) {
    const row=taskRow({title:job.repo_id, status:states[job.status] || job.status,
      attention:['failed','interrupted','rights_hold','blocked'].includes(job.status),
      subtitle:`버전 ${job.revision} · 요청자 ${job.requester_id || job.requester || ''}`});
    row.dataset.job=job.id; root.append(row);
    if(job.error) line(row,job.error==='gated_team_use_evidence_required'?'팀 이용 허가 근거가 필요합니다. 확인 후 새 가져오기를 등록하세요.':failures[job.error] || job.error);
    const files=job.files || [], received=f=>f.downloaded_bytes ?? (job.status==='completed'?f.bytes:0);
    line(row,`진행 ${size(files.reduce((n,f)=>n+received(f),0))} / ${size(files.reduce((n,f)=>n+f.bytes,0))} · 받은 양은 검수 완료와 별개입니다.`);
    const details=document.createElement('details'), summary=document.createElement('summary');
    details.dataset.job=job.id;details.open=opened.has(job.id);
    summary.textContent=`파일별 진행 ${files.length}개`;details.append(summary);row.append(details);
    for(const file of files)line(details,`${file.path} · ${size(received(file))} / ${size(file.bytes)} · ${file.sha256?'해시 검증 완료':'검증 대기'}`);
    if(job.reason) line(row,job.reason);
    if(job.status==='completed') line(row,'원본 검증·라벨 검수 후 학습 자료로 준비하세요.');
    const canControl=session.capabilities.includes('import') && job.requester_id===session.user_id;
    if(canControl && ['failed','interrupted','queued','cancelled','blocked'].includes(job.status)) button(row,'같은 버전 재시도',async()=>{
      await api('/api/learning/imports/retry',{id:job.id}); await jobs();
    });
    if(canControl && ['queued','running'].includes(job.status)) button(row,'가져오기 취소',async()=>{
      await api('/api/learning/imports/cancel',{id:job.id}); await jobs();
    });
    if(focusId===job.id) [...row.querySelectorAll('ui-button, summary')].find(node=>node.textContent===focusText)?.focus({preventScroll:true});
  }
}
$('login-form').addEventListener('submit',event=>{event.preventDefault();perform(async()=>{
  const password=$('password').value; $('password').value='';
  await api('/api/accounts/login',{username:$('username').value,password}); await refresh();
});});
$('logout').addEventListener('click',()=>perform(async()=>{
  active=false; $('signed-in').hidden=true;
  for(const id of ['connections','imports','connection','repos','repo-connection']) $(id).replaceChildren();
  try { await api('/api/accounts/logout',{}); } finally { signedOut(); }
  await refresh();
}));
for(const [id,purpose] of [['hf-login','login'],['hf-link','link'],['hf-manage','manage']]) $(id).addEventListener('click',()=>perform(async()=>{
  const result=await api('/api/accounts/oauth',{purpose}); window.location.assign(result.url);
}));
$('connect-form').addEventListener('submit',event=>{event.preventDefault();perform(async()=>{
  const secret=$('provider-token').value; $('provider-token').value='';
  await api('/api/accounts/connect',{token:secret,sharing:$('sharing').value,
    resources:$('resources').value.split('\n').map(x=>x.trim()).filter(Boolean)}); await refresh();
});});
$('import-form').addEventListener('submit',event=>{event.preventDefault();perform(async()=>{
  await api('/api/learning/imports/create',{connection_id:$('connection').value,repo_type:$('repo-type').value,
    repo_id:$('repo-id').value.trim(),revision:$('revision').value.trim(),
    files:$('files').value.split('\n').map(x=>x.trim()).filter(Boolean),
    rights:{license:$('license').value.trim(),evidence:$('rights-evidence').value.trim(),internal_use:$('internal-use').checked,
      gated_team_use:$('gated-team-use').checked,team_use_evidence:$('team-use-evidence').value.trim()}});
  await jobs();
});});
function selectedRepo() {
  const repoId=$('manage-repo-id').value.trim();
  if(!repoId) throw new Error('저장소 이름을 입력하세요.');
  return {connection_id:$('repo-connection').value, repo_type:$('manage-repo-type').value, repo_id:repoId};
}
async function loadRepos() {
  if(!$('repo-connection').value) throw new Error('관리 계정을 선택하세요.');
  const query=new URLSearchParams({connection_id:$('repo-connection').value, repo_type:$('manage-repo-type').value});
  const data=await api('/api/accounts/repos?'+query.toString());
  const root=$('repos'); root.replaceChildren();
  if(!data.repos.length){empty(root,'저장소가 없습니다. 아래에서 비공개 저장소를 만들 수 있습니다.');return;}
  for(const repo of data.repos){
    const state=repo.missing?'없음':(repo.private?'비공개':'공개');
    root.append(taskRow({title:repo.repo_id,status:state,subtitle:repo.sha?repo.sha.slice(0,7):'커밋 없음'}));
  }
}
$('repo-list-form').addEventListener('submit',event=>{event.preventDefault();perform(loadRepos);});
$('repo-create-form').addEventListener('submit',event=>{event.preventDefault();perform(async()=>{
  await api('/api/accounts/repos/create',selectedRepo());
  $('manage-repo-id').value='';
  await loadRepos();
});});
$('repo-delete-form').addEventListener('submit',event=>{event.preventDefault();perform(async()=>{
  const repo=selectedRepo();
  if($('repo-confirm').value.trim()!==repo.repo_id) throw new Error('삭제 확인은 저장소 이름과 같아야 합니다.');
  await api('/api/accounts/repos/delete',{...repo, confirm:repo.repo_id});
  $('repo-confirm').value='';
  await loadRepos();
});});
$('reload').addEventListener('click',()=>perform(refresh));
setInterval(()=>{if(active&&!pending&&!document.hidden)perform(jobs);},5000);
perform(refresh);
