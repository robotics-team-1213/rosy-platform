const status = {pending:'대기',approved:'승인',excluded:'제외'};
const actions = {import:'가져온 검수 상태 · 검수자 식별 불가',additional_import:'추가 자료 가져오기 · 검수 대기',save:'검수 앱에서 라벨 수정',approve:'검수 앱에서 승인 · 담당자 미기록',candidates:'원본 초안 적용',exclude:'검수 앱에서 제외 · 담당자 미기록',reopen:'검수 앱에서 재검수 시작',
  paint:'브러시 저장',fill:'전체 채우기',fill_unknown:'미검수 영역 채우기',flood:'점 영역 저장',
  sample:'선택 영역 저장',polygon:'다각형 저장',apply_draft:'모델 초안 적용',merge_draft:'사람 라벨 유지 · 초안 보완',undo:'수정 되돌리기'};

export function reviewerSummary(value, lane) {
  const events=value.events[lane] || [], latest=events[0];
  const approval=events.find(event=>event.action==='approve');
  const actor=event=>event?.actor || '미기록';
  return `최근 작업자: ${actor(latest)} · 현재 승인자: ${value[`${lane}_status`]==='approved'?actor(approval):'승인 전'}`;
}

function overview() {
  let node=document.getElementById('review-people-summary');
  if(!node){
    node=document.createElement('p');node.id='review-people-summary';node.className='review-people-summary';node.setAttribute('role','status');
    const title=document.getElementById('pixel-title') || document.getElementById('frame-title');
    title.after(node);
    const link=document.createElement('a');link.href='#review-history-events';link.textContent='검수 이력 보기';link.className='review-history-link';
    link.onclick=()=>{const details=document.querySelector('.review-history');details.open=true;document.getElementById('review-history-events').focus();};
    node.after(link);document.getElementById('review-history-events').tabIndex=-1;
  }
  return node;
}

export function resetHistory(message='검수 주체와 이력을 불러오는 중…') {
  overview().textContent=message;
  document.getElementById('review-history-summary').textContent=message;
  document.getElementById('review-history-events').replaceChildren();
}

export function feedbackPresentation(value) {
  if(!value.available)return {state:'pending',title:'AI 검사 결과 없음',note:'저장된 AI 의견이 없습니다. 직접 검수하거나 학습 작업에서 검사 실행 구성을 확인하세요.'};
  const labels={concern:'검토할 문제 있음',no_obvious_concern:'뚜렷한 문제를 찾지 못함',uncertain:'AI 판단 보류',abstain:'AI 응답 없음'};
  const issues={missed_visible_road:'보이는 주행 영역 누락',drivable_outside_lane:'차선 밖 주행 영역',obstacle_as_drivable:'장애물을 주행 영역으로 표시',uncertain_visibility:'시야 불확실',none:'특정 문제 지적 없음'};
  const model=`검사 AI: ${value.model || '미기록'} · 버전 ${value.model_digest || '미기록'}`;
  if(!value.current)return {state:'warning',title:'이전 마스크의 AI 의견 · 재검사 필요',note:`${model} · 현재 마스크와 일치하지 않습니다. 이전 의견: ${value.feedback.note || '없음'}`};
  return {state:value.review_blocked || value.feedback.verdict!=='no_obvious_concern'?'warning':'ready',
    title:labels[value.feedback.verdict] || 'AI 상태 확인 필요',
    note:`${issues[value.feedback.issue] || '문제 종류 미기록'} · ${value.feedback.note || '추가 설명 없음'} · ${model} · 현재 마스크와 일치 · 미검수 ${value.unknown_pixels.toLocaleString()}픽셀`};
}

export function showHistory(value) {
  overview().textContent=reviewerSummary(value,document.getElementById('pixel-title')?'pixel':'object');
  const source = value.source ? `원본 초안: ${value.source}` : '원본 초안: 출처 기록 없음';
  document.getElementById('review-history-summary').textContent =
    `${source} · 객체 ${status[value.object_status]} · 픽셀 ${status[value.pixel_status]}`;
  const list = document.getElementById('review-history-events');
  list.replaceChildren();
  const chronological=[];
  for (const [lane, label] of [['object','객체'],['pixel','픽셀']]) {
    const events = value.events[lane];
    if (!events.length) {
      const item = document.createElement('li');
      item.textContent = `${label}: 앱 변경 이력 없음${value[`${lane}_status`] === 'pending' ? '' : ' · 가져온 상태, 검수자 식별 불가'}`;
      chronological.push({item,ts:'',version:0});
    }
    for (const event of events) {
      const item = document.createElement('li');
      let action=actions[event.action] || event.action;
      if(event.actor) action=action.replace(' · 담당자 미기록', '');
      item.textContent = `${label} v${event.version} · ${action} · 작업자 ${event.actor || '미기록'} · ${event.ts} UTC`;
      chronological.push({item,ts:event.ts,version:event.version});
    }
  }
  chronological.sort((a,b)=>b.ts.localeCompare(a.ts)||b.version-a.version).forEach(row=>list.append(row.item));
}
