import {accountFetch} from '/account-session.js';
import '/common/ui.js';
import '/commands.js';
import {createRecordingReview} from '/record-review.js';
const $=id=>document.getElementById(id),API='/api/learning/recording';
const timingFields={'record-fps':'fps','record-camera-age':'max_camera_age_s','record-arm-age':'max_arm_age_s','record-camera-skew':'max_camera_skew_s','record-arm-skew':'max_arm_skew_s','record-gap':'max_gap_s'};
const statusLabels={idle:'대기',arming:'입력 준비 중',recording:'녹화 중',exporting:'자료 변환 중',ready:'준비됨',failed:'실패',draft:'확인 대기',kept:'보관됨',discarded:'제외됨',invalid:'기록 무효'};
let snapshot={},session=null,token='',project='',connected=false,polling=false,pending={},mutations=0,stopping=false,selectionGeneration=0,refreshQueued=false;
let sessionId=new URL(location.href).searchParams.get('session')||'',loadedSession='',profileSignature='',sourceSignature='',initialProfile=new URL(location.href).searchParams.get('profile')||'';
const episodeNodes=new Map();
const savedReview=createRecordingReview({request,onChange:availability});
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function error(message){$('record-error').hidden=!message;$('record-error').textContent=message||'';}
function uuid(){const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;const h=Array.from(b,x=>x.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
function storageKey(){return `rosy.recording.pending:${project}:${sessionId}`;}
function readPending(){try{pending=JSON.parse(localStorage.getItem(storageKey())||'{}');}catch{pending={};}if(pending.create&&!session){$('record-name').value=pending.create.name;for(const [id,key] of Object.entries(timingFields))$(id).value=pending.create.timing[key]??'';initialProfile=pending.create.profile_id;}}
function savePending(){localStorage.setItem(storageKey(),JSON.stringify(pending));}
function setURL(){const u=new URL(location.href);if(sessionId)u.searchParams.set('session',sessionId);else u.searchParams.delete('session');history.replaceState(null,'',u);}
async function request(path,body){const options={cache:'no-store',signal:AbortSignal.timeout(30000)};if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-Pinky-Token':token};options.body=JSON.stringify(body);}const response=await accountFetch(path,options),value=await response.json();if(!response.ok)throw new Error(response.status===401?'로그인·계정에서 접속한 뒤 다시 확인하세요.':response.status===403?'프로젝트의 녹화 관리 권한을 확인하세요.':value.error||`요청 실패 (${response.status})`);return value;}
function button(id,reason){$(id).disabled=!!reason;$(id).reason=reason;}
function baseReason(){return !connected?'연결을 다시 확인하세요.':!token?'로그인·계정에서 관리 권한을 확인하세요.':!snapshot.configured?'이 호스트에 로컬 녹화 입력을 설정하세요.':'';}
function active(){return snapshot.active||(['arming','recording'].includes(session?.status)?session:null);}
function profile(){const id=session?.profile_id||$('record-profile').value;return (snapshot.profiles||[]).find(p=>p.id===id);}
function readiness(){
  const p=profile()?.profile;if(!p)return '저장 구성을 선택하세요.';
  const sources=snapshot.sources||[],missing=[];
  for(const arm of p.arms){const source=sources.find(s=>s.kind==='arm'&&s.arm_id===arm.id);if(source?.status!=='ready')missing.push(`${arm.id}: ${source?.reason||'상태·수락된 행동 입력이 없습니다.'}`);}
  for(const camera of p.cameras.filter(c=>c.purposes.some(p=>p!=='monitor'))){const source=sources.find(s=>s.kind==='camera'&&s.source_identity===camera.source_identity);if(source?.status!=='ready')missing.push(`${camera.id}: ${source?.reason||'녹화 가능한 카메라 입력이 없습니다.'}`);}
  return missing.join(' · ');
}
function timing(){return Object.fromEntries(Object.entries(timingFields).map(([id,key])=>[key,Number($(id).value)]));}
function setupProblem(){return !$('record-name').value.trim()?'세션 이름을 입력하세요.':!profile()?'저장 구성을 선택하세요.':Object.keys(timingFields).some(id=>!$(id).validity.valid)?'측정한 녹화 주파수와 시간 기준을 모두 선언하세요.':'';}
function availability(){
  const base=baseReason(),live=active(),busy=mutations?'요청 처리 중입니다.':'',frozen=!!session||!!live;
  for(const id of ['record-name','record-profile',...Object.keys(timingFields)])$(id).disabled=frozen||!!mutations;
  $('record-session').disabled=!!mutations||!!live;button('record-new',busy||(live?'현재 회차를 정지한 뒤 새 구성으로 세션을 만드세요.':''));
  const createReason=base||busy||(live?'현재 회차를 먼저 정지하세요.':session?'구성 변경은 새 구성·녹화 세션에서 저장하세요.':pending.create?'':setupProblem());
  $('record-create-reason').textContent=createReason||'선택한 구성 버전과 시간 기준을 고정해 새 세션을 저장합니다.';button('record-create',createReason);
  $('record-create').textContent=pending.create?'같은 세션 저장 요청 다시 확인':'이 구성으로 세션 저장';
  const startReason=base||busy||(snapshot.review_busy||savedReview.isPreparing()?'저장 기록의 무결성 검사를 마치거나 검수를 닫은 뒤 녹화하세요.':'')||(!session?'녹화 세션을 먼저 저장하세요.':session.export?'변환을 시작한 세션의 구성·회차는 고정됩니다. 새 녹화는 새 세션에서 시작하세요.':pending.start?'':live?'현재 회차를 정지한 뒤 다음 회차를 시작하세요.':readiness());
  $('episode-start-reason').textContent=startReason||'입력의 출처·순서·시간 기준을 다시 확인한 뒤 새 회차를 시작할 수 있습니다.';button('episode-start',startReason);$('episode-start').textContent=pending.start?'같은 회차 시작 요청 다시 확인':'새 회차 녹화 시작';
  $('record-live').hidden=!live;
  if(live)$('record-live-status').textContent=`${live.name||'현재 세션'} · ${statusLabels[live.status]||'상태 미확인'} · 구성 변경은 회차를 정지한 뒤 새 세션에 적용하세요.`;
  button('episode-stop',!live?'녹화 중인 회차가 없습니다.':!connected?'연결을 다시 확인하세요.':!token?'관리 권한이 필요합니다.':stopping?'정지 처리 중입니다.':'');
  if(live&&savedReview.isOpen())savedReview.close();
  const kept=(session?.episodes||[]).filter(e=>e.status==='kept'&&e.integrity_verified).length,exp=session?.export;
  button('record-export',base||busy||(!session?'녹화 세션을 선택하세요.':live?'현재 회차를 먼저 정지하세요.':exp?.status==='running'?'자료 변환 중입니다.':exp?.status==='succeeded'?'완료된 자료를 내려받거나 학습센터로 전달하세요.':kept<2?'무결성이 확인된 보관 회차 2개 이상이 필요합니다.':!snapshot.exporter?.available?snapshot.exporter?.reason||'이 호스트에 변환기를 설정하세요.':''));
  $('record-export').textContent=pending.export?'같은 변환 요청 다시 확인':'LeRobot 자료 변환';
  button('record-publish',base||busy||(!snapshot.import_available?'이 호스트에서는 ZIP을 내려받아 학습센터의 폴더 업로드를 사용하세요.':exp?.status!=='succeeded'?'자료 변환을 완료하세요.':''));$('record-publish').textContent=pending.publish?'같은 전달 요청 다시 확인':'학습센터로 자료 전달';
  for(const view of episodeNodes.values()){const e=view.episode,frozen=session?.export?'변환을 시작한 세션의 구성·회차는 고정됩니다. 새 녹화는 새 세션에서 시작하세요.':'',reason=base||busy||frozen||(live?'현재 회차를 먼저 정지하세요.':e.status!=='draft'?'확인 대기 회차만 판정할 수 있습니다.':!e.integrity_verified?'기록 무결성을 확인하지 못해 보관할 수 없습니다.':'');view.keep.disabled=!!reason;view.keep.reason=reason;view.discard.reason=base||busy||frozen||(live?'현재 회차를 정지하세요.':!['draft','invalid'].includes(e.status)?'확인 대기·무효 회차만 제외할 수 있습니다.':'');view.discard.disabled=!!view.discard.reason;view.outcome.disabled=!!mutations||!!frozen||!!live||e.status!=='draft'||!!pending['keep:'+e.id];view.review.reason=!connected?'연결을 다시 확인하세요.':busy||(live?'현재 회차를 정지한 뒤 저장 기록을 여세요.':!['draft','kept'].includes(e.status)||!e.integrity_verified?'무결성이 확인된 저장 회차를 선택하세요.':'');view.review.disabled=!!view.review.reason;}
}
function options(select,rows,placeholder){const signature=JSON.stringify(rows),previous=select.value;if(select.dataset.signature===signature)return;select.dataset.signature=signature;select.replaceChildren();for(const [value,label] of [['',placeholder],...rows]){const opt=node('option',label);opt.value=value;select.append(opt);}if(rows.some(([id])=>id===previous))select.value=previous;}
function renderProfile(){
  const p=profile(),signature=JSON.stringify(p);if(signature===profileSignature)return;profileSignature=signature;$('record-profile-summary').replaceChildren();if(!p)return;
  const doc=p.profile,dl=node('dl',null,'record-facts');$('record-profile-summary').append(node('h3',doc.name));
  for(const [key,value] of [['작업 팔',`${doc.arms.length}대 · ${doc.mode==='cooperative'?'협동':'독립'}`],['관절 순서',doc.arms.map(a=>`${a.id}: ${a.joint_names.join(', ')} (${a.units})`).join(' / ')],['카메라',`${doc.cameras.length}개 · 학습 입력 ${doc.cameras.filter(c=>c.purposes.includes('policy')).length}개`],['시야·역할',doc.cameras.map(c=>`${c.id} (${c.role})`).join(' / ')]])dl.append(node('dt',key),node('dd',value));$('record-profile-summary').append(dl);
  const details=node('details');details.append(node('summary','구성 버전·물리 출처'),node('p',`저장 버전 ${p.revision}`,'record-note'));
  for(const c of doc.cameras)details.append(node('p',`${c.id} · 배치 ${c.placement} · 출처 ${c.source_identity} · 입력 ${c.input_key} · ${c.purposes.join(', ')} · ${c.shape.join(' × ')}`,'record-note'));$('record-profile-summary').append(details);
}
function safeLocalURL(value){if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//'))return null;try{const u=new URL(value,location.origin);return u.origin===location.origin?u.pathname+u.search:null;}catch{return null;}}
function renderSources(){
  const sources=snapshot.sources||[],signature=JSON.stringify(sources);$('record-sources-empty').hidden=!!sources.length;if(signature===sourceSignature){for(const img of $('record-sources').querySelectorAll('img')){const url=new URL(img.src);url.searchParams.set('_record_preview',Date.now());img.src=url.pathname+url.search;}return;}sourceSignature=signature;$('record-sources').replaceChildren();
  for(const s of sources){const section=node('article',null,'record-source');section.dataset.kind=s.kind;section.append(node('h3',s.label||s.id));
    const preview=safeLocalURL(s.preview_url);if(preview){const img=node('img');img.src=preview;img.alt=`${s.label||s.id} 현재 미리보기`;img.loading='lazy';section.append(img);}
    section.append(node('p',`${s.status==='ready'?'녹화 입력 준비됨':s.status==='preview_only'?'미리보기 전용':'사용 불가'}${s.reason?' · '+s.reason:''}`,'record-source-status'));
    const details=node('details');details.append(node('summary','입력 출처·기록 범위'),node('p',`물리 출처 ${s.source_identity||'미확인'} · 팔 ${s.arm_id||'공유·미지정'} · ${s.purposes?.join(', ')||'용도 미지정'}`,'record-note'));if(s.joint_names)details.append(node('p',`${s.joint_names.join(', ')} · ${s.units||'단위 미확인'}`,'record-note'));if(s.shape)details.append(node('p',`입력 크기 ${s.shape.join(' × ')}`,'record-note'));section.append(details);$('record-sources').append(section);
  }
}
function renderEpisodes(){
  const episodes=session?.episodes||[],ids=new Set(episodes.map(e=>e.id));$('record-episodes-empty').hidden=!!episodes.length;
  for(const [id,view] of episodeNodes)if(!ids.has(id)){view.section.remove();episodeNodes.delete(id);}
  for(const e of episodes){let view=episodeNodes.get(e.id);if(!view){const section=node('article',null,'record-episode'),heading=node('h3'),detail=node('p'),failure=node('p'),label=node('label','과제 결과 · 사람이 별도로 선택','ui-field-label'),outcome=node('select'),actions=node('div',null,'ui-actions'),keep=node('ui-button','기록 확인·보관'),discard=node('ui-button','회차 제외');outcome.className='ui-field';outcome.dataset.outcome=e.id;for(const [value,text] of [['unknown','미확인'],['success','성공 · 사람 판정'],['failure','실패 · 사람 판정']]){const opt=node('option',text);opt.value=value;outcome.append(opt);}outcome.value=e.task_outcome||'unknown';label.append(outcome);keep.dataset.keep=e.id;discard.dataset.discard=e.id;keep.setAttribute('kind','quiet');discard.setAttribute('kind','quiet');keep.onclick=()=>act('keep:'+e.id,'/keep',{session_id:sessionId,episode_id:e.id,task_outcome:outcome.value,request_id:uuid()});discard.onclick=()=>act('discard:'+e.id,'/discard',{session_id:sessionId,episode_id:e.id,request_id:uuid()});const review=node('ui-button','저장 기록 재생·검수');review.dataset.review=e.id;review.setAttribute('kind','quiet');review.onclick=()=>{if(!review.disabled)savedReview.open(sessionId,e.id,review);};actions.append(review,keep,discard);section.append(heading,detail,failure,label,actions);$('record-episodes').append(section);view={section,heading,detail,failure,outcome,keep,discard,review};episodeNodes.set(e.id,view);}view.episode=e;view.heading.textContent=`회차 ${e.id} · ${statusLabels[e.status]||'상태 미확인'}`;view.detail.textContent=`${e.frames??0}프레임 · 무결성 ${e.integrity_verified?'확인됨':'미확인'} · 과제 결과 ${e.task_outcome==='success'?'성공 · 사람 판정':e.task_outcome==='failure'?'실패 · 사람 판정':'미확인'}`;view.failure.hidden=!e.error;view.failure.textContent=typeof e.error==='string'?e.error:e.error?.message||'';view.keep.textContent=pending['keep:'+e.id]?'같은 보관 요청 다시 확인':'기록 확인·보관';view.discard.textContent=pending['discard:'+e.id]?'같은 제외 요청 다시 확인':'회차 제외';}
}
function renderExport(){const exp=session?.export,status=exp?.status;let text=status==='running'?'LeRobot 자료 변환 중입니다. 이 화면을 다시 열어 진행을 확인할 수 있습니다.':status==='succeeded'?'학습용 자료 변환 완료. 원본 검사·분할은 학습센터에서 이어집니다.':status==='failed'?`변환 실패: ${typeof exp.error==='string'?exp.error:exp.error?.message||'오류 정보 없음'}`:'보관한 회차를 LeRobot v3 학습 자료로 변환하세요.';if(!snapshot.import_available)text+=' 이 호스트에서는 ZIP을 내려받아 학습센터의 폴더 업로드를 사용하세요.';$('export-status').textContent=text;const artifact=safeLocalURL(exp?.artifact_url);$('record-download').hidden=!(status==='succeeded'&&artifact);if(artifact)$('record-download').href=artifact;if(session?.study_id){$('record-study-link').href='/learning/imitate?study='+encodeURIComponent(session.study_id)+'&panel=inspect';$('record-study-link').hidden=false;}}
function render(){
  options($('record-profile'),(snapshot.profiles||[]).map(p=>[p.id,p.profile.name]),'구성을 선택하세요');if(initialProfile&&(snapshot.profiles||[]).some(p=>p.id===initialProfile)){$('record-profile').value=initialProfile;initialProfile='';}if(!$('record-profile').value&&snapshot.profiles?.length===1)$('record-profile').value=snapshot.profiles[0].id;
  const sessions=snapshot.sessions||[];options($('record-session'),sessions.map(s=>[s.id,s.name]),'새 세션');if(session&&!Array.from($('record-session').options).some(o=>o.value===session.id)){const opt=node('option',session.name);opt.value=session.id;$('record-session').append(opt);}$('record-session').value=sessionId;
  if(session&&loadedSession!==session.id){loadedSession=session.id;$('record-name').value=session.name;$('record-profile').value=session.profile_id;for(const [id,key] of Object.entries(timingFields))$(id).value=session.timing[key]??'';}
  $('record-host').textContent=`녹화 호스트: ${snapshot.host_id||'미설정'} · 현재 접속한 호스트의 등록된 입력만 사용합니다.`;
  renderProfile();renderSources();renderEpisodes();renderExport();availability();
}
async function refresh(){
  if(polling){refreshQueued=true;return;}const generation=selectionGeneration;polling=true;$('record-refresh').disabled=true;
  try{const auth=await request('/api/learning/tasks');if(generation!==selectionGeneration)return;token=auth.token||'';const next=auth.project_id||auth.project?.id||'';if(next!==project){project=next;readPending();}
    const value=await request(API+'/snapshot');if(generation!==selectionGeneration)return;snapshot=value;
    if(!sessionId&&snapshot.active?.id){sessionId=snapshot.active.id;readPending();setURL();}
    if(sessionId){const id=sessionId;try{const selected=await request(API+'/session/'+encodeURIComponent(id));if(generation!==selectionGeneration||id!==sessionId)return;session=selected;}catch(exc){if(generation!==selectionGeneration)return;if(!pending.create)throw exc;}}
    connected=true;render();
  }catch(exc){if(generation===selectionGeneration){connected=false;error(`${exc.message} 다시 확인을 눌러 연결을 확인하세요.`);availability();}}
  finally{polling=false;$('record-refresh').disabled=false;if(refreshQueued||generation!==selectionGeneration){refreshQueued=false;void refresh();}}
}
async function act(kind,path,body){if(kind==='stop'?stopping:mutations)return;const isStop=kind==='stop';if(isStop)stopping=true;else mutations++;error('');try{if(kind!=='stop')await savedReview.close();if(!pending[kind]){pending[kind]=body;savePending();}availability();const result=await request(API+path,pending[kind]);delete pending[kind];savePending();if(kind==='publish'){const url=safeLocalURL(result.url);if(!url||!url.startsWith('/learning/imitate?'))throw new Error('학습센터 전달 주소를 확인하지 못했습니다. 다시 확인하세요.');$('record-study-link').href=url;$('record-study-link').hidden=false;$('record-status').textContent='학습센터 자료 전달 완료. 원본 검사·분할로 이동하세요.';}else{session=result;if(kind==='create'){sessionId=session.id;setURL();}render();$('record-status').textContent='요청 접수를 확인했습니다. 저장된 기록을 확인하세요.';}await refresh();}catch(exc){error(`${exc.message} 같은 요청 다시 확인으로 접수 여부를 확인할 수 있습니다. 자동으로 다시 실행하지 않습니다.`);}finally{if(isStop)stopping=false;else mutations--;availability();}}
$('record-create').onclick=()=>{if($('record-create').disabled)return;if(!sessionId){sessionId=uuid();setURL();readPending();}const selected=profile();act('create','/session',{request_id:sessionId,name:$('record-name').value.trim(),profile_id:selected.id,profile_revision:selected.revision,timing:timing()});};
$('episode-start').onclick=()=>{if(!$('episode-start').disabled)act('start','/start',{session_id:sessionId,request_id:uuid()});};
$('episode-stop').onclick=()=>{const live=active();if(live&&!$('episode-stop').disabled)act('stop','/stop',{session_id:live.id,request_id:uuid()});};
$('record-export').onclick=()=>{if(!$('record-export').disabled)act('export','/export',{session_id:sessionId,request_id:uuid()});};
$('record-publish').onclick=()=>{if(!$('record-publish').disabled)act('publish','/publish',{session_id:sessionId,request_id:uuid()});};
function reset(){selectionGeneration++;savedReview.close();session=null;loadedSession='';profileSignature='';episodeNodes.clear();$('record-episodes').replaceChildren();$('record-study-link').hidden=true;readPending();setURL();error('');}
$('record-new').onclick=()=>{if(active()){error('현재 회차를 먼저 정지하세요. 새 구성은 다음 세션에 적용합니다.');return;}sessionId='';reset();$('record-name').value='';render();};
$('record-session').onchange=async()=>{if(active()){error('현재 회차를 먼저 정지하세요.');render();return;}sessionId=$('record-session').value;reset();await refresh();};
$('record-profile').onchange=()=>{renderProfile();availability();};for(const id of ['record-name',...Object.keys(timingFields)])$(id).oninput=availability;
$('record-refresh').onclick=refresh;
addEventListener('popstate',()=>{sessionId=new URL(location.href).searchParams.get('session')||'';reset();refresh();});
readPending();refresh();setInterval(()=>{if(!document.hidden&&!polling&&!mutations)refresh();},3000);
