const status = {pending:'대기',approved:'승인',excluded:'제외'};
const actions = {import:'가져온 검수 상태 · 검수자 식별 불가',additional_import:'추가 자료 가져오기 · 검수 대기',save:'라벨 수정',approve:'승인',candidates:'원본 초안 적용',exclude:'제외',reopen:'재검수 시작',
  paint:'브러시 저장',fill:'전체 채우기',fill_unknown:'미검수 영역 채우기',flood:'점 영역 저장',
  sample:'선택 영역 저장',polygon:'다각형 저장',apply_draft:'모델 초안 적용',undo:'수정 되돌리기'};

export function showHistory(value) {
  const source = value.source ? `원본 초안: ${value.source}` : '원본 초안: 출처 기록 없음';
  document.getElementById('review-history-summary').textContent =
    `${source} · 객체 ${status[value.object_status]} · 픽셀 ${status[value.pixel_status]}`;
  const list = document.getElementById('review-history-events');
  list.replaceChildren();
  for (const [lane, label] of [['object','객체'],['pixel','픽셀']]) {
    const events = value.events[lane];
    if (!events.length) {
      const item = document.createElement('li');
      item.textContent = `${label}: 앱 변경 이력 없음${value[`${lane}_status`] === 'pending' ? '' : ' · 가져온 상태, 검수자 식별 불가'}`;
      list.append(item);
    }
    for (const event of events) {
      const item = document.createElement('li');
      item.textContent = `${label} v${event.version} · ${actions[event.action] || event.action} · ${event.ts} UTC`;
      list.append(item);
    }
  }
}
