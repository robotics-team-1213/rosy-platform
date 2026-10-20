const panel = document.createElement('aside'); panel.id = 'rosy-sample-controls'; panel.setAttribute('aria-label', '샘플 개발 제어');
const label = document.createElement('strong'); label.textContent = 'SAMPLE · 실제 장치와 연결되지 않음'; panel.append(label);
const hint = document.createElement('span'); hint.textContent = '로그인: sample / sample-password'; panel.append(hint);
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
button('조회자 시나리오', async () => { await control('reset', {scenario_id:'viewer'}); location.assign('/console/login'); });
for (const [text, event] of [['운행 완료', 'complete'], ['운행 실패', 'fail'], ['연결 대기', 'hold'], ['운행 재개', 'resume']]) {
  button(text, () => control('advance', {flow_id:'work', event}));
}
button('샘플 음성 입력', () => dispatchEvent(new CustomEvent('rosy-sample-voice', {detail:{text:'샘플 로봇의 상태를 알려줘'}})));
button('마이크 거절', () => dispatchEvent(new CustomEvent('rosy-sample-voice', {detail:{error:'not-allowed'}})));
for (const [text, state] of [['영상 지연', 'stale'], ['영상 복구', 'live'], ['영상 없음', 'lost']]) {
  button(text, () => dispatchEvent(new CustomEvent('rosy-sample-media', {detail:{state}})));
}
panel.append(message); document.body.append(panel);
