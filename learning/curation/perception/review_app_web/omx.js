// D-792 S4: read-only list of prepared OMX demonstration sets. No writes, no device action.
import {accountFetch} from '/account-session.js';
import '/common/ui.js';
import '/commands.js';
const $=id=>document.getElementById(id);
const VERDICT={ok:'맞음',adjust:'조정 필요',unmeasurable:'측정 불가'};
const SPLIT={train:'학습',eval:'평가',test:'시험',exclude:'제외'};
const OUTCOME={success:'성공',failure:'실패',unknown:'미정'};

$('theme').value=document.documentElement.dataset.theme||'dark';
$('theme').onchange=()=>{document.documentElement.dataset.theme=$('theme').value;try{localStorage.setItem('rosy.theme',$('theme').value);}catch{} document.dispatchEvent(new CustomEvent('rosy:theme'));};

function el(tag,text,cls){const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;}
function camera(checks){
  const roles=Object.entries(checks||{});
  if(!roles.length)return '기록 없음';
  return roles.map(([role,c])=>`${role}: ${VERDICT[c.before]||c.before} → ${VERDICT[c.after]||c.after}`).join(' · ');
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
  return section;
}
async function load(){
  $('omx-status').setAttribute('state','pending');$('omx-status').textContent='불러오는 중입니다.';
  try{
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
