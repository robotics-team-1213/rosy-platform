import {accountFetch} from '/account-session.js';
import '/common/ui.js';
import '/commands.js';
const $=id=>document.getElementById(id);
let token,busy=false,loading=false,loaded=false,importsReady=false;
const importStates={queued:'대기',running:'가져오는 중',failed:'실패',interrupted:'중단됨',cancelled:'취소됨',blocked:'접근 차단',rights_hold:'이용 권한 확인 필요'};
function show(id,value){$(id).textContent=value;$(id).hidden=!value;}
function controls(){
  const blocked=busy||loading||!token,reason=loading?'현재 연결과 권한을 확인하는 중입니다.':busy?'파일 검증을 마친 뒤 다시 사용할 수 있습니다.':!token?'자료 등록 권한을 다시 확인하세요.':'';
  for(const id of ['import','cad']){$(id).disabled=blocked;$(id).reason=reason;}
  for(const id of ['catalog-path','catalog-classes','cad-path'])$(id).disabled=blocked;
  for(const id of ['catalog-retry','hf-retry']){$(id).disabled=busy||loading;$(id).reason=reason;}
  for(const button of $('hf-imports').querySelectorAll('[data-hf-send]')){button.disabled=blocked||!importsReady;button.reason=reason||(!importsReady?'가져오기 목록을 다시 확인하세요.':'');}
}
async function request(path,body){const response=await accountFetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':token},body:JSON.stringify(body)}:{});if(response.status>=500){const error=new Error('자료 등록 서비스를 사용할 수 없습니다. 잠시 후 다시 시도하세요.');error.status=response.status;throw error;}const value=await response.json();if(!response.ok){if([401,403].includes(response.status))token=undefined;throw new Error(response.status===403?'이 작업대의 자료 등록 권한이 거부되었습니다.':response.status===401?'로그인 상태를 확인할 수 없습니다. 로그인·계정에서 연결을 확인하세요.':value.error||'요청 실패');}return value;}
function map(value){if(!value)return;$('map-status').setAttribute('state','warning');$('map-status').textContent=`${value.map_id} · CAD/그래프 파일 출처 확인됨 · 영상 투영 미검증`;$('map-details').textContent=JSON.stringify(value,null,2);}
async function perform(id,path,body,done){if(busy||loading||!token)return;busy=true;show('catalog-error','');controls();try{await done(await request(path,body));}catch(error){show('catalog-error',error.message+(token?' · 원본 자료와 검증 경로를 확인하세요.':' · 다시 확인으로 권한을 새로 읽으세요.'));$('catalog-error').scrollIntoView({block:'center'});if(!token){$('catalog-load').hidden=false;$('catalog-load').setAttribute('state','error');$('catalog-load').textContent='자료 등록 권한을 확인할 수 없습니다.';$('catalog-retry').hidden=false;}}finally{busy=false;controls();}}
function register(event){event.preventDefault();if(loading||!token||!$('import-form').reportValidity())return;perform('import','/api/import',{path:$('catalog-path').value,classes:$('catalog-classes').value.trim()||undefined},value=>{$('result').setAttribute('state','ready');show('result',`새 사진 ${value.added}장 · 중복 표현 ${value.duplicate_representations}개 · 새 픽셀 검수 대기 ${value.pixel_reviews_pending}장. 기존 승인·제외는 유지됩니다.`);});}
function el(tag,cls,text){const node=document.createElement(tag);if(cls)node.className=cls;if(text)node.textContent=text;return node;}
function hfState(state,text){$('hf-load').setAttribute('state',state);$('hf-load').setAttribute('role',state==='error'?'alert':'status');$('hf-load').textContent=text;}
function hfJobs(jobs){
  const root=$('hf-imports'),focused=root.contains(document.activeElement)?document.activeElement.closest('[data-import-job]')?.dataset.importJob:null;
  root.replaceChildren();$('hf-section').hidden=false;
  if(!jobs.length)root.append(el('ui-empty','','가져온 자료가 없습니다. 로그인·계정 화면에서 Hugging Face 자료를 가져오세요.'));
  for(const job of jobs){const row=el('article','ui-task-row'),head=el('div','ui-task-heading'),tag=el('ui-tag','',job.review?'검수 대기로 보냄':job.status==='completed'?'검증 완료 · 보내기 전':importStates[job.status]||'상태 확인 필요');tag.setAttribute('status',job.review?'active':'neutral');const title=el('h3','',job.repo_id);title.tabIndex=-1;head.append(title,tag);row.dataset.importJob=job.id;row.append(head,el('p','ui-task-meta',`버전 ${job.revision} · 파일 ${(job.files||[]).length}개 · 요청자 ${job.requester_id}`));
    if(job.review){const r=job.review;row.append(el('p','ui-task-next',`새 사진 ${r.added}장 · 픽셀 검수 대기 ${r.pixel_reviews_pending}장 · 보낸 사람 ${r.registered_by}. 사람이 확인하기 전까지 승인이 아닙니다.`));const open=el('a','','객체 검수 대기 열기'),actions=el('ui-actions');open.href='/?filter=pending';actions.append(open);row.append(actions);}
    else if(job.status==='completed'){const send=el('ui-button','','검수로 보내기');send.setAttribute('kind','primary');send.dataset.actionIcon='next';send.dataset.hfSend='';send.onclick=()=>perform('hf','/api/learning/imports/review',{id:job.id},()=>loadImports());const actions=el('ui-actions');actions.append(send);row.append(actions);}
    else{
      row.append(el('p','ui-task-next',['queued','running'].includes(job.status)?'가져오기가 끝나고 파일 해시가 검증되면 보낼 수 있습니다.':'현재 상태와 권한을 확인한 뒤 필요한 작업을 진행하세요.'));
      if(job.error||job.reason)row.append(el('p','ui-task-meta',job.error==='gated_team_use_evidence_required'?'팀 이용 허가 근거가 필요합니다. 확인 후 새 가져오기를 등록하세요.':job.reason||job.error));
      const actions=el('ui-actions'),link=el('a','','가져오기 상태·권한 확인');link.href='/accounts';actions.append(link);row.append(actions);
    }root.append(row);
  }
  if(focused){const row=[...root.children].find(node=>node.dataset.importJob===focused);(row?.querySelector('ui-button,a')||row?.querySelector('h3'))?.focus({preventScroll:true});}
}
async function loadImports(){
  importsReady=false;$('hf-section').hidden=false;hfState('pending','가져오기 목록을 확인하는 중입니다.');controls();
  try{const jobs=(await request('/api/learning/imports')).jobs;hfJobs(jobs);importsReady=true;hfState(jobs.length?'ready':'empty',jobs.length?`확인된 가져오기 ${jobs.length}개`:'확인된 가져오기 작업이 없습니다.');}
  catch(error){hfState('error',error.message+($('hf-imports').children.length?' · 아래는 마지막 확인 결과입니다. 다시 확인하세요.':' · 다시 확인을 눌러 목록을 읽으세요.'));if(!token){$('catalog-load').hidden=false;$('catalog-load').setAttribute('state','error');$('catalog-load').textContent='자료 등록 권한을 확인할 수 없습니다. 다시 확인하세요.';$('catalog-retry').hidden=false;}}
  finally{controls();}
}
function registerMap(event){event.preventDefault();if(loading||!token||!$('cad-form').reportValidity())return;perform('cad','/api/cad',{path:$('cad-path').value},map);}
$('import-form').onsubmit=register;$('import').onclick=register;$('cad-form').onsubmit=registerMap;$('cad').onclick=registerMap;
async function load(){if(loading||busy)return;loading=true;token=undefined;importsReady=false;controls();$('catalog-load').hidden=false;$('catalog-load').setAttribute('state','pending');$('catalog-load').textContent='자료 등록 권한과 현재 연결을 확인하는 중입니다.';$('catalog-retry').hidden=true;$('map-status').setAttribute('state','pending');$('map-status').textContent='지도 참조 확인 중입니다.';$('map-details').textContent='';if(!$('hf-section').hidden)hfState('pending','가져오기 목록을 확인하는 중입니다.');
  const started=performance.now();const timer=setInterval(()=>{const seconds=Math.floor((performance.now()-started)/1000);if(loading&&seconds>=3)$('catalog-load').textContent=`서버 응답 대기 ${seconds}초 · 자료 등록 권한과 현재 연결을 확인하고 있습니다.`;},1000);
  try{const value=await request('/api/catalog');token=value.token;if(!loaded){$('catalog-path').value=value.catalog||'';$('cad-path').value=value.cad_catalog||'';loaded=true;}$('map-status').setAttribute('state','empty');$('map-status').textContent='아직 연결한 지도 참조가 없습니다.';map(value.map_reference);$('catalog-load').hidden=true;if(value.imports)await loadImports();else{$('hf-section').hidden=true;$('hf-imports').replaceChildren();}}
  catch(error){$('catalog-load').setAttribute('state','error');$('catalog-load').textContent=error.status>=500?error.message:error.message+' 접근 권한과 연결을 확인한 뒤 다시 확인하세요.';$('map-status').setAttribute('state','error');$('map-status').textContent='지도 참조를 확인할 수 없습니다.';$('catalog-retry').hidden=false;if(!$('hf-section').hidden)hfState('error','가져오기 목록과 권한을 다시 확인하세요. 아래는 마지막 확인 결과입니다.');}
  finally{clearInterval(timer);loading=false;controls();}}
$('catalog-retry').onclick=load;
$('hf-retry').onclick=load;
controls();load();
