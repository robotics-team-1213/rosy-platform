import {cssColor, clearPalette} from '/common/ui.js';
import {showHistory} from '/history.js';
const $=id=>document.getElementById(id);
const states={pending:'픽셀 검수 대기',approved:'픽셀 승인',excluded:'픽셀 제외'};
const serverReasons={'known mask index required':'등록된 픽셀 클래스만 사용할 수 있습니다.','flood seed outside original image':'누른 점이 원본 사진 범위를 벗어났습니다.','bounded flood tolerance required':'비슷한 색 허용치는 0~100 사이 정수입니다.','bounded brush radius required':'브러시 반지름은 0~128 사이 정수입니다.','bounded brush points required':'브러시 획이 너무 깁니다. 나누어 그리세요.','brush point outside original image':'브러시 획이 원본 사진 범위를 벗어났습니다.','3..128 polygon points required':'영역은 꼭짓점 3~128개가 필요합니다.','polygon point outside original image':'영역 꼭짓점이 사진 밖에 있습니다.','mask encoding failed':'마스크를 저장하지 못했습니다.','no unknown pixels remain':'남은 미검수 픽셀이 없습니다.','exactly one background class required':'배경 클래스가 정확히 하나여야 합니다.','unknown pixel review action':'지원하지 않는 동작입니다.'};
function readableError(message){return serverReasons[message]||message;}
let workspace,frame,review,original,displayPhoto,maskImage,busy=false,ready=false,loading=true,conflicted=false,forbidden=false,serial=0,stroke=null,draft=[],tool='sample',polygon=[];
let detailView=false;
try {detailView=sessionStorage.getItem('rosy.review.detailView')==='true';} catch {}
let seeds=[],sampleImage=null,samplePixels=0,sampleTolerance=null,previewing=false,previewSerial=0;
let unknownPixels=null,totalPixels=0;
function error(value=''){$('pixel-error').textContent=value;$('pixel-error').hidden=!value;}
async function setView(detail){
 detailView=detail;
 try{sessionStorage.setItem('rosy.review.detailView',String(detail));}catch{}
 $('pixel-view-original').setAttribute('aria-pressed',String(!detail));
 $('pixel-view-detail').setAttribute('aria-pressed',String(detail));
 if(!ready)return;
 if(!detail){displayPhoto=original;$('pixel-view-status').textContent='원본 사진 · 학습 입력';paint();return;}
 const ticket=serial,index=frame.index;
 $('pixel-view-status').textContent='명암 보정 화면을 불러오는 중…';
 try{const photo=await image(`/api/view-images/${index}`);if(ticket!==serial||!detailView)return;
  if(photo.naturalWidth!==original.naturalWidth||photo.naturalHeight!==original.naturalHeight)throw new Error('보기 보정 크기가 원본과 다릅니다.');
  displayPhoto=photo;$('pixel-view-status').textContent='명암 보정 보기 · 흰 포화 영역은 복원되지 않음';paint();
 }catch(value){if(ticket!==serial)return;detailView=false;displayPhoto=original;
  $('pixel-view-original').setAttribute('aria-pressed','true');$('pixel-view-detail').setAttribute('aria-pressed','false');
  $('pixel-view-status').textContent=`명암 보정을 표시하지 못했습니다. 원본 보기로 돌아왔습니다. ${value.message}`;paint();}
}
function evaluationControls(){if(workspace.workspace_kind!=='evaluation')return;const label=document.createElement('label');label.className='ui-check';label.innerHTML='<input class="ui-field" id="pixel-unknown" type="checkbox">가려져 경계를 판단할 수 없는 투명 영역을 모두 확인했습니다 (평가 전용)';$('pixel-background').parentElement.insertAdjacentElement('afterend',label);$('pixel-unknown').onchange=enable;const help=[...label.parentElement.querySelectorAll('p')].find(p=>p.textContent.includes('255'));if(help)help.textContent='평가 전용: 가림 때문에 판단할 수 없는 영역만 255로 남기고 확인하세요. 학습 자료에는 포함되지 않습니다.';$('pixel-preparation').hidden=true;}
let candidateKey='';
function candidateOptions(){const rows=ready?review?.draft_candidates||[]:[],key=`${frame?.index}:${rows.map(row=>row.sha256).join(',')}`,select=$('pixel-candidates');
 if(key!==candidateKey){candidateKey=key;select.replaceChildren();for(const row of rows){const option=document.createElement('option');option.value=row.sha256;option.textContent=`${row.sha256.slice(0,12)} · ${row.catalog_sha256.slice(0,8)}`;select.append(option);}}
  $('pixel-candidate-tools').hidden=!rows.length;select.disabled=busy||!ready||loading||conflicted||forbidden||draft.length>0||seeds.length>0||polygon.length>0;
 $('pixel-apply-candidate').disabled=select.disabled||!rows.length||frame?.status==='excluded'||review?.status==='excluded';}
function visible(){return workspace?.frames.filter(row=>$('pixel-filter').value==='all'||row.pixel_status===$('pixel-filter').value)||[];}
function url(){const link=new URL(location.href);if(frame)link.searchParams.set('frame',frame.index);else link.searchParams.delete('frame');if($('pixel-filter').value==='all')link.searchParams.delete('filter');else link.searchParams.set('filter',$('pixel-filter').value);history.replaceState(null,'',link);}
function enable(){const dirty=draft.length>0,hasSamples=seeds.length>0,hasPolygon=polygon.length>0,selection=hasSamples||hasPolygon,locked=busy||!ready||loading||conflicted||forbidden||!!stroke,excluded=frame?.status==='excluded'||review?.status==='excluded',editable=!locked&&!excluded&&!!review?.classes,labelReady=editable&&$('pixel-class').value!=='';
 for(const button of $('pixel-quick-classes').querySelectorAll('button')){button.disabled=!editable;button.setAttribute('aria-pressed',String(button.value===$('pixel-class').value));}
 for(const button of $('pixel-frames').children)button.disabled=busy||loading||!!stroke||dirty||selection;
 $('pixel-fill-unknown').disabled=!editable||dirty||selection||!unknownPixels;
 $('pixel-fill-unknown').textContent='255 → 배경 초안';
 $('pixel-fill-unknown').setAttribute('aria-label',ready&&unknownPixels?`미검수 ${unknownPixels.toLocaleString()}픽셀만 배경 초안으로 채우기`:'미검수만 배경 초안으로 채우기');
 for(const id of ['pixel-view-original','pixel-view-detail'])$(id).disabled=!ready||loading;
 for(const [id,mode] of [['pixel-flood','sample'],['pixel-brush-tool','brush'],['pixel-polygon-tool','polygon']]){$(id).disabled=!labelReady||dirty||selection;$(id).setAttribute('aria-pressed',String(tool===mode));}
 for(const id of ['pixel-class','pixel-radius','pixel-tolerance-mode','pixel-tolerance','pixel-complete','pixel-background'])$(id).disabled=!editable;
 if($('pixel-unknown'))$('pixel-unknown').disabled=!editable;
 for(const id of ['pixel-fill','pixel-undo','pixel-exclude','pixel-reopen','pixel-approve']){$(id).disabled=id==='pixel-reopen'?locked||frame?.status==='excluded':!editable;$(id).reason=forbidden?'검수 권한이 거부되었습니다. 최신 내용을 다시 불러오세요.':locked?'사진 불러오기와 저장을 마친 뒤 다시 시도하세요.':excluded?'제외 사진은 먼저 재검수로 돌리세요.':!review?.classes?'자료 등록에서 검증된 class 파일을 연결하세요.':'';
  if((dirty||selection)&&id!=='pixel-undo'){$(id).disabled=true;$(id).reason='현재 초안을 적용하거나 버린 뒤 진행하세요.';}}
 $('pixel-fill').disabled=!labelReady||dirty||selection;
 if(!labelReady)$('pixel-fill').reason='먼저 픽셀 클래스를 선택하세요.';
 $('pixel-sample-apply').disabled=!labelReady||locked||dirty||(tool==='polygon'?polygon.length<3:!hasSamples||previewing||samplePixels===0);
 $('pixel-sample-apply').setAttribute('aria-label',tool==='polygon'?'다각형 영역 적용':'점 선택 영역 적용');
 $('pixel-sample-clear').disabled=!selection||busy;
 $('pixel-sample-clear').setAttribute('aria-label',tool==='polygon'?'다각형 영역 취소':'선택 점 지우기');
 $('pixel-radius').disabled=!labelReady||tool!=='brush';
 $('pixel-tolerance-mode').disabled=!labelReady||tool!=='sample';
 $('pixel-tolerance').disabled=!labelReady||tool!=='sample';
 $('pixel-save').disabled=!dirty||locked;$('pixel-discard').disabled=!dirty||busy||!!stroke;
 for(const id of ['pixel-save','pixel-discard'])$(id).reason=!dirty?'저장하지 않은 브러시 획이 없습니다.':busy||stroke?'현재 저장·편집을 마친 뒤 다시 시도하세요.':conflicted?'다른 탭에서 바뀌었습니다. 초안을 버리고 다시 불러오세요.':'';
 $('pixel-draft').textContent=hasPolygon?`영역 꼭짓점 ${polygon.length}개 · ${polygon.length<3?'3개 이상 찍으세요':'Enter로 적용하세요'}`:hasSamples?`${seeds.length}점 선택 · ${previewing?'색 영역 계산 중':sampleImage?`${samplePixels.toLocaleString()}픽셀 미리보기 · Lab 허용치 ${sampleTolerance}`:'미리보기 실패'}`:dirty?`저장하지 않은 브러시 ${draft.length}획`:!$('pixel-class').value?'먼저 픽셀 클래스를 선택하세요.':tool==='sample'?'차선 안을 클릭해 색을 선택하세요. 여러 점을 추가할 수 있습니다.':'';
 if((!dirty&&!selection)&&(!$('pixel-complete').checked||!$('pixel-background').checked)){$('pixel-approve').disabled=true;$('pixel-approve').reason='사진 전체와 기본 배경을 각각 확인하세요.';}
 if(ready&&unknownPixels>0){
  const evaluation=workspace.workspace_kind==='evaluation';
  const canReviewUnknown=evaluation&&frame.source.source_kind==='mcap'&&unknownPixels<totalPixels&&$('pixel-unknown')?.checked;
  if(!canReviewUnknown){
   $('pixel-approve').disabled=true;
   $('pixel-approve').reason=evaluation?(unknownPixels===totalPixels?'사진 전체가 가림 후보여서 승인할 수 없습니다.':frame.source.source_kind!=='mcap'?'MCAP 평가 사진에서만 가림 후보를 승인할 수 있습니다.':'가림 후보를 확인하고 평가 전용 확인란을 선택하세요.'):`미검수 ${unknownPixels.toLocaleString()}픽셀이 남았습니다. 경계를 수정하거나 판단할 수 없으면 대기로 두세요.`;
  }
 }
 $('pixel-approval-hint').textContent=ready&&$('pixel-approve').disabled?$('pixel-approve').reason:'';
 $('pixel-approve').reason='';
 const rows=visible(),pos=rows.findIndex(row=>row.index===frame?.index);
 for(const [id,available] of [['pixel-prev',pos>0],['pixel-next',pos>=0&&pos<rows.length-1],['pixel-next-pending',workspace?.frames.some(row=>row.pixel_status==='pending'&&row.status!=='excluded'&&row.index!==frame?.index)]]){$(id).disabled=busy||!!stroke||dirty||selection||!ready||!available;$(id).reason=!available?id==='pixel-next-pending'?'다른 검수 대기 사진이 없습니다.':'현재 필터에서 더 이동할 사진이 없습니다.':busy||stroke||dirty||selection?'현재 초안을 적용하거나 버린 뒤 이동하세요.':'';}
 for(const id of ['pixel-frame','pixel-filter'])$(id).disabled=busy||loading||!!stroke||dirty||selection;
 $('pixel-reload').disabled=busy||loading||!!stroke||dirty||selection;$('pixel-reload').reason=loading?'검수 내용을 불러오는 중입니다.':busy||stroke||dirty||selection?'현재 초안을 적용하거나 버린 뒤 다시 불러오세요.':'';
 $('pixel-export').disabled=busy||loading||!!stroke||dirty||selection||conflicted||forbidden||!workspace;$('pixel-export').reason=loading?'검수 내용을 불러오는 중입니다.':forbidden?'검수 권한이 거부되었습니다. 최신 내용을 다시 불러오세요.':busy||stroke||dirty||selection||conflicted?'저장을 마치고 최신 내용을 확인하세요.':'';
 candidateOptions();
}
async function request(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':workspace.token},body:JSON.stringify(body)}:{});if(response.status>=500){const error=new Error('검수 서비스를 사용할 수 없습니다. 잠시 후 다시 시도하세요.');error.status=response.status;throw error;}const value=await response.json();if(!response.ok){if(response.status===409)conflicted=true;if(response.status===403){forbidden=true;throw new Error('검수 권한이 거부되었습니다. 최신 내용을 다시 불러오고 접근 권한을 확인하세요.');}throw new Error(readableError(value.error));}return value;}
function options(){const rows=visible(),firstUse=!workspace.frames.length;$('pixel-frame').replaceChildren();for(const row of rows){const option=document.createElement('option');option.value=row.index;option.textContent=`사진 ${row.index+1} · ${states[row.pixel_status]}`;$('pixel-frame').append(option);}if(frame)$('pixel-frame').value=frame.index;$('pixel-frame').parentElement.hidden=!rows.length;$('pixel-filter').parentElement.hidden=firstUse;for(const id of ['pixel-prev','pixel-next','pixel-next-pending'])$(id).hidden=!rows.length;$('pixel-empty').hidden=!!rows.length;$('pixel-empty').querySelector('h3').textContent=firstUse?'등록된 사진이 없습니다':'이 상태의 픽셀 검수가 없습니다';$('pixel-all').hidden=false;$('pixel-all').textContent=firstUse?'자료 등록 열기':'전체 보기';$('pixel-content').hidden=!rows.length;thumbnails(rows);}
function image(path){return new Promise((resolve,reject)=>{const value=new Image();value.onload=()=>resolve(value);value.onerror=()=>reject(new Error('원본 또는 마스크를 불러오지 못했습니다. 승인할 수 없습니다.'));value.src=path;});}
let thumbnailKey='',thumbnailSelected=null;
function thumbnails(rows){const strip=$('pixel-frames'),key=rows.map(row=>row.index).join(',');strip.hidden=!rows.length;
 if(key!==thumbnailKey){thumbnailKey=key;thumbnailSelected=null;strip.replaceChildren();for(const row of rows){const button=document.createElement('ui-button'),thumb=document.createElement('img'),label=document.createElement('span'),badge=document.createElement('small');button.setAttribute('kind','segment');button.className='pixel-frame-item';button.dataset.index=row.index;thumb.loading='lazy';thumb.alt='';thumb.className='frame-thumb';thumb.src=`/api/images/${row.index}`;label.textContent=`사진 ${row.index+1}`;badge.className='frame-badge';label.append(badge);button.append(thumb,label);button.onclick=async()=>{if(button.disabled)return;await select(row.index);if(ready)canvas.focus({preventScroll:true});};strip.append(button);}}
 for(const button of strip.children){const row=workspace.frames.find(item=>item.index===Number(button.dataset.index));button.setAttribute('aria-pressed',String(row.index===frame?.index));button.querySelector('.frame-badge').textContent=row.status==='excluded'?'객체 제외':states[row.pixel_status];}
 const selected=strip.querySelector('[aria-pressed="true"]');if(selected&&selected.dataset.index!==thumbnailSelected){thumbnailSelected=selected.dataset.index;strip.scrollLeft+=selected.getBoundingClientRect().left-strip.getBoundingClientRect().left-8;}}
// classes.yaml requires a colour per class; names come from its optional display (D-485).
function classColor(index){const cls=review?.classes?.classes.find(row=>row.index===index);return cls?`#${cls.color.map(v=>v.toString(16).padStart(2,'0')).join('')}`:cssColor('--ink');}
function className(cls){return cls.display||cls.name;}
function legend(){ const classes=review.classes?.classes||[],ignored=classes.filter(c=>c.role==='ignore');$('pixel-legend').replaceChildren();for(const cls of classes){const item=document.createElement('span'),swatch=document.createElement('i');swatch.className='pixel-swatch';swatch.style.background=classColor(cls.index);swatch.setAttribute('aria-hidden','true');item.append(swatch,document.createTextNode(className(cls)));$('pixel-legend').append(item);}$('pixel-class-help').textContent=`픽셀 면 · ${classes.map(className).join(' · ')}. 255는 클래스가 아닙니다.${workspace.workspace_kind==='evaluation'?' 가림으로 판단할 수 없는 픽셀만 따로 확인할 수 있습니다.':''}${ignored.length?' '+ignored.map(className).join('·')+': 픽셀로 표시하지만 로봇 주행 해석에는 쓰지 않습니다.':''}`;}
function quickClasses(){const row=$('pixel-quick-classes');row.replaceChildren();for(const [index,cls] of (review.classes?.classes||[]).entries()){const button=document.createElement('button'),swatch=document.createElement('i'),label=document.createElement('span'),key=document.createElement('kbd');button.type='button';button.value=String(cls.index);button.className='pixel-class-chip';button.setAttribute('aria-label',`${className(cls)} 클래스 선택`);swatch.className='pixel-swatch';swatch.style.background=classColor(cls.index);swatch.setAttribute('aria-hidden','true');label.textContent=className(cls);key.textContent=index<9?String(index+1):'·';button.append(swatch,label,key);button.onclick=()=>{if(button.disabled)return;$('pixel-class').value=button.value;$('pixel-class').dispatchEvent(new Event('change'));canvas.focus({preventScroll:true});};row.append(button);}}
let paletteCache=null,paletteTheme='';
function palette(){const theme=document.documentElement.dataset.theme;if(paletteCache&&paletteTheme===theme)return paletteCache;const scratch=document.createElement('canvas');scratch.width=scratch.height=1;const ctx=scratch.getContext('2d'),values={};for(const cls of review.classes?.classes||[]){ctx.fillStyle=classColor(cls.index);ctx.fillRect(0,0,1,1);values[cls.index]=[...ctx.getImageData(0,0,1,1).data];}ctx.fillStyle=cssColor('--status-warn');ctx.fillRect(0,0,1,1);values[255]=[...ctx.getImageData(0,0,1,1).data];paletteCache=values;paletteTheme=theme;return values;}
function trace(ctx,line,style){ctx.strokeStyle=ctx.fillStyle=style;ctx.lineWidth=Math.max(1,line.radius*2);ctx.lineCap=ctx.lineJoin='round';ctx.beginPath();line.points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();for(const [x,y] of line.points){if(line.radius===0){ctx.fillRect(x,y,1,1);continue;}ctx.beginPath();ctx.arc(x,y,line.radius,0,Math.PI*2);ctx.fill();}}
// Draft strokes are previews only; the eraser (255) shows the bare photo inside the stroke.
let overlayCanvas=null,overlayKey='',scratch=null;
function overlay(){ // Recoloured mask layer (D-469): rebuild when frame, version or display setting changes.
  const key=[frame.index,review.version,$('pixel-opacity').value,$('pixel-show-unknown').checked,document.documentElement.dataset.theme].join('|');
  if(overlayCanvas&&overlayKey===key)return overlayCanvas;
  const off=document.createElement('canvas');off.width=original.naturalWidth;off.height=original.naturalHeight;
  const other=off.getContext('2d');other.drawImage(maskImage,0,0);
  const data=other.getImageData(0,0,off.width,off.height),colors=palette();const opacity=Number($('pixel-opacity').value)/100;let unknown=0;
  for(let i=0;i<data.data.length;i+=4)if(data.data[i]===255)unknown++;
  const rare=unknown>0&&unknown*100<off.width*off.height;
  for(let i=0;i<data.data.length;i+=4){const value=data.data[i],color=colors[value];if(!color||(value===255&&!$('pixel-show-unknown').checked)){data.data[i+3]=0;continue;}data.data[i]=color[0];data.data[i+1]=color[1];data.data[i+2]=color[2];data.data[i+3]=value===255&&rare?255:Math.round(opacity*(value===255?180:255));}
  unknownPixels=unknown;totalPixels=off.width*off.height;
  $('pixel-coverage').textContent=`${workspace.workspace_kind==='evaluation'?'255 가림 후보':'미검수'} ${unknown.toLocaleString()}픽셀 / ${(off.width*off.height).toLocaleString()}픽셀 (${rare?'<1':Math.round(unknown/(off.width*off.height)*100)}%)`;
  other.putImageData(data,0,0);overlayCanvas=off;overlayKey=key;return off;
}
function sampleOverlay(){if(!sampleImage)return null;const off=document.createElement('canvas');off.width=original.naturalWidth;off.height=original.naturalHeight;const ctx=off.getContext('2d');ctx.drawImage(sampleImage,0,0);const data=ctx.getImageData(0,0,off.width,off.height),colors=palette(),opacity=Number($('pixel-opacity').value)/100;for(let i=0;i<data.data.length;i+=4){const value=data.data[i],color=colors[value];if(value===255||!color){data.data[i+3]=0;continue;}data.data[i]=color[0];data.data[i+1]=color[1];data.data[i+2]=color[2];data.data[i+3]=Math.round(opacity*255);}ctx.putImageData(data,0,0);return off;}
function eraserLines(ctx,lines){ // One scratch pass for every eraser stroke: trace all, then clip to the photo.
  if(!scratch||scratch.width!==ctx.canvas.width||scratch.height!==ctx.canvas.height){scratch=document.createElement('canvas');scratch.width=ctx.canvas.width;scratch.height=ctx.canvas.height;}
  const other=scratch.getContext('2d');other.clearRect(0,0,scratch.width,scratch.height);
  for(const line of lines)trace(other,line,cssColor('--ink'));
  other.globalCompositeOperation='source-in';other.drawImage(displayPhoto||original,0,0);other.globalCompositeOperation='source-over';
  ctx.drawImage(scratch,0,0);
}
function paint(){if(!ready)return;const canvas=$('pixel-canvas'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(displayPhoto||original,0,0);const mask=overlay();if($('pixel-mask-visible').checked)ctx.drawImage(mask,0,0);if(sampleImage)ctx.drawImage(sampleOverlay(),0,0);
  const opacity=Number($('pixel-opacity').value)/100,lines=stroke?[...draft,stroke]:draft;
  for(const line of lines)if(line.label!==255){ctx.globalAlpha=opacity;trace(ctx,line,classColor(line.label));ctx.globalAlpha=1;}
  const erasers=lines.filter(line=>line.label===255);if(erasers.length)eraserLines(ctx,erasers);
  if(polygon.length){ctx.beginPath();polygon.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));if(polygon.length>2){ctx.closePath();ctx.globalAlpha=.25;ctx.fillStyle=classColor(Number($('pixel-class').value))||cssColor('--status-warn');ctx.fill();ctx.globalAlpha=1;}ctx.setLineDash([4,3]);ctx.lineWidth=2;ctx.strokeStyle=cssColor('--ink');ctx.stroke();ctx.setLineDash([]);for(const [x,y] of polygon){ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fillStyle=cssColor('--ink');ctx.fill();}}
  const radius=Math.max(3,5*canvas.width/Math.max(1,canvas.getBoundingClientRect().width));ctx.lineWidth=Math.max(2,radius/2);for(const [x,y] of seeds){ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.fillStyle=cssColor('--ink');ctx.fill();ctx.strokeStyle=cssColor('--ground');ctx.stroke();}
}
async function select(index){const ticket=++serial,selectedClass=$('pixel-class').value;ready=false;stroke=null;draft=[];polygon=[];clearSamples();brush.hidden=true;frame=workspace.frames.find(row=>row.index===Number(index));error();$('pixel-coverage').textContent='';$('pixel-decision').hidden=true;$('pixel-complete').checked=$('pixel-background').checked=false;options();url();enable();if(!frame)return;
 $('review-history-summary').textContent='검수 기록을 불러오는 중…';
 request(`/api/history/${frame.index}`).then(value=>{if(ticket===serial)showHistory(value);})
   .catch(()=>{if(ticket===serial)$('review-history-summary').textContent='검수 기록을 불러오지 못했습니다. 최신 내용을 다시 불러오세요.';});
 $('pixel-title').textContent=`사진 ${frame.index+1} 픽셀 검수`;$('pixel-object').href=`/?frame=${frame.index}`;if($('pixel-unknown'))$('pixel-unknown').checked=false;
 try{const next=await request(`/api/masks/${frame.index}`);const [photo,pixels]=await Promise.all([image(`/api/images/${frame.index}`),image(`/api/mask-images/${frame.index}?v=${next.version}`)]);if(ticket!==serial)return;if(photo.naturalWidth!==frame.source.width||photo.naturalHeight!==frame.source.height||pixels.naturalWidth!==photo.naturalWidth||pixels.naturalHeight!==photo.naturalHeight)throw new Error('원본과 마스크 크기가 다릅니다.');review=next;original=displayPhoto=photo;maskImage=pixels;const canvas=$('pixel-canvas');canvas.width=photo.naturalWidth;canvas.height=photo.naturalHeight;
 $('pixel-class').replaceChildren();const choose=document.createElement('option');choose.value='';choose.textContent='클래스를 선택하세요';$('pixel-class').append(choose);for(const cls of next.classes?.classes||[]){const option=document.createElement('option');option.value=cls.index;option.textContent=className(cls);$('pixel-class').append(option);}const unknown=document.createElement('option');unknown.value=255;unknown.textContent='미검수로 지우기';$('pixel-class').append(unknown);$('pixel-class').value=selectedClass||String(next.classes?.classes.find(cls=>cls.name==='lane_line')?.index??'');$('pixel-status').setAttribute('state',next.status==='approved'?'ready':'warning');$('pixel-status').textContent=`${states[next.status]} · v${next.version} · ${photo.naturalWidth} × ${photo.naturalHeight} · 객체 ${frame.status==='excluded'?'제외':frame.status==='approved'?'승인':'대기'}`;$('pixel-source').textContent=JSON.stringify({source:frame.source,mask:next,map_reference:workspace.map_reference},null,2);legend();quickClasses();ready=true;paint();if(detailView)void setView(true);else $('pixel-view-status').textContent='원본 사진 · 학습 입력';}
 catch(value){if(ticket===serial)error(value.message);}finally{if(ticket===serial)enable();}}
// After a decision, open the next pending photo whose pixels are editable (object exclusion locks them).
function nextPending(index){const rows=workspace.frames,pos=rows.findIndex(row=>row.index===index);return [...rows.slice(pos+1),...rows.slice(0,pos)].find(row=>row.pixel_status==='pending'&&row.status!=='excluded');}
function mutate(action,extra={}){return commit([{action,...extra}]);}
// Each saved draft stroke leaves the draft, so a failed save keeps only the unsaved rest.
async function commit(bodies){if(busy||!ready||conflicted||forbidden)return;busy=true;error();enable();let saved=0;try{for(const body of bodies){review=await request(`/api/masks/${frame.index}`,{version:review.version,...body});saved++;if(body.action==='paint')draft.shift();}frame.pixel_status=review.status;const selectedClass=$('pixel-class').value,decided=bodies.length===1&&['approve','exclude'].includes(bodies[0].action),decision=decided?`사진 ${frame.index+1} ${states[review.status]}`:'',pending=decided&&nextPending(frame.index),next=['all','pending'].includes($('pixel-filter').value)&&pending;if(next){await select(next.index);if([...$('pixel-class').options].some(o=>o.value===selectedClass))$('pixel-class').value=selectedClass;$('pixel-decision').textContent=`${decision} · 다음 검수 대기 사진 ${next.index+1}을 열었습니다.`;$('pixel-decision').hidden=false;return;}if($('pixel-filter').value!=='all'&&review.status!==$('pixel-filter').value)$('pixel-filter').value='all';await select(frame.index);$('pixel-class').value=selectedClass;if(decided){$('pixel-decision').textContent=pending?decision:`${decision} · 편집 가능한 검수 대기 사진을 모두 처리했습니다.`;$('pixel-decision').hidden=false;}}
 catch(value){const message=value.message,rest=draft;if(saved){await select(frame.index);draft=rest;paint();}error(message);}finally{busy=false;enable();}}
function filter(){const rows=visible();if(rows.length)select(rows.some(row=>row.index===frame?.index)?frame.index:rows[0].index);else{++serial;ready=false;frame=null;review=null;error();$('pixel-title').textContent='픽셀 검수';$('pixel-status').setAttribute('state','empty');$('pixel-status').textContent=workspace.frames.length?`${$('pixel-filter').selectedOptions[0].textContent} 0장 · 필터 결과가 없습니다.`:'등록된 사진 0장 · 자료 등록에서 원본을 추가하세요.';options();url();enable();}}
$('pixel-frame').onchange=async()=>{await select($('pixel-frame').value);if(ready)canvas.focus({preventScroll:true});};$('pixel-filter').onchange=filter;$('pixel-all').onclick=()=>{if(!workspace.frames.length){location.assign('/catalog');return;}$('pixel-filter').value='all';filter();};
for(const [id,step] of [['pixel-prev',-1],['pixel-next',1]])$(id).onclick=()=>{const rows=visible(),pos=rows.findIndex(row=>row.index===frame.index);if(rows[pos+step])select(rows[pos+step].index);};
$('pixel-next-pending').onclick=()=>{const next=nextPending(frame.index);if(next){$('pixel-filter').value='pending';select(next.index);}};
$('pixel-fill').onclick=()=>{if(confirm('현재 마스크 전체를 선택 클래스로 바꾸고 재검수하시겠습니까?'))mutate('fill',{label:Number($('pixel-class').value)});};
$('pixel-fill-unknown').onclick=()=>{if(confirm('현재 255 영역만 배경 초안으로 채웁니다. 기존 클래스는 보존되지만 놓친 선과 물체가 없는지 사진 전체를 다시 확인해야 합니다. 계속할까요?'))mutate('fill_unknown');};
for(const [id,mode] of [['pixel-flood','sample'],['pixel-brush-tool','brush'],['pixel-polygon-tool','polygon']])$(id).onclick=()=>{tool=mode;brush.hidden=true;enable();canvas.focus({preventScroll:true});};
$('pixel-undo').onclick=()=>{if(polygon.length){polygon.pop();paint();enable();}else if(seeds.length){seeds.pop();refreshSample();}else if(draft.length){draft.pop();paint();enable();}else mutate('undo');};
$('pixel-save').onclick=()=>commit(draft.map(({label,radius,points})=>({action:'paint',label,radius,points})));$('pixel-discard').onclick=()=>{draft=[];paint();enable();};
addEventListener('beforeunload',event=>{if(draft.length||stroke||seeds.length||polygon.length)event.preventDefault();});
$('pixel-approve').onclick=()=>mutate('approve',{complete_frame_review:$('pixel-complete').checked,background_reviewed:$('pixel-background').checked,unknown_pixels_reviewed:$('pixel-unknown')?.checked===true});$('pixel-exclude').onclick=()=>mutate('exclude');$('pixel-reopen').onclick=()=>mutate('reopen');
$('pixel-apply-candidate').onclick=()=>{if(confirm('새 초안을 적용하면 현재 마스크가 대체되고 픽셀 승인이 해제됩니다. 계속할까요?'))mutate('apply_draft',{draft_sha256:$('pixel-candidates').value});};
for(const id of ['pixel-complete','pixel-background'])$(id).onchange=enable;$('pixel-opacity').oninput=paint;$('pixel-show-unknown').onchange=paint;$('pixel-mask-visible').onchange=paint;
$('pixel-view-original').onclick=()=>setView(false);$('pixel-view-detail').onclick=()=>setView(true);
function clearSamples(){++previewSerial;seeds=[];sampleImage=null;samplePixels=0;sampleTolerance=null;previewing=false;if(ready){paint();enable();}}
async function refreshSample(){const ticket=++previewSerial;sampleImage=null;samplePixels=0;sampleTolerance=null;if(!seeds.length){previewing=false;paint();enable();return;}previewing=true;paint();enable();try{const result=await request(`/api/mask-preview/${frame.index}`,{version:review.version,label:Number($('pixel-class').value),seeds,tolerance:$('pixel-tolerance-mode').value==='auto'?'auto':Number($('pixel-tolerance').value)});const preview=await image(`data:image/png;base64,${result.mask_png}`);if(ticket!==previewSerial)return;sampleImage=preview;samplePixels=result.selected_pixels;sampleTolerance=result.tolerance;error();}catch(value){if(ticket===previewSerial)error(value.message);}finally{if(ticket===previewSerial){previewing=false;paint();enable();}}}
$('pixel-sample-apply').onclick=()=>{if(tool==='polygon'){if(polygon.length>=3)mutate('polygon',{label:Number($('pixel-class').value),points:polygon.map(point=>[...point])});return;}if(!sampleImage||previewing||!seeds.length)return;mutate('sample',{label:Number($('pixel-class').value),seeds:seeds.map(point=>[...point]),tolerance:sampleTolerance});};
$('pixel-sample-clear').onclick=()=>{if(tool==='polygon'){polygon=[];paint();enable();}else clearSamples();};
for(const id of ['pixel-class','pixel-tolerance-mode'])$(id).addEventListener('change',()=>{if(seeds.length){if($('pixel-class').value)refreshSample();else clearSamples();}if(polygon.length)paint();enable();});
$('pixel-tolerance').addEventListener('input',()=>{if(seeds.length&&$('pixel-tolerance-mode').value==='manual')refreshSample();});
function point(event){const box=$('pixel-canvas').getBoundingClientRect();return [Math.max(0,Math.min(frame.source.width-1,Math.floor((event.clientX-box.left)*frame.source.width/box.width))),Math.max(0,Math.min(frame.source.height-1,Math.floor((event.clientY-box.top)*frame.source.height/box.height)))];}
// Brush size preview: a circle follows the pointer at the current radius in screen scale.
const brush=$('pixel-brush');
function brushAt(event){
  if(!ready||busy||conflicted||forbidden||tool!=='brush'||!review?.classes||!$('pixel-class').value||frame?.status==='excluded'||review?.status==='excluded'){brush.hidden=true;return;}
  const box=canvas.getBoundingClientRect(),stage=brush.parentElement.getBoundingClientRect();
  const size=2*Number($('pixel-radius').value)*box.width/frame.source.width;
  if(!Number.isFinite(size)||size<3){brush.hidden=true;return;}
  brush.style.width=brush.style.height=size+'px';
  brush.style.left=(event.clientX-stage.left)+'px';
  brush.style.top=(event.clientY-stage.top)+'px';
  brush.hidden=false;
}
const canvas=$('pixel-canvas');canvas.onpointerdown=event=>{if(!ready||busy||conflicted||forbidden||!review.classes||!$('pixel-class').value||frame.status==='excluded'||review.status==='excluded'||event.button!==0)return;if(tool==='sample'){if(seeds.length>=32){error('선택 점은 최대 32개입니다.');return;}seeds.push(point(event));refreshSample();event.preventDefault();return;}if(tool==='polygon'){if(polygon.length>=128){error('영역 꼭짓점은 최대 128개입니다.');return;}polygon.push(point(event));paint();enable();event.preventDefault();return;}const radius=Number($('pixel-radius').value);if(!Number.isInteger(radius)||radius<0||radius>128){error('브러시 반지름은 0~128 사이 정수입니다.');return;}stroke={id:event.pointerId,points:[point(event)],radius,label:Number($('pixel-class').value)};canvas.setPointerCapture(event.pointerId);event.preventDefault();enable();paint();};
canvas.onpointermove=event=>{if(!stroke){brushAt(event);return;}brush.hidden=true;if(stroke.id!==event.pointerId||stroke.points.length>=2048)return;stroke.points.push(point(event));paint();};
canvas.onpointerup=event=>{if(!stroke||stroke.id!==event.pointerId)return;const finished=stroke;stroke=null;if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);draft.push(finished);paint();enable();};
function cancel(){if(!stroke)return;const id=stroke.id;stroke=null;if(canvas.hasPointerCapture(id))canvas.releasePointerCapture(id);paint();enable();}canvas.onpointercancel=cancel;canvas.onlostpointercapture=cancel;canvas.addEventListener('pointerleave',()=>{brush.hidden=true;});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&stroke){event.preventDefault();cancel();}else if(event.key==='Escape'&&polygon.length){event.preventDefault();polygon=[];paint();enable();}else if(event.key==='Escape'&&seeds.length){event.preventDefault();clearSamples();}
  // Arrow keys move between photos; number fields keep their native stepping.
  if((event.key==='ArrowLeft'||event.key==='ArrowRight')&&!['INPUT','SELECT','TEXTAREA'].includes(event.target?.tagName)){
    const button=$(event.key==='ArrowLeft'?'pixel-prev':'pixel-next');
    if(button&&!button.disabled){event.preventDefault();button.click();}
  }
  // Number keys pick the n-th class, A approves, X excludes (D-485); approval checks stay manual (D-461).
  // Physical keys (event.code) so a Korean IME layout still works; checkboxes keep working.
  if(event.target?.matches?.('input:not([type=checkbox]):not([type=radio]), textarea, select')||event.isComposing||event.ctrlKey||event.metaKey||event.altKey||event.repeat||busy||stroke)return;
  const digit=/^(?:Digit|Numpad)([1-9])$/.exec(event.code||''),key=digit?digit[1]:{KeyA:'a',KeyB:'b',KeyC:'c',KeyM:'m',KeyN:'n',KeyP:'p',KeyT:'t',KeyV:'v',KeyX:'x'}[event.code]||(/^[1-9abcmnptvx]$/i.test(event.key)?event.key.toLowerCase():null);
  if(key==='v'&&ready){event.preventDefault();setView(!detailView);return;}
  if(key==='m'&&ready){event.preventDefault();$('pixel-mask-visible').click();return;}
  if(key==='t'&&!polygon.length&&!$('pixel-flood').disabled){event.preventDefault();$(tool==='brush'?'pixel-flood':'pixel-brush-tool').click();return;}
  if(key==='p'&&!$('pixel-polygon-tool').disabled){event.preventDefault();$('pixel-polygon-tool').click();return;}
  if(event.key==='Backspace'&&tool==='polygon'&&polygon.length){event.preventDefault();polygon.pop();paint();enable();return;}
  if((event.code==='BracketLeft'||event.code==='BracketRight')&&tool==='brush'&&!$('pixel-radius').disabled){event.preventDefault();$('pixel-radius').value=String(Math.max(0,Math.min(128,Number($('pixel-radius').value)+(event.code==='BracketRight'?1:-1))));enable();return;}
  if(event.key==='Enter'&&event.target===canvas&&!$('pixel-sample-apply').disabled){event.preventDefault();$('pixel-sample-apply').click();return;}
  if(key==='c'&&!$('pixel-complete').disabled){event.preventDefault();$('pixel-complete').click();return;}
  if(key==='b'&&!$('pixel-background').disabled){event.preventDefault();$('pixel-background').click();return;}
  if(key==='n'&&!$('pixel-next-pending').disabled){event.preventDefault();$('pixel-next-pending').click();return;}
  const option=/^[1-9]$/.test(key)?[...$('pixel-class').options].filter(o=>o.value!==''&&o.value!=='255')[Number(key)-1]:null;
  if(option&&!$('pixel-class').disabled){event.preventDefault();$('pixel-class').value=option.value;$('pixel-class').dispatchEvent(new Event('change'));}
  // X only excludes a pending mask; approved or excluded ones change by mouse only.
  const decision=key==='a'?'pixel-approve':key==='x'&&review?.status==='pending'?'pixel-exclude':null;
  if(decision&&!$(decision).disabled){event.preventDefault();$(decision).click();}
  });
$('pixel-theme').value=document.documentElement.dataset.theme||'dark';$('pixel-theme').onchange=()=>{document.documentElement.dataset.theme=$('pixel-theme').value;try{localStorage.setItem('rosy.theme',$('pixel-theme').value);}catch{}clearPalette();document.dispatchEvent(new CustomEvent('rosy:theme'));if(review){legend();paint();}};
async function load(){const index=frame?.index;loading=true;ready=false;++serial;workspace=undefined;error();$('pixel-title').textContent='사진 불러오는 중';$('pixel-status').setAttribute('state','pending');$('pixel-status').textContent='검수 내용을 확인하는 중 · 현재 사진과 결정 내용을 불러오고 있습니다.';$('pixel-frame').parentElement.hidden=true;$('pixel-filter').parentElement.hidden=true;for(const id of ['pixel-prev','pixel-next','pixel-next-pending'])$(id).hidden=true;$('pixel-content').hidden=true;$('pixel-empty').hidden=true;$('pixel-all').hidden=true;$('pixel-export-result').textContent='';enable();const started=performance.now();const timer=setInterval(()=>{const seconds=Math.floor((performance.now()-started)/1000);if(loading&&seconds>=3)$('pixel-status').textContent=`서버 응답 대기 ${seconds}초 · 현재 사진과 결정 내용을 확인하고 있습니다.`;},1000);try{workspace=await request('/api/workspace');}finally{clearInterval(timer);}if(workspace.workspace_kind==='evaluation'&&!$('pixel-unknown'))evaluationControls();loading=false;conflicted=false;forbidden=false;const params=new URLSearchParams(location.search);$('pixel-filter').value=params.get('filter')||'all';if(!$('pixel-filter').value)$('pixel-filter').value='all';options();const rows=visible(),wanted=index??Number(params.get('frame'));if(rows.length)await select(rows.some(row=>row.index===wanted)?wanted:rows[0].index);else filter();}
function loadError(e){loading=false;workspace=undefined;frame=null;review=null;ready=false;error();$('pixel-title').textContent='픽셀 검수';$('pixel-status').setAttribute('state','error');$('pixel-status').textContent=forbidden?'검수 권한이 거부되었습니다. 이 작업대의 접근 권한을 확인한 뒤 다시 불러오세요.':e?.status>=500?'검수 서비스를 사용할 수 없습니다. 서비스가 복구되면 다시 불러오세요.':'검수 내용을 불러오지 못했습니다. 연결을 확인하고 다시 시도하세요.';$('pixel-frame').parentElement.hidden=true;$('pixel-filter').parentElement.hidden=true;for(const id of ['pixel-prev','pixel-next','pixel-next-pending'])$(id).hidden=true;$('pixel-content').hidden=true;$('pixel-empty').hidden=false;$('pixel-empty').querySelector('h3').textContent='작업 내용을 확인할 수 없습니다';$('pixel-all').hidden=true;enable();}
$('pixel-reload').onclick=()=>load().catch(loadError);
$('pixel-export').onclick=async()=>{if(busy||conflicted||forbidden)return;busy=true;enable();error();try{const value=await request('/api/prepare',{});$('pixel-export-result').textContent=`준비 시점 결과 · 객체 승인 ${value.exported_frames}장 · 픽셀 승인 ${value.pixel_approved_frames}장 준비. 이후 결정이 바뀌면 다시 준비하세요. 최신 결정 대조와 학습 수용은 별도입니다.`;$('pixel-export-details').textContent=JSON.stringify(value,null,2);}catch(value){error(value.message);$('pixel-export-result').textContent=`자료 준비 실패 · ${value.message}`;$('pixel-export-result').scrollIntoView({block:'center'});}finally{busy=false;enable();}};
enable();load().catch(loadError);
