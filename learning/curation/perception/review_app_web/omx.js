// Original episodes stay immutable; segment reviews append versions in the local review workspace.
import {accountFetch} from '/account-session.js';
import {confirmIrreversible} from '/common/ui.js';
import '/commands.js';
const $=id=>document.getElementById(id);
const VERDICT={ok:'맞음',adjust:'조정 필요',unmeasurable:'측정 불가'};
const SPLIT={train:'학습',eval:'평가',test:'시험',exclude:'제외'};
const OUTCOME={success:'성공',failure:'실패',unknown:'미정'};
let token;
const editors=new Set();
let editGeneration=0,loading=false,savesInFlight=0;
const pendingEdits=()=>[...editors].some(editor=>editor());
window.addEventListener('beforeunload',event=>{if(pendingEdits()){event.preventDefault();event.returnValue='';}});

$('theme').value=document.documentElement.dataset.theme||'dark';
$('theme').onchange=()=>{document.documentElement.dataset.theme=$('theme').value;try{localStorage.setItem('rosy.theme',$('theme').value);}catch{} document.dispatchEvent(new CustomEvent('rosy:theme'));};

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
  segmentReview(set,section);
  const sourceInfo=el('details',null,'omx-source-info');sourceInfo.append(el('summary','원본 전체 시연 상태·메타데이터'));
  const t=set.trainable,status=el('ui-status',t.ok?`전체 시연 학습 가능 — ${Object.entries(t.counts).map(([k,v])=>`${SPLIT[k]||k} ${v}`).join(', ')}`:`전체 시연 학습 불가 — ${t.reason}`);
  status.setAttribute('state',t.ok?'ready':'warning');sourceInfo.append(status);
  const cs=set.camera_setup;
  sourceInfo.append(el('p',cs?`카메라 기준: ${Object.entries(cs.references||{}).map(([r,v])=>`${r} ${String(v).slice(0,8)}`).join(', ')} (${cs.mode})`
    :'카메라 맞춤 판정 없음 — prepare에 --camera-reference를 주면 기록됩니다.','quiet'));
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
  if(loading)return;
  if(savesInFlight){$('omx-status').textContent='저장 응답을 기다린 뒤 다시 확인하세요.';return;}
  if(pendingEdits()&&!await confirmIrreversible({message:'미저장 구간 또는 입력이 있습니다. 다시 불러오면 현재 편집을 잃습니다.',action:'편집 버리고 다시 확인',opener:$('refresh')}))return;
  const generation=editGeneration;loading=true;$('refresh').disabled=true;
  $('omx-status').setAttribute('state','pending');$('omx-status').textContent='불러오는 중입니다.';
  try{
    token=(await (await accountFetch('/api/workspace')).json()).token;
    const response=await accountFetch('/api/learning/omx');
    const value=await response.json();
    if(!response.ok)throw new Error(response.status===403?'이 작업대의 권한이 거부되었습니다.':value.error||'요청 실패');
    if(generation!==editGeneration){$('omx-status').setAttribute('state','warning');$('omx-status').textContent='불러오는 동안 편집이 바뀌어 기존 화면을 보존했습니다. 필요하면 다시 확인하세요.';return;}
    editors.clear();$('sets').replaceChildren(...value.sets.map(render));
    $('omx-status').setAttribute('state',value.sets.length?'ready':'empty');
    $('omx-status').textContent=value.sets.length?`세트 ${value.sets.length}개`:'연결된 OMX 준비 세트가 없습니다.';
  }catch(error){$('omx-status').setAttribute('state','error');$('omx-status').textContent=error.message||String(error);}
  finally{loading=false;$('refresh').disabled=false;}
}
$('refresh').addEventListener('click',load);
load();
