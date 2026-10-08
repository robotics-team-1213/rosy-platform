import { cssColor, canvasFont, clearPalette } from '/common/ui.js';
import { drawnBox, dragBox, hitBox, boxHandles } from '/box-geometry.mjs';
import { showHistory } from '/history.js';
const font = (size, family) => canvasFont(size, family);

const $ = id => document.getElementById(id);
// Filled from the workspace's bound class set (D-485), in class index order.
let names = {'':'클래스 선택 필요'}, classOptions = [['','클래스 선택 필요']], classColors = {};
const states = {unknown:'알 수 없음', red:'빨강', yellow:'노랑', green:'초록', off:'꺼짐'};
const statuses = {approved:'승인', excluded:'제외', pending:'검수 대기'};
const serverReasons = {'known object class required':'모든 박스에 클래스를 지정하세요.','box outside original image':'박스가 원본 사진 범위를 벗어났습니다.','unknown signal state':'신호 상태가 올바르지 않습니다.','boxes must be a list':'박스 목록이 올바르지 않습니다.','unknown review action':'지원하지 않는 동작입니다.'};
function readableError(message) {return serverReasons[message] || message;}
let workspace, frame, image, sourceImage, ready = false, busy = false, loading = true, conflicted = false, forbidden = false, loadFailed = false, loadSerial = 0, drawing = false;
let detailView=false;
try {detailView=sessionStorage.getItem('rosy.review.detailView')==='true';} catch {}
let gesture = null, selected = null, coordinatePreview = null;
let undo = null;
function visibleFrames() {return workspace?.frames.filter(item=>$('filter').value==='all'||item.status===$('filter').value)||[];}
function sourceCandidates() {return frame?.source?.objects || frame?.source?.boxes || [];}

function error(message='') { $('error').textContent = message; $('error').hidden = !message; }
function setView(detail) {
  detailView=detail;
  try {sessionStorage.setItem('rosy.review.detailView',String(detail));} catch {}
  $('view-original').setAttribute('aria-pressed',String(!detail));
  $('view-detail').setAttribute('aria-pressed',String(detail));
  if (!ready) return;
  if (!detail) {image=sourceImage;$('view-status').textContent='원본 사진 · 학습 입력';paint();return;}
  const ticket=loadSerial,index=frame.index,next=new Image();
  $('view-status').textContent='명암 보정 화면을 불러오는 중…';
  next.onload=()=>{if(ticket!==loadSerial||!detailView)return;
    if(next.naturalWidth!==sourceImage.naturalWidth||next.naturalHeight!==sourceImage.naturalHeight){next.onerror();return;}
    image=next;$('view-status').textContent='명암 보정 보기 · 흰 포화 영역은 복원되지 않음';paint();};
  next.onerror=()=>{if(ticket!==loadSerial)return;detailView=false;image=sourceImage;
    $('view-original').setAttribute('aria-pressed','true');$('view-detail').setAttribute('aria-pressed','false');
    $('view-status').textContent='명암 보정을 표시하지 못했습니다. 원본 보기로 돌아왔습니다.';paint();};
  next.src=`/api/view-images/${index}`;
}
function enable() {
  const locked = !ready || busy || loading || conflicted || forbidden || !!gesture;
  const unclassified = frame?.review.boxes.some(box => box.label == null);
  $('approve').disabled = locked || !$('complete').checked || frame?.status === 'excluded' || unclassified;
  const reason = forbidden ? '검수 권한이 거부되었습니다. 최신 내용을 다시 불러오세요.' : !ready ? '사진을 불러온 뒤 승인할 수 있습니다.' : busy ? '저장을 마친 뒤 승인할 수 있습니다.' : conflicted ? '최신 내용을 불러온 뒤 다시 확인하세요.' : frame?.status === 'excluded' ? '제외 사진은 재검수로 돌려야 합니다.' : unclassified ? '클래스가 없는 박스가 있습니다. 모든 박스의 클래스를 지정하세요.' : !$('complete').checked ? '사진 전체 확인에 체크하세요.' : '';
  $('object-approval-hint').textContent = reason;
  if (reason) $('approve').setAttribute('reason',reason); else $('approve').removeAttribute('reason');
  $('exclude').disabled = locked || frame?.status === 'excluded';
  $('reopen').disabled = locked;
  $('draw').disabled = $('add').disabled = locked || frame?.status === 'excluded';
  $('delete-selected').disabled = locked || frame?.status === 'excluded' || selected===null;
  for (const button of $('object-quick-classes').querySelectorAll('button')) {
    button.disabled = locked || frame?.status === 'excluded' || selected===null;
    button.setAttribute('aria-pressed', String(selected!==null && frame.review.boxes[selected]?.label===button.value));
  }
  $('candidates').disabled = locked || frame?.status === 'excluded' || !sourceCandidates().length;
  $('candidates').reason = !sourceCandidates().length ? '이 사진에는 가져올 원본 객체 후보가 없습니다.' : '';
  $('undo').disabled = locked || !undo || frame?.status === 'excluded';
  $('undo').reason=locked?'작업 중':!undo?'수정 없음':frame?.status==='excluded'?'제외된 사진':'';
  $('prepare').disabled = busy || loading || conflicted || forbidden || !!gesture || !workspace;
  $('prepare').reason = loading ? '검수 내용을 불러오는 중입니다.' : forbidden ? '검수 권한이 거부되었습니다. 최신 내용을 다시 불러오세요.' : '';
  $('reload').disabled = busy || loading || !!gesture;
  $('view-original').disabled = $('view-detail').disabled = !ready || loading;
  $('filter').disabled = busy || loading || !!gesture;
  $('complete').disabled = locked || frame?.status === 'excluded';
  document.querySelectorAll('#boxes input, #boxes select, #boxes ui-button').forEach(el => el.disabled = locked || frame?.status === 'excluded');
  document.querySelectorAll('#frames ui-button').forEach(el => el.disabled = busy || loading || !!gesture);
  const visible=visibleFrames(),position=visible.findIndex(item=>item.index===frame?.index);
  for(const [id,available,reason] of [
    ['prev-frame',position>0,'현재 필터의 첫 번째 사진입니다.'],
    ['next-frame',position>=0&&position<visible.length-1,'현재 필터의 마지막 사진입니다.'],
    ['next-pending',workspace?.frames.some(item=>item.status==='pending'&&item.index!==frame?.index),'다른 검수 대기 사진이 없습니다.']
  ]) {
    $(id).reason=busy||gesture?'현재 작업을 마친 뒤 이동할 수 있습니다.':!ready?'사진을 불러오는 중입니다.':!available?reason:'';
    $(id).disabled=busy||!!gesture||!ready||!available;
  }
}
async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json', 'X-Pinky-Token':workspace.token}, body:JSON.stringify(body)});
  if (response.status >= 500) {const error=new Error('검수 서비스를 사용할 수 없습니다. 잠시 후 다시 시도하세요.');error.status=response.status;throw error;}
  const value = await response.json();
  if (!response.ok) {
    if (response.status === 409) conflicted = true;
    if (response.status === 403) {forbidden = true; throw new Error('검수 권한이 거부되었습니다. 최신 내용을 다시 불러오고 접근 권한을 확인하세요.');}
    throw new Error(readableError(value.error || '저장하지 못했습니다'));
  }
  return value;
}
function list() {
  const counts = workspace.frames.reduce((a,f) => {a[f.status]++; return a;}, {approved:0,excluded:0,pending:0});
  $('counts').textContent = `승인 ${counts.approved} · 제외 ${counts.excluded} · 대기 ${counts.pending}`;
  const visible=visibleFrames();
  $('filter').parentElement.hidden=!workspace.frames.length;
  $('empty-frames').textContent=workspace.frames.length?'이 상태의 사진이 없습니다.':'등록된 사진이 없습니다.';
  $('empty-frames').hidden=visible.length>0;
  const key=visible.map(f=>f.index).join(',');
  if (key===listKey) {
    // Same membership (D-469): refresh badges and selection in place instead of
    // rebuilding every thumbnail, which would refetch all original images.
    for (const button of $('frames').children) {
      const item=workspace.frames.find(f=>f.index===Number(button.dataset.index));
      button.setAttribute('aria-pressed',String(item.index===frame?.index));
      button.querySelector('.frame-badge').textContent=statuses[item.status];
    }
    revealSelected();
    return;
  }
  listKey=key;
  $('frames').replaceChildren();
  visible.forEach(f => {
    const button = document.createElement('ui-button'); button.setAttribute('kind','segment'); button.dataset.index=f.index; button.setAttribute('aria-pressed',String(f.index === frame?.index));
    // loading must precede src: Chromium starts an eager fetch the moment src is set.
    const thumb=document.createElement('img');thumb.loading='lazy';thumb.alt='';thumb.className='frame-thumb';thumb.src=`/api/images/${f.index}`;
    const name=document.createElement('span');name.className='frame-label';name.textContent=`사진 ${f.index+1}`;button.append(thumb,name);
    const badge = document.createElement('span'); badge.className = 'frame-badge'; badge.textContent = statuses[f.status]; name.append(badge);
    button.onclick = () => { if (!busy && !gesture) select(f.index); }; $('frames').append(button);
  });
  revealed=null; revealSelected();
}
// Narrow screens show the photos as one horizontal strip; keep the open photo in view
// without scrolling the page away from the editor.
let revealed=null;
function revealSelected() {
  const strip=$('frames'), button=strip.querySelector('[aria-pressed="true"]');
  // Only when the open photo changes, so a box edit does not undo the reviewer's own scrolling.
  if (!button || button.dataset.index===revealed) return;
  revealed=button.dataset.index;
  strip.scrollLeft+=button.getBoundingClientRect().left-strip.getBoundingClientRect().left-8;
}
let listKey='';
function paint() {
  const canvas = $('canvas'), ctx = canvas.getContext('2d');
  ctx.clearRect(0,0,canvas.width,canvas.height);
  if (!ready) return;
  ctx.drawImage(image,0,0);
  ctx.fillStyle = cssColor('--ink');
  ctx.lineWidth = Math.max(1,canvas.width/320); ctx.font = font(14,'mono');
  const boxes = coordinatePreview || frame.review.boxes;
  const marker = 8 * canvas.width / Math.max(1,canvas.getBoundingClientRect().width);
  boxes.forEach((box,i) => {
    const bounds = gesture?.index === i ? gesture.preview : box.bbox_xyxy;
    const [x0,y0,x1,y1] = bounds;
    // Unclassified boxes block approval (D-469): keep them visibly distinct on the canvas.
    const rgb = classColors[box.label];
    ctx.strokeStyle = box.label == null ? cssColor('--status-warn') : rgb ? `#${rgb.map(v=>v.toString(16).padStart(2,'0')).join('')}` : cssColor('--series-primary');
    ctx.strokeRect(x0,y0,x1-x0,y1-y0);
    ctx.fillText(String(i+1),x0+3,Math.max(14,y0-3));
    if (i === selected) {
      for (const [x,y] of Object.values(boxHandles(bounds))) {
        ctx.fillStyle=cssColor('--ground'); ctx.fillRect(x-marker/2,y-marker/2,marker,marker);
        ctx.strokeRect(x-marker/2,y-marker/2,marker,marker);
      }
      ctx.fillStyle=cssColor('--ink');
    }
  });
  if (gesture?.mode === 'draw') {
    const [x0,y0,x1,y1] = gesture.preview;
    ctx.setLineDash([marker,marker/2]); ctx.strokeRect(x0,y0,x1-x0,y1-y0); ctx.setLineDash([]);
  }
}
async function select(index) {
  const serial = ++loadSerial;
  cancelGesture(); selected=null; coordinatePreview=null; undo=null;
  $('empty-review').hidden=true;$('review-content').hidden=false;
  ready = false; frame = structuredClone(workspace.frames.find(f => f.index === index));
  for (const link of document.querySelectorAll('a[href^="/pixels"]')) link.href = `/pixels?frame=${frame.index}`;
  $('complete').checked = false; drawing = false; $('draw').setAttribute('aria-pressed','false');
  $('frame-title').textContent = `사진 ${index+1}`; $('status').textContent = statuses[frame.status];
  frameHeading();saveView();
  $('review-history-summary').textContent='검수 기록을 불러오는 중…';
  request(`/api/history/${index}`).then(value=>{if(serial===loadSerial)showHistory(value);})
    .catch(()=>{if(serial===loadSerial)$('review-history-summary').textContent='검수 기록을 불러오지 못했습니다. 새로고침을 눌러 다시 확인하세요.';});
  $('source-info').textContent = frame.source.source_kind === 'mcap'
    ? `${frame.source.width} × ${frame.source.height} · MCAP ${frame.source.source_session} · ${frame.source.mcap.frame.bag} SHA ${frame.source.mcap.bags.find(b => b.name === frame.source.mcap.frame.bag).sha256} · ${frame.source.mcap.frame.topic} · log ${frame.source.mcap.frame.log_ns} · channel ${frame.source.mcap.frame.channel_id} · ordinal ${frame.source.mcap.frame.message_ordinal} · 가져올 때 원본 픽셀 검증`
    : `${frame.source.width} × ${frame.source.height} · ${frame.source.video || '원본 사진'} · frame ${frame.source.video_frame ?? index}`;
  const candidates=sourceCandidates();
  $('candidate-details').open = frame.status === 'pending' && candidates.length > 0 && frame.review.boxes.length === 0 && frame.version <= 1;
  $('candidate-source').textContent = candidates.length
    ? `원본 객체 후보 ${candidates.length}개 · 출처: ${frame.source.annotation_source || '원본 라벨 자료'} · 사람이 모든 박스를 확인해야 합니다.`
    : '원본 객체 후보가 없습니다. 자동 객체 탐지는 이 화면에서 실행하지 않습니다. 사진을 확인하고 필요한 박스를 직접 그리세요.';
  if(frame.source.annotation_note) $('candidate-source').textContent += ` ${frame.source.annotation_note}.`;
  $('image-message').hidden = false; $('image-message').textContent = '사진을 불러오는 중';
  $('canvas').width = frame.source.width; $('canvas').height = frame.source.height;
  renderBoxes(); list(); paint(); enable();
  const next = new Image();
  next.onload = () => {
    if (serial !== loadSerial) return;
    if (next.naturalWidth !== frame.source.width || next.naturalHeight !== frame.source.height) {
      error('사진 크기가 원본과 다릅니다'); return;
    }
    sourceImage=image=next; ready = true; $('image-message').hidden = true;
    $('save-status').textContent = `서버 저장됨 · v${frame.version}`; paint(); enable();
    if(detailView)setView(true);else $('view-status').textContent='원본 사진 · 학습 입력';
  };
  next.onerror = () => { if (serial === loadSerial) {error('원본 사진을 불러오지 못했습니다. 승인할 수 없습니다.'); enable();} };
  next.src = `/api/images/${index}?v=${frame.version}`;
}
function selectField(label, options, value, changed) {
  const wrapper = document.createElement('label'); wrapper.append(document.createTextNode(label));
  const select = document.createElement('select'); select.className = 'ui-field';
  for (const [id,text] of options) {const option=document.createElement('option'); option.value=id; option.textContent=text; select.append(option);}
  select.value=value ?? ''; select.onchange=() => changed(select.value); wrapper.append(select); return wrapper;
}
function renderBoxes() {
  $('boxes').replaceChildren(); $('empty').hidden = !!frame.review.boxes.length;
  $('empty').textContent = '현재 박스 0개 · 사진 전체에서 필요한 박스를 그리세요. 객체가 없으면 전체 확인 후 승인하세요.';
  frame.review.boxes.forEach((box,i) => {
    const row=document.createElement('details'); row.className='box-row';row.open=selected===i||(selected===null&&i===0);
    const heading=document.createElement('summary');heading.textContent=`박스 ${i+1} · ${names[box.label??'']||'클래스 선택 필요'}`;
    heading.onclick=()=> {selected=i;paint();enable();};row.append(heading);
    const top=document.createElement('div'); top.className='box-top';
    const number=document.createElement('span'); number.className='box-number'; number.textContent=`#${i+1}`; top.append(number);
    const pick=document.createElement('ui-button'); pick.setAttribute('kind','toggle'); pick.setAttribute('aria-pressed',String(selected===i)); pick.textContent=`박스 ${i+1} 선택`;
    pick.onclick=()=> {selected=i; drawing=false; $('draw').setAttribute('aria-pressed','false'); renderBoxes(); paint(); enable();}; top.append(pick);
    top.append(selectField(`박스 ${i+1} 클래스`,classOptions,box.label,value => edit(boxes=> {boxes[i].label=value || null; if(value==='traffic_light') boxes[i].signal_state ??= 'unknown';})));
    if (box.label === 'traffic_light') top.append(selectField(`박스 ${i+1} 신호`,Object.entries(states),box.signal_state || 'unknown',value=>edit(boxes=>boxes[i].signal_state=value)));
    const remove=document.createElement('ui-button'); remove.setAttribute('kind','quiet'); remove.textContent=`박스 ${i+1} 삭제`; remove.onclick=()=> {selected=null;edit(boxes=>boxes.splice(i,1));}; top.insertBefore(remove,top.querySelector('label')); row.append(top);
    const coordinates=document.createElement('div'); coordinates.className='coordinates';
    ['x0','y0','x1','y1'].forEach((name,j) => {
      const label=document.createElement('label'); label.textContent=name;
      const input=document.createElement('input'); input.className='ui-field'; input.type='number'; input.step='0.1'; input.min='0'; input.max=String(j%2 ? frame.source.height : frame.source.width); input.value=box.bbox_xyxy[j]; input.setAttribute('aria-label',`박스 ${i+1} ${name}`);
      input.onfocus=()=> {selected=i; paint();};
      input.oninput=()=> {
        const boxes=structuredClone(frame.review.boxes); boxes[i].bbox_xyxy[j]=Number(input.value);
        const [x0,y0,x1,y1]=boxes[i].bbox_xyxy;
        if (input.value!=='' && 0<=x0 && x0<x1 && x1<=frame.source.width && 0<=y0 && y0<y1 && y1<=frame.source.height) {
          coordinatePreview=boxes; paint();
        }
      };
      input.onchange=()=>edit(boxes=>boxes[i].bbox_xyxy[j]=Number(input.value)); label.append(input); coordinates.append(label);
    }); row.append(coordinates); $('boxes').append(row);
  });
  enable();
}
function quickClasses() {
  const row=$('object-quick-classes'); row.replaceChildren();
  for (const cls of workspace.object_class_set.classes) {
    const button=document.createElement('button'), swatch=document.createElement('i'), label=document.createElement('span'), key=document.createElement('kbd');
    button.type='button'; button.value=cls.name; button.className='review-class-chip';
    button.setAttribute('aria-label',`${cls.display} 클래스 지정${cls.hotkey ? ` · ${cls.hotkey.toUpperCase()}` : ''}`);
    swatch.className='review-swatch'; swatch.setAttribute('aria-hidden','true');
    if(cls.color) swatch.style.background=`rgb(${cls.color.join(',')})`;
    label.textContent=cls.display; key.textContent=cls.hotkey?.toUpperCase()||'·';
    button.append(swatch,label,key);
    button.onclick=()=>{if(button.disabled||selected===null)return;
      edit(boxes=>{boxes[selected].label=cls.name;if(cls.name==='traffic_light')boxes[selected].signal_state ??= 'unknown';});
      $('canvas').focus({preventScroll:true});};
    row.append(button);
  }
  enable();
}
async function mutate(action, extras={}, restoring=false) {
  if (busy || !ready || conflicted || forbidden) return;
  busy=true; error(); $('complete').checked=false; $('save-status').textContent='서버에 저장 중…'; enable();
  const id=frame.index;
  const previous=structuredClone(frame.review.boxes);
  try {
    const saved=await request(`/api/frames/${id}`,{version:frame.version,action,...extras});
    workspace.frames[workspace.frames.findIndex(f=>f.index===id)]=saved; frame=structuredClone(saved);
    $('export-result').textContent=$('export-result').textContent.replace(/^이번 준비 결과 · /,'이전 준비 결과 · 현재 결정을 반영하려면 다시 준비하세요. ');
    undo=restoring?null:['save','candidates'].includes(action)?{index:id,boxes:previous}:null;
    // A decision finishes this photo, so open the next pending one (D-461 next task first).
    // Audits inside the approved/excluded filters stay where they are.
    const decided=['approve','exclude'].includes(action), advance=decided&&['all','pending'].includes($('filter').value)&&nextPending(id);
    if(!advance&&$('filter').value!=='all'&&frame.status!==$('filter').value) {$('filter').value='all';saveView();}
    $('status').textContent=statuses[frame.status]; $('save-status').textContent=`서버 저장됨 · v${frame.version}`;
    if(decided&&['all','pending'].includes($('filter').value)) $('drag-status').textContent=`사진 ${id+1} ${statuses[frame.status]} · ${advance?'다음 검수 대기 사진입니다.':'검수 대기 사진을 모두 처리했습니다.'}`;
    if(advance) {select(advance.index); return;}
    frameHeading();
    request(`/api/history/${id}`).then(value=>{if(frame?.index===id)showHistory(value);})
      .catch(()=>{if(frame?.index===id)$('review-history-summary').textContent='검수 기록을 불러오지 못했습니다. 새로고침을 눌러 다시 확인하세요.';});
    coordinatePreview=null; if (selected>=frame.review.boxes.length) selected=null;
    renderBoxes(); list(); paint();
  } catch(e) {coordinatePreview=null; error(e.message); renderBoxes(); paint(); $('save-status').textContent=`저장 실패 · ${e.message}`;}
  finally {busy=false; enable();}
}
function edit(change) {
  if (busy || !ready || conflicted || forbidden) return;
  const boxes=structuredClone(frame.review.boxes); change(boxes); mutate('save',{boxes});
}
$('complete').onchange=enable;
$('approve').onclick=()=> {if ($('complete').checked) mutate('approve',{complete_frame_review:true});};
$('exclude').onclick=()=>mutate('exclude'); $('reopen').onclick=()=>mutate('reopen');
$('candidates').onclick=()=> {if (window.confirm('현재 수정 라벨을 원본 초안으로 바꾸고 재검수하시겠습니까?')) mutate('candidates');};
$('draw').onclick=()=> {drawing=!drawing; $('draw').setAttribute('aria-pressed',String(drawing));};
$('add').onclick=()=>edit(boxes=>boxes.push({label:null,bbox_xyxy:[0,0,Math.min(40,frame.source.width),Math.min(40,frame.source.height)]}));
$('delete-selected').onclick=()=> {if(selected!==null) {const index=selected; selected=null;edit(boxes=>boxes.splice(index,1));}};
$('undo').onclick=()=> {if(undo?.index===frame?.index&&!$('undo').disabled) {selected=null;mutate('save',{boxes:undo.boxes},true);}};
function point(event) {const rect=$('canvas').getBoundingClientRect(); return [Math.max(0,Math.min(frame.source.width,(event.clientX-rect.left)*frame.source.width/rect.width)),Math.max(0,Math.min(frame.source.height,(event.clientY-rect.top)*frame.source.height/rect.height))];}
function canDrag() {return ready && !busy && !loading && !conflicted && !forbidden && frame.status!=='excluded';}
function cancelGesture() {
  if (!gesture) return;
  const id=gesture.pointerId; gesture=null;
  if ($('canvas').hasPointerCapture(id)) $('canvas').releasePointerCapture(id);
  if (frame) {renderBoxes(); paint(); enable();}
  $('drag-status').textContent='변경을 취소했습니다.';
}
function previewGesture(event) {
  if (!gesture || gesture.pointerId!==event.pointerId) return;
  const current=point(event), {width,height}=frame.source;
  gesture.preview=gesture.mode==='draw' ? drawnBox(gesture.start,current,width,height) : dragBox(gesture.original,gesture.mode,gesture.start,current,width,height);
  if (gesture.index!==null) {
    ['x0','y0','x1','y1'].forEach((name,j)=> {
      const input=document.querySelector(`input[aria-label="박스 ${gesture.index+1} ${name}"]`);
      if(input) input.value=gesture.preview[j];
    });
  }
  paint();
}
$('canvas').onpointerdown=event=> {
  if (!canDrag() || gesture || event.isPrimary===false || event.button!==0) return;
  const start=point(event), tolerance=(event.pointerType==='touch' ? 14 : 10)*frame.source.width/$('canvas').getBoundingClientRect().width;
  const hit=drawing ? null : hitBox(frame.review.boxes,start,tolerance,selected);
  selected=hit?.index ?? null; coordinatePreview=null;
  gesture={pointerId:event.pointerId,start,index:selected,mode:hit?.mode ?? 'draw',original:hit ? [...frame.review.boxes[hit.index].bbox_xyxy] : null,preview:hit ? [...frame.review.boxes[hit.index].bbox_xyxy] : [...start,...start]};
  $('canvas').focus({preventScroll:true});
  $('canvas').setPointerCapture(event.pointerId); renderBoxes(); enable(); paint();
  $('drag-status').textContent=gesture.mode==='draw' ? '새 박스를 그리고 있습니다. 놓으면 저장됩니다.' : '박스 위치·크기를 수정 중입니다. 놓으면 저장됩니다.';
  event.preventDefault();
};
$('canvas').onpointermove=event=> {
  if (gesture) {previewGesture(event); return;}
  if (!canDrag()) {$('canvas').style.cursor='default';return;}
  const hit=drawing ? null : hitBox(frame.review.boxes,point(event),10*frame.source.width/$('canvas').getBoundingClientRect().width,selected);
  const cursors={nw:'nwse-resize',se:'nwse-resize',ne:'nesw-resize',sw:'nesw-resize',n:'ns-resize',s:'ns-resize',e:'ew-resize',w:'ew-resize',move:'move'};
  $('canvas').style.cursor=hit ? cursors[hit.mode] : 'crosshair';
};
$('canvas').onpointerup=event=> {
  if (!gesture || gesture.pointerId!==event.pointerId) return;
  previewGesture(event);
  const finished=gesture; gesture=null;
  if ($('canvas').hasPointerCapture(event.pointerId)) $('canvas').releasePointerCapture(event.pointerId);
  const [x0,y0,x1,y1]=finished.preview;
  if (finished.mode==='draw' && (x1-x0<2 || y1-y0<2)) {paint(); enable(); $('drag-status').textContent='박스의 시작점과 끝점을 드래그하세요.';return;}
  if (finished.original && finished.original.every((v,i)=>v===finished.preview[i])) {paint(); enable(); $('drag-status').textContent=`박스 ${selected+1} 선택됨 · 안쪽은 이동, 손잡이는 크기 조절`;return;}
  $('drag-status').textContent='변경한 박스를 서버에 저장합니다.';
  if (finished.mode==='draw') {selected=frame.review.boxes.length; drawing=false; $('draw').setAttribute('aria-pressed','false'); edit(boxes=>boxes.push({label:null,bbox_xyxy:finished.preview}));}
  else edit(boxes=>boxes[finished.index].bbox_xyxy=finished.preview);
};
$('canvas').onpointercancel=event=> {if(gesture?.pointerId===event.pointerId) cancelGesture();};
$('canvas').onlostpointercapture=event=> {if(gesture?.pointerId===event.pointerId) cancelGesture();};
const TEXT_ENTRY='input:not([type=checkbox]):not([type=radio]), textarea, select';
function shortcut(event) {
  const digit=/^(?:Digit|Numpad)([1-9])$/.exec(event.code||'');
  return digit ? digit[1] : {KeyA:'a',KeyC:'c',KeyN:'n',KeyV:'v',KeyX:'x'}[event.code] || (/^[1-9acnvx]$/i.test(event.key) ? event.key.toLowerCase() : null);
}
document.addEventListener('keydown',event=> {
  if(event.key==='Escape' && gesture) {event.preventDefault();cancelGesture();}
  if(event.key==='Delete' && document.activeElement===$('canvas') && selected!==null && canDrag() && !gesture) {
    event.preventDefault(); $('delete-selected').click();
  }
  // Arrow keys move between photos; number fields keep their native stepping.
  if((event.key==='ArrowLeft'||event.key==='ArrowRight') && !['INPUT','SELECT','TEXTAREA'].includes(event.target?.tagName)) {
    const button=$(event.key==='ArrowLeft'?'prev-frame':'next-frame');
    if(button && !button.disabled) {event.preventDefault(); button.click();}
  }
  // Number keys set the selected box's class, A approves, X excludes (D-485). Approval
  // stays explicit (D-461): A only clicks an enabled 승인, never ticks 사진 전체 확인.
  // Physical keys (event.code) so a Korean IME layout still works; checkboxes keep working.
  if(event.target?.matches?.(TEXT_ENTRY) || event.isComposing || event.ctrlKey || event.metaKey || event.altKey || event.repeat || busy || gesture) return;
  const key=shortcut(event);
  if(key==='v'&&ready){event.preventDefault();setView(!detailView);return;}
  if(key==='c' && !$('complete').disabled) {event.preventDefault();$('complete').click();return;}
  if(key==='n' && !$('next-pending').disabled) {event.preventDefault();$('next-pending').click();return;}
  const cls=workspace?.object_class_set.classes.find(c=>c.hotkey===key);
  const field=cls && selected!==null ? $('boxes').children[selected]?.querySelector('select') : null;
  if(field && !field.disabled) {event.preventDefault(); if(field.value!==cls.name) {field.value=cls.name; field.onchange();}}
  // X only excludes a pending photo; approved or excluded photos change by mouse only.
  const decision=key==='a' ? 'approve' : key==='x' && frame?.status==='pending' ? 'exclude' : null;
  if(decision && !$(decision).disabled) {event.preventDefault(); $(decision).click();}
});
$('view-original').onclick=()=>setView(false);
$('view-detail').onclick=()=>setView(true);
function frameHeading() {
  $('status').setAttribute('status',frame.status==='pending'?'warn':'neutral');
  const visible=visibleFrames();
  $('frame-progress').textContent=`${visible.findIndex(item=>item.index===frame.index)+1} / ${visible.length} · ${frame.source.width} × ${frame.source.height} · 박스 ${frame.review.boxes.length}개${frame.source.annotation_note?' · '+frame.source.annotation_note:''}`;
}
function saveView() {
  const url=new URL(location.href);if(frame) url.searchParams.set('frame',frame.index);else url.searchParams.delete('frame');
  if($('filter').value==='all') url.searchParams.delete('filter');else url.searchParams.set('filter',$('filter').value);
  history.replaceState(null,'',url);
}
function applyFilter() {
  const visible=visibleFrames();
  if(visible.length) select(visible.some(item=>item.index===frame?.index)?frame.index:visible[0].index);
  else {++loadSerial;cancelGesture();ready=false;frame=undefined;undo=null;selected=null;coordinatePreview=null;$('review-content').hidden=true;$('empty-review').hidden=false;const firstUse=!workspace.frames.length;$('empty-review').querySelector('h2').textContent=firstUse?'등록된 사진이 없습니다':'이 상태의 사진이 없습니다';$('empty-review').querySelector('p').textContent=firstUse?'자료 등록에서 원본 사진을 추가하세요.':'전체 사진을 열거나 다른 검수 상태를 선택하세요.';$('show-all').textContent=firstUse?'자료 등록 열기':'전체 사진 보기';list();saveView();enable();}
}
$('filter').onchange=applyFilter;
$('show-all').onclick=()=> {if(loadFailed){load();return;}if(!workspace.frames.length){location.assign('/catalog');return;}$('filter').value='all';applyFilter();};
$('prev-frame').onclick=()=> {const visible=visibleFrames(),index=visible.findIndex(item=>item.index===frame.index);if(index>0) select(visible[index-1].index);};
$('next-frame').onclick=()=> {const visible=visibleFrames(),index=visible.findIndex(item=>item.index===frame.index);if(index<visible.length-1) select(visible[index+1].index);};
function nextPending(index) {
  const position=workspace.frames.findIndex(item=>item.index===index);
  return [...workspace.frames.slice(position+1),...workspace.frames.slice(0,position)].find(item=>item.status==='pending');
}
$('next-pending').onclick=()=> {const next=nextPending(frame.index);if(next) {$('filter').value='pending';select(next.index);}};
$('reload').onclick=async()=> {if(!busy) await load(frame?.index);};
$('theme').value=document.documentElement.dataset.theme || 'dark';
$('theme').onchange=()=> {document.documentElement.dataset.theme=$('theme').value; try {localStorage.setItem('rosy.theme',$('theme').value);} catch {} clearPalette(); document.dispatchEvent(new CustomEvent('rosy:theme')); paint();};
function receipt(value, historical=false) {
  $('export-result').textContent=`${historical?'이전 준비 결과 · 현재 결정을 반영하려면 다시 준비하세요. ':'이번 준비 결과 · '}승인 ${value.exported_frames}장 준비 완료 · 미승인 ${value.queued_frames}장 유지. 학습 반영은 학습 세션의 세션 분리·고정 평가 제외 확인 후 진행합니다.`;
  $('export-details').textContent=JSON.stringify(value,null,2);
}
$('prepare').onclick=async()=> {
  if (busy || conflicted || forbidden) return; busy=true; enable(); error(); $('export-result').textContent='원본과 승인 라벨을 검증하는 중…';
  try {receipt(await request('/api/prepare',{}));} catch(e) {error(e.message); $('export-result').textContent=`자료 준비 실패 · ${e.message}`;$('export-result').scrollIntoView({block:'center'});} finally {busy=false; enable();}
};
async function load(index) {
  loading=true;ready=false;++loadSerial;cancelGesture();$('counts').textContent='불러오는 중';$('frames').replaceChildren();listKey='';$('filter').parentElement.hidden=true;$('empty-frames').hidden=true;$('review-content').hidden=true;$('empty-review').hidden=false;$('empty-review').querySelector('h2').textContent='검수 내용을 확인하는 중';$('empty-review').querySelector('p').textContent='현재 사진과 결정 내용을 불러오고 있습니다.';$('show-all').hidden=true;enable();
  const started=performance.now();
  const timer=setInterval(()=>{const seconds=Math.floor((performance.now()-started)/1000);if(loading&&seconds>=3)$('empty-review').querySelector('p').textContent=`서버 응답 대기 ${seconds}초 · 현재 사진과 결정 내용을 확인하고 있습니다.`;},1000);
  try {workspace=await request('/api/workspace'); loading=false; loadFailed=false; conflicted=false; forbidden=false; error();$('show-all').hidden=false;
    const classes=workspace.object_class_set.classes;
    // An ordered list, not object keys: integer-like names would jump ahead of the others.
    classOptions=[['','클래스 선택 필요'],...classes.map(c=>[c.name,c.display])]; names=Object.fromEntries(classOptions);
    classColors=Object.fromEntries(classes.filter(c=>c.color).map(c=>[c.name,c.color]));
    quickClasses();
    $('object-class-help').textContent=`객체 박스 · ${classes.map(c=>c.display).join(' · ')}. 종류와 경계를 확인하세요. 통로 안팎은 로봇·콘·표지판 등의 종류를 바꾸지 않습니다.`;
    let guide=$('obstacle-guide');
    if(!guide){guide=document.createElement('p');guide.id='obstacle-guide';guide.className='quiet';document.querySelector('.inspector-heading').append(guide);}
    guide.hidden=!classes.some(c=>c.name==='obstacle');
    guide.textContent='기타 장애물은 주행 경로를 실제로 막는 독립 물체에만 사용하세요. 벽·고정 기둥·바닥 표시·그림자·경로 밖 물체는 제외합니다. 애매하면 승인 전에 박스를 수정하거나 삭제하세요.';
    if(workspace.exports.length) receipt(workspace.exports[0],true);
    if (!workspace.frames.length) {applyFilter();return;}
    const params=new URLSearchParams(location.search);
    $('filter').value=params.get('filter')||'all';if(!$('filter').value) $('filter').value='all';
    const candidate=params.has('frame')?Number(params.get('frame')):undefined;
    const visible=visibleFrames(),wanted=index??candidate;
    if(visible.length) await select(visible.some(item=>item.index===wanted)?wanted:visible[0].index);else applyFilter();
  } catch(e) {loading=false;loadFailed=true;workspace=undefined;frame=undefined;ready=false;listKey='';$('frames').replaceChildren();$('counts').textContent='상태를 확인할 수 없습니다.';$('filter').parentElement.hidden=true;$('empty-frames').textContent='사진 목록을 불러오지 못했습니다.';$('empty-frames').hidden=false;$('review-content').hidden=true;$('empty-review').hidden=false;$('empty-review').querySelector('h2').textContent=forbidden?'검수 권한이 거부되었습니다':e.status>=500?'검수 서비스를 사용할 수 없습니다':'검수 내용을 불러오지 못했습니다';$('empty-review').querySelector('p').textContent=forbidden?'이 작업대의 접근 권한을 확인한 뒤 다시 불러오세요.':e.status>=500?'서비스가 복구되면 다시 불러오세요.':'연결을 확인하고 다시 시도하세요.';$('show-all').hidden=false;$('show-all').textContent='다시 불러오기';enable();} finally {clearInterval(timer);}
}
enable();load();
