// Original episodes stay immutable; segment reviews append versions in the local review workspace.
import {accountFetch} from '/account-session.js';
import '/common/ui.js';
import '/commands.js';
const $=id=>document.getElementById(id);
const VERDICT={ok:'맞음',adjust:'조정 필요',unmeasurable:'측정 불가'};
const SPLIT={train:'학습',eval:'평가',test:'시험',exclude:'제외'};
const OUTCOME={success:'성공',failure:'실패',unknown:'미정'};
let token;

$('theme').value=document.documentElement.dataset.theme||'dark';
$('theme').onchange=()=>{document.documentElement.dataset.theme=$('theme').value;try{localStorage.setItem('rosy.theme',$('theme').value);}catch{} document.dispatchEvent(new CustomEvent('rosy:theme'));};

function el(tag,text,cls){const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;}
function camera(checks){
  const roles=Object.entries(checks||{});
  if(!roles.length)return '기록 없음';
  return roles.map(([role,c])=>`${role}: ${VERDICT[c.before]||c.before} → ${VERDICT[c.after]||c.after}`).join(' · ');
}
function field(form,label,name,type='text',value=''){
  const wrapper=el('label',label+' '),input=el('input');
  input.name=name;input.type=type;input.value=value;input.className='ui-field';
  if(type==='number'){input.min=0;input.step=1;}
  wrapper.append(input);form.append(wrapper);return input;
}
function choice(form,label,name,options){
  const wrapper=el('label',label+' '),input=el('select');input.name=name;input.className='ui-field';
  input.setAttribute('aria-label',label);
  for(const [value,text] of options){const option=el('option',text);option.value=value;input.append(option);}
  wrapper.append(input);form.append(wrapper);return input;
}
function segmentReview(set,section){
  const detail=el('details'),summary=el('summary','파지 구간 검수');detail.append(summary);
  const status=el('p',null,'quiet'),list=el('div'),form=el('form');
  form.className='learning-form ui-form';
  let saved=set.segment_review||{version:0,document:null},rows=structuredClone(saved.document?.segments||[]);
  const episode=choice(form,'원본 Episode','episode',set.episodes.map(e=>[String(e.episode_index),String(e.episode_index)]));
  const cameraKey=choice(form,'카메라','camera',set.camera_keys.map(k=>[k,k.replace('observation.images.','')]));
  const frame=field(form,'확인 프레임','frame','number','0'),preview=el('button','프레임 확인');preview.type='button';form.append(preview);
  const image=el('img');image.alt='선택한 원본 Episode의 카메라 프레임';image.hidden=true;image.style.maxWidth='100%';
  const start=field(form,'시작 프레임 (포함)','start','number','0'),end=field(form,'끝 프레임 (제외)','end','number','1');
  const markStart=el('button','현재 프레임을 시작으로'),markEnd=el('button','현재 프레임 다음을 끝으로');
  markStart.type=markEnd.type='button';markStart.onclick=()=>{start.value=frame.value;};markEnd.onclick=()=>{end.value=Number(frame.value)+1;};
  form.append(markStart,markEnd);
  field(form,'대상 물체','object');field(form,'검수자','reviewer');field(form,'관찰 근거','reason');
  choice(form,'구간 결과','outcome',[['unknown','미판정'],['success','성공을 직접 확인함'],['failure','실패']]);
  choice(form,'사람 개입','intervention',[['false','없음'],['true','있음']]);
  choice(form,'분할','split',[['exclude','제외·보존'],['train','학습'],['eval','독립 평가'],['test','최종 시험']]);
  const add=el('button','구간 추가');add.type='submit';form.append(add);
  const save=el('button','검수 저장'),download=el('button','선택 JSON 내려받기');save.type=download.type='button';
  preview.onclick=async()=>{try{
    const query=new URLSearchParams({id:set.id,episode:episode.value,frame:frame.value,camera:cameraKey.value});
    const response=await accountFetch('/api/learning/omx/frame?'+query);
    if(!response.ok)throw new Error((await response.json()).error||'프레임 확인 실패');
    const blob=await response.blob(),reader=new FileReader();
    image.src=await new Promise((resolve,reject)=>{
      reader.onload=()=>resolve(reader.result);
      reader.onerror=()=>reject(new Error('프레임 이미지를 읽지 못했습니다.'));
      reader.readAsDataURL(blob);
    });
    image.hidden=false;
    status.textContent=`원본 Episode ${episode.value}, 프레임 ${frame.value}`;
  }catch(error){image.hidden=true;status.textContent=error.message;}};
  const show=()=>{
    list.replaceChildren(...rows.map((row,index)=>{
      const p=el('p',`Episode ${row.episode_index}: [${row.start_frame}, ${row.end_frame}) · ${row.object} · ${OUTCOME[row.outcome]} · ${SPLIT[row.split]}`);
      const remove=el('button','삭제');remove.type='button';remove.onclick=()=>{rows.splice(index,1);download.disabled=true;show();};p.append(remove);return p;
    }));
  };
  form.onsubmit=event=>{
    event.preventDefault();const source=set.episodes.find(e=>String(e.episode_index)===episode.value),values=new FormData(form);
    const row=Object.fromEntries(['episode_index','content_sha256','frames','session_id','cycle_id'].filter(k=>source[k]!=null).map(k=>[k,source[k]]));
    Object.assign(row,{start_frame:Number(start.value),end_frame:Number(end.value),intervention:values.get('intervention')==='true'});
    for(const key of ['object','reviewer','reason','outcome','split'])row[key]=values.get(key);
    rows.push(row);download.disabled=true;show();status.textContent='저장 전입니다. 구간 결과는 전체 Episode 성공과 별개입니다.';
  };
  save.onclick=async()=>{try{
    const response=await accountFetch('/api/learning/omx/segments',{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':token},
      body:JSON.stringify({id:set.id,version:saved.version,segments:rows})});
    const value=await response.json();if(!response.ok)throw new Error(value.error||'저장 실패');
    saved=value;rows=structuredClone(value.document.segments);download.disabled=false;show();status.textContent=`검수 ${saved.version} 저장됨. 원본은 보존됩니다.`;
  }catch(error){status.textContent=error.message;}};
  download.disabled=!saved.document;
  download.onclick=()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify(saved.document,null,2)+'\n'],{type:'application/json'}));
    const link=el('a');link.href=url;link.download=`omx-segments-${set.id}-v${saved.version}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  detail.append(el('p','원본을 보며 시작과 끝을 고른 뒤 결과·개입·분할을 직접 기록하세요. 실패·미판정·개입 구간은 제외로 보존합니다. 같은 원본·세션·cycle의 구간은 한 분할에만 둡니다.'),form,image,list,save,download,status);
  show();section.append(detail);
}
function render(set){
  const section=el('section',null,'learning-section');
  section.append(el('h3',set.name));
  if(set.error){const s=el('ui-status',set.error);s.setAttribute('state','error');section.append(s);return section;}
  const t=set.trainable,status=el('ui-status',t.ok?`학습 가능 — ${Object.entries(t.counts).map(([k,v])=>`${SPLIT[k]||k} ${v}`).join(', ')}`:`학습 불가 — ${t.reason}`);
  status.setAttribute('state',t.ok?'ready':'warning');section.append(status);
  const cs=set.camera_setup;
  section.append(el('p',cs?`카메라 기준: ${Object.entries(cs.references||{}).map(([r,v])=>`${r} ${String(v).slice(0,8)}`).join(', ')} (${cs.mode})`
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
  const wrap=el('div',null,'omx-table-wrap');wrap.append(table);section.append(wrap);
  segmentReview(set,section);
  return section;
}
async function load(){
  $('omx-status').setAttribute('state','pending');$('omx-status').textContent='불러오는 중입니다.';
  try{
    token=(await (await accountFetch('/api/workspace')).json()).token;
    const response=await accountFetch('/api/learning/omx');
    const value=await response.json();
    if(!response.ok)throw new Error(response.status===403?'이 작업대의 권한이 거부되었습니다.':value.error||'요청 실패');
    $('sets').replaceChildren(...value.sets.map(render));
    $('omx-status').setAttribute('state',value.sets.length?'ready':'empty');
    $('omx-status').textContent=value.sets.length?`세트 ${value.sets.length}개`:'연결된 OMX 준비 세트가 없습니다.';
  }catch(error){$('omx-status').setAttribute('state','error');$('omx-status').textContent=error.message||String(error);}
}
$('refresh').addEventListener('click',load);
load();
