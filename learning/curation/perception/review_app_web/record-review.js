// Saved raw evidence only. Opening or playing never writes an episode decision.
const $=id=>document.getElementById(id),API='/api/learning/recording';
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function value(number){return Number.isFinite(number)?String(number):'미확인';}
function localImage(path){if(typeof path!=='string'||!path.startsWith('/')||path.startsWith('//'))throw new Error('저장 영상 주소를 확인하지 못했습니다.');const url=new URL(path,location.origin);if(url.origin!==location.origin)throw new Error('동일한 저장소의 영상만 재생할 수 있습니다.');return url.pathname+url.search;}
export function createRecordingReview({request,onChange=()=>{}}){
  let generation=0,selection=null,metadata=null,current=0,wanted=0,loading=false,playing=false,timer=null;
  function status(message){$('record-review-status').textContent=message;}
  function controls(){const ready=!!metadata;$('review-frame').disabled=!ready;$('review-prev').disabled=!ready||wanted<=0;$('review-next').disabled=!ready||wanted>=metadata.frames-1;$('review-play').disabled=!ready;$('review-play').textContent=playing?'일시 정지':'재생';$('review-play').setAttribute('aria-pressed',String(playing));}
  function pause(){playing=false;clearTimeout(timer);timer=null;controls();}
  async function close(){
    const previous=selection,closedAt=++generation;pause();selection=null;metadata=null;loading=false;
    $('record-review-panel').hidden=true;$('review-cameras').replaceChildren();$('review-joints').replaceChildren();$('review-clocks').replaceChildren();$('review-frame-position').textContent='';controls();onChange();
    if(previous){try{await request(API+'/review-close',previous);}catch(exc){if(closedAt===generation)$('record-status').textContent=`저장 기록 검수 닫기 확인 실패: ${exc.message} 다시 확인하세요.`;}}
  }
  function table(headers,rows){const table=node('table',null,'record-review-table'),head=node('tr'),thead=node('thead'),body=node('tbody');for(const text of headers){const th=node('th',text);th.scope='col';head.append(th);}thead.append(head);for(const values of rows){const row=node('tr');for(const text of values)row.append(node('td',text));body.append(row);}table.append(thead,body);return table;}
  function clocks(frame){
    const rows=[];
    for(const arm of frame.arms)rows.push([arm.id,value(arm.state_timestamp),value(arm.reference_timestamp),value(arm.received_at),'—']);
    for(const camera of frame.cameras)rows.push([camera.id,'—',value(camera.timestamp),value(camera.received_at),value(camera.sequence)]);
    $('review-clocks').replaceChildren(node('p',`기록 기준 시각 ${value(frame.grid_time)} · 처리 시각 ${value(frame.processed_at)}`,'record-note'),table(['입력','측정 상태 시각','수락 참조·영상 시각','수신 시각','생산 순서'],rows));
  }
  async function paint(frame,expected,ticket){
    if(frame.frame_index!==expected||frame.total_frames!==metadata.frames||frame.scope!=='content_integrity_at_load')throw new Error('선택한 저장 프레임의 근거가 일치하지 않습니다. 다시 열어 확인하세요.');
    const figures=[],decodes=[];
    for(const camera of frame.cameras){const figure=node('figure',null,'record-review-camera'),image=node('img'),caption=node('figcaption',`${camera.id} · ${camera.role} · ${camera.purposes.join(', ')}`);image.src=localImage(camera.image_url);image.alt=`저장 회차 ${selection.episode_id} · ${camera.id} · 프레임 ${expected+1}`;figure.append(image,caption);figures.push(figure);decodes.push(image.decode());}
    await Promise.all(decodes);
    if(ticket!==generation||wanted!==expected)return false;
    $('review-cameras').replaceChildren(...figures);
    const rows=[];for(const arm of frame.arms)arm.joint_names.forEach((joint,index)=>rows.push([arm.id,joint,value(arm.state[index]),value(arm.accepted_reference[index]),arm.units]));
    $('review-joints').replaceChildren(table(['작업 팔','원본 관절','측정 상태','수락된 동작 참조','원본 단위'],rows));clocks(frame);
    current=expected;$('review-frame').value=String(expected);$('review-frame-position').textContent=`프레임 ${expected+1} / ${metadata.frames} · ${(expected/metadata.fps).toFixed(3).replace(/0+$/,'').replace(/\.$/,'')}초`;
    status(`불러올 때 기록 무결성 확인 · ${metadata.checked_at} · 실제 동작·과제 성공은 검증하지 않았습니다.`);controls();return true;
  }
  async function loadFrame(index,ticket=generation){
    if(!metadata||ticket!==generation)return;
    wanted=Math.max(0,Math.min(metadata.frames-1,index));$('review-frame').value=String(wanted);controls();if(loading)return;
    loading=true;
    try{
      while(ticket===generation&&metadata){const next=wanted;status('저장 프레임을 읽는 중입니다.');const selected=selection,revision=metadata.evidence_revision;
        const frame=await request(`${API}/review-frame/${encodeURIComponent(selected.session_id)}/${encodeURIComponent(selected.episode_id)}/${revision}/${next}`);
        if(ticket!==generation)return;if(next!==wanted)continue;
        await paint(frame,next,ticket);if(ticket!==generation)return;if(next===wanted)break;
      }
    }catch(exc){if(ticket===generation){pause();status(`저장 기록 재생 실패: ${exc.message} 닫은 뒤 다시 열어 확인하세요.`);}}
    finally{if(ticket===generation){loading=false;controls();if(playing)schedule();}}
  }
  function schedule(){clearTimeout(timer);if(!playing||loading||!metadata)return;if(current>=metadata.frames-1){pause();return;}timer=setTimeout(()=>loadFrame(current+1),1000/Math.max(1,Math.min(60,metadata.fps)));}
  async function prepare(ticket,refresh){
    try{const selected=selection;const result=await request(`${API}/review/${encodeURIComponent(selected.session_id)}/${encodeURIComponent(selected.episode_id)}${refresh?'?refresh=1':''}`);if(ticket!==generation)return;
      if(result.status==='preparing'){status('저장 기록의 무결성과 영상 목록을 준비하는 중입니다. 녹화 정지는 계속 사용할 수 있습니다.');timer=setTimeout(()=>prepare(ticket,false),1000);return;}
      if(result.status!=='ready')throw new Error(typeof result.error==='string'?result.error:result.error?.message||'저장 기록을 확인하지 못했습니다.');
      if(result.scope!=='content_integrity_at_load'||!Number.isInteger(result.frames)||result.frames<1||!Number.isFinite(result.fps)||result.fps<=0||!/^[0-9a-f]{64}$/.test(result.evidence_revision))throw new Error('검수할 저장 기록의 버전·범위를 확인하지 못했습니다.');
      metadata=result;$('review-frame').min='0';$('review-frame').max=String(result.frames-1);$('review-frame').step='1';$('review-evidence').textContent=`구성 버전 ${result.profile_revision} · 기록 버전 ${result.evidence_revision} · 범위 ${result.scope}`;onChange();await loadFrame(0,ticket);
    }catch(exc){if(ticket===generation){pause();status(`저장 기록 준비 실패: ${exc.message} 닫은 뒤 다시 열어 확인하세요.`);}}
  }
  async function open(session_id,episode_id,trigger){const closing=close(),closedAt=generation;await closing;if(closedAt!==generation)return;const ticket=++generation;selection={session_id,episode_id};current=0;wanted=0;loading=false;$('record-review-panel').hidden=false;$('review-title').textContent=`저장 기록 재생·검수 · ${episode_id}`;status('저장 기록의 무결성을 확인하는 중입니다.');$('review-frame').value='0';controls();onChange();$('record-review-panel').scrollIntoView({block:'start'});if(trigger)$('review-close').dataset.returnEpisode=episode_id;prepare(ticket,true);}
  $('review-close').onclick=()=>{const episode=$('review-close').dataset.returnEpisode;close();for(const button of document.querySelectorAll('[data-review]'))if(button.dataset.review===episode&&!button.disabled){button.focus();break;}};
  $('review-play').onclick=()=>{if(playing){pause();return;}if(!metadata)return;playing=true;controls();if(current>=metadata.frames-1)loadFrame(0);else schedule();};
  $('review-prev').onclick=()=>{pause();loadFrame(wanted-1);};$('review-next').onclick=()=>{pause();loadFrame(wanted+1);};$('review-frame').oninput=()=>{pause();loadFrame(Number($('review-frame').value));};
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});controls();
  return {open,close,pause,isOpen:()=>!!selection,isPreparing:()=>!!selection&&!metadata};
}
