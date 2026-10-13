import {accountFetch} from '/account-session.js';
import '/common/ui.js';
import '/commands.js';
const $ = id => document.getElementById(id);
let token, active = false, pending = false;
const states = {queued:'대기',running:'가져오는 중',completed:'가져옴 · 검수 대기',failed:'실패',
  interrupted:'중단됨',cancelled:'취소됨',rights_hold:'이용 권한 확인 필요',blocked:'접근 차단'};
function error(message) { $('account-error').textContent=message || ''; $('account-error').hidden=!message; }
async function api(path, body) {
  const response=await accountFetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',
    headers:body===undefined?{}:{'Content-Type':'application/json','X-Pinky-Token':token || ''},
    body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();
  if (!response.ok) {
    const failure = new Error(data.error || '요청을 처리하지 못했습니다.');
    failure.status = response.status; throw failure;
  }
  return data;
}
function line(parent,text) { const p=document.createElement('p'); p.textContent=text; parent.append(p); return p; }
function button(parent,label,action) {
  const b=document.createElement('button'); b.type='button'; b.className='ui-field'; b.textContent=label;
  b.addEventListener('click',()=>perform(action)); parent.append(b);
}
async function perform(action) {
  if(pending)return;
  pending=true; error('');
  try { await action(); } catch(e) { error(e.message); }
  finally { pending=false; }
}
async function refresh() {
  const options=await api('/api/accounts/options');
  $('hf-login').hidden=$('hf-link').hidden=!options.oauth;
  if(options.rosy_account) $('hf-login').hidden=true;
  if(!options.enabled) {
    $('account-status').textContent='협업 계정이 설정되지 않았습니다. 관리자에게 프로젝트 설정을 요청하세요.';
    $('login-panel').hidden=$('signed-in').hidden=true; active=false; return;
  }
  let session;
  try { session=await api('/api/accounts/session'); }
  catch(e) {
    if (e.status !== 401 && e.status !== 403) {
      token=null; active=false; $('signed-in').hidden=true;
      throw e;
    }
    if(options.rosy_account) {
      $('login-panel').hidden=true; $('signed-in').hidden=true;
      $('account-status').textContent='Rosy Account로 연결 중…';
      window.location.assign('/api/account/login?return=/accounts'); return;
    }
    token=null; active=false; $('login-panel').hidden=false; $('signed-in').hidden=true;
    $('account-status').textContent='프로젝트에 로그인하세요.'; return;
  }
  token=session.token; active=true; $('login-panel').hidden=true; $('signed-in').hidden=false;
  $('account-status').textContent='로그인됨';
  $('identity').textContent=`프로젝트 ${session.project_id} · 작업자 ${session.user_id} · 권한 ${session.capabilities.join(', ')}`;
  $('import-panel').hidden=!session.capabilities.includes('import');
  const list=$('connections'), select=$('connection'); list.replaceChildren(); select.replaceChildren();
  for(const account of session.connections) {
    const row=document.createElement('article'); list.append(row);
    line(row,`${account.username || account.subject} · ${account.sharing==='project'?'프로젝트 연결':'개인 연결'}`);
    button(row,'연결 해제',async()=>{
      if(!confirm('연결을 해제하면 이 계정을 사용하는 새 가져오기가 중단됩니다. 해제할까요?'))return;
      await api('/api/accounts/disconnect',{connection_id:account.connection_id}); await refresh();
    });
    const option=document.createElement('option'); option.value=account.connection_id;
    option.textContent=account.username || account.subject; select.append(option);
  }
  if(!session.connections.length) line(list,'연결된 계정이 없습니다.');
  await jobs();
}
async function jobs() {
  if(!active)return;
  const result=await api('/api/learning/imports'), root=$('imports'); root.replaceChildren();
  if(!result.jobs.length) line(root,'가져오기 작업이 없습니다.');
  for(const job of result.jobs) {
    const row=document.createElement('article'); root.append(row);
    line(row,`${job.repo_id} · ${states[job.status] || job.status}`);
    line(row,`버전 ${job.revision} · 요청자 ${job.requester_id || job.requester || ''}`);
    if(job.error) line(row,job.error==='gated_team_use_evidence_required'?'팀 이용 허가 근거가 필요합니다. 확인 후 새 가져오기를 등록하세요.':job.error);
    if(job.reason) line(row,job.reason);
    if(job.status==='completed') line(row,'원본 검증·라벨 검수 후 학습 자료로 준비하세요.');
    if(['failed','interrupted','queued','cancelled','blocked'].includes(job.status)) button(row,'같은 버전 재시도',async()=>{
      await api('/api/learning/imports/retry',{id:job.id}); await jobs();
    });
    if(['queued','running'].includes(job.status)) button(row,'가져오기 취소',async()=>{
      await api('/api/learning/imports/cancel',{id:job.id}); await jobs();
    });
  }
}
$('login-form').addEventListener('submit',event=>{event.preventDefault();perform(async()=>{
  const password=$('password').value; $('password').value='';
  await api('/api/accounts/login',{username:$('username').value,password}); await refresh();
});});
$('logout').addEventListener('click',()=>perform(async()=>{
  active=false; $('signed-in').hidden=true;
  for(const id of ['connections','imports','connection']) $(id).replaceChildren();
  try { await api('/api/accounts/logout',{}); } finally { token=null; }
  await refresh();
}));
for(const [id,purpose] of [['hf-login','login'],['hf-link','link']]) $(id).addEventListener('click',()=>perform(async()=>{
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
$('reload').addEventListener('click',()=>perform(refresh));
setInterval(()=>{if(active&&!pending&&!document.hidden)perform(jobs);},5000);
perform(refresh);
