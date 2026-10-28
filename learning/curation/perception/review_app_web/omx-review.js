// Explicit human labels and source-bound frame reads; source recordings stay immutable.
import {accountFetch} from '/account-session.js';
import {confirmIrreversible} from '/common/ui.js';
const $=id=>document.getElementById(id),API='/api/learning/omx/center';
const OBJECT={moved_as_intended:'의도대로 이동',grasp_missed:'집기 실패',dropped:'낙하',displaced:'의도와 다르게 이동',untouched:'변화 없음',unknown:'미정'};
let current=null,pending=null,token='',saving=false,loading=false,stale=false;
let modified=false,editVersion=0,confirming=false;
let generation=0,controller=null,playing=false,playTimer=null,frameBusy=false,shownFrame=-1,activeContext='',pendingPreview=false;
function el(tag,text){const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;}
function uuid(){
  const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;
  const h=Array.from(b,x=>x.toString(16).padStart(2,'0')).join('');
  return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
}
async function request(path,body,signal){
  const options={cache:'no-store',signal};
  if(body!==undefined){
    if(!token){const response=await accountFetch('/api/learning');token=(await response.json()).token;}
    options.method='POST';options.headers={'Content-Type':'application/json','X-Pinky-Token':token};options.body=JSON.stringify(body);
  }
  const response=await accountFetch(path,options),value=await response.json();
  if(!response.ok)throw new Error(value.error||`요청 실패 (${response.status})`);
  return value;
}
function publishLoaded(reviewId=current?.latest_review_id){
  document.dispatchEvent(new CustomEvent('omx-review-loaded',{detail:{prepared_id:current?.prepared_id,
    source_revision:current?.source_revision,latest_review_id:reviewId??null,dirty:modified,saving:saving||loading||stale}}));
}
function saveReady(){
  $('review-save').disabled=!current||saving||loading||stale||!$('reviewer').value.trim()||!$('review-confirmed').checked;
}
function dirty(){modified=true;editVersion++;pending=null;$('review-confirmed').checked=false;publishLoaded();saveReady();}
window.addEventListener('beforeunload',event=>{if(modified||saving){event.preventDefault();event.returnValue='';}});
async function discardReview(action,opener){
  if(saving||loading||confirming)return false;
  if(!modified)return true;
  const version=editVersion;confirming=true;
  try{return await confirmIrreversible({message:'저장하지 않은 시도별 검수와 검수자 입력이 있습니다. 편집을 버릴까요?',action,opener})&&version===editVersion;}
  finally{confirming=false;}
}
function identity(value){$('review-identity').textContent=value?`${value.kind} · ${value.id}`:'로컬 입력 검수자 · 신원 미검증. 계정 사용 시 서버가 검수자를 바인딩합니다.';}
function choice(field,values,value,index){
  const select=el('select');select.className='ui-field';select.dataset.field=field;
  select.setAttribute('aria-label',`시도 ${index} ${{outcome:'결과',object_result:'물체 결과',split:'분할'}[field]}`);
  for(const [key,label] of Object.entries(values)){const option=el('option',label);option.value=key;select.append(option);}
  select.value=value;select.onchange=dirty;return select;
}
function render(){
  const inspection=current.inspection;
  $('review-meta').textContent=`원본 revision ${current.source_revision}\nrig ${inspection.rig_revision}\ncalibration ${inspection.calibration_revision}\nsource ${inspection.source_mode}\n`+JSON.stringify(inspection.episodes,null,2);
  identity(current.reviewer_identity);
  const table=el('table');table.className='omx-episodes';table.append(el('caption','원본 시도별 결정 · 성공/학습 포함은 자동 선택하지 않습니다.'));
  const head=el('thead'),headers=el('tr');
  for(const title of ['시도','결과','물체 결과','분할','이유']){const th=el('th',title);th.scope='col';headers.append(th);}
  head.append(headers);table.append(head);const body=el('tbody');
  for(const decision of current.decisions){
    const row=el('tr');row.dataset.episode=decision.episode_index;
    const id=el('th',decision.episode_index);id.scope='row';row.append(id);
    for(const [field,values] of [['outcome',{success:'성공',failure:'실패',unknown:'미정'}],['object_result',OBJECT],['split',{train:'학습',eval:'평가',test:'시험',exclude:'제외'}]]){
      const cell=el('td');cell.append(choice(field,values,decision[field]??'unknown',decision.episode_index));row.append(cell);
    }
    const reason=el('textarea');reason.className='ui-field';reason.dataset.field='reason';reason.value=decision.reason??'';
    reason.setAttribute('aria-label',`시도 ${decision.episode_index} 이유`);reason.maxLength=2000;reason.oninput=dirty;
    const cell=el('td');cell.append(reason);row.append(cell);body.append(row);
  }
  table.append(body);const wrap=el('div');wrap.className='omx-table-wrap';wrap.append(table);$('review-decisions').replaceChildren(wrap);
  $('review-episode').replaceChildren(...inspection.episodes.map(episode=>{const option=el('option',`시도 ${episode.episode_index}`);option.value=episode.episode_index;return option;}));
  $('review-camera').replaceChildren(...inspection.camera_keys.map((camera,index)=>{const option=el('option',camera);option.value=index;return option;}));
  $('reviewer').readOnly=current.reviewer_identity?.kind==='authenticated';
  if($('reviewer').readOnly)$('reviewer').value=current.reviewer_identity.id;
  $('review-confirmed').checked=false;$('review-editor').hidden=false;$('review-play').disabled=false;
  resetFrame();saveReady();publishLoaded(current.latest_review_id);
}
function resetFrame(){
  const episode=current?.inspection.episodes.find(row=>String(row.episode_index)===$('review-episode').value);
  if(!episode)return;
  $('review-frame').max=episode.frames-1;$('review-frame').value=0;preview();
}
function stopPlayback(){
  playing=false;clearTimeout(playTimer);playTimer=null;$('review-play').textContent='자동 넘김 시작';$('review-play').setAttribute('aria-pressed','false');
}
function clearMedia(){
  const image=$('review-image');image.onload=null;image.onerror=null;image.hidden=true;image.removeAttribute('src');
  $('review-gallery').hidden=true;$('review-gallery').replaceChildren();shownFrame=-1;
}
function cancelViewer(){
  stopPlayback();generation++;controller?.abort();controller=null;frameBusy=false;pendingPreview=false;activeContext='';clearMedia();$('review-viewer').setAttribute('aria-busy','false');$('review-play').disabled=true;
}
function scheduleNext(){
  if(!playing||frameBusy||!current)return;
  const frame=Number($('review-frame').value);
  if(frame>=Number($('review-frame').max)){stopPlayback();$('review-frame-status').textContent+=' · 마지막 프레임에서 멈췄습니다.';return;}
  const rate=Number($('review-rate').value);
  if(!Number.isFinite(rate)||rate<1||rate>10){stopPlayback();$('review-frame-status').textContent='요청 속도는 1–10 프레임/초로 지정하세요.';return;}
  clearTimeout(playTimer);playTimer=setTimeout(()=>{playTimer=null;if(playing){$('review-frame').value=frame+1;preview(true);}},1000/rate);
}
async function decodeGroup(data,source,episode,frame,indices){
  if(data.prepared_id!==source.prepared_id||data.source_revision!==source.source_revision||data.episode_index!==episode||data.frame_index!==frame||!Number.isSafeInteger(data.index)||data.index<0||
    !Number.isFinite(data.timestamp_seconds)||data.timestamp_seconds<0||!Number.isFinite(data.fps)||data.fps<=0||Math.abs(data.timestamp_seconds-frame/data.fps)>0.001)throw new Error('원본·프레임·기록 시각이 요청과 다릅니다.');
  if(!Array.isArray(data.frames)||data.frames.length!==indices.length)throw new Error('요청 카메라 묶음이 누락되었습니다.');
  let pixels=0,bytes=0;
  for(const [index,item] of data.frames.entries()){
    if(item.camera_index!==indices[index]||item.camera_key!==source.inspection.camera_keys[indices[index]])throw new Error('카메라 식별자·순서가 요청과 다릅니다.');
    if(!Number.isSafeInteger(item.width)||!Number.isSafeInteger(item.height)||item.width<1||item.height<1||typeof item.jpeg_base64!=='string')throw new Error('카메라 이미지 크기·JPEG가 유효하지 않습니다.');
    pixels+=item.width*item.height;const raw=atob(item.jpeg_base64);bytes+=raw.length;
    if(raw.charCodeAt(0)!==255||raw.charCodeAt(1)!==216||pixels>16000000||bytes>8*1024*1024)throw new Error('카메라 JPEG 형식·크기 한도를 확인하세요.');
  }
  return Promise.all(data.frames.map(async item=>{
    const image=new Image();image.alt=`시도 ${episode}, 프레임 ${frame}, ${item.camera_key}`;image.src='data:image/jpeg;base64,'+item.jpeg_base64;await image.decode();
    if(image.naturalWidth!==item.width||image.naturalHeight!==item.height)throw new Error('카메라 JPEG 크기가 선언과 다릅니다.');
    const figure=el('figure');figure.append(image,el('figcaption',`${item.camera_index}: ${item.camera_key}`));return figure;
  }));
}
async function preview(automatic=false){
  if(!current||loading||stale)return;
  if(automatic!==true)stopPlayback();
  const ticket=++generation,source=current;
  const episode=Number($('review-episode').value),frame=Number($('review-frame').value),camera=Number($('review-camera').value),keys=source.inspection.camera_keys;
  const view=$('review-view').value,context=[source.prepared_id,source.source_revision,episode,view,view==='group'?Math.floor(camera/8):camera].join('/');
  clearMedia();$('review-viewer').setAttribute('aria-busy','true');
  $('review-frame-label').textContent=`시도 ${episode} · 프레임 ${frame} / ${$('review-frame').max} · ${keys[camera]}`;
  $('review-frame-status').textContent='선택한 실제 프레임을 읽는 중입니다.';
  // An aborted client cannot cancel native decoding: finish this view's read before its latest cursor.
  if(frameBusy&&activeContext===context){pendingPreview=true;return;}
  pendingPreview=false;activeContext=context;controller?.abort();
  const reader=new AbortController(),signal=reader.signal;controller=reader;frameBusy=true;
  try{
    if(view==='group'){
      const start=Math.floor(camera/8)*8,indices=Array.from({length:Math.min(8,keys.length-start)},(_,index)=>start+index);
      const data=await request(`${API}/review-frame-set/${source.prepared_id}/${source.source_revision}/${episode}/${frame}/${indices.join(',')}`,undefined,signal);
      if(ticket!==generation)return;
      const figures=await decodeGroup(data,source,episode,frame,indices);if(ticket!==generation)return;
      $('review-gallery').replaceChildren(...figures);$('review-gallery').hidden=false;
      $('review-frame-status').textContent=`기록 행 ${data.index} · 시각 ${data.timestamp_seconds} s · source fps ${data.fps} · 카메라 ${start+1}–${start+indices.length} / ${keys.length} (선택 카메라 포함)`;
    }else{
      const image=new Image();image.id='review-image';image.style.cssText=$('review-image').style.cssText;image.alt=`시도 ${episode}, 프레임 ${frame}, 카메라 ${keys[camera]}`;
      await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(new Error('원본 리비전·해시와 카메라를 확인하세요.'));signal.addEventListener('abort',()=>{image.removeAttribute('src');reject(new DOMException('Cancelled','AbortError'));},{once:true});image.src=`${API}/review-frame/${source.prepared_id}/${source.source_revision}/${episode}/${frame}/${camera}`;});
      if(ticket!==generation)return;image.onload=null;image.onerror=null;$('review-image').replaceWith(image);$('review-frame-status').textContent='선택 프레임의 RGB 이미지를 읽었습니다. 기록 시각은 묶음 보기에서 확인하세요.';
    }
    shownFrame=frame;
  }catch(error){if(ticket!==generation)return;stopPlayback();clearMedia();$('review-frame-status').textContent=`프레임 읽기 실패: ${error.message}`;}
  finally{if(controller===reader){
    frameBusy=false;$('review-viewer').setAttribute('aria-busy','false');
    if(pendingPreview){pendingPreview=false;preview(playing);}else if(ticket===generation&&playing)scheduleNext();
  }}
}
function togglePlayback(){
  if(playing){stopPlayback();return;}if(!current||loading||stale)return;
  playing=true;$('review-play').textContent='자동 넘김 정지';$('review-play').setAttribute('aria-pressed','true');
  if(!frameBusy){if(shownFrame===Number($('review-frame').value))scheduleNext();else preview(true);}
}
function preparedChanged(){
  const select=$('prepared-set');
  if(current&&select.value!==current.prepared_id&&(modified||saving||loading)){
    if(!Array.from(select.options).some(option=>option.value===current.prepared_id))select.add(new Option(current.name,current.prepared_id));
    select.value=current.prepared_id;publishLoaded();
  }
  const selected=select.value;$('review-open').disabled=!selected||loading||saving;
  if(current&&current.prepared_id!==selected){cancelViewer();current=null;pending=null;stale=false;$('review-editor').hidden=true;$('review-status').textContent='선택한 자료의 검수를 명시적으로 불러오세요.';publishLoaded(null);}
}
$('prepared-set').addEventListener('change',async event=>{
  const select=$('prepared-set'),selected=select.value;
  if(!current||current.prepared_id===selected||(!modified&&!saving&&!loading))return;
  event.stopImmediatePropagation();select.value=current.prepared_id;
  if(await discardReview('편집 버리고 자료 바꾸기',select)){
    modified=false;select.value=selected;select.dispatchEvent(new Event('change',{bubbles:true}));
  }
},true);
$('review-open').onclick=async()=>{
  if(loading||saving||!$('prepared-set').value)return;
  if(!await discardReview('편집 버리고 다시 불러오기',$('review-open')))return;
  const selected=$('prepared-set').value;loading=true;$('review-fields').disabled=true;cancelViewer();preparedChanged();publishLoaded();
  try{
    const value=await request(API+'/review/'+encodeURIComponent(selected));
    if($('prepared-set').value!==selected)return;
    current=value;pending=null;modified=false;stale=false;loading=false;render();
    $('review-status').textContent=(current.fixture_only?'시험 fixture · 현장 자료 수용 아님. ':'')+`검수 불러옴 · ${current.trainable?.ok?'학습 분할 준비됨':current.trainable?.reason||'학습 준비 안 됨'}`;
  }catch(error){$('review-status').textContent=`검수 읽기 실패: ${error.message}`;stale=true;cancelViewer();saveReady();publishLoaded();}
  finally{loading=false;$('review-fields').disabled=false;saveReady();preparedChanged();publishLoaded();}
};
$('review-episode').onchange=resetFrame;$('review-camera').onchange=()=>preview();$('review-frame').oninput=()=>preview();$('review-view').onchange=()=>preview();
$('review-play').onclick=togglePlayback;$('review-rate').onchange=stopPlayback;
$('review-viewer').onkeydown=event=>{
  if(event.target.closest('input,select,textarea,button,ui-button,a,[contenteditable="true"]'))return;
  if(event.code==='Space'){event.preventDefault();togglePlayback();}
  else if(['ArrowLeft','ArrowRight'].includes(event.code)){event.preventDefault();$('review-frame').value=Math.max(0,Math.min(Number($('review-frame').max),Number($('review-frame').value)+(event.code==='ArrowLeft'?-1:1)));preview();}
};
for(const [id,target] of [['review-first',()=>0],['review-last',()=>Number($('review-frame').max)],['review-previous',()=>Math.max(0,Number($('review-frame').value)-1)],['review-next',()=>Math.min(Number($('review-frame').max),Number($('review-frame').value)+1)]]){
  $(id).onclick=()=>{$('review-frame').value=target();preview();};
}
$('reviewer').oninput=dirty;$('review-confirmed').onchange=saveReady;
$('native-review-form').onsubmit=async event=>{
  event.preventDefault();if($('review-save').disabled)return;
  const source=current;pending??={prepared_id:source.prepared_id,source_revision:source.source_revision,
    decisions:Array.from($('review-decisions').querySelectorAll('tbody tr'),row=>{
      const decision={episode_index:Number(row.dataset.episode)};
      for(const field of ['outcome','split','object_result','reason'])decision[field]=row.querySelector(`[data-field="${field}"]`).value;
      return decision;
    }),reviewer:$('reviewer').value.trim(),confirmed:true,request_id:uuid()};
  saving=true;$('review-fields').disabled=true;saveReady();preparedChanged();publishLoaded();
  try{
    const value=await request(API+'/review',pending);
    if(current!==source)return;
    pending=null;modified=false;current.latest_review_id=value.saved_review_id||value.latest_review_id;
    identity(value.reviewer_identity);publishLoaded(current.latest_review_id);
    $('review-status').textContent=`검수 스냅샷 저장됨 ${current.latest_review_id} · ${value.trainable?.ok?'학습 분할 준비됨':value.trainable?.reason||'학습 준비 판정은 자료 목록에서 확인하세요.'}`;
    document.dispatchEvent(new CustomEvent('omx-review-saved'));
  }catch(error){
    if(current!==source)return;
    stale=/stale|revision|hash|changed|리비전|해시|원본.*변경/i.test(error.message);
    if(stale)cancelViewer();
    $('review-status').textContent=`검수 저장 응답: ${error.message}`+(stale?' · 원본을 명시적으로 다시 불러온 뒤 검수하세요.':' · 같은 입력으로 재시도할 수 있습니다.');
  }finally{saving=false;$('review-fields').disabled=false;saveReady();preparedChanged();publishLoaded();}
};
$('prepared-set').addEventListener('change',preparedChanged);
document.addEventListener('omx-prepared-loaded',preparedChanged);
