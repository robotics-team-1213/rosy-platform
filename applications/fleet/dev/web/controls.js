const panel = document.createElement('aside'); panel.id = 'rosy-sample-controls'; panel.setAttribute('aria-label', '샘플 개발 제어');
const label = document.createElement('strong'); label.textContent = 'SAMPLE · 실제 장치와 연결되지 않음'; panel.append(label);
const hint = document.createElement('span'); hint.textContent = '로그인: sample / CHANGE_ME'; panel.append(hint);
const tokenHint = document.createElement('span'); tokenHint.textContent = '카메라 승인용 고급 접속 토큰: sample-operator'; panel.append(tokenHint);
const message = document.createElement('output'); message.setAttribute('aria-live', 'polite');
function button(text, action) {
  const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
  node.addEventListener('click', async () => {
    try { await action(); message.textContent = '적용됨'; }
    catch { message.textContent = '현재 상태에서는 적용할 수 없습니다.'; }
  }); panel.append(node);
}
async function control(path, payload) {
  const response = await fetch('/__dev/' + path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  if (!response.ok) throw Error('transition refused');
}
button('샘플 초기화', async () => { await control('reset', {scenario_id:'normal'}); location.assign('/console/login'); });
const cellHint = document.createElement('span'); cellHint.textContent = 'Cell 예제 문서 ID: sample · 작업셀: sample-cell · 인스턴스: sample-arm'; panel.append(cellHint);
for (const [text, event] of [['Cell 보류', 'hold'], ['Cell 동작 완료', 'action-complete'], ['Cell 목표 확인', 'complete']]) {
  button(text, () => control('advance', {flow_id:'cell_jobs', event}));
}
button('조회자 시나리오', async () => { await control('reset', {scenario_id:'viewer'}); location.assign('/console/login'); });
button('검토자로 로그인', async () => {
  const response = await fetch('/api/fleet/auth/login', {method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({login:'sample-reviewer', password:'CHANGE_ME'})});
  if (!response.ok) throw Error('login refused');
  location.reload();
});
for (const [text, event] of [['운행 완료', 'complete'], ['운행 실패', 'fail'], ['연결 대기', 'hold'], ['운행 재개', 'resume']]) {
  button(text, () => control('advance', {flow_id:'work', event}));
}
button('샘플 음성 입력', () => dispatchEvent(new CustomEvent('rosy-sample-voice', {detail:{text:'샘플 로봇의 상태를 알려줘'}})));
for (const [text, event] of [['AI 답변', 'answer'], ['AI 보류', 'hold'], ['AI 결과 미확인', 'unknown']]) {
  button(text, () => control('advance', {flow_id:'assistant', event}));
}
button('마이크 거절', () => dispatchEvent(new CustomEvent('rosy-sample-voice', {detail:{error:'not-allowed'}})));
for (const [text, state] of [['영상 지연', 'stale'], ['영상 복구', 'live'], ['영상 없음', 'lost']]) {
  button(text, () => dispatchEvent(new CustomEvent('rosy-sample-media', {detail:{state}})));
}
panel.append(message); document.body.append(panel);
