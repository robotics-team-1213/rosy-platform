// Prepared demonstrations and host training share the Learning workspace.
import {accountFetch} from '/account-session.js';
import {confirmIrreversible} from '/common/ui.js';
import '/commands.js';
import '/omx-review.js';
import {profileDocumentKey} from '/omx-profiles.js';
import {renderExportRun} from '/omx-export.js';
const $=id=>document.getElementById(id);
const VERDICT={ok:'맞음',adjust:'조정 필요',unmeasurable:'측정 불가'};
const SPLIT={train:'학습',eval:'평가',test:'시험',exclude:'제외'};
const OUTCOME={success:'성공',failure:'실패',unknown:'미정'};
let preparedSets=[],preparedReady=false,exportProfile=null,exporting=false,pendingExport=null,loadedReview=null,selectedProfileRecord=null;
const editors=new Set();
let editGeneration=0,preparedLoading=false,savesInFlight=0;
const pendingEdits=()=>[...editors].some(editor=>editor());
window.addEventListener('beforeunload',event=>{if(pendingEdits()){event.preventDefault();event.returnValue='';}});


function el(tag,text,cls){const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;}
function button(text,kind='quiet'){
  const node=el('ui-button',text);
  if(kind==='primary')node.setAttribute('kind','primary');
  else node.setAttribute('kind','quiet');
  return node;
}
function camera(checks){
  const roles=Object.entries(checks||{});
  if(!roles.length)return '기록 없음';
  return roles.map(([role,c])=>`${role}: ${VERDICT[c.before]||c.before} → ${VERDICT[c.after]||c.after}`).join(' · ');
}
function field(form,label,name,type='text',value=''){
  const wrapper=el('label',label+' ','ui-field-label'),input=el('input');
  input.name=name;input.type=type;input.value=value;input.className='ui-field';
  if(type==='number'){input.min=0;input.step=1;}
  wrapper.append(input);form.append(wrapper);return input;
}
function choice(form,label,name,options){
  const wrapper=el('label',label+' ','ui-field-label'),input=el('select');input.name=name;input.className='ui-field';
  input.setAttribute('aria-label',label);
  for(const [value,text] of options){const option=el('option',text);option.value=value;input.append(option);}
  wrapper.append(input);form.append(wrapper);return input;
}
function segmentReview(set,section){
  const detail=el('details',null,'omx-review'),summary=el('summary','파지 구간 검수');detail.append(summary);
  const status=el('p','원본을 선택하고 프레임 확인을 누르세요.','quiet'),saveStatus=el('ui-status'),selectionStatus=el('p',null,'quiet'),list=el('ol',null,'omx-segments'),form=el('form',null,'omx-editor');
  status.setAttribute('role','status');saveStatus.setAttribute('role','status');
  let saved=set.segment_review||{version:0,document:null},rows=structuredClone(saved.document?.segments||[]);
  let saving=false,draftDirty=false,saveError='';
  const rowsDirty=()=>JSON.stringify(rows)!==JSON.stringify(saved.document?.segments||[]);
  editors.add(()=>saving||draftDirty||rowsDirty());
  const sourcePanel=el('fieldset'),sourceFields=el('div',null,'omx-fields'),resultPanel=el('fieldset'),resultFields=el('div',null,'omx-fields');
  sourcePanel.append(el('legend','1. 원본을 보고 구간 선택'));
  const stage=el('div',null,'omx-stage'),placeholder=el('p','아직 원본 프레임을 확인하지 않았습니다.','quiet'),image=el('img');
  image.alt='선택한 원본 Episode의 카메라 프레임';image.hidden=true;stage.append(image,placeholder);
  sourcePanel.append(stage,status,sourceFields);resultPanel.append(el('legend','2. 구간 결과 확인'),resultFields);form.append(sourcePanel,resultPanel);
  const episode=choice(sourceFields,'원본 Episode','episode',set.episodes.map(e=>[String(e.episode_index),String(e.episode_index)]));
  const cameraKey=choice(sourceFields,'카메라','camera',set.camera_keys.map(k=>[k,k.replace('observation.images.','')]));
  const frame=field(sourceFields,'확인 프레임','frame','number','0'),preview=button('프레임 확인','primary');sourceFields.append(preview);
  const start=field(sourceFields,'시작 프레임 (포함)','start','number','0'),end=field(sourceFields,'끝 프레임 (제외)','end','number','1');
  const markStart=button('현재 프레임을 시작으로'),markEnd=button('현재 프레임 다음을 끝으로');
  const changed=()=>{draftDirty=true;editGeneration++;show();};
  markStart.type=markEnd.type='button';markStart.onclick=()=>{start.value=frame.value;};markEnd.onclick=()=>{end.value=Number(frame.value)+1;};
  markStart.addEventListener('click',changed);markEnd.addEventListener('click',changed);
  const markers=el('ui-actions');markers.append(markStart,markEnd);sourcePanel.append(markers,el('p','시작은 포함하고 끝은 제외합니다. 예: [2, 6)은 2~5번 프레임입니다.','quiet'));
  for(const label of ['대상 물체','검수자','관찰 근거']){
    const input=field(resultFields,label,{'대상 물체':'object','검수자':'reviewer','관찰 근거':'reason'}[label]);input.maxLength=1000;
    if(label!=='검수자')input.required=true;
  }
  choice(resultFields,'구간 결과','outcome',[['unknown','미판정'],['success','성공을 직접 확인함'],['failure','실패']]);
  choice(resultFields,'사람 개입','intervention',[['false','없음'],['true','있음']]);
  choice(resultFields,'분할','split',[['exclude','제외·보존'],['train','학습'],['eval','독립 평가'],['test','최종 시험']]);
  resultPanel.append(el('p','성공을 직접 확인하고 개입이 없는 구간만 학습·평가에 포함하세요. 나머지는 제외로 보존합니다. 계정 접속 시 검수자는 로그인한 사용자로 기록됩니다.','quiet'));
  const add=button('구간 추가','primary');add.type='submit';resultPanel.append(add);
  const save=button('검수 저장','primary'),download=button('선택 JSON 내려받기');
  form.addEventListener('input',event=>{editGeneration++;if(![frame,cameraKey].includes(event.target))draftDirty=true;show();});
  const updateBounds=()=>{
    const count=set.episodes.find(e=>String(e.episode_index)===episode.value).frames;
    frame.max=start.max=count-1;end.min=1;end.max=count;
  };updateBounds();
  let previewVersion=0;
  for(const input of [episode,cameraKey,frame])input.oninput=()=>{
    previewVersion++;image.hidden=true;placeholder.hidden=false;updateBounds();status.textContent='원본 선택이 바뀌었습니다. 프레임을 다시 확인하세요.';
  };
  preview.onclick=async()=>{const version=++previewVersion;try{
    const query=new URLSearchParams({id:set.id,episode:episode.value,frame:frame.value,camera:cameraKey.value});
    const response=await accountFetch('/api/learning/omx/frame?'+query);
    if(!response.ok)throw new Error((await response.json()).error||'프레임 확인 실패');
    const blob=await response.blob(),reader=new FileReader();
    const dataURL=await new Promise((resolve,reject)=>{
      reader.onload=()=>resolve(reader.result);
      reader.onerror=()=>reject(new Error('프레임 이미지를 읽지 못했습니다.'));
      reader.readAsDataURL(blob);
    });
    if(version!==previewVersion)return;
    image.src=dataURL;image.hidden=false;placeholder.hidden=true;
    status.textContent=`원본 Episode ${episode.value}, 프레임 ${frame.value}`;
  }catch(error){if(version!==previewVersion)return;image.hidden=true;placeholder.hidden=false;status.textContent=error.message;}};
  const show=()=>{
    list.replaceChildren(...rows.map((row,index)=>{
      const p=el('li'),text=el('span',`Episode ${row.episode_index}: [${row.start_frame}, ${row.end_frame}) · ${row.object} · ${OUTCOME[row.outcome]} · ${SPLIT[row.split]}`);
      const remove=button('삭제');remove.onclick=()=>{rows.splice(index,1);editGeneration++;saveError='';show();};p.append(text,remove);return p;
    }));
    const dirty=rowsDirty(),base=saved.version?`검수 ${saved.version} 저장됨.`:'저장된 검수가 없습니다.';
    save.disabled=saving||!dirty;save.reason=saving?'저장 응답을 기다리는 중입니다.':!dirty?'저장할 구간 변경이 없습니다.':'';
    download.disabled=saving||dirty||!saved.document;download.reason=download.disabled?'구간 변경을 저장한 뒤 내려받을 수 있습니다.':'';
    saveStatus.setAttribute('state',saveError?'error':saving?'pending':dirty||draftDirty?'warning':'ready');
    saveStatus.textContent=saveError||(saving?'저장 중입니다. 추가 편집은 계속할 수 있습니다.':`${base} ${dirty?'미저장 구간 변경이 있습니다.':`구간 ${rows.length}개.`} ${draftDirty?'입력 중인 내용은 구간 추가를 눌러야 저장 대상이 됩니다.':''}`);
    const counts=Object.fromEntries(Object.keys(SPLIT).map(key=>[key,(saved.document?.segments||[]).filter(row=>row.split===key).length]));
    selectionStatus.textContent=`저장된 구간 선택: ${Object.entries(counts).map(([key,count])=>`${SPLIT[key]} ${count}`).join(' · ')}. ${counts.train&&counts.eval?'독립 분할·원본 검증은 모델 PC 내보내기에서 수행합니다.':'학습 데이터 내보내기에는 독립 학습·평가 구간이 더 필요합니다.'}`;
  };
  form.onsubmit=event=>{
    event.preventDefault();const source=set.episodes.find(e=>String(e.episode_index)===episode.value),values=new FormData(form);
    const row=Object.fromEntries(['episode_index','content_sha256','frames','session_id','cycle_id'].filter(k=>source[k]!=null).map(k=>[k,source[k]]));
    Object.assign(row,{start_frame:Number(start.value),end_frame:Number(end.value),intervention:values.get('intervention')==='true'});
    for(const key of ['object','reviewer','reason','outcome','split'])row[key]=values.get(key);
    if(row.start_frame>=row.end_frame||row.end_frame>source.frames){saveError='시작보다 큰 끝 프레임을 원본 범위 안에서 선택하세요.';show();return;}
    if(rows.some(r=>r.episode_index===row.episode_index&&r.start_frame===row.start_frame&&r.end_frame===row.end_frame)){saveError='이미 추가한 원본 구간입니다.';show();return;}
    if(row.split!=='exclude'&&(row.outcome!=='success'||row.intervention)){saveError='미판정·실패·사람 개입 구간은 분할에서 제외·보존을 선택하세요.';show();return;}
    rows.push(row);draftDirty=false;saveError='';editGeneration++;show();
  };
  save.onclick=async()=>{if(saving||!rowsDirty())return;const submitted=JSON.stringify(rows);saving=true;savesInFlight++;editGeneration++;saveError='';show();try{
    const response=await accountFetch('/api/learning/omx/segments',{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':token},
      body:JSON.stringify({id:set.id,version:saved.version,segments:JSON.parse(submitted)})});
    const value=await response.json();if(!response.ok)throw new Error(value.error||'저장 실패');
    saved=value;if(JSON.stringify(rows)===submitted)rows=structuredClone(value.document.segments);
  }catch(error){saveError=`저장하지 못했습니다: ${error.message}. 입력 내용은 유지됩니다.`;}finally{saving=false;savesInFlight--;show();}};
  download.onclick=()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify(saved.document,null,2)+'\n'],{type:'application/json'}));
    const link=el('a');link.href=url;link.download=`omx-segments-${set.id}-v${saved.version}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const actions=el('ui-actions');actions.append(save,download);
  detail.append(form,el('h4','3. 구간 저장·내려받기'),saveStatus,selectionStatus,list,actions,el('p','선택 JSON은 검수 기록입니다. 실제 학습 데이터 내보내기는 모델 PC에서 수행합니다. 같은 원본·세션·cycle은 한 분할에만 둡니다. 원본 전체 시연의 결과는 바뀌지 않습니다.','quiet'));
  show();section.append(detail);
}
function render(set){
  const section=el('section',null,'learning-section');
  section.append(el('h3',set.name));
  if(set.error){const s=el('ui-status',set.error);s.setAttribute('state','error');section.append(s);return section;}
  if(set.episodes.length&&set.camera_keys?.length)segmentReview(set,section);
  const sourceInfo=el('details',null,'omx-source-info');sourceInfo.append(el('summary','원본 전체 시연 상태·메타데이터'));
  const t=set.trainable,status=el('ui-status',t.ok?`전체 시연 학습 가능 — ${Object.entries(t.counts).map(([k,v])=>`${SPLIT[k]||k} ${v}`).join(', ')}`:`전체 시연 학습 불가 — ${t.reason}`);
  status.setAttribute('state',t.ok?'ready':'warning');sourceInfo.append(status);
  const cs=set.camera_setup,native=Object.entries(set.camera_reference||{});
  for(const [role,r] of native){const p=el('p',`${role}: 기준 일치(prepare-native에서 거부 검사 통과) · 기준 `,'quiet omx-native-reference'),rev=String(r.revision).slice(0,12);
    if(r.reference&&/^[0-9a-f]{64}$/.test(r.revision)){const a=el('a',rev);a.href=`/api/learning/camera/stills/${r.revision}`;p.append(a);}else p.append(rev);sourceInfo.append(p);}
  if(cs)sourceInfo.append(el('p',`섀도 증거(prepare 프레임 비교, 거부하지 않음): ${Object.entries(cs.references||{}).map(([r,v])=>`${r} ${String(v).slice(0,8)}`).join(', ')} (${cs.mode})`,'quiet omx-shadow-reference'));
  if(!cs&&!native.length)sourceInfo.append(el('p','카메라 맞춤 판정 없음 — prepare에 --camera-reference를 주면 기록됩니다.','quiet'));
  const table=el('table',null,'omx-episodes'),head=el('tr');
  ['Episode','세션','프레임','분할','결과','검수자','이유','카메라(시작 → 끝)'].forEach(h=>head.append(el('th',h)));
  table.append(el('thead'));table.tHead.append(head);
  const body=el('tbody');
  for(const e of set.episodes){
    const row=el('tr');
    [e.episode_index,e.session_id,e.frames,SPLIT[e.split]||e.split,OUTCOME[e.outcome]||e.outcome,e.reviewer||'—',e.reason||'—',camera(e.camera)]
      .forEach(v=>row.append(el('td',v==null?'—':String(v))));
    body.append(row);
  }
  table.append(body);
  const wrap=el('div',null,'omx-table-wrap');wrap.append(table);sourceInfo.append(wrap);section.append(sourceInfo);
  return section;
}
async function load(){
  if(preparedLoading)return;
  if(savesInFlight){$('omx-status').textContent='저장 응답을 기다린 뒤 다시 확인하세요.';return;}
  if(pendingEdits()&&!await confirmIrreversible({message:'미저장 구간 또는 입력이 있습니다. 다시 불러오면 현재 편집을 잃습니다.',action:'편집 버리고 다시 확인',opener:$('refresh')}))return;
  const generation=editGeneration;preparedLoading=true;$('refresh').disabled=true;
  $('omx-status').setAttribute('state','pending');$('omx-status').textContent='불러오는 중입니다.';
  try{
    token=(await (await accountFetch('/api/workspace')).json()).token;
    const response=await accountFetch('/api/learning/omx');
    const value=await response.json();
    if(!response.ok)throw new Error(response.status===403?'이 작업대의 권한이 거부되었습니다.':value.error||'요청 실패');
    if(generation!==editGeneration){$('omx-status').setAttribute('state','warning');$('omx-status').textContent='불러오는 동안 편집이 바뀌어 기존 화면을 보존했습니다. 필요하면 다시 확인하세요.';return;}
    preparedSets=value.sets;preparedReady=true;
    const selected=$('prepared-set').value;
    $('prepared-set').replaceChildren(...(preparedSets.length?preparedSets.map(set=>{const option=el('option',set.name);option.value=set.id;return option;}):[new Option('등록된 검수 시연 없음','')]));
    if(preparedSets.some(set=>set.id===selected))$('prepared-set').value=selected;
    if(!preparedSets.length)$('prepared-set').value='';
    $('prepared-set').disabled=!preparedSets.length;exportSelection();
    $('empty-prepared').hidden=!!preparedSets.length;
    document.dispatchEvent(new CustomEvent('omx-prepared-loaded'));
    editors.clear();$('sets').replaceChildren(...value.sets.map(render));
    $('omx-status').setAttribute('state',value.sets.length?'ready':'empty');
    $('omx-status').textContent=value.sets.length?`세트 ${value.sets.length}개`:'연결된 OMX 준비 세트가 없습니다.';
  }catch(error){preparedReady=false;exportSelection();$('omx-status').setAttribute('state','error');$('omx-status').textContent=error.message||String(error);}
  finally{preparedLoading=false;$('refresh').disabled=false;}
}
const CENTER='/api/learning/omx/center';
const STAGES=[
  ['profile-panel','무엇을 성공으로 볼까요?','과제와 성공·실패·초기화 조건을 먼저 고정해야 두 학습 방법을 같은 과제로 비교할 수 있습니다. 팔과 카메라의 위치·역할도 이 조건의 일부입니다.','확인할 근거: 과제와 입력 설정을 저장하고, 사용할 저장 프로필을 명시적으로 선택합니다.','이후 현장 상태 확인'],
  ['owner-section','이 작업대에서 준비를 이어갈 수 있나요?','올바른 작업대와 팔의 관측 상태를 확인합니다. 상태 조회만으로 제어권이나 실물 실행 준비를 판단할 수는 없습니다.','확인할 근거: 선택한 작업대의 관측 결과와 제어 연결 여부. 연결되지 않은 항목은 현장 준비가 더 필요합니다.','이후 시범 수집 준비'],
  ['capture-section','어떤 시범과 교정 경험을 남길까요?','영상만 저장하면 행동을 배울 수 없습니다. 리더 입력, 실제 적용 행동, 시도 결과가 같은 시점 기준으로 묶여야 합니다.','확인할 근거: 영상·상태·행동·개입·종료·초기화가 기록된 시연. 현재 현장 수집 제어 연결은 별도로 필요합니다.','기존 시연을 검수하기'],
  ['dataset-section','이 시연을 학습에 쓸 수 있나요?','프레임과 결과를 사람이 확인하고 학습·평가 자료를 나눕니다. 평가에 쓸 시도를 학습에 섞으면 개선을 판단하기 어렵습니다.','확인할 근거: 저장된 검수 결정, 분할 기록과 검증을 통과한 학습 데이터. 과제·팔·카메라 선언이 선택한 설정과 일치해야 합니다.','이후 성공 판정 확인'],
  ['reward-section','로봇의 성공과 다음 시도의 시작을 어떻게 정할까요?','HIL-SERL이 잘못된 성공 판정을 배우지 않도록 놓침·가림·낙하를 구분하고, 같은 초기 상태로 돌아갈 방법을 정합니다.','확인할 근거: 성공·실패 오판 검수와 초기화 절차. 현재 보상 분류기·현장 초기화 연결은 별도입니다.','준비한 데이터로 학습 설정'],
  ['train-section','어떤 경험으로 정책을 개선할까요?','ACT는 시범·교정 행동을, SAC는 결과가 포함된 전이를 사용합니다. 같은 초기 데이터를 선택하고 학습 범위와 예산을 확인하세요.','확인할 근거: 접수된 작업, 소비한 입력, 저장 정책과 평가. 현재 호스트 학습은 현장 actor의 직접 시도를 대신하지 않습니다.','저장된 평가를 비교하기'],
  ['comparison-section','무엇이 좋아졌고 다음에 무엇을 바꿀까요?','같은 초기 자료와 팔 범위의 결과를 비교합니다. 행동 오차와 실물 성공률을 구분하고, 사람 개입·초기화·낙하·작업 시간을 함께 판단합니다.','확인할 근거: 같은 조건의 평가와 별도 실물 시험 기록. 결과가 없거나 조건이 다르면 우열을 정하지 않습니다.','과제 조건을 다시 검토하기']
];
let centerReady=false;
function updateJourney(){
  const row=snapshot.datasets.find(d=>d.id===$('dataset').value),profile=selectedProfileRecord?.profile||row?.profile;
  $('journey-goal').textContent=profile?.task?`${profile.name||'선택한 과제'} · ${profile.task}`:'과제는 아직 선택하지 않았습니다.';
  $('journey-data').textContent=row?`현재 데이터: ${row.name} · 작업 팔 ${(row.profile?.arms||[]).length}대 · 카메라 ${(row.profile?.cameras||[]).length}개`:'현재 선택된 학습 데이터가 없습니다.';
  let target='profile-panel',label='과제와 성공 조건 정하기',reason='같은 과제를 비교하려면 목표와 성공 조건을 먼저 정하고 저장 설정을 선택하세요.';
  if(!centerReady){reason='학습 데이터 상태를 아직 확인하지 못했습니다. 다시 확인한 뒤 다음 작업을 결정하세요.';}
  else if(profile?.task){
    if(selectedProfileRecord&&row&&profileDocumentKey(profile)!==profileDocumentKey(row.profile)){
      target='dataset-section';label='과제와 일치하는 데이터 선택';reason='선택한 설정과 데이터의 과제·팔·카메라 선언이 다릅니다. 이 조합으로는 학습할 수 없습니다.';
    }else if(!row){
      target=preparedSets.length?'dataset-section':'capture-section';label=preparedSets.length?'등록 시연 검수·변환':'시범과 교정 기록 준비';reason='선택한 과제의 학습 데이터가 필요합니다. 현장 수집 연결 여부를 확인하거나 이미 수집한 시연을 연결하세요.';
    }else{
      const runs=snapshot.runs.filter(run=>run.dataset_id===row.id&&run.execution_mode!=='native_export'&&matchingTarget(run,row));
      const active=runs.some(run=>['running','queued'].includes(run.status));
      if(active){target='train-section';label='진행 중인 학습 확인';reason='현재 데이터에서 시작한 학습이 있습니다. 소비한 입력과 작업 상태를 확인하세요.';}
      else if(runs.some(run=>run.result?.evaluation)){target='comparison-section';label='같은 조건의 저장 평가 비교';reason='현재 데이터와 팔 범위의 평가가 있습니다. 실제 성공률은 별도 실물 시험 기록으로 확인해야 합니다.';}
      else{target='train-section';label='학습 방법과 실행 조건 확인';reason='선택한 데이터로 학습을 준비할 수 있습니다. 학습기 가용 상태와 입력 범위를 확인한 뒤 직접 시작하세요.';}
    }
  }
  $('journey-reason').textContent=reason;$('journey-next').textContent=label;$('journey-next').href='#'+target;
}
async function loadLearningEntry(){
  const status=$('learning-account-state');
  try{
    const options=await request('/api/accounts/options');
    if(!options.enabled){status.textContent='계정 서버 연결 준비 중입니다. 로그인 화면에서 연결 상태를 확인할 수 있습니다.';return;}
    const session=await request('/api/accounts/session');
    status.textContent=`로그인: ${session.user_id} · Hugging Face 연결 계정 ${(session.connections||[]).length}개. 계정·외부 자료 화면에서 사용할 연결을 확인하세요.`;
  }catch(exc){status.textContent='로그인 상태를 확인할 수 없습니다. 계정 화면에서 로그인과 연결을 확인하세요.';}
}
function showSection(){
  const requested=document.getElementById(location.hash.slice(1));
  const stage=STAGES.find(([key])=>requested&&(requested.id===key||$(key).contains(requested)))||STAGES[0];
  const [id,question,purpose,done,next]=stage,target=requested&&$(id).contains(requested)?requested:$(id);
  const all=new URLSearchParams(location.search).get('view')==='all';
  for(const [key] of STAGES)$(key).hidden=!all&&key!==id;
  $('sets').parentElement.hidden=!all&&id!=='dataset-section';
  $('stage-question').textContent=question;$('stage-purpose').textContent=purpose;$('stage-done').textContent=done;
  $('stage-next').href='#'+STAGES[(STAGES.indexOf(stage)+1)%STAGES.length][0];$('stage-next').textContent=next;
  $('workflow-view').textContent=all?'단계별 작업으로 돌아가기':'전체 도구 펼쳐 보기';$('workflow-view').href=all?'?'+location.hash:'?view=all'+location.hash;
  for(const link of $('omx-sections').querySelectorAll('a')){
    if(link.getAttribute('href')==='#'+id)link.setAttribute('aria-current','location');
    else link.removeAttribute('aria-current');
  }
  if(all&&!location.hash)return;
  for(let node=target;node&&node!==$('omx-main');node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
  if(!location.hash)return;
  const focus=id==='profile-panel'?$('profile-task'):target;
  if(focus===target)target.tabIndex=-1;
  focus.focus({preventScroll:true});$('stage-question').scrollIntoView({block:'start'});
  window.scrollBy({top:-document.querySelector('ui-topbar').getBoundingClientRect().height,behavior:'instant'});
}
$('omx-main').addEventListener('click',event=>{
  const link=event.target.closest('a[href^="#"]');
  if(link&&link.hash===location.hash)showSection();
});
window.addEventListener('hashchange',showSection);
window.addEventListener('popstate',showSection);
$('workflow-view').onclick=event=>{event.preventDefault();history.pushState(null,'',$('workflow-view').href);showSection();};
window.addEventListener('pageshow',showSection);
if(document.readyState==='complete')showSection();
const OWNER_STATE={disabled:'비활성',ready:'대기',active:'실행 중',hold:'보류'};
let ownerRequest=0,ownerTargetsKey='';
function clearOwner(message,state='warning'){
  $('owner-status').textContent=message;$('owner-status').setAttribute('state',state);
  $('owner-details').textContent='';
}
function ownerTargets(meta){
  const targets=meta?.configured&&Array.isArray(meta.targets)?meta.targets:[];
  const key=JSON.stringify(targets);
  if(key!==ownerTargetsKey){
    const selected=$('owner-target').value;
    ownerTargetsKey=key;ownerRequest++;
    $('owner-target').replaceChildren(...(targets.length?targets.map(target=>{
      const option=el('option',`${target.workcell_id} · ${target.instance_id}`);
      option.value=target.workcell_id;return option;
    }):[new Option('상태 연결 설정 없음','')]));
    if(targets.some(target=>target.workcell_id===selected))$('owner-target').value=selected;
    clearOwner('현장 상태를 다시 확인합니다.');
  }
  $('owner-target').disabled=!targets.length;$('owner-refresh').disabled=!targets.length;
  if(!targets.length)clearOwner('현장 상태 연결이 설정되지 않았습니다. 담당자가 작업대와 읽기 전용 연결을 설정해야 합니다.');
  else refreshOwner();
}
async function refreshOwner(){
  const target=$('owner-target').value;
  if(!target)return;
  const current=++ownerRequest;
  clearOwner('현장 상태를 조회하는 중입니다.','pending');$('owner-refresh').disabled=true;
  try{
    const value=await request(CENTER+'/owner-status/'+encodeURIComponent(target));
    if(current!==ownerRequest||target!==$('owner-target').value)return;
    if(value.status!=='observed'||value.workcell_id!==target||!OWNER_STATE[value.owner?.state]){
      clearOwner(value.reason==='VIEWER_CREDENTIAL_UNAVAILABLE'?'읽기 전용 인증 연결을 확인하세요.':'현장 상태를 조회할 수 없습니다. 연결과 작업대 설정을 확인하세요.');return;
    }
    clearOwner(`최근 조회 상태: ${OWNER_STATE[value.owner.state]} · ${value.instance_id}`,'ready');
    $('owner-details').textContent=`관측 순번 ${value.owner.observed_sequence??'없음'} · 조회 완료 ${value.received_at} · 원인 ${value.owner.reason??'없음'}`;
  }catch(exc){if(current===ownerRequest)clearOwner('현장 상태를 조회할 수 없습니다. 다시 확인하세요.');}
  finally{if(current===ownerRequest)$('owner-refresh').disabled=false;}
}
$('owner-target').onchange=()=>refreshOwner();
$('owner-refresh').onclick=()=>refreshOwner();
document.addEventListener('visibilitychange',()=>{
  if(document.hidden){ownerRequest++;clearOwner('화면을 떠나 자동 조회를 멈췄습니다. 다시 열면 확인합니다.');}
  else refreshOwner();
});
const STATE={launching:'시작 중',queued:'대기',running:'학습 중',stopping:'중지 중',stopped:'중지됨',cancelled:'취소됨',completed:'완료',succeeded:'완료',failed:'실패',interrupted:'중단됨'};
let snapshot={datasets:[],runs:[],methods:{}},token='',submitting=false,pendingRequest=null,loading=false,uploading=false,addingExperience=false,pendingExperience=null,targetDataset='';
function error(message){$('center-error').hidden=!message;$('center-error').textContent=message||'';}
async function request(path,body){
  const options={cache:'no-store'};
  if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-Pinky-Token':token};options.body=JSON.stringify(body);}
  const response=await accountFetch(path,options),value=await response.json();
  if(!response.ok)throw new Error(value.error||`요청 실패 (${response.status})`);
  return value;
}
function describe(value){return typeof value==='string'?value:JSON.stringify(value??'미확인');}
function exportSelection(){
  const prepared=preparedSets.find(set=>set.id===$('prepared-set').value);
  const saved=loadedReview?.prepared_id===prepared?.id&&loadedReview?.latest_review_id;
  const savedPending=$('export-saved-review').checked&&(loadedReview?.dirty||loadedReview?.saving);
  $('export-saved-review').disabled=!saved;
  if(!saved)$('export-saved-review').checked=false;
  $('export-review-status').textContent=$('export-saved-review').checked?`저장 검수 ${saved} 사용 · 원본 revision ${loadedReview.source_revision}${savedPending?' · 미저장 편집 또는 검수 처리 중입니다. 저장·다시 불러오기를 마치거나 원본 검수 사용을 선택하세요.':''}`:`원본 검수 결정 사용${saved?' · 저장 검수 '+saved+'를 사용하려면 위 항목을 선택하세요.':' · 저장 검수는 검수를 불러온 뒤 선택할 수 있습니다.'}`;
  $('prepared-status').textContent=!preparedReady?'등록 자료 연결을 다시 확인하세요.':!prepared?'검수 시연을 자료 등록 화면에서 연결하세요.':prepared.trainable?.ok?'검수 분할 준비됨 · 실제 변환 입력은 서버가 다시 검증합니다.':`변환 준비 안 됨: ${prepared.error||prepared.trainable?.reason||'검수·분할을 확인하세요.'}`;
  $('native-export').disabled=exporting||savedPending||!token||!preparedReady||!prepared?.trainable?.ok||!exportProfile||!$('export-name').value.trim();
}
function onlineReady(row){return row?.profile?.schema==='rosy.omx.learning-profile/2';}
function needsArm(dataset){return dataset?.profile?.mode==='independent'&&dataset.profile.arms?.length>1;}
function configureTarget(dataset){
  const select=$('arm-target'),previous=targetDataset===dataset?.id?select.value:'',required=needsArm(dataset),old=select.value;
  $('arm-target-field').hidden=!required;select.disabled=!required;select.required=required;
  const placeholder=el('option','학습 팔을 선택하세요');placeholder.value='';
  select.replaceChildren(placeholder,...(required?dataset.profile.arms.map(arm=>{const option=el('option',arm.id);option.value=arm.id;return option;}):[]));
  select.value=required&&dataset.profile.arms.some(arm=>arm.id===previous)?previous:'';
  targetDataset=dataset?.id||'';if(old!==select.value)pendingRequest=null;
  $('arm-target-status').textContent=required?`${select.value?'선택 팔 '+select.value:'개별 학습 팔 선택 필요'} · 선택 팔의 입력과 소속·공유 카메라를 사용합니다. 보상·종료 신호는 서버가 검증합니다.`:
    dataset?.profile?.mode==='cooperative'?'협동 모드 · 전체 팔과 공동 입력을 사용합니다.':'단일 팔 또는 전체 입력 · 서버가 학습 범위를 검증합니다.';
}
function trainingScope(run){return run.result?.training_scope||run.training_scope;}
function targetLabel(run){
  const scope=trainingScope(run);
  if(scope)return `${scope.mode==='independent'?'개별 팔':'협동 전체'} ${(scope.arm_ids||[]).join(', ')}`;
  return run.arm_id?`요청 팔 ${run.arm_id} · 실행 대상 미기록`:'입력 범위 기록 없음';
}
function matchingTarget(run,dataset){
  const scope=trainingScope(run);
  if(needsArm(dataset))return scope?.mode==='independent'&&profileDocumentKey(scope.arm_ids)===profileDocumentKey([$('arm-target').value]);
  if(!scope)return true;
  return scope.mode===dataset.profile?.mode&&profileDocumentKey(scope.arm_ids)===profileDocumentKey((dataset.profile.arms||[]).map(arm=>arm.id));
}
function selection(){
  const online=$('execution-mode').value==='online_experience';
  $('method').querySelector('[value="act"]').disabled=online;
  if(online)$('method').value='hilserl';
  $('execution-description').textContent=online?'지속 SAC는 새로 추가한 경험을 받아 CPU 학습을 이어가고, 입력이 없으면 기다립니다. 학습 단계는 입력마다 수행할 단계 수입니다.':'저장된 시범·교정·전이를 CPU로 재학습합니다.';
  const row=snapshot.datasets.find(d=>d.id===$('dataset').value),area=$('dataset-profile');area.replaceChildren();
  configureTarget(row);
  document.dispatchEvent(new CustomEvent('omx-dataset-profile',{detail:row?.profile||null}));
  if(row){
    const profile=row.profile||{};
    area.append(el('p',`${profile.task||'과제 설명 없음'} · 작업 팔 ${(profile.arms||[]).length}대 · 카메라 ${(profile.cameras||[]).length}개`));
    const details=el('details'),summary=el('summary','자료 출처·버전과 전체 입력 프로필');details.append(summary,el('p',`출처: ${describe(row.source)} · revision: ${describe(row.revision)}`),el('pre',JSON.stringify(profile,null,2)));area.append(details);
    if(/synthetic|smoke/i.test(JSON.stringify({source:row.source,profile})))area.append(el('p','합성 스모크 자료입니다. 실물 수집·개입·성공 증거가 아닙니다.','quiet'));
  }
  const method=snapshot.methods[$('method').value];
  const compatible=!selectedProfileRecord||profileDocumentKey(selectedProfileRecord.profile)===profileDocumentKey(row?.profile);
  $('profile-clear').disabled=!selectedProfileRecord;
  $('selected-profile-status').textContent=!selectedProfileRecord?'저장 프로필 선택 없음 · 등록 데이터의 입력 프로필을 사용합니다.':
    `저장 프로필 ${selectedProfileRecord.id} · revision ${selectedProfileRecord.revision} · `+(!row?'학습 데이터를 선택하세요.':compatible?'등록 데이터의 입력 선언과 일치합니다.':'학습 불가: 현재 데이터의 입력 선언(이름·과제·팔·카메라·배치)과 다릅니다. 일치하는 자료를 선택하거나 저장 프로필 선택을 해제하세요.');
  $('method-status').textContent=method?.available?(online?'지속 SAC·경험 수신 실행기 준비됨':'오프라인 경험 학습 실행기 준비됨'):`실행 불가: ${method?.reason||method?.error||'실행기 준비를 확인하세요.'}`;
  const needsBounds=!!row&&!onlineReady(row);
  if(online&&needsBounds)$('method-status').textContent='지속 SAC는 관절별 고정 action_limits가 검증된 프로필 schema 2 자료가 필요합니다. 기존 자료는 오프라인 재학습에서 사용할 수 있습니다.';
  $('start').disabled=submitting||!token||!row||!method?.available||(online&&needsBounds)||!compatible||(needsArm(row)&&!$('arm-target').value);
  $('add-experience').disabled=addingExperience||!token||!row||needsBounds||!$('experience-run').value;
  if($('experience-run').value&&needsBounds)$('experience-status').textContent='경험 추가에는 관절별 고정 action_limits가 있는 프로필 schema 2 자료를 선택하세요.';
  renderComparison(row);
  exportSelection();
  updateJourney();
}
function renderComparison(dataset){
  const area=$('comparison');area.replaceChildren();
  if(!dataset){area.append(el('p','초기 학습 데이터를 선택하면 같은 자료에서 시작한 작업의 평가를 볼 수 있습니다.','quiet'));return;}
  if(needsArm(dataset)&&!$('arm-target').value){area.append(el('p','학습 팔을 선택하면 같은 팔의 입력 범위가 기록된 평가만 비교합니다.','quiet'));return;}
  const runs=snapshot.runs.filter(run=>run.execution_mode!=='native_export'&&run.dataset_id===dataset.id&&run.result?.evaluation&&matchingTarget(run,dataset));
  if(!runs.length){area.append(el('p','선택한 초기 데이터에 저장된 평가 결과가 없습니다. 정책과 평가가 저장되면 표시됩니다.','quiet'));return;}
  const table=el('table',null,'omx-episodes');
  table.append(el('caption',`동일 초기 데이터: ${dataset.name}${needsArm(dataset)?' · 개별 팔 '+$('arm-target').value:''} · 저장된 평가 ${runs.length}개`));
  const head=el('thead'),headers=el('tr');
  for(const text of ['방법·작업','학습 입력 범위','자료 출처','상태','학습 단계','누적 입력','평가 프레임','행동 MAE','학습 평균 기준 MAE','시범 프레임','롤아웃 프레임','현장 성공','사람 개입 시간','초기화 횟수','낙하 횟수','사이클 시간']){
    const cell=el('th',text);cell.scope='col';headers.append(cell);
  }
  head.append(headers);table.append(head);
  const body=el('tbody');
  for(const run of runs){
    const result=run.result,evaluation=result.evaluation,replay=result.replay||{};
    const online=run.execution_mode==='online_experience',version=result.version??run.progress?.latest_version;
    const label=online?`지속 SAC · 정책 버전 ${version??'미수집'}`:run.method==='act'?'ACT 시범/교정':'SAC 오프라인 재학습';
    const row=el('tr'),method=el('th');method.scope='row';method.append(el('span',label),el('p',run.id,'quiet'));row.append(method);
    const total=result.total_steps??result.steps??run.steps;
    const inputs=result.inputs??run.progress?.consumed_inputs;
    const values=[targetLabel(run),result.source??dataset.source,STATE[run.status]||run.status,
      online?`${total??'미수집'} (입력당 ${run.steps})`:total,
      online?(Array.isArray(inputs)?`초기 포함 ${inputs.length}개`:'미수집'):'초기 자료만',
      evaluation.frames,evaluation.action_mae,evaluation.constant_train_mean_mae,
      replay.demonstration_frames,replay.rollout_frames,'미검증','미수집','미수집','미수집','미수집'];
    for(const value of values)row.append(el('td',value==null?'미수집':String(value)));
    body.append(row);
  }
  table.append(body);
  const wrap=el('div',null,'omx-table-wrap');wrap.append(table);area.append(wrap);
  if(runs.length===1)area.append(el('p','평가 기록이 1개입니다. 같은 초기 자료의 다른 학습 결과가 저장되면 함께 표시됩니다.','quiet'));
}
function renderRuns(){
  const selected=$('experience-run').value,live=snapshot.runs.filter(run=>run.execution_mode==='online_experience'&&run.status==='running');
  $('experience-run').replaceChildren(...(live.length?live.map(run=>{const option=el('option',run.id);option.value=run.id;return option;}):[el('option','실행 중인 지속 SAC 작업 없음')]));
  if(live.some(run=>run.id===selected))$('experience-run').value=selected;
  if(!live.length)$('experience-run').value='';
  $('experience-run').disabled=!live.length;
  const conversions=snapshot.runs.filter(run=>run.execution_mode==='native_export').map(run=>renderExportRun(run,{states:STATE,request,refresh:refreshCenter,
    selectDataset:id=>{$('dataset').value=id;pendingRequest=null;selection();}}));
  $('export-runs').replaceChildren(...(conversions.length?conversions:[el('p','변환 기록이 없습니다. 검수할 시연과 프로필을 선택하세요.','quiet')]));
  const nodes=snapshot.runs.filter(run=>run.execution_mode!=='native_export').map(run=>{
    const online=run.execution_mode==='online_experience',section=el('section',null,'learning-section');
    section.append(el('h3',`${online?'지속 SAC·경험 수신':run.method==='act'?'ACT 시범/교정':'HIL-SERL SAC 오프라인 재학습'} · ${STATE[run.status]||run.status}`));
    section.append(el('p',`작업 ${run.id} · 데이터 ${run.dataset_id}`,'quiet'));
    section.append(el('p',targetLabel(run)));
    if(trainingScope(run)){const details=el('details');details.append(el('summary','학습 입력 범위 기록'),el('pre',JSON.stringify(trainingScope(run),null,2)));section.append(details);}
    const progress=run.progress??{};
    if(online){
      const phase={waiting_for_experience:'경험 대기 중',training:'학습 중'}[progress.phase]||progress.phase||'상태 확인 중';
      section.append(el('p',`${phase} · 누적 학습 ${progress.total_steps??0}단계 · 정책 버전 ${progress.latest_version??'저장 전'}`));
      const inputs=run.inputs||[],counts=status=>inputs.filter(input=>input.status===status).length;
      section.append(el('p',`접수된 입력 ${inputs.length}개 · 입력 대기 ${counts('queued')}개 · 소비 ${counts('consumed')}개 · 거절 ${counts('rejected')}개`));
      if(inputs.length){const details=el('details'),summary=el('summary','입력 대기열·처리 결과');details.append(summary,el('pre',JSON.stringify(inputs,null,2)));section.append(details);}
      for(const [label,items] of [['소비한 입력',progress.consumed_inputs],['거절된 입력',progress.input_errors]]){
        section.append(el('p',`${label} ${Array.isArray(items)?items.length:0}개`));
        for(const item of items||[])section.append(el('pre',describe(item)));
      }
    }
    section.append(el('p',`목표 ${run.steps}단계 · 현재 기록: ${describe(progress)}`));
    if(run.error)section.append(el('p',describe(run.error)));
    if(run.result){const details=el('details'),summary=el('summary','저장·평가 결과');details.append(summary,el('pre',JSON.stringify(run.result,null,2)));section.append(details);}
    if(run.status==='succeeded'||(online&&progress.latest_version!=null)){const link=el('a',online?'최신 저장 정책·입력·평가 내려받기':'모델·입력 프로필·정규화·평가 내려받기');link.href=CENTER+'/artifact/'+encodeURIComponent(run.id);link.download=`omx-${run.id}.zip`;section.append(link);}
    if(['queued','running'].includes(run.status)){
      const stop=el('ui-button','이 학습 중지');stop.type='button';stop.setAttribute('kind','quiet');
      stop.onclick=async()=>{stop.disabled=true;try{await request(CENTER+'/stop',{id:run.id});await refreshCenter();}catch(exc){error(exc.message);stop.disabled=false;}};section.append(stop);
    }
    return section;
  });
  $('runs').replaceChildren(...(nodes.length?nodes:[el('p','학습 기록이 없습니다. 데이터를 선택하고 학습을 시작하세요.','quiet')]));
}
async function refreshCenter(){
  if(loading)return;loading=true;
  try{
    if(!token)token=(await request('/api/learning')).token;
    snapshot=await request(CENTER);centerReady=true;
    ownerTargets(snapshot.owner_status);
    const selected=$('dataset').value;
    $('dataset').replaceChildren(...(snapshot.datasets.length?[new Option('이번 과제의 데이터를 선택하세요',''),...snapshot.datasets.map(row=>{const option=el('option',row.name);option.value=row.id;return option;})]:[new Option('등록된 학습 데이터 없음','')]));
    $('dataset').value=snapshot.datasets.some(row=>row.id===selected)?selected:'';
    $('dataset').disabled=!snapshot.datasets.length;
    $('empty-datasets').hidden=!!snapshot.datasets.length;
    renderRuns();selection();
    $('center-status').setAttribute('state','ready');$('center-status').textContent=`데이터 ${snapshot.datasets.length}개 · 작업 ${snapshot.runs.length}개 · ${new Date().toLocaleTimeString('ko-KR')} 확인`;
  }catch(exc){centerReady=false;updateJourney();ownerRequest++;clearOwner('학습센터 연결을 확인한 뒤 현장 상태를 다시 조회하세요.');$('center-status').setAttribute('state','error');$('center-status').textContent='실행기 연결을 확인하세요.';$('start').disabled=true;error(exc.message);}
  finally{loading=false;}
}
function uuid(){
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
$('prepared-set').onchange=()=>{pendingExport=null;exportSelection();};
$('export-saved-review').onchange=()=>{pendingExport=null;exportSelection();};
document.addEventListener('omx-review-loaded',event=>{if(loadedReview?.prepared_id!==event.detail.prepared_id)$('export-saved-review').checked=false;loadedReview=event.detail;pendingExport=null;exportSelection();});
document.addEventListener('omx-review-saved',()=>{load();refreshCenter();});
$('export-name').oninput=()=>{pendingExport=null;exportSelection();};
$('export-profile').onchange=async()=>{
  exportProfile=null;selectedProfileRecord=null;$('export-profile').required=true;pendingExport=null;pendingRequest=null;selection();
  const file=$('export-profile').files[0];
  if(!file){$('export-status').textContent='프로필 JSON 파일을 선택하세요.';return;}
  try{
    if(file.size>1024*1024)throw new Error('프로필 JSON은 1 MiB 이하여야 합니다.');
    const profile=JSON.parse(await file.text());
    if(!profile||typeof profile!=='object'||Array.isArray(profile))throw new Error('프로필은 JSON 객체여야 합니다.');
    if($('export-profile').files[0]!==file)return;
    exportProfile=profile;$('export-status').textContent='프로필 파일을 읽었습니다. 대응과 단위는 서버가 검증합니다.';
  }catch(exc){$('export-status').textContent=exc.message||'올바른 프로필 JSON 객체를 선택하세요.';}
  exportSelection();
};
document.addEventListener('omx-profile-selected',event=>{
  selectedProfileRecord=event.detail;exportProfile=structuredClone(event.detail.profile);pendingExport=null;pendingRequest=null;
  $('export-profile').value='';$('export-profile').required=false;
  $('export-status').textContent=`저장 프로필 ${event.detail.id} · revision ${event.detail.revision} 선택됨. 현재 native 변환 지원 조건은 별도로 검증합니다.`;selection();
});
$('profile-clear').onclick=()=>{
  selectedProfileRecord=null;exportProfile=null;pendingRequest=null;pendingExport=null;$('export-profile').required=true;
  $('export-status').textContent='저장 프로필 선택을 해제했습니다. 변환하려면 프로필 파일을 선택하거나 저장 프로필을 다시 선택하세요.';selection();
};
$('native-export-form').onsubmit=async event=>{
  event.preventDefault();if(exporting||$('native-export').disabled)return;
  exporting=true;exportSelection();error('');
  pendingExport??={prepared_id:$('prepared-set').value,name:$('export-name').value.trim(),profile:exportProfile,request_id:uuid()};
  if($('export-saved-review').checked)pendingExport.review_id=loadedReview.latest_review_id;
  if(selectedProfileRecord)pendingExport.profile_id=selectedProfileRecord.id;
  try{await request(CENTER+'/export',pendingExport);pendingExport=null;$('export-status').textContent='변환 작업을 접수했습니다. 아래 실제 검증·변환 상태를 확인하세요.';await refreshCenter();}
  catch(exc){$('export-status').textContent=`변환 접수 응답: ${exc.message} · 같은 입력으로 다시 시도할 수 있습니다.`;error(exc.message);}
  finally{exporting=false;exportSelection();}
};
$('dataset').onchange=()=>{pendingRequest=null;selection();};
$('arm-target').onchange=()=>{pendingRequest=null;selection();};
$('method').onchange=()=>{pendingRequest=null;selection();};
$('execution-mode').onchange=()=>{pendingRequest=null;selection();};
$('experience-run').onchange=()=>{pendingExperience=null;selection();};
$('train-form').oninput=()=>{pendingRequest=null;};
$('train-form').onsubmit=async event=>{
  event.preventDefault();if(submitting||$('start').disabled)return;
  submitting=true;selection();error('');
  pendingRequest??={dataset_id:$('dataset').value,method:$('method').value,steps:Number($('steps').value),batch_size:Number($('batch-size').value),device:'cpu',seed:0,request_id:uuid()};
  if(selectedProfileRecord)pendingRequest.profile_id=selectedProfileRecord.id;
  if(needsArm(snapshot.datasets.find(row=>row.id===$('dataset').value)))pendingRequest.arm_id=$('arm-target').value;
  const route=$('execution-mode').value==='online_experience'?'/online-run':'/run';
  try{await request(CENTER+route,pendingRequest);pendingRequest=null;await refreshCenter();}catch(exc){error(exc.message);}
  finally{submitting=false;selection();}
};
$('experience-form').onsubmit=async event=>{
  event.preventDefault();if(addingExperience||$('add-experience').disabled)return;
  addingExperience=true;selection();error('');
  const id=$('experience-run').value,dataset_id=$('dataset').value;
  if(pendingExperience?.id!==id||pendingExperience?.dataset_id!==dataset_id)pendingExperience={id,dataset_id,request_id:uuid()};
  try{await request(CENTER+'/experience',pendingExperience);pendingExperience=null;$('experience-status').textContent='경험을 입력 대기열에 추가했습니다.';await refreshCenter();}
  catch(exc){$('experience-status').textContent='경험 추가 실패. 입력과 실행 상태를 확인하고 다시 시도하세요.';error(exc.message);}
  finally{addingExperience=false;selection();}
};
$('dataset-folder').onchange=()=>{if(!$('dataset-name').value)$('dataset-name').value=$('dataset-folder').files[0]?.webkitRelativePath.split('/')[0]||'';};
$('upload-form').onsubmit=async event=>{
  event.preventDefault();if(uploading)return;
  if(!token){error('실행기 연결을 확인한 뒤 다시 시도하세요.');return;}
  uploading=true;error('');$('upload').disabled=true;
  try{
    const files=Array.from($('dataset-folder').files),upload_id=uuid();
    if(!files.some(file=>file.name==='dataset.json'))throw new Error('폴더에 데이터 설명 파일 dataset.json이 필요합니다.');
    const names=new Set();
    for(const file of files){
      const relative=file.webkitRelativePath.split('/').slice(1).join('/');
      if(relative!==file.name||!(/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(file.name))||!(/\.npz$/.test(file.name)||['dataset.json','native-split-receipt.json','conversion-receipt.json'].includes(file.name))||names.has(file.name))throw new Error('폴더 바로 아래에 dataset.json, .npz와 공식 변환 영수증만 넣어 주세요.');
      if(!file.size)throw new Error(`빈 파일은 올릴 수 없습니다: ${file.name}`);names.add(file.name);
    }
    const total=files.reduce((sum,file)=>sum+file.size,0);let uploaded=0;
    for(const file of files){
      for(let offset=0;offset<file.size;offset+=256*1024){
        const bytes=new Uint8Array(await file.slice(offset,offset+256*1024).arrayBuffer());let binary='';
        for(let begin=0;begin<bytes.length;begin+=8192)binary+=String.fromCharCode(...bytes.subarray(begin,begin+8192));
        await request(CENTER+'/upload',{upload_id,name:file.name,offset,data:btoa(binary)});uploaded+=bytes.length;
        $('upload-status').textContent=`${file.name} · ${Math.round(uploaded/total*100)}% 업로드`;
      }
    }
    const published=await request(CENTER+'/publish',{upload_id,name:$('dataset-name').value});
    $('upload-status').textContent='업로드와 데이터 검증을 마쳤습니다.';await refreshCenter();
    const id=published.id||published.dataset?.id;if(id){$('dataset').value=id;selection();}
  }catch(exc){$('upload-status').textContent='업로드 또는 검증 실패. 새 업로드로 다시 시도하세요.';error(exc.message);}
  finally{uploading=false;$('upload').disabled=false;}
};
$('refresh').addEventListener('click',()=>{load();refreshCenter();loadLearningEntry();});
load();refreshCenter();loadLearningEntry();
setInterval(()=>{if(!document.hidden)refreshCenter();},3000);
