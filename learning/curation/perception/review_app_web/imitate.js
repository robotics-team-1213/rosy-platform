import {accountFetch} from '/account-session.js';
import '/common/ui.js';
import '/commands.js';
const $=id=>document.getElementById(id),API='/api/learning/omx/center';
const active=new Set(['launching','running','stopping']);
const labels={launching:'시작 준비 중',running:'실행 중',stopping:'중지 처리 중',failed:'실패',interrupted:'중단됨',cancelled:'취소됨',succeeded:'완료'};
const phases={validating:'원본 확인 중',inspecting:'시연 검사 중',preparing:'학습 자료 준비 중',training:'ACT 학습 중',evaluating:'남겨 둔 자료 평가 중',finished:'완료'};
const panels=['upload','inspect','learn','results'];
let study=null,listing={},token='',project='',connected=false,working=false,polling=false,resourceGeneration=0,refreshQueued=false;
let studyId=new URL(location.href).searchParams.get('study')||'',selected=[],manifest=[],matched=false;
let pending=null,inspectionKey='',splitSaved='',dirty=false,resultSignature='',selectionGeneration=0;
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function error(message){$('imitate-error').hidden=!message;$('imitate-error').textContent=message||'';}
function uuid(){const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;const h=Array.from(b,v=>v.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
function storageKey(){return `rosy.imitation.pending:${project}:${studyId}`;}
function readPending(){try{pending=JSON.parse(localStorage.getItem(storageKey())||'null');}catch{pending=null;}if(pending?.kind==='train'){for(const [id,key] of [['train-steps','steps'],['train-batch','batch_size'],['train-seed','seed']])$(id).value=pending.body[key];}}
function remember(value){localStorage.setItem(storageKey(),JSON.stringify(value));pending=value;}
function forget(){localStorage.removeItem(storageKey());pending=null;}
function setURL(){const u=new URL(location.href);if(studyId)u.searchParams.set('study',studyId);else u.searchParams.delete('study');history.replaceState(null,'',u);}
function panel(name,focus=false){
  if(!panels.includes(name))name='upload';
  for(const key of panels){$('panel-'+key).hidden=key!==name;$('tab-'+key).setAttribute('aria-selected',String(key===name));$('tab-'+key).tabIndex=key===name?0:-1;}
  const u=new URL(location.href);u.searchParams.set('panel',name);history.replaceState(null,'',u);if(focus)$('tab-'+name).focus();
}
for(const name of panels){$('tab-'+name).onclick=()=>panel(name);$('tab-'+name).onkeydown=event=>{let i=panels.indexOf(name);if(event.key==='ArrowRight')i++;else if(event.key==='ArrowLeft')i--;else if(event.key==='Home')i=0;else if(event.key==='End')i=panels.length-1;else return;event.preventDefault();panel(panels[(i+panels.length)%panels.length],true);};}
async function request(path,body){
  const options={cache:'no-store',signal:AbortSignal.timeout(60000)};
  if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-Pinky-Token':token};options.body=JSON.stringify(body);}
  const response=await accountFetch(path,options),value=await response.json();
  if(!response.ok)throw new Error(response.status===401?'로그인·계정에서 접속한 뒤 다시 확인하세요.':response.status===403?'프로젝트의 학습 관리 권한을 확인하세요.':value.error||`요청 실패 (${response.status})`);
  return value;
}
function disable(id,reason){$(id).disabled=!!reason;$(id).reason=reason;$(id).setAttribute('aria-describedby',id==='train-start'?'train-reason':'action-status');}
function splitSelection(){const value={train:[],validation:[],eval:[]};for(const input of $('episode-rows').querySelectorAll('select'))if(value[input.value])value[input.value].push(Number(input.dataset.episode));for(const list of Object.values(value))list.sort((a,b)=>a-b);return value;}
function splitProblem(){const s=splitSelection();return !study?.inspection?'원본 검사를 먼저 마치세요.':!s.train.length||!s.eval.length?'학습·평가 에피소드를 각 1개 이상 선택하세요.':'';}
function gate(){return working?'요청 처리 중입니다.':!connected?'연결을 다시 확인하세요.':!token?'로그인·계정에서 학습 관리 권한을 확인하세요.':'';}
function availability(){
  const basic=gate(),method=listing.methods?.act;
  const host=!listing.configured?'학습 실행기 연결이 필요합니다.':!listing.host_id?'학습 호스트 식별 설정이 필요합니다.':method?.available!==true?method?.reason||'ACT 실행기를 사용할 수 없습니다.':'';
  const occupied=listing.busy?'현재 실행을 마치거나 중지한 뒤 시작하세요.':'';
  const uploaded=study?.upload&&study.upload.files.every(f=>f.offset===f.size);
  disable('upload-start',basic||(!listing.configured?'자료 저장소 연결이 필요합니다.':'')||(!matched?'같은 원본 폴더를 선택하고 파일 확인을 마치세요.':study?.upload.locked?'검사한 원본은 잠겨 있습니다. 새 작업을 만드세요.':!study&&!$('study-name').value.trim()?'학습 작업 이름을 입력하세요.':pending&&!['create'].includes(pending.kind)?'이전 요청의 접수 여부를 먼저 확인하세요.':''));
  disable('inspect-start',basic||host||(pending?.kind==='inspect'?'':occupied)||(!uploaded?'자료 업로드를 마치세요.':study?.status==='inspecting'&&!pending?'원본 검사가 진행 중입니다.':study?.inspection?'검사를 마친 원본입니다.':''));
  disable('split-save',basic||occupied||splitProblem()||(pending&&pending.kind!=='split'?'이전 요청을 먼저 확인하세요.':''));
  const invalid=['train-steps','train-batch','train-seed'].some(id=>!$(id).validity.valid);
  const trainReason=basic||host||(pending?.kind==='train'?'':occupied)||(!study?.inspection?'원본 검사를 마치세요.':!study.split||dirty?'확인·분할에서 분할을 저장하세요.':pending&&pending.kind!=='train'?'이전 요청의 접수 여부를 확인하세요.':invalid?'학습 설정의 허용 범위를 확인하세요.':'');
  $('train-reason').textContent=trainReason||'저장한 분할로 ACT CPU 학습을 시작할 수 있습니다.';disable('train-start',trainReason);
  $('train-start').textContent=pending?.kind==='train'?'같은 학습 요청 다시 확인':'ACT 학습 시작';
  $('inspect-start').textContent=pending?.kind==='inspect'?'같은 검사 요청 다시 확인':'원본 검사';
  $('split-save').textContent=pending?.kind==='split'?'같은 분할 요청 다시 확인':'분할 저장';
  $('upload-start').textContent=pending?.kind==='create'?'같은 자료 요청 이어가기':study?'자료 업로드 이어가기':'자료 올리기';
  for(const id of ['train-steps','train-batch','train-seed'])$(id).disabled=working||pending?.kind==='train';
  for(const input of $('episode-rows').querySelectorAll('select'))input.disabled=working||!!pending;
  $('source-folder').disabled=working;$('study-select').disabled=working;$('study-new').disabled=working;
  const current=listing.active_run||(study?.runs||[]).find(r=>active.has(r.status));
  $('active-run').hidden=!current;
  if(current){$('active-title').textContent=current.execution_mode==='lerobot_inspect'?'현재 실행 · 원본 검사':'현재 실행 · ACT 학습';$('active-progress').textContent=progress(current);$('active-identity').textContent=`실행 ${current.id}${current.study_id&&current.study_id!==studyId?' · 다른 학습 작업':''}`;$('active-stop').dataset.run=current.id;disable('active-stop',!connected?'연결을 다시 확인하세요.':!token?'관리 권한이 필요합니다.':current.status==='stopping'?'중지 처리 중입니다.':'');}
  $('train-host').textContent=`ACT · LeRobot 0.4.4 · CPU · 실행 호스트 ${listing.host_id||'미확인'}`;
}
function progress(run){const p=run.progress||{};return `${labels[run.status]||'상태 미확인'} · ${phases[p.phase]||'세부 진행 정보 없음'}${Number.isFinite(p.step)?` · ${p.step} / ${p.steps??run.steps??'?'}단계`:''}`;}
function facts(rows){$('source-facts').replaceChildren(...rows.flatMap(([k,v])=>[node('dt',k),node('dd',v)]));}
function source(){
  const info=study?.inspection,key=info?`${study.id}:${info.revision}`:'';
  if(key!==inspectionKey){
    inspectionKey=key;dirty=false;splitSaved='';$('episode-rows').replaceChildren();$('camera-facts').replaceChildren();
    if(info){
      const names=v=>v.names?.length?v.names.join(', '):'이름 없음 · 원본 인덱스 순서';
      facts([['원본 로봇',info.robot_type||'미확인'],['프레임률',`${info.fps} fps`],['에피소드·프레임',`${info.total_episodes}개 · ${info.total_frames}프레임`],['상태 벡터',`${info.state.shape.join(' × ')} · ${names(info.state)}`],['행동 벡터',`${info.action.shape.join(' × ')} · ${names(info.action)}`],['원본 단위',known(info.units)],['수집 세션 독립성',known(info.capture_session_independence)]]);
      for(const c of info.cameras)$('camera-facts').append(node('p',`${c.key} · 원본 ${c.shape.join(' × ')} · ${c.dtype} → 학습 RGB 128 × 128`));
      const episodes=[...info.episodes].sort((a,b)=>a.index-b.index);
      episodes.forEach((e,i)=>{const row=node('tr'),select=node('select');select.className='ui-field';select.dataset.episode=e.index;select.setAttribute('aria-label',`에피소드 ${e.index} 용도`);for(const [value,text] of [['train','학습'],['validation','검증'],['eval','평가'],['excluded','제외']]){const opt=node('option',text);opt.value=value;select.append(opt);}select.value=i===episodes.length-1?'eval':'train';select.onchange=()=>{dirty=true;splitState();availability();};const cell=node('td');cell.append(select);row.append(node('th',e.index),node('td',e.frames),node('td',e.task||'미기록'),cell);$('episode-rows').append(row);});
    }else facts([]);
  }
  if(info&&study.split&&study.split.revision!==splitSaved&&!dirty){for(const input of $('episode-rows').querySelectorAll('select')){const id=Number(input.dataset.episode);input.value=['train','validation','eval'].find(k=>study.split[k].includes(id))||'excluded';}splitSaved=study.split.revision;}
  splitState();
}
function known(value){return value==null||value==='unknown'?'미확인':typeof value==='string'?value:JSON.stringify(value);}
function splitState(){const reason=splitProblem();$('split-state').textContent=!study?.inspection?'원본 검사 후 분할을 제안합니다.':reason||(!study.split?'분할 제안 · 아직 저장하지 않았습니다.':dirty?'분할 변경 중 · 저장해야 학습에 반영됩니다.':`분할 저장됨 · ${study.split.train.length}개 학습 / ${study.split.validation.length}개 검증 / ${study.split.eval.length}개 평가`);}
function render(){
  const rows=listing.studies||[],signature=JSON.stringify(rows.map(s=>[s.id,s.name]));
  if($('study-select').dataset.signature!==signature){$('study-select').dataset.signature=signature;$('study-select').replaceChildren(node('option','새 작업'));$('study-select').firstChild.value='';for(const s of rows){const opt=node('option',s.name);opt.value=s.id;$('study-select').append(opt);}}
  if(study&&!Array.from($('study-select').options).some(o=>o.value===study.id)){const opt=node('option',study.name);opt.value=study.id;$('study-select').append(opt);}$('study-select').value=studyId;
  $('study-summary').textContent=study?`${study.name} · ${study.status==='uploading'?'자료 업로드 중':study.status==='inspecting'?'원본 검사 중':study.status==='ready'?'원본 검사 완료':study.status==='failed'?'검사 실패':'상태 미확인'}`:'새 작업에서 원본 폴더를 올리세요.';
  if(study){const u=study.upload;$('upload-progress').max=Math.max(u.total_bytes,1);$('upload-progress').value=u.uploaded_bytes;$('upload-status').textContent=`${u.files.length}개 파일 · ${u.uploaded_bytes.toLocaleString()} / ${u.total_bytes.toLocaleString()} bytes${u.locked?' · 원본 잠김':selected.length?'':' · 같은 폴더를 다시 선택하면 이어갈 수 있습니다.'}`;$('study-name').value=study.name;}
  $('study-name').disabled=!!study||working;
  $('inspect-status').textContent=study?.error?`검사 실패: ${typeof study.error==='string'?study.error:study.error.message}`:study?.inspection?'원본 검사 완료. 에피소드별 용도를 확인하고 분할을 저장하세요.':study?.status==='inspecting'?'원본을 검사하고 있습니다. 위 현재 실행에서 중지할 수 있습니다.':'업로드를 마치면 원본을 검사할 수 있습니다.';
  source();results();availability();
}
function finite(v){return Number.isFinite(v)?Number(v.toPrecision(5)).toString():'미확인';}
function results(){
  const runs=(study?.runs||[]).filter(r=>r.execution_mode==='lerobot_train'),signature=JSON.stringify(runs);if(signature===resultSignature)return;resultSignature=signature;
  $('results-empty').hidden=!!runs.length;$('study-results').replaceChildren();
  for(const run of [...runs].reverse()){
    const section=node('article',null,'imitate-result');section.append(node('h3',`ACT · ${labels[run.status]||'상태 미확인'}`),node('p',progress(run)),node('p',`실행 ${run.id}`,'imitate-note'));
    if(run.error)section.append(node('p',typeof run.error==='string'?run.error:run.error.message));
    const e=run.result?.evaluation;
    if(e){section.append(node('p',`평가 표본 ${e.samples??'미확인'}개 · 별도 프로세스 모델 재적재 ${e.model_reloaded_in_new_process===true?'확인됨':'미확인'}`));const table=node('table',null,'imitate-table'),head=node('tr'),body=node('tbody'),wrap=node('div',null,'imitate-table-wrap');table.append(node('caption',`원본 값의 단위로 비교 · 물리 단위 ${known(e.units)}`));for(const text of ['원본 행동','모델 MAE','학습 평균 기준 MAE']){const th=node('th',text);th.scope='col';head.append(th);}const thead=node('thead');thead.append(head);(e.mae_per_joint||[]).forEach((v,i)=>{const row=node('tr');row.append(node('th',e.joint_names?.[i]||`action[${i}]`),node('td',finite(v)),node('td',finite(e.train_mean_baseline_mae_per_joint?.[i])));body.append(row);});table.append(thead,body);wrap.append(table);section.append(wrap);}
    section.append(node('p','실물 성능 미검증 · 정책 적용 없음','imitate-note'));
    if(run.status==='succeeded'){const a=node('a','모델·설정·출처·분할·평가 ZIP 내려받기','workspace-link');a.dataset.artifact=run.id;a.href=API+'/artifact/'+encodeURIComponent(run.id);section.append(a);}$('study-results').append(section);
  }
}
async function refresh(){
  if(polling){refreshQueued=true;return;}const generation=resourceGeneration;polling=true;$('imitate-refresh').disabled=true;
  try{const auth=await request('/api/learning/tasks');if(generation!==resourceGeneration)return;token=auth.token||'';const nextProject=auth.project_id||auth.project?.id||'';if(project!==nextProject){project=nextProject;readPending();}
    const value=await request(API+'/lerobot-studies');if(generation!==resourceGeneration)return;listing=value;
    if(studyId){const id=studyId;try{const selected=await request(API+'/lerobot-study/'+encodeURIComponent(id));if(generation!==resourceGeneration||id!==studyId)return;study=selected;}catch(exc){if(generation!==resourceGeneration)return;if(pending?.kind!=='create')throw exc;}}connected=true;render();}
  catch(exc){if(generation===resourceGeneration){connected=false;error(`${exc.message} 다시 확인을 눌러 연결을 확인하세요.`);availability();}}
  finally{polling=false;$('imitate-refresh').disabled=false;if(refreshQueued||generation!==resourceGeneration){refreshQueued=false;void refresh();}}
}
const paths=[/^meta\/(info|stats)\.json$/,/^meta\/tasks\.parquet$/,/^meta\/episodes\/chunk-\d{3}\/file-\d{3}\.parquet$/,/^data\/chunk-\d{3}\/file-\d{3}\.parquet$/,/^videos\/observation\.images\.[A-Za-z0-9_-]+\/chunk-\d{3}\/file-\d{3}\.mp4$/,/^(README\.md|LICEN[CS]E|LICENSE\.txt|LICENSE\.md|UPSTREAM_README\.md|source-provenance\.json)$/];
function sameManifest(a,b){return a.length===b.length&&a.every((f,i)=>f.name===b[i].name&&f.size===b[i].size&&f.sha256===b[i].sha256);}
$('source-folder').onchange=async()=>{
  const generation=++selectionGeneration;matched=false;manifest=[];selected=[];error('');$('upload-excluded').replaceChildren();availability();
  try{
    const files=Array.from($('source-folder').files),names=new Set();let total=0;const included=[];
    for(const file of files){const relative=file.webkitRelativePath,name=relative?relative.slice(relative.indexOf('/')+1):file.name;const parts=name.split('/');if(parts.some(p=>['.cache','.git','.gitattributes','.DS_Store'].includes(p))){$('upload-excluded').append(node('li',name));continue;}
      if(!name||name.length>256||parts.some(p=>!p||p==='.'||p==='..')||/[\\:\u0000-\u001f]/.test(name)||!paths.some(pattern=>pattern.test(name)))throw new Error(`지원하지 않는 파일입니다: ${name}. LeRobot v3 원본 폴더를 확인하세요.`);
      if(names.has(name.toLowerCase()))throw new Error(`파일 경로가 중복됩니다: ${name}`);names.add(name.toLowerCase());total+=file.size;if(file.size>512*1024**2||total>2*1024**3||included.length>=10000)throw new Error('자료 크기·파일 수 한도를 초과했습니다.');included.push({name,file});}
    if(!included.length)throw new Error('업로드할 원본 파일이 없습니다.');if(!crypto.subtle)throw new Error('이 접속에서는 안전한 파일 해시를 계산할 수 없습니다. HTTPS 또는 localhost로 접속하세요.');
    included.sort((a,b)=>a.name<b.name?-1:a.name>b.name?1:0);
    const checked=[];
    for(const [i,item] of included.entries()){$('upload-status').textContent=`파일 확인 중 · ${i+1} / ${included.length} · ${item.name}`;const bytes=await item.file.arrayBuffer();const hash=await crypto.subtle.digest('SHA-256',bytes);if(generation!==selectionGeneration)return;checked.push({name:item.name,size:item.file.size,sha256:Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('')});}
    const original=study?.upload.files||pending?.body.files;
    if(original&&!sameManifest(checked,[...original].sort((a,b)=>a.name<b.name?-1:a.name>b.name?1:0)))throw new Error('선택한 파일 목록·크기·내용이 저장한 원본과 다릅니다. 같은 폴더를 다시 선택하거나 새 작업을 만드세요.');
    manifest=checked;selected=included;matched=true;$('upload-status').textContent=`${included.length}개 파일 · ${total.toLocaleString()} bytes · 파일 내용 확인됨`;
  }catch(exc){error(exc.message);}finally{availability();}
};
async function mutate(kind,path,body){
  if(working)return;working=true;error('');
  try{if(pending&&pending.kind!==kind)throw new Error('이전 요청의 접수 여부를 먼저 확인하세요.');if(!pending)remember({kind,body});availability();const result=await request(API+path,pending.body);forget();$('action-status').textContent='요청 접수를 확인했습니다.';return result;}
  catch(exc){error(`${exc.message} 같은 요청 다시 확인을 누르면 저장한 요청으로 접수 여부를 확인합니다.`);throw exc;}
  finally{working=false;availability();}
}
$('upload-start').onclick=async()=>{
  if($('upload-start').disabled)return;
  try{
    if(!study||pending?.kind==='create'){if(!studyId){studyId=uuid();setURL();}study=await mutate('create','/lerobot-study',{request_id:studyId,name:$('study-name').value.trim(),files:manifest});render();}
    working=true;availability();error('');
    study=await request(API+'/lerobot-study/'+studyId);
    for(const entry of study.upload.files){const source=selected.find(f=>f.name===entry.name);if(!source)throw new Error('동일한 원본 폴더를 다시 선택하세요.');let offset=entry.offset;
      while(offset<entry.size){const bytes=new Uint8Array(await source.file.slice(offset,offset+256*1024).arrayBuffer());let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);const reply=await request(API+'/lerobot-upload',{study_id:studyId,name:entry.name,offset,data:btoa(binary)});if(reply.offset!==offset+bytes.length)throw new Error('업로드 위치가 예상과 다릅니다. 다시 확인 후 같은 폴더로 이어가세요.');offset=reply.offset;entry.offset=offset;study.upload.uploaded_bytes=study.upload.files.reduce((n,f)=>n+f.offset,0);render();}
    }
    $('action-status').textContent='자료 업로드 완료. 확인·분할에서 원본 검사를 시작하세요.';panel('inspect');
  }catch(exc){error(`${exc.message} 다시 확인 후 같은 폴더로 업로드를 이어갈 수 있습니다.`);}
  finally{working=false;await refresh();availability();}
};
$('inspect-start').onclick=async()=>{if($('inspect-start').disabled)return;try{await mutate('inspect','/lerobot-inspect',{study_id:studyId,request_id:uuid()});await refresh();}catch{}};
$('split-save').onclick=async()=>{if($('split-save').disabled)return;try{const saved=await mutate('split','/lerobot-split',{study_id:studyId,source_revision:study.source_revision,...splitSelection(),request_id:uuid()});study=saved;dirty=false;splitSaved='';render();}catch{}};
$('train-start').onclick=async()=>{if($('train-start').disabled)return;try{await mutate('train','/lerobot-run',{study_id:studyId,split_revision:study.split.revision,steps:Number($('train-steps').value),batch_size:Number($('train-batch').value),seed:Number($('train-seed').value),request_id:uuid()});panel('results');await refresh();}catch{}};
$('active-stop').onclick=async()=>{if($('active-stop').disabled)return;const id=$('active-stop').dataset.run;$('active-stop').disabled=true;try{await request(API+'/stop',{id});$('action-status').textContent='중지를 요청했습니다. 현재 실행의 처리 결과를 확인하세요.';await refresh();}catch(exc){error(exc.message);}finally{availability();}};
function reset(){resourceGeneration++;study=null;selected=[];manifest=[];matched=false;inspectionKey=null;splitSaved='';dirty=false;resultSignature='';selectionGeneration++;$('source-folder').value='';$('study-name').value='';$('upload-status').textContent='선택한 자료가 없습니다.';$('upload-progress').value=0;$('upload-excluded').replaceChildren();error('');readPending();setURL();render();}
$('study-new').onclick=()=>{studyId='';reset();panel('upload');};
$('study-select').onchange=async()=>{studyId=$('study-select').value;reset();await refresh();};
$('study-name').oninput=availability;for(const id of ['train-steps','train-batch','train-seed'])$(id).oninput=availability;
$('imitate-refresh').onclick=refresh;
addEventListener('popstate',()=>{const u=new URL(location.href),id=u.searchParams.get('study')||'';if(id!==studyId){studyId=id;reset();refresh();}panel(u.searchParams.get('panel'));});
panel(new URL(location.href).searchParams.get('panel'));readPending();refresh();setInterval(()=>{if(!document.hidden&&!working)refresh();},5000);
