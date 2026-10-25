// Guided input declarations; saved versions never acquire device authority.
import {accountFetch} from '/account-session.js';
const $=id=>document.getElementById(id),API='/api/learning/omx/center';
const PURPOSES=['policy','record','reward','evaluation','monitor'];
const copy=value=>structuredClone(value);
export function profileDocumentKey(value){
  function ordered(item){
    if(Array.isArray(item))return item.map(ordered);
    if(item&&typeof item==='object')return Object.fromEntries(Object.keys(item).sort().map(key=>[key,ordered(item[key])]));
    return item;
  }
  return JSON.stringify(ordered(value));
}
const empty=()=>({schema:'rosy.omx.learning-profile/1',name:'',task:'',mode:'',arms:[],cameras:[]});
let records=[],parent=null,draft=empty(),datasetProfile=null,pending=null,saving=false,token='';
function el(tag,text){const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;}
function uuid(){const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;const h=Array.from(b,x=>x.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
async function request(path,body){
  const options={cache:'no-store'};
  if(body!==undefined){
    if(!token){const response=await accountFetch('/api/learning');token=(await response.json()).token;}
    options.method='POST';options.headers={'Content-Type':'application/json','X-Pinky-Token':token};options.body=JSON.stringify(body);
  }
  const response=await accountFetch(path,options),value=await response.json();
  if(!response.ok)throw new Error(value.error||`요청 실패 (${response.status})`);return value;
}
function text(value,label){if(typeof value!=='string'||!value.trim())throw new Error(`${label}을 직접 입력하세요.`);return value.trim();}
function numeric(value,label){if(value===''||value==null||!Number.isFinite(Number(value)))throw new Error(`${label}을 비우지 말고 직접 선언하세요.`);return Number(value);}
function documentValue(){
  if(!draft.arms.length||draft.arms.length>32||!draft.cameras.length||draft.cameras.length>64)throw new Error('팔 1–32개와 카메라 1–64개가 필요합니다.');
  const profile={schema:draft.schema,name:text(draft.name,'이름'),task:text(draft.task,'과제'),mode:text(draft.mode,'사용 방식'),arms:[],cameras:[]};
  for(const arm of draft.arms){
    if(!arm.joint_names.length)throw new Error('순서가 있는 관절 이름이 필요합니다.');
    const row={id:text(arm.id,'팔 ID'),joint_names:arm.joint_names.map(name=>text(name,'관절 이름')),units:text(arm.units,'단위')};
    if(profile.schema.endsWith('/2'))row.action_limits=arm.joint_names.map((_,index)=>{
      const pair=arm.action_limits?.[index]||['',''];
      const lower=numeric(pair[0],'관절 하한·상한'),upper=numeric(pair[1],'관절 하한·상한');
      if(lower>=upper)throw new Error('관절 하한·상한은 유한한 증가 범위여야 합니다.');return [lower,upper];
    });profile.arms.push(row);
  }
  for(const camera of draft.cameras){
    const row={};for(const field of ['id','input_key','role','source_identity','placement'])row[field]=text(camera[field],`카메라 ${field}`);
    row.arm_id=camera.arm_id===null||camera.arm_id===''?null:text(camera.arm_id,'카메라 팔 ID');
    if(row.arm_id!==null&&!profile.arms.some(arm=>arm.id===row.arm_id))throw new Error(`알 수 없는 팔 연결 ${row.arm_id}: 직접 수정하세요.`);
    row.shape=[3,...camera.shape.slice(1).map(value=>{const n=numeric(value,'카메라 높이·너비');if(!Number.isInteger(n)||n<1||n>4096)throw new Error('카메라 높이·너비는 1–4096 정수여야 합니다.');return n;})];
    row.purposes=[...camera.purposes];if(!row.purposes.length)throw new Error('카메라마다 목적을 선택하세요.');profile.cameras.push(row);
  }
  if(!profile.cameras.some(camera=>camera.purposes.includes('policy')))throw new Error('policy 카메라를 하나 이상 직접 선택하세요.');
  return profile;
}
function diff(){
  let after;try{after=documentValue();}catch{after=draft;}
  const before=parent?.profile||{};
  const changes=['name','task','mode','schema','arms','cameras'].filter(key=>profileDocumentKey(before[key])!==profileDocumentKey(after[key]))
    .map(field=>({field,before:before[field]??null,after:after[field]}));
  $('profile-diff').textContent=`부모 ${parent?.id||'없음'} · revision ${parent?.revision||'새 작성'}\n`+(changes.length?JSON.stringify(changes,null,2):'변경 없음');
}
function edited(){pending=null;diff();}
function field(label,value,key,update,{type='text',change=false}={}){
  const wrap=el('label',label);wrap.className='ui-field-label';const input=el('input');input.className='ui-field';input.type=type;
  if(type==='number')input.step='any';input.value=value??'';input.dataset.field=key;
  input[change?'onchange':'oninput']=()=>{update(input.value);edited();};wrap.append(input);return wrap;
}
function select(label,value,key,values,update){
  const wrap=el('label',label);wrap.className='ui-field-label';const input=el('select');input.className='ui-field';input.dataset.field=key;
  for(const [key,title] of values){const option=el('option',title);option.value=key;input.append(option);}input.value=value;
  input.onchange=()=>{update(input.value);edited();};wrap.append(input);return wrap;
}
function orderButtons(section,items,index,kind){
  for(const [action,label,offset] of [['up','위로',-1],['down','아래로',1],['remove','삭제',0]]){
    const button=el('ui-button',`${kind} ${index+1} ${label}`);button.type='button';button.setAttribute('kind','quiet');button.dataset.action=action;
    button.disabled=action==='up'&&index===0||action==='down'&&index===items.length-1;
    button.onclick=()=>{if(saving)return;if(action==='remove')items.splice(index,1);else{const [item]=items.splice(index,1);items.splice(index+offset,0,item);}edited();render();};section.append(button);
  }
}
function renderArms(){
  $('profile-arms').replaceChildren(...draft.arms.map((arm,index)=>{
    const section=el('fieldset');section.dataset.arm=index;section.append(el('legend',`팔 ${index+1}`));
    section.append(field('팔 ID',arm.id,'id',value=>arm.id=value));
    section.append(field('관절 이름 · 쉼표로 순서 선언',arm.joint_names.join(', '),'joints',value=>{
      const old=new Map(arm.joint_names.map((name,i)=>[name,arm.action_limits?.[i]]));
      arm.joint_names=value?value.split(',').map(name=>name.trim()):[];
      arm.action_limits=arm.joint_names.map(name=>old.get(name)||['','']);render();
    },{change:true}));
    section.append(select('관절 단위',arm.units,'units',[['','직접 선택'],['rad','rad'],['degrees','degrees'],['normalized_-100_100','normalized_-100_100']],value=>arm.units=value));
    if(draft.schema.endsWith('/2'))arm.joint_names.forEach((name,joint)=>{
      for(const [side,key,label] of [[0,'lower','하한'],[1,'upper','상한']])section.append(field(`${name} ${label}`,arm.action_limits?.[joint]?.[side]??'',`${key}-${joint}`,value=>{
        arm.action_limits??=arm.joint_names.map(()=>['','']);arm.action_limits[joint]??=['',''];arm.action_limits[joint][side]=value;
      },{type:'number'}));
    });orderButtons(section,draft.arms,index,'팔');return section;
  }));$('profile-add-arm').disabled=draft.arms.length>=32;
}
function renderCameras(){
  $('profile-cameras').replaceChildren(...draft.cameras.map((camera,index)=>{
    const section=el('fieldset');section.dataset.camera=index;section.append(el('legend',`카메라 ${index+1}`));
    for(const [key,label] of [['id','카메라 ID'],['input_key','모델 입력 키 · observation.images.…'],['arm_id','팔 ID · 공유 카메라는 비움'],['role','역할'],['source_identity','실제 입력 출처 식별자'],['placement','배치 식별자']]){
      section.append(field(label,camera[key],key,value=>camera[key]=value));
    }
    section.append(field('RGB 높이 H',camera.shape[1],'height',value=>camera.shape[1]=value,{type:'number'}),field('RGB 너비 W',camera.shape[2],'width',value=>camera.shape[2]=value,{type:'number'}));
    const purposes=el('fieldset');purposes.append(el('legend','카메라 목적 · policy 하나 이상 필요'));
    for(const purpose of PURPOSES){const label=el('label',purpose),input=el('input');label.className='ui-check';input.className='ui-field';input.type='checkbox';input.dataset.purpose=purpose;input.checked=camera.purposes.includes(purpose);
      input.onchange=()=>{camera.purposes=PURPOSES.filter(p=>purposes.querySelector(`[data-purpose="${p}"]`).checked);edited();};label.prepend(input);purposes.append(label);}
    section.append(purposes);orderButtons(section,draft.cameras,index,'카메라');return section;
  }));$('profile-add-camera').disabled=draft.cameras.length>=64;
}
function render(){
  for(const key of ['name','task','mode'])$('profile-'+key).value=draft[key];$('profile-bounds').checked=draft.schema.endsWith('/2');renderArms();renderCameras();diff();
}
function record(){return records.find(row=>row.id===$('profile-record').value);}
function recordSelection(){
  const selected=record();$('profile-clone').disabled=!selected;$('profile-use').disabled=!selected;
  $('profile-record-meta').textContent=selected?`저장 ID ${selected.id} · revision ${selected.revision} · 작성자 ${JSON.stringify(selected.created_by)} · 실물 배치 검증 안 됨 · 정책 실행 승인 안 됨`:'';
  const link=$('profile-download');link.setAttribute('aria-disabled',String(!selected));
  if(selected){link.href=API+'/profile/'+encodeURIComponent(selected.id);link.download=`omx-profile-${selected.id}.json`;}else{link.removeAttribute('href');link.removeAttribute('download');}
}
async function loadProfiles(selectedId){
  try{
    const value=await request(API+'/profiles'),previous=selectedId||$('profile-record').value;records=value.profiles;
    $('profile-record').replaceChildren(...(records.length?records.map(row=>{const option=el('option',`${row.profile.name} · ${row.id}`);option.value=row.id;return option;}):[new Option('저장된 프로필 없음','')]));
    if(records.some(row=>row.id===previous))$('profile-record').value=previous;
    $('profile-record').disabled=!records.length;recordSelection();$('profiles-status').textContent=`저장 프로필 ${records.length}개 · 편집 중인 입력은 유지됩니다.`;
  }catch(error){$('profiles-status').textContent=`프로필 목록 사용 불가: ${error.message}`;}
}
for(const key of ['name','task','mode'])$('profile-'+key).addEventListener(key==='mode'?'change':'input',()=>{draft[key]=$('profile-'+key).value;edited();});
$('profile-bounds').onchange=()=>{draft.schema='rosy.omx.learning-profile/'+($('profile-bounds').checked?'2':'1');edited();render();};
$('profile-add-arm').onclick=()=>{if(saving||draft.arms.length>=32)return;draft.arms.push({id:'',joint_names:[],units:''});edited();render();};
$('profile-add-camera').onclick=()=>{if(saving||draft.cameras.length>=64)return;draft.cameras.push({id:'',input_key:'',arm_id:null,role:'',source_identity:'',placement:'',shape:[3,'',''],purposes:[]});edited();render();};
$('profile-record').onchange=recordSelection;$('profiles-refresh').onclick=()=>loadProfiles();
$('profile-clone').onclick=()=>{const selected=record();if(saving||!selected)return;parent=copy(selected);draft=copy(selected.profile);pending=null;render();};
$('profile-new').onclick=()=>{if(saving)return;parent=null;draft=empty();pending=null;render();};
document.addEventListener('omx-dataset-profile',event=>{datasetProfile=event.detail;$('profile-import-dataset').disabled=!datasetProfile?.schema;});
$('profile-import-dataset').onclick=()=>{if(saving||!datasetProfile)return;parent=null;draft=copy(datasetProfile);pending=null;render();};
$('profile-use').onclick=()=>{const selected=record();if(selected)document.dispatchEvent(new CustomEvent('omx-profile-selected',{detail:{id:selected.id,revision:selected.revision,profile:copy(selected.profile)}}));};
$('profile-form').onsubmit=async event=>{
  event.preventDefault();if(saving)return;
  try{
    const profile=documentValue();pending??={profile,request_id:uuid()};if(parent)pending.parent_id=parent.id;
    saving=true;$('profile-fields').disabled=true;$('profile-fields').inert=true;
    const saved=await request(API+'/profile',pending);pending=null;parent=copy(saved);draft=copy(saved.profile);
    await loadProfiles(saved.id);render();$('profiles-status').textContent=`새 불변 프로필 저장됨 ${saved.id} · revision ${saved.revision}`;
  }catch(error){$('profiles-status').textContent=`프로필 저장: ${error.message}`;}
  finally{saving=false;$('profile-fields').disabled=false;$('profile-fields').inert=false;}
};
render();loadProfiles();
