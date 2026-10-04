import { cssColor, canvasFont, clearPalette } from '/common/ui.js';

const $ = id => document.getElementById(id);
const names = {'':'클래스 선택 필요',robot:'로봇', obstacle_box:'장애물 상자', cone:'콘', traffic_light:'신호등', sign:'표지판', person_feet:'사람 발'};
const states = {unknown:'알 수 없음', red:'빨강', yellow:'노랑', green:'초록', off:'꺼짐'};
const statuses = {approved:'승인', excluded:'제외', pending:'검수 대기'};
let workspace, frame, image, ready = false, busy = false, conflicted = false, loadSerial = 0, drawing = false, start;

function error(message='') { $('error').textContent = message; $('error').hidden = !message; }
function enable() {
  const locked = !ready || busy || conflicted;
  $('approve').disabled = locked || !$('complete').checked || frame?.status === 'excluded';
  const reason = !ready ? '사진을 불러온 뒤 승인할 수 있습니다.' : busy ? '저장을 마친 뒤 승인할 수 있습니다.' : conflicted ? '최신 내용을 불러온 뒤 다시 확인하세요.' : frame?.status === 'excluded' ? '제외 사진은 재검수로 돌려야 합니다.' : !$('complete').checked ? '사진 전체 확인에 체크하세요.' : '';
  if (reason) $('approve').setAttribute('reason',reason); else $('approve').removeAttribute('reason');
  $('exclude').disabled = locked || frame?.status === 'excluded';
  $('reopen').disabled = locked;
  $('draw').disabled = $('add').disabled = locked || frame?.status === 'excluded';
  $('candidates').disabled = locked || frame?.status === 'excluded';
  $('prepare').disabled = busy || conflicted || !workspace;
  $('reload').disabled = busy;
  $('filter').disabled = busy;
  $('complete').disabled = locked || frame?.status === 'excluded';
  document.querySelectorAll('#boxes input, #boxes select, #boxes ui-button').forEach(el => el.disabled = locked || frame?.status === 'excluded');
  document.querySelectorAll('#frames ui-button').forEach(el => el.disabled = busy);
}
async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json', 'X-Pinky-Token':workspace.token}, body:JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok) {
    if (response.status === 409) conflicted = true;
    throw new Error(value.error || '저장하지 못했습니다');
  }
  return value;
}
function list() {
  const counts = workspace.frames.reduce((a,f) => {a[f.status]++; return a;}, {approved:0,excluded:0,pending:0});
  $('counts').textContent = `승인 ${counts.approved} · 제외 ${counts.excluded} · 대기 ${counts.pending}`;
  $('frames').replaceChildren();
  workspace.frames.filter(f => $('filter').value === 'all' || f.status === $('filter').value).forEach(f => {
    const button = document.createElement('ui-button'); button.setAttribute('kind','segment'); button.setAttribute('aria-pressed',String(f.index === frame?.index));
    button.textContent = `사진 ${f.index + 1}`;
    const badge = document.createElement('span'); badge.className = 'frame-badge'; badge.textContent = statuses[f.status]; button.append(badge);
    button.onclick = () => { if (!busy) select(f.index); }; $('frames').append(button);
  });
}
function paint() {
  const canvas = $('canvas'), ctx = canvas.getContext('2d');
  ctx.clearRect(0,0,canvas.width,canvas.height);
  if (!ready) return;
  ctx.drawImage(image,0,0);
  ctx.strokeStyle = cssColor('--series-primary'); ctx.fillStyle = cssColor('--ink');
  ctx.lineWidth = Math.max(1,canvas.width/320); ctx.font = canvasFont(14,'mono');
  frame.review.boxes.forEach((box,i) => {
    const [x0,y0,x1,y1] = box.bbox_xyxy; ctx.strokeRect(x0,y0,x1-x0,y1-y0);
    ctx.fillText(String(i+1),x0+3,Math.max(14,y0-3));
  });
}
async function select(index) {
  const serial = ++loadSerial;
  ready = false; frame = structuredClone(workspace.frames.find(f => f.index === index));
  $('complete').checked = false; drawing = false; $('draw').setAttribute('aria-pressed','false');
  $('frame-title').textContent = `사진 ${index+1}`; $('status').textContent = statuses[frame.status];
  $('source-info').textContent = `${frame.source.width} × ${frame.source.height} · ${frame.source.video || '원본 사진'} · frame ${frame.source.video_frame ?? index}`;
  $('candidate-source').textContent = `원본 초안 출처: ${frame.source.annotation_source || '원본 라벨 자료'} · 초안은 정답 승인이 아닙니다.`;
  $('image-message').hidden = false; $('image-message').textContent = '사진을 불러오는 중';
  $('canvas').width = frame.source.width; $('canvas').height = frame.source.height;
  renderBoxes(); list(); paint(); enable();
  const next = new Image();
  next.onload = () => {
    if (serial !== loadSerial) return;
    if (next.naturalWidth !== frame.source.width || next.naturalHeight !== frame.source.height) {
      error('사진 크기가 원본과 다릅니다'); return;
    }
    image = next; ready = true; $('image-message').hidden = true;
    $('save-status').textContent = `서버 저장됨 · v${frame.version}`; paint(); enable();
  };
  next.onerror = () => { if (serial === loadSerial) {error('원본 사진을 불러오지 못했습니다. 승인할 수 없습니다.'); enable();} };
  next.src = `/api/images/${index}?v=${frame.version}`;
}
function selectField(label, options, value, changed) {
  const wrapper = document.createElement('label'); wrapper.append(document.createTextNode(label));
  const select = document.createElement('select'); select.className = 'ui-field';
  for (const [id,text] of Object.entries(options)) {const option=document.createElement('option'); option.value=id; option.textContent=text; select.append(option);}
  select.value=value ?? ''; select.onchange=() => changed(select.value); wrapper.append(select); return wrapper;
}
function renderBoxes() {
  $('boxes').replaceChildren(); $('empty').hidden = !!frame.review.boxes.length;
  frame.review.boxes.forEach((box,i) => {
    const row=document.createElement('div'); row.className='box-row'; const top=document.createElement('div'); top.className='box-top';
    const number=document.createElement('span'); number.className='box-number'; number.textContent=`#${i+1}`; top.append(number);
    top.append(selectField(`박스 ${i+1} 클래스`,names,box.label,value => edit(boxes=> {boxes[i].label=value || null; if(value==='traffic_light') boxes[i].signal_state ??= 'unknown';})));
    if (box.label === 'traffic_light') top.append(selectField(`박스 ${i+1} 신호`,states,box.signal_state || 'unknown',value=>edit(boxes=>boxes[i].signal_state=value)));
    const remove=document.createElement('ui-button'); remove.setAttribute('kind','quiet'); remove.textContent=`박스 ${i+1} 삭제`; remove.onclick=()=>edit(boxes=>boxes.splice(i,1)); top.append(remove); row.append(top);
    const coordinates=document.createElement('div'); coordinates.className='coordinates';
    ['x0','y0','x1','y1'].forEach((name,j) => {
      const label=document.createElement('label'); label.textContent=name;
      const input=document.createElement('input'); input.className='ui-field'; input.type='number'; input.step='0.1'; input.min='0'; input.max=String(j%2 ? frame.source.height : frame.source.width); input.value=box.bbox_xyxy[j]; input.setAttribute('aria-label',`박스 ${i+1} ${name}`);
      input.onchange=()=>edit(boxes=>boxes[i].bbox_xyxy[j]=Number(input.value)); label.append(input); coordinates.append(label);
    }); row.append(coordinates); $('boxes').append(row);
  });
  enable();
}
async function mutate(action, extras={}) {
  if (busy || !ready || conflicted) return;
  busy=true; error(); $('complete').checked=false; $('save-status').textContent='서버에 저장 중…'; enable();
  const id=frame.index;
  try {
    const saved=await request(`/api/frames/${id}`,{version:frame.version,action,...extras});
    workspace.frames[workspace.frames.findIndex(f=>f.index===id)]=saved; frame=structuredClone(saved);
    $('status').textContent=statuses[frame.status]; $('save-status').textContent=`서버 저장됨 · v${frame.version}`;
    renderBoxes(); list(); paint();
  } catch(e) {error(e.message); renderBoxes(); $('save-status').textContent='저장 실패 · 최신 내용 불러오기 후 다시 수정하세요';}
  finally {busy=false; enable();}
}
function edit(change) {
  if (busy || !ready || conflicted) return;
  const boxes=structuredClone(frame.review.boxes); change(boxes); mutate('save',{boxes});
}
$('complete').onchange=enable;
$('approve').onclick=()=> {if ($('complete').checked) mutate('approve',{complete_frame_review:true});};
$('exclude').onclick=()=>mutate('exclude'); $('reopen').onclick=()=>mutate('reopen');
$('candidates').onclick=()=> {if (window.confirm('현재 수정 라벨을 원본 초안으로 바꾸고 재검수하시겠습니까?')) mutate('candidates');};
$('draw').onclick=()=> {drawing=!drawing; $('draw').setAttribute('aria-pressed',String(drawing));};
$('add').onclick=()=>edit(boxes=>boxes.push({label:null,bbox_xyxy:[0,0,Math.min(40,frame.source.width),Math.min(40,frame.source.height)]}));
function point(event) {const rect=$('canvas').getBoundingClientRect(); return [Math.max(0,Math.min(frame.source.width,(event.clientX-rect.left)*frame.source.width/rect.width)),Math.max(0,Math.min(frame.source.height,(event.clientY-rect.top)*frame.source.height/rect.height))];}
$('canvas').onpointerdown=event=> {if (drawing && ready && !busy && !conflicted && frame.status!=='excluded') {start=point(event); $('canvas').setPointerCapture(event.pointerId);}};
$('canvas').onpointerup=event=> {
  if (!start) return; const end=point(event), begin=start; start=null;
  if (Math.abs(begin[0]-end[0])<2 || Math.abs(begin[1]-end[1])<2) return;
  edit(boxes=>boxes.push({label:null,bbox_xyxy:[Math.min(begin[0],end[0]),Math.min(begin[1],end[1]),Math.max(begin[0],end[0]),Math.max(begin[1],end[1])].map(v=>Math.round(v*10)/10)}));
};
$('canvas').onpointercancel=()=> {start=null;};
$('filter').onchange=list;
$('reload').onclick=async()=> {if(!busy) await load(frame?.index);};
$('theme').value=document.documentElement.dataset.theme || 'dark';
$('theme').onchange=()=> {document.documentElement.dataset.theme=$('theme').value; try {localStorage.setItem('rosy.theme',$('theme').value);} catch {} clearPalette(); document.dispatchEvent(new CustomEvent('rosy:theme')); paint();};
function receipt(value) {
  $('export-result').textContent=`승인 ${value.exported_frames}장 준비 완료 · 미승인 ${value.queued_frames}장 유지. 학습 반영은 학습 세션의 세션 분리·고정 평가 제외 확인 후 진행합니다.`;
  $('export-details').textContent=JSON.stringify(value,null,2);
}
$('prepare').onclick=async()=> {
  if (busy || conflicted) return; busy=true; enable(); error(); $('export-result').textContent='원본과 승인 라벨을 검증하는 중…';
  try {receipt(await request('/api/prepare',{}));} catch(e) {error(e.message); $('export-result').textContent='자료 준비 실패';} finally {busy=false; enable();}
};
async function load(index) {
  try {workspace=await request('/api/workspace'); conflicted=false; error();
    if(workspace.exports.length) receipt(workspace.exports[0]);
    if (!workspace.frames.length) throw new Error('등록된 사진이 없습니다');
    await select(index ?? workspace.frames[0].index);
  } catch(e) {error(e.message);}
}
load();
