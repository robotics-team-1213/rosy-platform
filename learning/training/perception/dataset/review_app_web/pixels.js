import {cssColor, clearPalette} from '/common/ui.js';
const $=id=>document.getElementById(id);
const names={floor:'배경',background:'배경',lane_line:'차선',wall:'벽',drivable:'주행 영역',stop_line:'정지선',crosswalk:'횡단보도'};
const states={pending:'픽셀 검수 대기',approved:'픽셀 승인',excluded:'픽셀 제외'};
const serverReasons={'known mask index required':'등록된 픽셀 클래스만 사용할 수 있습니다.','flood seed outside original image':'누른 점이 원본 사진 범위를 벗어났습니다.','bounded flood tolerance required':'비슷한 색 허용치는 0~100 사이 정수입니다.','bounded brush radius required':'브러시 반지름은 1~128 사이 정수입니다.','bounded brush points required':'브러시 획이 너무 깁니다. 나누어 그리세요.','brush point outside original image':'브러시 획이 원본 사진 범위를 벗어났습니다.','mask encoding failed':'마스크를 저장하지 못했습니다.','unknown pixel review action':'지원하지 않는 동작입니다.'};
function readableError(message){return serverReasons[message]||message;}
let workspace,frame,review,original,maskImage,busy=false,ready=false,conflicted=false,forbidden=false,serial=0,stroke=null,draft=[],flood=false;
function error(value=''){$('pixel-error').textContent=value;$('pixel-error').hidden=!value;}
function visible(){return workspace?.frames.filter(row=>$('pixel-filter').value==='all'||row.pixel_status===$('pixel-filter').value)||[];}
function url(){const link=new URL(location.href);if(frame)link.searchParams.set('frame',frame.index);else link.searchParams.delete('frame');if($('pixel-filter').value==='all')link.searchParams.delete('filter');else link.searchParams.set('filter',$('pixel-filter').value);history.replaceState(null,'',link);}
function enable(){const dirty=draft.length>0,locked=busy||!ready||conflicted||forbidden||!!stroke,excluded=frame?.status==='excluded'||review?.status==='excluded',editable=!locked&&!excluded&&!!review?.classes;
 for(const id of ['pixel-class','pixel-radius','pixel-tolerance-mode','pixel-tolerance','pixel-complete','pixel-background'])$(id).disabled=!editable;
 for(const id of ['pixel-flood','pixel-fill','pixel-undo','pixel-exclude','pixel-reopen','pixel-approve']){$(id).disabled=id==='pixel-reopen'?locked||frame?.status==='excluded':!editable;$(id).reason=forbidden?'검수 권한이 거부되었습니다. 최신 내용을 다시 불러오세요.':locked?'사진 불러오기와 저장을 마친 뒤 다시 시도하세요.':excluded?'제외 사진은 먼저 재검수로 돌리세요.':!review?.classes?'자료 등록에서 검증된 class 파일을 연결하세요.':'';
  if(dirty&&id!=='pixel-undo'){$(id).disabled=true;$(id).reason='초안을 저장하거나 버린 뒤 진행하세요.';}}
 $('pixel-save').disabled=!dirty||locked;$('pixel-discard').disabled=!dirty||busy||!!stroke;
 for(const id of ['pixel-save','pixel-discard'])$(id).reason=!dirty?'저장하지 않은 브러시 획이 없습니다.':busy||stroke?'현재 저장·편집을 마친 뒤 다시 시도하세요.':conflicted?'다른 탭에서 바뀌었습니다. 초안을 버리고 다시 불러오세요.':'';
 $('pixel-draft').textContent=dirty?`저장하지 않은 브러시 ${draft.length}획`:'';
 if(!dirty&&(!$('pixel-complete').checked||!$('pixel-background').checked)){$('pixel-approve').disabled=true;$('pixel-approve').reason='사진 전체와 기본 배경을 각각 확인하세요.';}
 const rows=visible(),pos=rows.findIndex(row=>row.index===frame?.index);
 for(const [id,available] of [['pixel-prev',pos>0],['pixel-next',pos>=0&&pos<rows.length-1]]){$(id).disabled=busy||!!stroke||dirty||!ready||!available;$(id).reason=!available?'현재 필터에서 더 이동할 사진이 없습니다.':busy||stroke||dirty?'현재 저장·편집을 마친 뒤 이동하세요.':'';}
 for(const id of ['pixel-frame','pixel-filter'])$(id).disabled=busy||!!stroke||dirty;
 $('pixel-reload').disabled=busy||!!stroke||dirty;$('pixel-reload').reason=busy||stroke||dirty?'현재 저장·편집을 마친 뒤 다시 불러오세요.':'';
 $('pixel-export').disabled=busy||!!stroke||dirty||conflicted||forbidden;$('pixel-export').reason=forbidden?'검수 권한이 거부되었습니다. 최신 내용을 다시 불러오세요.':busy||stroke||dirty||conflicted?'저장을 마치고 최신 내용을 확인하세요.':'';
}
async function request(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':workspace.token},body:JSON.stringify(body)}:{});const value=await response.json();if(!response.ok){if(response.status===409)conflicted=true;if(response.status===403){forbidden=true;throw new Error('검수 권한이 거부되었습니다. 최신 내용을 다시 불러오고 접근 권한을 확인하세요.');}throw new Error(readableError(value.error));}return value;}
function options(){const rows=visible(),firstUse=!workspace.frames.length;$('pixel-frame').replaceChildren();for(const row of rows){const option=document.createElement('option');option.value=row.index;option.textContent=`사진 ${row.index+1} · ${states[row.pixel_status]}`;$('pixel-frame').append(option);}if(frame)$('pixel-frame').value=frame.index;$('pixel-frame').parentElement.hidden=!rows.length;$('pixel-filter').parentElement.hidden=firstUse;for(const id of ['pixel-prev','pixel-next'])$(id).hidden=!rows.length;$('pixel-empty').hidden=!!rows.length;$('pixel-empty').querySelector('h3').textContent=firstUse?'등록된 사진이 없습니다':'이 상태의 픽셀 검수가 없습니다';$('pixel-all').hidden=false;$('pixel-all').textContent=firstUse?'자료 등록 열기':'전체 보기';$('pixel-content').hidden=!rows.length;}
function image(path){return new Promise((resolve,reject)=>{const value=new Image();value.onload=()=>resolve(value);value.onerror=()=>reject(new Error('원본 또는 마스크를 불러오지 못했습니다. 승인할 수 없습니다.'));value.src=path;});}
function classToken(index){const cls=review?.classes?.classes.find(row=>row.index===index);return {floor:'--ink-quiet',background:'--ink-quiet',lane_line:'--series-primary',wall:'--ink',drivable:'--series-goal',stop_line:'--series-secondary',crosswalk:'--surface-line'}[cls?.name]||'--ink';}
function legend(){ $('pixel-legend').replaceChildren();for(const cls of review.classes?.classes||[]){const item=document.createElement('span'),swatch=document.createElement('i');swatch.className='pixel-swatch';swatch.style.background=cssColor(classToken(cls.index));swatch.setAttribute('aria-hidden','true');item.append(swatch,document.createTextNode(names[cls.name]||cls.name));$('pixel-legend').append(item);}}
let paletteCache=null,paletteTheme='';
function palette(){const theme=document.documentElement.dataset.theme;if(paletteCache&&paletteTheme===theme)return paletteCache;const scratch=document.createElement('canvas');scratch.width=scratch.height=1;const ctx=scratch.getContext('2d'),values={};for(const cls of review.classes?.classes||[]){ctx.fillStyle=cssColor(classToken(cls.index));ctx.fillRect(0,0,1,1);values[cls.index]=[...ctx.getImageData(0,0,1,1).data];}paletteCache=values;paletteTheme=theme;return values;}
function trace(ctx,line,style){ctx.strokeStyle=ctx.fillStyle=style;ctx.lineWidth=line.radius*2;ctx.lineCap=ctx.lineJoin='round';ctx.beginPath();line.points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();for(const [x,y] of line.points){ctx.beginPath();ctx.arc(x,y,line.radius,0,Math.PI*2);ctx.fill();}}
// Draft strokes are previews only; the eraser (255) shows the bare photo inside the stroke.
let overlayCanvas=null,overlayKey='',scratch=null;
function overlay(){ // Recoloured mask layer (D-469): rebuild only when frame, mask version, opacity or theme change.
  const key=[frame.index,review.version,$('pixel-opacity').value,document.documentElement.dataset.theme].join('|');
  if(overlayCanvas&&overlayKey===key)return overlayCanvas;
  const off=document.createElement('canvas');off.width=original.naturalWidth;off.height=original.naturalHeight;
  const other=off.getContext('2d');other.drawImage(maskImage,0,0);
  const data=other.getImageData(0,0,off.width,off.height),colors=palette();const opacity=Number($('pixel-opacity').value)/100;
  for(let i=0;i<data.data.length;i+=4){const value=data.data[i],color=colors[value];if(value===255||!color){data.data[i+3]=0;continue;}data.data[i]=color[0];data.data[i+1]=color[1];data.data[i+2]=color[2];data.data[i+3]=Math.round(opacity*255);}
  other.putImageData(data,0,0);overlayCanvas=off;overlayKey=key;return off;
}
function eraserLines(ctx,lines){ // One scratch pass for every eraser stroke: trace all, then clip to the photo.
  if(!scratch||scratch.width!==ctx.canvas.width||scratch.height!==ctx.canvas.height){scratch=document.createElement('canvas');scratch.width=ctx.canvas.width;scratch.height=ctx.canvas.height;}
  const other=scratch.getContext('2d');other.clearRect(0,0,scratch.width,scratch.height);
  for(const line of lines)trace(other,line,cssColor('--ink'));
  other.globalCompositeOperation='source-in';other.drawImage(original,0,0);other.globalCompositeOperation='source-over';
  ctx.drawImage(scratch,0,0);
}
function paint(){if(!ready)return;const canvas=$('pixel-canvas'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(original,0,0);ctx.drawImage(overlay(),0,0);
  const opacity=Number($('pixel-opacity').value)/100,lines=stroke?[...draft,stroke]:draft;
  for(const line of lines)if(line.label!==255){ctx.globalAlpha=opacity;trace(ctx,line,cssColor(classToken(line.label)));ctx.globalAlpha=1;}
  const erasers=lines.filter(line=>line.label===255);if(erasers.length)eraserLines(ctx,erasers);
}
async function select(index){const ticket=++serial;ready=false;stroke=null;draft=[];flood=false;brush.hidden=true;$('pixel-flood').setAttribute('aria-pressed','false');frame=workspace.frames.find(row=>row.index===Number(index));error();$('pixel-complete').checked=$('pixel-background').checked=false;options();url();enable();if(!frame)return;
 $('pixel-title').textContent=`사진 ${frame.index+1} 픽셀 검수`;$('pixel-object').href=`/?frame=${frame.index}`;
 try{const next=await request(`/api/masks/${frame.index}`);const [photo,pixels]=await Promise.all([image(`/api/images/${frame.index}`),image(`/api/mask-images/${frame.index}?v=${next.version}`)]);if(ticket!==serial)return;if(photo.naturalWidth!==frame.source.width||photo.naturalHeight!==frame.source.height||pixels.naturalWidth!==photo.naturalWidth||pixels.naturalHeight!==photo.naturalHeight)throw new Error('원본과 마스크 크기가 다릅니다.');review=next;original=photo;maskImage=pixels;const canvas=$('pixel-canvas');canvas.width=photo.naturalWidth;canvas.height=photo.naturalHeight;
 $('pixel-class').replaceChildren();for(const cls of next.classes?.classes||[]){const option=document.createElement('option');option.value=cls.index;option.textContent=names[cls.name]||cls.name;$('pixel-class').append(option);}const unknown=document.createElement('option');unknown.value=255;unknown.textContent='미검수로 지우기';$('pixel-class').append(unknown);$('pixel-status').setAttribute('state',next.status==='approved'?'ready':'warning');$('pixel-status').textContent=`${states[next.status]} · v${next.version} · ${photo.naturalWidth} × ${photo.naturalHeight} · 객체 ${frame.status==='excluded'?'제외':frame.status==='approved'?'승인':'대기'}`;$('pixel-source').textContent=JSON.stringify({source:frame.source,mask:next,map_reference:workspace.map_reference},null,2);legend();ready=true;paint();}
 catch(value){if(ticket===serial)error(value.message);}finally{if(ticket===serial)enable();}}
function mutate(action,extra={}){return commit([{action,...extra}]);}
// Each saved draft stroke leaves the draft, so a failed save keeps only the unsaved rest.
async function commit(bodies){if(busy||!ready||conflicted||forbidden)return;busy=true;error();enable();let saved=0;try{for(const body of bodies){review=await request(`/api/masks/${frame.index}`,{version:review.version,...body});saved++;if(body.action==='paint')draft.shift();}frame.pixel_status=review.status;if($('pixel-filter').value!=='all'&&review.status!==$('pixel-filter').value)$('pixel-filter').value='all';const selectedClass=$('pixel-class').value;await select(frame.index);$('pixel-class').value=selectedClass;}
 catch(value){const message=value.message,rest=draft;if(saved){await select(frame.index);draft=rest;paint();}error(message);}finally{busy=false;enable();}}
function filter(){const rows=visible();if(rows.length)select(rows.some(row=>row.index===frame?.index)?frame.index:rows[0].index);else{++serial;ready=false;frame=null;review=null;error();$('pixel-title').textContent='픽셀 검수';$('pixel-status').setAttribute('state','empty');$('pixel-status').textContent=workspace.frames.length?`${$('pixel-filter').selectedOptions[0].textContent} 0장 · 필터 결과가 없습니다.`:'등록된 사진 0장 · 자료 등록에서 원본을 추가하세요.';options();url();enable();}}
$('pixel-frame').onchange=()=>select($('pixel-frame').value);$('pixel-filter').onchange=filter;$('pixel-all').onclick=()=>{if(!workspace.frames.length){location.assign('/catalog');return;}$('pixel-filter').value='all';filter();};
for(const [id,step] of [['pixel-prev',-1],['pixel-next',1]])$(id).onclick=()=>{const rows=visible(),pos=rows.findIndex(row=>row.index===frame.index);if(rows[pos+step])select(rows[pos+step].index);};
$('pixel-fill').onclick=()=>{if(confirm('현재 마스크 전체를 선택 클래스로 바꾸고 재검수하시겠습니까?'))mutate('fill',{label:Number($('pixel-class').value)});};
$('pixel-flood').onclick=()=>{flood=!flood;$('pixel-flood').setAttribute('aria-pressed',String(flood));};$('pixel-undo').onclick=()=>{if(draft.length){draft.pop();paint();enable();}else mutate('undo');};
$('pixel-save').onclick=()=>commit(draft.map(({label,radius,points})=>({action:'paint',label,radius,points})));$('pixel-discard').onclick=()=>{draft=[];paint();enable();};
addEventListener('beforeunload',event=>{if(draft.length||stroke)event.preventDefault();});
$('pixel-approve').onclick=()=>mutate('approve',{complete_frame_review:$('pixel-complete').checked,background_reviewed:$('pixel-background').checked});$('pixel-exclude').onclick=()=>mutate('exclude');$('pixel-reopen').onclick=()=>mutate('reopen');
for(const id of ['pixel-complete','pixel-background'])$(id).onchange=enable;$('pixel-opacity').oninput=paint;
function point(event){const box=$('pixel-canvas').getBoundingClientRect();return [Math.max(0,Math.min(frame.source.width-1,Math.floor((event.clientX-box.left)*frame.source.width/box.width))),Math.max(0,Math.min(frame.source.height-1,Math.floor((event.clientY-box.top)*frame.source.height/box.height)))];}
function suggestTolerance(x,y){const r=4,x0=Math.max(0,x-r),y0=Math.max(0,y-r),w=Math.min(original.naturalWidth,x+r+1)-x0,h=Math.min(original.naturalHeight,y+r+1)-y0;const scratch=document.createElement('canvas');scratch.width=w;scratch.height=h;const ctx=scratch.getContext('2d',{willReadFrequently:true});ctx.drawImage(original,x0,y0,w,h,0,0,w,h);const data=ctx.getImageData(0,0,w,h).data,n=w*h,mean=[0,0,0];for(let i=0;i<data.length;i+=4){mean[0]+=data[i];mean[1]+=data[i+1];mean[2]+=data[i+2];}mean[0]/=n;mean[1]/=n;mean[2]/=n;let peak=0;for(let i=0;i<data.length;i+=4){peak=Math.max(peak,Math.abs(data[i]-mean[0]),Math.abs(data[i+1]-mean[1]),Math.abs(data[i+2]-mean[2]));}return Math.max(4,Math.min(48,Math.round(peak*1.5)+4));}
// Brush size preview: a circle follows the pointer at the current radius in screen scale.
const brush=$('pixel-brush');
function brushAt(event){
  if(!ready||busy||conflicted||forbidden||flood||!review?.classes||frame?.status==='excluded'||review?.status==='excluded'){brush.hidden=true;return;}
  const box=canvas.getBoundingClientRect(),stage=brush.parentElement.getBoundingClientRect();
  const size=2*Number($('pixel-radius').value)*box.width/frame.source.width;
  if(!Number.isFinite(size)||size<3){brush.hidden=true;return;}
  brush.style.width=brush.style.height=size+'px';
  brush.style.left=(event.clientX-stage.left)+'px';
  brush.style.top=(event.clientY-stage.top)+'px';
  brush.hidden=false;
}
const canvas=$('pixel-canvas');canvas.onpointerdown=event=>{if(!ready||busy||conflicted||forbidden||!review.classes||frame.status==='excluded'||review.status==='excluded'||event.button!==0)return;if(flood){const [x,y]=point(event);const automatic=$('pixel-tolerance-mode').value==='auto'&&!event.shiftKey;const tolerance=automatic?suggestTolerance(x,y):Number($('pixel-tolerance').value);if(!Number.isInteger(tolerance)||tolerance<0||tolerance>100){error('비슷한 색 허용치는 0~100 사이 정수입니다.');return;}$('pixel-tolerance').value=tolerance;if(automatic)$('pixel-draft').textContent=`비슷한 색 허용치 자동 제안: ${tolerance} (Shift+클릭은 입력값 사용)`;mutate('flood',{label:Number($('pixel-class').value),seed:[x,y],tolerance});return;}const radius=Number($('pixel-radius').value);if(!Number.isInteger(radius)||radius<1||radius>128){error('브러시 반지름은 1~128 사이 정수입니다.');return;}stroke={id:event.pointerId,points:[point(event)],radius,label:Number($('pixel-class').value)};canvas.setPointerCapture(event.pointerId);event.preventDefault();enable();paint();};
canvas.onpointermove=event=>{if(!stroke){brushAt(event);return;}brush.hidden=true;if(stroke.id!==event.pointerId||stroke.points.length>=2048)return;stroke.points.push(point(event));paint();};
canvas.onpointerup=event=>{if(!stroke||stroke.id!==event.pointerId)return;const finished=stroke;stroke=null;if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);draft.push(finished);paint();enable();};
function cancel(){if(!stroke)return;const id=stroke.id;stroke=null;if(canvas.hasPointerCapture(id))canvas.releasePointerCapture(id);paint();enable();}canvas.onpointercancel=cancel;canvas.onlostpointercapture=cancel;canvas.addEventListener('pointerleave',()=>{brush.hidden=true;});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&stroke){event.preventDefault();cancel();}
  // Arrow keys move between photos; number fields keep their native stepping.
  if((event.key==='ArrowLeft'||event.key==='ArrowRight')&&!['INPUT','SELECT','TEXTAREA'].includes(event.target?.tagName)){
    const button=$(event.key==='ArrowLeft'?'pixel-prev':'pixel-next');
    if(button&&!button.disabled){event.preventDefault();button.click();}
  }});
$('pixel-theme').value=document.documentElement.dataset.theme||'dark';$('pixel-theme').onchange=()=>{document.documentElement.dataset.theme=$('pixel-theme').value;try{localStorage.setItem('rosy.theme',$('pixel-theme').value);}catch{}clearPalette();document.dispatchEvent(new CustomEvent('rosy:theme'));if(review){legend();paint();}};
async function load(){const index=frame?.index;workspace=await request('/api/workspace');conflicted=false;forbidden=false;const params=new URLSearchParams(location.search);$('pixel-filter').value=params.get('filter')||'all';if(!$('pixel-filter').value)$('pixel-filter').value='all';options();const rows=visible(),wanted=index??Number(params.get('frame'));if(rows.length)await select(rows.some(row=>row.index===wanted)?wanted:rows[0].index);else filter();}
function loadError(){workspace=undefined;frame=null;review=null;ready=false;error();$('pixel-title').textContent='픽셀 검수';$('pixel-status').setAttribute('state','error');$('pixel-status').textContent=forbidden?'검수 권한이 거부되었습니다. 이 작업대의 접근 권한을 확인한 뒤 다시 불러오세요.':'검수 내용을 불러오지 못했습니다. 연결을 확인하고 다시 시도하세요.';$('pixel-frame').parentElement.hidden=true;$('pixel-filter').parentElement.hidden=true;for(const id of ['pixel-prev','pixel-next'])$(id).hidden=true;$('pixel-content').hidden=true;$('pixel-empty').hidden=false;$('pixel-empty').querySelector('h3').textContent='작업 내용을 확인할 수 없습니다';$('pixel-all').hidden=true;enable();}
$('pixel-reload').onclick=()=>load().catch(loadError);
$('pixel-export').onclick=async()=>{if(busy||conflicted||forbidden)return;busy=true;enable();error();try{const value=await request('/api/prepare',{});$('pixel-export-result').textContent=`객체 승인 ${value.exported_frames}장 · 픽셀 승인 ${value.pixel_approved_frames}장 준비. 최신 결정 대조와 학습 수용은 별도입니다.`;$('pixel-export-details').textContent=JSON.stringify(value,null,2);}catch(value){error(value.message);$('pixel-export-result').textContent=`자료 준비 실패 · ${value.message}`;$('pixel-export-result').scrollIntoView({block:'center'});}finally{busy=false;enable();}};
load().catch(loadError);
