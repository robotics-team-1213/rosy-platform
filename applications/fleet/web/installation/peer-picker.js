// D-452: catalogue metadata selects a known owner, never an advertised URL.
import {createPollGate} from '/console/assets/poll-gate.js';
export const PEER_ROLES = {robot: '로봇', fleet: '사이트 관제', 'overhead-camera': '관제 카메라',
  dock: '도킹 장치', signal: '신호기', 'model-host': '모델 호스트', pilot: 'Pilot 앱', cam: 'Cam 앱'};

export function peerOwnerAction(peer, {robots = [], sources = []} = {}) {
  if (peer.approval !== 'approved' || !peer.peer_id || ['conflict', 'expired'].includes(peer.freshness)) return null;
  if (peer.role === 'robot' && robots.includes(peer.peer_id)) {
    return {href: `/console?robot=${encodeURIComponent(peer.peer_id)}`, label: '로봇 상태 보기'};
  }
  if (peer.role === 'cam' && sources.includes(peer.peer_id)) return {source: peer.peer_id, label: '카메라 보기'};
  return null;
}

export function peerStateText(peer) {
  if (peer.freshness === 'conflict') return '장비 정보 충돌 · 확인 필요';
  if (peer.freshness === 'expired') return '검색 정보 만료';
  if (peer.approval !== 'approved') return '승인 필요';
  if (peer.readiness === 'verified') return '승인됨 · 연결 확인됨';
  if (peer.readiness === 'unreachable') return '승인됨 · 연결 확인 실패';
  return '승인됨 · 상태 미확인';
}

export function createPeerPicker({scope, el, call, isLocked, isActive, sources, onCamera}) {
  const list = el('peer-list'), empty = el('peer-empty'), status = el('peer-status');
  const filter = el('peer-role'), retry = el('peer-retry');
  let snapshot = null, robots = [], pending = null;
  const gate = createPollGate();
  for (const [value, name] of Object.entries(PEER_ROLES)) {
    const option = document.createElement('option');
    option.value = value; option.textContent = name; filter.append(option);
  }

  function message(text, tone = 'neutral', label = '장비 목록 준비') {
    list.replaceChildren(); list.hidden = true;
    empty.textContent = text; empty.hidden = false;
    status.textContent = label; status.setAttribute('status', tone);
  }

  function render() {
    if (!snapshot) return;
    const focused = document.activeElement?.closest?.('[data-peer-key]');
    const focusedKey = focused?.dataset.peerKey;
    const peers = snapshot.peers.filter(peer => !filter.value || peer.role === filter.value);
    const rows = peers.map(peer => {
      const item = document.createElement('li');
      item.dataset.peerKey = `${peer.role}:${peer.peer_id || peer.hostname || peer.name}`;
      const identity = document.createElement('div'); identity.className = 'peer-identity';
      const name = document.createElement('b'); name.textContent = peer.name;
      const detail = document.createElement('small');
      detail.textContent = `${PEER_ROLES[peer.role] || '장비'} · ${peerStateText(peer)}`;
      identity.append(name, detail); item.append(identity);
      const action = peerOwnerAction(peer, {robots, sources: sources()});
      if (action) {
        const control = document.createElement(action.href ? 'a' : 'ui-button');
        control.textContent = action.label;
        if (action.href) { control.href = action.href; control.className = 'peer-owner-link'; }
        else { control.setAttribute('kind', 'quiet'); control.dataset.cameraSource = action.source; }
        item.append(control);
      } else {
        const note = document.createElement('small'); note.className = 'peer-owner-note';
        note.textContent = peer.approval !== 'approved' ? '운영자가 승인한 뒤 연결할 수 있습니다.'
          : ['conflict', 'expired'].includes(peer.freshness) ? '장비 정보를 다시 확인하세요.'
            : '등록된 담당 화면이 없습니다.';
        item.append(note);
      }
      return item;
    });
    list.replaceChildren(...rows); list.hidden = rows.length === 0;
    empty.hidden = rows.length !== 0;
    empty.textContent = filter.value ? '이 역할의 장비가 없습니다. 다른 역할을 선택하거나 다시 찾으세요.'
      : '아직 장비가 없습니다. 장비 전원과 승인된 네트워크 연결을 확인한 뒤 다시 찾으세요.';
    const expired = snapshot.scanner_state === 'expired';
    status.textContent = expired ? '검색 정보 만료 · 승인 목록은 유지됩니다.'
      : snapshot.scanner_state === 'never_seen' ? '네트워크 검색 대기 · 승인 목록 표시'
        : `${snapshot.peers.length}개 장비 · 검색 정보 수신 중`;
    status.setAttribute('status', expired ? 'warn' : 'neutral');
    if (focusedKey) rows.find(row => row.dataset.peerKey === focusedKey)?.querySelector('a, ui-button')?.focus({preventScroll: true});
  }

  function reset() {
    snapshot = null; robots = []; pending = null;
    gate.reset();
    message('접속 후 장비 목록을 확인하세요.', 'neutral', '접속 필요');
    retry.removeAttribute('disabled');
    retry.removeAttribute('reason');
  }

  async function refresh() {
    const life = scope.capture(); life.check();
    if (isLocked() || !isActive() || pending || !gate.due()) return;
    const work = {}; pending = work;
    retry.setAttribute('reason', '장비 목록을 확인하는 동안 기다려 주세요.');
    retry.setAttribute('disabled', '');
    if (!snapshot) message('장비 목록을 확인하고 있습니다.', 'neutral', '불러오는 중');
    try {
      const [catalogue, ownerState] = await Promise.allSettled([
        call('/api/fleet/peers', {signals: [AbortSignal.timeout(10000)]}),
        call('/api/fleet/state', {signals: [AbortSignal.timeout(10000)]}),
      ]);
      life.check();
      if (pending !== work || isLocked()) return;
      if (catalogue.status !== 'fulfilled') throw catalogue.reason;
      if (!Array.isArray(catalogue.value.peers) || catalogue.value.peers.length > 64) throw new Error('Invalid peer catalogue');
      robots = ownerState.status === 'fulfilled' ? (ownerState.value.robots || []).map(robot => robot.robot_id) : [];
      snapshot = catalogue.value; gate.ok(); render();
    } catch (error) {
      if (error.name === 'AbortError' || !life.current() || pending !== work) return;
      snapshot = null; robots = [];
      const absent = gate.fail(error.status, error.code) === 'absent';
      message(error.status === 401 || isLocked() ? '인증이 필요합니다. 접속 후 다시 찾으세요.'
        : absent ? '이 Fleet에는 장비 검색이 설정되지 않았습니다. 연결한 사이트를 확인하세요.'
          : '장비 목록을 확인하지 못했습니다. 연결을 확인한 뒤 다시 찾으세요.', 'warn',
        error.status === 401 || isLocked() ? '접속 필요' : absent ? '검색 미설정' : '목록 확인 실패');
    } finally {
      if (life.current() && pending === work) {
        pending = null; retry.removeAttribute('disabled'); retry.removeAttribute('reason');
      }
    }
  }

  scope.listen(filter, 'change', render);
  scope.listen(retry, 'click', () => { gate.reset(); return refresh(); });
  scope.listen(list, 'click', async event => {
    const source = event.target.closest?.('[data-camera-source]')?.dataset.cameraSource;
    if (!source || isLocked() || !sources().includes(source)) return;
    const life = scope.capture(); life.check();
    await onCamera(source); life.check();
  });
  scope.onDispose(reset);
  return {refresh, reset, render};
}
