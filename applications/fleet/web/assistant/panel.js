// Console owns draft/display only; Fleet owns durable requests and all facts.
import { createVoice } from './assistant-voice.js';
import {voicePlatform} from '/console/assets/app-runtime.js';
export function createDialogue() {
  let identity = null, generation = 0, conversation = crypto.randomUUID(), pending = null;
  const rows = [];
  function reset() { generation++; conversation = crypto.randomUUID(); pending = null; rows.length = 0; }
  return {
    rows,
    get busy() { return pending !== null; },
    get pending() { return pending; },
    setIdentity(value) { if (value !== identity) { identity = value; reset(); return true; } return false; },
    reset,
    begin(text, selectedRobot = null, locale = 'ko-KR') {
      if (!identity) throw new Error('ASSISTANT_IDENTITY_REQUIRED');
      if (pending) throw new Error('ASSISTANT_PENDING');
      if (!text.trim() || text.length > 2000) throw new Error('ASSISTANT_TEXT_INVALID');
      pending = {generation, message:{conversation_id:conversation, request_id:crypto.randomUUID(), text,
        selected_robot_id:selectedRobot || null, locale}};
      return pending;
    },
    retry() { return pending; },
    failed(ticket) { return ticket?.generation === generation && ticket === pending; },
    receive(ticket, row) {
      if (ticket?.generation !== generation || row.request_id !== ticket.message.request_id ||
          row.conversation_id !== ticket.message.conversation_id || ticket !== pending) return false;
      const at = rows.findIndex(old => old.request_id === row.request_id);
      if (at < 0) rows.push(row); else rows[at] = row;
      if (rows.length > 40) rows.shift();
      if (!['PENDING', 'RUNNING'].includes(row.state)) pending = null;
      return true;
    },
  };
}

const stateText = {PENDING:'요청 접수', RUNNING:'확인 중', ANSWERED:'답변', HOLD:'보류', UNKNOWN:'처리 결과 미확인'};

export function createAssistantPanel({scope, call, el, readSelection}) {
  const dialogue = createDialogue();
  const panel = el('assistant-panel'), input = el('assistant-input'), list = el('assistant-messages');
  const status = el('assistant-state'), toggle = el('assistant-toggle');
  let identity = null, available = false, timer = null;
  let listening = false;
  const voiceState = el('assistant-voice-state');
  const voice = createVoice({platform: voicePlatform, onText(text) { if (identity && !dialogue.busy) { input.value = text; input.focus(); } },
    onState(state) {
      listening = state === 'listening';
      voiceState.textContent = {listening:'듣고 있습니다. 인식을 마치면 내용을 확인하고 전송해 주세요.',
        ready:'인식문을 확인하고 전송해 주세요.', empty:'인식된 음성이 없습니다.', denied:'마이크 사용이 거부되었습니다.',
        unavailable:'이 브라우저에서 한국어 음성 입력을 사용할 수 없습니다. 텍스트로 입력해 주세요.',
        'too-long':'입력 길이를 초과했습니다. 짧게 다시 말해 주세요.', error:'음성을 인식하지 못했습니다. 텍스트로 입력해 주세요.',
        'no-voice':'한국어 읽기 음성이 없습니다. 화면의 답변을 확인해 주세요.'}[state] || '';
      paint();
    }});
  function clearTimer() { clearTimeout(timer); timer = null; }
  function setOff(control, off, reason) {
    control.disabled = off;
    if (off) control.setAttribute('reason', reason);
    else control.removeAttribute('reason');
  }
  function paint() {
    const reason = !identity ? '기명 운영자로 로그인해 주세요.' : listening ? '음성 인식을 마쳐 주세요.' : '요청 처리 중입니다.';
    setOff(el('assistant-send'), !identity || !available || dialogue.busy || listening,
      identity && !available ? '관제 AI 연결 준비 중입니다.' : reason);
    setOff(input, !identity || dialogue.busy || listening, reason);
    input.setAttribute('aria-describedby', 'assistant-state assistant-voice-state');
    setOff(el('assistant-dictate'), !identity || dialogue.busy || listening, reason);
    setOff(el('assistant-read'), !identity || listening || !dialogue.rows.some(row => row.state === 'ANSWERED' && row.response),
      !identity || listening ? reason : '읽을 답변이 없습니다.');
    setOff(el('assistant-voice-prepare'), !identity, reason);
    list.replaceChildren();
    for (const row of identity ? dialogue.rows : []) {
      const item = document.createElement('li');
      const question = document.createElement('p'); question.textContent = '나: '+row.text;
      const answer = document.createElement('p'); answer.textContent = row.response || stateText[row.state] || '상태 확인 필요';
      const meta = document.createElement('small'); meta.textContent = stateText[row.state] || '상태 확인 필요';
      item.append(question, answer, meta);
      if (row.reason) { const reason = document.createElement('small'); reason.textContent = row.reason; item.append(reason); }
      if (row.facts?.length) {
        const facts = document.createElement('ul');
        for (const fact of row.facts) {
          const shown = document.createElement('li');
          shown.textContent = `${fact.text} · 조회 ${new Date(fact.observed_at*1000).toLocaleTimeString('ko-KR')}`;
          facts.append(shown);
        }
        item.append(facts);
      }
      list.append(item);
    }
  }
  async function refreshStatus() {
    if (!identity) { status.textContent = '기명 운영자로 로그인해 주세요.'; return; }
    const owner = identity;
    try {
      const result = await call('/api/fleet/assistant/status');
      if (owner !== identity) return;
      available = result.available;
      status.textContent = available ? '상태 조회와 상황 설명을 요청할 수 있습니다.' : '관제 AI 연결 준비 중입니다. 기존 관제 기능을 이용해 주세요.';
    } catch (error) {
      if (owner !== identity || error.name === 'AbortError') return;
      available = false;
      status.textContent = error.status === 403 ? '기명 운영자 접속이 필요합니다.' : '관제 AI 연결 상태를 확인하지 못했습니다.';
    }
    paint();
  }
  async function poll(ticket) {
    try {
      const row = await call('/api/fleet/assistant/messages/'+encodeURIComponent(ticket.message.request_id));
      if (!dialogue.receive(ticket, row)) return;
      paint();
      if (dialogue.busy) timer = setTimeout(() => poll(ticket), 1000);
      else status.textContent = stateText[row.state] || '상태 확인 필요';
    } catch (error) {
      if (!dialogue.failed(ticket) || error.name === 'AbortError') return;
      status.textContent = '요청 상태를 확인하지 못했습니다. 같은 요청 확인을 눌러주세요.';
      el('assistant-retry').hidden = false;
    }
  }
  async function post(ticket) {
    if (!ticket) return;
    el('assistant-retry').hidden = true;
    status.textContent = '요청을 확인하고 있습니다.'; paint();
    try {
      const row = await call('/api/fleet/assistant/messages', {method:'POST', body:JSON.stringify(ticket.message)});
      if (!dialogue.receive(ticket, row)) return;
      input.value = ''; paint();
      if (dialogue.busy) timer = setTimeout(() => poll(ticket), 1000);
      else status.textContent = stateText[row.state] || '상태 확인 필요';
    } catch (error) {
      if (!dialogue.failed(ticket) || error.name === 'AbortError') return;
      status.textContent = '접수 여부를 확인하지 못했습니다. 같은 요청 확인을 눌러주세요.';
      el('assistant-retry').hidden = false;
    }
  }
  function send() {
    if (!available || !identity || dialogue.busy || !input.value.trim()) return;
    post(dialogue.begin(input.value, readSelection(), el('assistant-locale').value));
  }
  function close() {
    voice.cancel(); listening = false; paint();
    voiceState.textContent = '';
    panel.hidden = true; toggle.setAttribute('aria-expanded', 'false'); toggle.focus();
  }
  scope.listen(toggle, 'click', () => {
    panel.hidden = !panel.hidden; toggle.setAttribute('aria-expanded', String(!panel.hidden));
    if (!panel.hidden) { refreshStatus(); input.focus(); }
  });
  scope.listen(el('assistant-close'), 'click', close);
  scope.listen(el('assistant-locale'), 'change', () => {
    voice.setLocale(el('assistant-locale').value); listening = false; paint();
  });
  scope.listen(panel, 'keydown', event => { if (event.key === 'Escape') close(); });
  scope.listen(el('assistant-send'), 'click', send);
  scope.listen(input, 'keydown', event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); send(); } });
  scope.listen(el('assistant-retry'), 'click', () => { clearTimer(); post(dialogue.retry()); });
  scope.listen(el('assistant-dictate'), 'click', () => { if (identity && !dialogue.busy) voice.start(); });
  scope.listen(el('assistant-dictate-stop'), 'click', () => voice.stop());
  scope.listen(el('assistant-voice-prepare'), 'click', async () => {
    if (!identity) return;
    const owner = identity;
    voiceState.textContent = '한국어 음성 입력을 준비하고 있습니다.';
    try {
      const ready = await voice.prepare();
      if (owner === identity) voiceState.textContent = ready ? '음성 입력을 사용할 수 있습니다.' : '이 브라우저에서 한국어 음성 입력을 사용할 수 없습니다.';
    } catch { if (owner === identity) voiceState.textContent = '음성 입력을 준비하지 못했습니다. 텍스트로 입력해 주세요.'; }
  });
  scope.listen(el('assistant-read'), 'click', () => {
    if (!identity) return;
    const last = dialogue.rows.findLast(row => row.state === 'ANSWERED' && row.response);
    if (last) voice.speak(last.response);
  });
  scope.listen(el('assistant-read-stop'), 'click', () => voice.stopSpeaking());
  scope.onDispose(() => {
    clearTimer(); voice.cancel(); listening = false; identity = null; available = false;
    input.value = ''; voiceState.textContent = ''; el('assistant-retry').hidden = true;
    status.textContent = '접속을 확인하고 있습니다.'; paint();
  });
  return {
    setIdentity(auth) {
      const next = !auth.locked && auth.role === 'operator' && auth.principal !== 'site-console' &&
        !auth.principal?.startsWith('development-') ? auth.principal || null : null;
      const changed = dialogue.setIdentity(next);
      if (!changed && identity === next) return;
      identity = next; available = false; clearTimer(); voice.cancel(); listening = false; input.value = ''; voiceState.textContent = '';
      el('assistant-retry').hidden = true; paint();
      status.textContent = identity ? '대화를 열면 연결 상태를 확인합니다.' : '기명 운영자로 로그인해 주세요.';
      if (!panel.hidden) refreshStatus();
      if (identity && dialogue.pending) poll(dialogue.pending);
    },
  };
}
