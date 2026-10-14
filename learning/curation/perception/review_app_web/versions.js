import {accountFetch} from '/account-session.js';
import {actorName} from '/ai-jobs.js';
// Read-only history. Frame changes invalidate every outstanding response.
let generation=0;
const labels={import:'자료 가져오기',additional_import:'추가 자료',save:'라벨 수정',approve:'승인',exclude:'제외',reopen:'재검수',paint:'브러시 저장',fill:'전체 채우기',fill_unknown:'미검수 채우기',flood:'점 영역',sample:'선택 영역',polygon:'다각형',apply_draft:'AI 초안 적용',merge_draft:'AI 초안 보완',undo:'되돌리기',candidates:'원본 초안 적용'};
function element(tag,text){const node=document.createElement(tag);if(tag==='ui-button')node.setAttribute('kind','quiet');if(text)node.textContent=text;return node;}
function panel(){
  let node=document.getElementById('review-versions');
  if(!node){node=element('details');node.id='review-versions';node.className='review-history';node.append(element('summary','전체 이력 · 이전 버전 비교'));document.querySelector('.review-history').after(node);}
  return node;
}
export function resetVersions(){generation++;const node=document.getElementById('review-versions');if(node)node.remove();}
async function read(url){const response=await accountFetch(url);if(!response.ok)throw new Error('버전 정보를 불러오지 못했습니다.');return response.json();}
export function showVersions(lane,index){
  resetVersions();const ticket=generation,node=panel(),note=element('p','이전 버전은 읽기 전용입니다. 현재 편집 내용과 승인은 바뀌지 않습니다.'),list=element('ul'),preview=element('section'),more=element('ui-button','이력 불러오기'),message=element('p');
  message.setAttribute('role','status');preview.setAttribute('aria-label','선택한 이전 버전');node.append(note,list,more,message,preview);let before=null,loaded=false,selection=0;
  async function select(number){
    const request=++selection;preview.replaceChildren(element('p','버전 불러오는 중…'));
    try{
      const value=await read(`/api/review-versions/${lane}/${index}/${number}`);
      if(ticket!==generation||request!==selection)return;
      preview.replaceChildren(element('h3',`이전 버전 v${number} · 읽기 전용`));
      preview.append(element('p',`작업자 ${actorName(value.actor)} · ${value.ts?`${value.ts} UTC`:'시각 미기록'} · 상태 ${{approved:'승인',excluded:'제외',pending:'대기'}[value.status]||'기록 없음'}`));
      if(!value.available){preview.append(element('p','이 버전의 원본 스냅샷이 남아 있지 않아 비교할 수 없습니다.'));return;}
      if(lane==='pixel'){
        const photo=element('img');photo.alt=`이전 픽셀 버전 ${number}, 원본 사진 위에 표시`;photo.src=`/api/review-version-images/${index}/${number}`;
        photo.onerror=()=>{if(ticket===generation&&request===selection)preview.append(element('p','이전 마스크 이미지를 불러오지 못했습니다.'));};preview.append(photo);
      }else{
        const canvas=element('canvas');canvas.setAttribute('role','img');canvas.setAttribute('aria-label',`이전 객체 버전 ${number}, 원본 사진 위에 표시한 객체 박스`);const photo=new Image();photo.onload=()=>{if(ticket!==generation||request!==selection)return;canvas.width=photo.naturalWidth;canvas.height=photo.naturalHeight;const ctx=canvas.getContext('2d');ctx.drawImage(photo,0,0);ctx.strokeStyle=getComputedStyle(node).getPropertyValue('--ink').trim()||'black';ctx.lineWidth=Math.max(2,canvas.width/300);for(const box of value.boxes){const [x,y,x1,y1]=box.bbox_xyxy;ctx.strokeRect(x,y,x1-x,y1-y);}};photo.onerror=()=>{if(ticket===generation&&request===selection)preview.append(element('p','원본 사진을 불러오지 못했습니다.'));};photo.src=`/api/images/${index}`;preview.append(canvas);
        const rows=element('ul');for(const box of value.boxes)rows.append(element('li',`${box.label||'미분류'} · [${box.bbox_xyxy.join(', ')}]`));
        preview.append(element('p','현재 화면의 원본 사진·객체와 좌표를 비교하세요.'));preview.append(rows);if(!value.boxes.length)preview.append(element('p','객체 없음'));
      }
    }catch(error){if(ticket===generation&&request===selection)preview.replaceChildren(element('p',error.message));}
  }
  async function load(){
    more.disabled=true;message.textContent='이력 불러오는 중…';
    try{
      const value=await read(`/api/review-history/${lane}/${index}${before===null?'':`?before=${before}`}`);
      if(ticket!==generation)return;
      for(const event of value.events){const item=element('li'),button=element('ui-button',`v${event.version} · ${labels[event.action]||event.action} · ${actorName(event.actor)} · ${event.ts} UTC`);button.onclick=()=>select(event.version);item.append(button);list.append(item);}
      before=value.next_before;loaded=true;more.hidden=before===null;more.textContent='이전 이력 더 보기';message.textContent=list.children.length?'버전을 선택하면 저장된 결과를 조회합니다.':'아직 저장된 이력이 없습니다.';
    }catch(error){if(ticket===generation)message.textContent=error.message;}
    finally{if(ticket===generation)more.disabled=false;}
  }
  more.onclick=load;node.ontoggle=()=>{if(node.open&&!loaded&&!more.disabled)load();};
}
