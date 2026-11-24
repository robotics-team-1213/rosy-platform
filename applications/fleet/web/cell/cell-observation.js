import {patchAttr, patchHidden, patchText} from '/common/control-dom.js';
import {createScope} from '/common/scope.js';
import {frameBadge} from '/console/assets/vision-view.js';
import {createRobotProfiles} from '/console/assets/robot-profile-view.js';
import {INCIDENT_BASES, INCIDENT_CAUSES} from '/console/assets/cell-frames.js';
import {createMotorHealthState, jointLabel, renderMotorHealth, renderMotorHealthSummary} from '/common/motor-health.js';

// A second joint lagging with the stopped one points at an outside restraint, not that motor (arm_a, 2026-11-01).
const LAGGING_DEG = 1;
const faultLine = fault => {
  const stopped = fault.motors.filter(motor => motor.fault);
  const lagging = fault.motors.filter(motor => !motor.fault && motor.error_deg >= LAGGING_DEG);
  return [
    ...stopped.map(motor => `${jointLabel(motor.joint)}(ID ${motor.id}) 정지 · 오차 ${motor.error_deg.toFixed(1)}° ` +
      `(목표 ${Math.round(motor.command_raw)} / 현재 ${Math.round(motor.present_raw)} tick, PWM ${Math.round(motor.pwm)}/${Math.round(motor.pwm_limit)})`),
    fault.stop_reasons.join(', '),
    lagging.length ? `함께 뒤처진 관절: ${lagging.map(motor => `${jointLabel(motor.joint)} ${motor.error_deg.toFixed(1)}°`).join(', ')}` : '',
  ].filter(Boolean).join(' · ');
};

const element = (tag, text = '') => {
  const node = document.createElement(tag); node.textContent = text; return node;
};
const staleArm = entry => {
  entry.fresh = false;
  patchText(entry.values, '최신 피드백 없음');
  patchText(entry.status, '수신 대기 · 원본 만료');
  patchAttr(entry.status, 'state', 'unavailable');
  entry.updateVisibility?.();
};
const staleCamera = (entry, detail = '') => {
  entry.live = false;
  entry.reason = detail;
  patchHidden(entry.image, true);
  patchText(entry.status, detail ? `최신 영상 없음 · ${detail}` : '최신 영상 없음');
  patchAttr(entry.status, 'state', 'unavailable');
  entry.updateVisibility?.();
};

const BASE = '/api/fleet/workcell-observations';
const STATE_LABEL = {open: '열림 · 사람 확인 필요', explained: '열림 · AI 설명 있음', cleared: '해제됨'};
const when = seconds => new Date(seconds * 1000).toLocaleString('ko-KR');

// D-971: what the control PC measured, as plain lines (text only, never markup)
export const incidentLines = incident => {
  const {facts = {}, decision = {}, recovery = null} = incident;
  const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const latched = facts.latched === undefined ? {} : facts.latched, flagged = facts.flagged === undefined ? [] : facts.flagged;
  const measured = ['latched', 'flagged', 'folded', 'torque_after', 'windup_hits'].some(key => key in facts)
    && record(latched) && Object.values(latched).every(latch => record(latch)
      && typeof latch.hw_error === 'number'
      && (latch.bits === undefined || (Array.isArray(latch.bits) && latch.bits.every(bit => typeof bit === 'string'))))
    && Array.isArray(flagged) && flagged.every(row => record(row) && typeof row.command === 'string'
      && ['error', 'fault'].every(key => row[key] == null || typeof row[key] === 'string'))
    && (facts.folded === undefined || typeof facts.folded === 'boolean')
    && (facts.windup_hits === undefined || Array.isArray(facts.windup_hits));
  const measurements = measured ? [
    Object.entries(facts.latched || {}).map(([id, latch]) => `ID ${id} 오류 ${latch.hw_error} (${(latch.bits || []).join('/')})`).join(', '),
    facts.folded === undefined ? '' : `홈 접힘 ${facts.folded ? '예' : '아니오'} · 종료 후 토크 ${JSON.stringify(facts.torque_after || {})}`,
    (facts.windup_hits || []).length ? `출력 상승 감지 ${facts.windup_hits.length}건` : '',
    (facts.flagged || []).map(row => `실행기: ${row.command} ${row.error || row.fault || ''}`).join(' · '),
  ].filter(Boolean) : [];
  return [
    typeof decision.reason === 'string' ? decision.reason : JSON.stringify(decision.reason),
    ...(measurements.length ? measurements : [Object.keys(facts).length ? JSON.stringify(facts) : '']),
    recovery ? `장치 안전 재부팅: ${JSON.stringify(recovery).slice(0, 300)}` : '',
  ].filter(Boolean);
};

export function createCellObservation({request, root, credential = () => '', onSummary = null}) {
  const empty = element('ui-empty', '접속하면 작업 셀의 실제 관측을 확인할 수 있습니다.');
  let life = null, pending = false, layout = '', disposed = false;
  let profiles = null;
  const arms = new Map(), cameras = new Map();
  // camera frames this browser held when a guard stop arrived, by session; the field PC keeps its own copies
  const faultFrames = new Map();
  const incidentFrames = new Map();  // D-971: blob URL of each incident frame, fetched once
  let seenFaults = null;
  // B-3 — 단계 화면 어디서든 볼 팔 예외 요약. 같은 내용을 다시 넘기지 않아 500 ms 폴링이 DOM을 흔들지 않는다.
  let lastSummaryKey = '', lastWorkcells = [], observedDisconnected = false;
  root.replaceChildren(empty);
  function paintHealth(entry) {
    const health = entry.health.read();
    entry.healthSeverity = health.severity || 'unknown';
    renderMotorHealthSummary(entry.healthSummary, health);
    if (entry.healthDetails.open) renderMotorHealth(entry.healthView, health);
    entry.healthPaintedAt = performance.now();
    entry.updateVisibility?.();
  }

  const isArmEntryActive = entry => Boolean(
    entry.fresh || entry.openIncidents > 0 || entry.healthSeverity === 'crit'
    || entry.healthSeverity === 'warn' || entry.focused,
  );

  function updateCellVisibility(cellState) {
    if (!cellState) return;
    const liveCams = cellState.camEntries.filter(cam => cam.live);
    const idleCams = cellState.camEntries.length - liveCams.length;
    const firstReason = cellState.camEntries.map(cam => cam.reason).find(Boolean) || '';
    const hideIdleCams = !cellState.showAllCameras && liveCams.length > 0;
    for (const camEntry of cellState.camEntries) {
      patchHidden(camEntry.card, hideIdleCams && !camEntry.live);
    }
    patchHidden(cellState.camBar, cellState.camEntries.length === 0 || liveCams.length === 0 || (idleCams === 0 && !cellState.showAllCameras));
    patchText(cellState.camSummary, cellState.showAllCameras
      ? `전체 셀 카메라 ${cellState.camEntries.length}대 표시 중`
      : `실시간 카메라 ${liveCams.length}/${cellState.camEntries.length}대 · 대기 ${idleCams}대 숨김`);
    patchText(cellState.camToggle, cellState.showAllCameras ? '실시간 카메라만 보기' : `대기 카메라 ${idleCams}대 보기`);
    patchHidden(cellState.camEmpty, cellState.camEntries.length === 0 || liveCams.length > 0);
    patchText(cellState.camEmptyText, firstReason
      ? `실시간 카메라 0/${cellState.camEntries.length}대 · ${firstReason}`
      : `실시간 카메라 0/${cellState.camEntries.length}대 · 영상 연결 확인 중`);

    const activeArms = cellState.armEntries.filter(isArmEntryActive);
    const idleArms = cellState.armEntries.length - activeArms.length;
    for (const armEntry of cellState.armEntries) {
      patchHidden(armEntry.card, !cellState.showAllArms && !isArmEntryActive(armEntry));
    }
    patchHidden(cellState.armBar, cellState.armEntries.length === 0 || (idleArms === 0 && !cellState.showAllArms));
    patchText(cellState.armSummary, cellState.showAllArms
      ? `전체 팔 ${cellState.armEntries.length}대 표시 중`
      : activeArms.length
        ? `활성·주의 팔 ${activeArms.length}대 표시 · 대기 팔 ${idleArms}대 숨김`
        : `활성·주의 팔 없음 · 대기 팔 ${idleArms}대 숨김`);
    patchText(cellState.armToggle, cellState.showAllArms ? '활성·주의 팔만 보기' : `대기 팔 ${idleArms}대 보기`);
    patchHidden(cellState.armEmpty, cellState.armEntries.length === 0 || cellState.showAllArms || activeArms.length > 0);
    patchText(cellState.armEmptyText, `활성·주의 팔 0/${cellState.armEntries.length}대 · 현재 대기 상태입니다.`);
  }

  const emitSummary = items => {
    const key = JSON.stringify(items.map(item => [item.key, item.severity, item.detail, item.sourceId]));
    if (key === lastSummaryKey) return;
    lastSummaryKey = key;
    onSummary?.(items);
  };
  // 우선순위: 보류 사건 > 원인 기록 대기 > 모터 건강 > 엔코더 만료. 팔마다 해당 항목을 모두 낸다.
  function summarize(workcells, disconnected = false) {
    if (!onSummary) return;
    if (disconnected) {
      emitSummary([{key: 'obs:disconnected', severity: 'warn', label: '셀 관측',
        detail: '관측 연결 확인 중 · 오래된 값은 표시하지 않습니다', sourceId: ''}]);
      return;
    }
    const items = [];
    for (const cell of workcells) for (const arm of cell.arms) {
      const open = (arm.incidents || []).filter(i => i.state !== 'cleared');
      const held = open.filter(i => i.decision?.hold !== false);
      if (held.length) items.push({key: `inc:${arm.source_id}`, severity: 'danger', label: arm.label || arm.source_id,
        detail: `보류 사건 ${held.length}건 · 확인 후 해제 필요`, sourceId: arm.source_id});
      const naming = open.length - held.length;
      if (naming > 0) items.push({key: `name:${arm.source_id}`, severity: 'warn', label: arm.label || arm.source_id,
        detail: `원인 기록 대기 ${naming}건`, sourceId: arm.source_id});
      const entry = arms.get(arm.source_id);
      if (entry) {
        const health = entry.health.read();
        if (health.severity === 'crit' || health.severity === 'warn') {
          const reason = (health.stopReasons || []).find(text => typeof text === 'string' && text);
          items.push({key: `health:${arm.source_id}:${health.severity}`,
            severity: health.severity === 'crit' ? 'danger' : 'warn', label: arm.label || arm.source_id,
            detail: reason ? `${health.label} · ${reason}` : health.label, sourceId: arm.source_id});
        }
        if (!arm.positions || performance.now() >= entry.expires) items.push({key: `stale:${arm.source_id}`,
          severity: 'warn', label: arm.label || arm.source_id, detail: '엔코더 피드백 만료 · 최신 값 없음', sourceId: arm.source_id});
      }
    }
    emitSummary(items);
  }

  function reset() {
    for (const entry of cameras.values()) if (entry.url) URL.revokeObjectURL(entry.url);
    for (const frames of faultFrames.values()) for (const frame of frames) URL.revokeObjectURL(frame.url);
    faultFrames.clear(); seenFaults = null;
    for (const url of incidentFrames.values()) URL.revokeObjectURL(url);
    incidentFrames.clear();
    arms.clear(); cameras.clear(); layout = '';
    lastWorkcells = []; observedDisconnected = false; emitSummary([]);
    empty.hidden = false; root.replaceChildren(empty);
  }
  function clear() {
    life?.dispose(); life = null; pending = false;
    reset(); empty.textContent = '접속하면 작업 셀의 실제 관측을 확인할 수 있습니다.';
  }
  function build(workcells) {
    const next = JSON.stringify(workcells.map(cell => [cell.workcell_id, cell.label,
      cell.arms.map(arm => [arm.source_id, arm.arm_id, arm.label]), cell.cameras]));
    if (next === layout) return;
    reset(); layout = next;
    empty.hidden = workcells.length > 0;
    empty.textContent = '등록된 작업 셀 관측이 없습니다.';
    for (const cell of workcells) {
      const section = element('section');
      const cellState = {
        showAllArms: false,
        showAllCameras: false,
        armEntries: [],
        camEntries: [],
        armBar: element('div'),
        armSummary: element('p'),
        armToggle: element('ui-button'),
        armEmpty: element('div'),
        armEmptyText: element('p'),
        camBar: element('div'),
        camSummary: element('p'),
        camToggle: element('ui-button'),
        camEmpty: element('div'),
        camEmptyText: element('p'),
      };
      const refreshCell = () => updateCellVisibility(cellState);
      cellState.camBar.className = 'cell-obs-toolbar';
      cellState.camToggle.setAttribute('kind', 'quiet');
      cellState.camToggle.setAttribute('type', 'button');
      cellState.camToggle.setAttribute('data-work-read', '');
      cellState.camToggle.addEventListener('click', () => {
        cellState.showAllCameras = !cellState.showAllCameras;
        refreshCell();
      });
      cellState.camBar.append(cellState.camSummary, cellState.camToggle);
      cellState.camEmpty.className = 'cell-obs-empty-strip';
      cellState.camEmpty.append(cellState.camEmptyText);

      cellState.armBar.className = 'cell-obs-toolbar';
      cellState.armToggle.setAttribute('kind', 'quiet');
      cellState.armToggle.setAttribute('type', 'button');
      cellState.armToggle.setAttribute('data-work-read', '');
      cellState.armToggle.addEventListener('click', () => {
        cellState.showAllArms = !cellState.showAllArms;
        refreshCell();
      });
      cellState.armBar.append(cellState.armSummary, cellState.armToggle);
      cellState.armEmpty.className = 'cell-obs-empty-strip';
      cellState.armEmpty.append(cellState.armEmptyText);

      section.append(element('h3', cell.label), cellState.camBar, cellState.camEmpty);
      // every camera of the cell side by side, the shared views first; a click enlarges one (2026-11-01)
      const wall = element('div'); wall.className = 'cell-camera-wall';
      const grid = element('div'); grid.className = 'cell-observation-grid';
      for (const arm of cell.arms) {
        const card = element('article'); card.className = 'cell-observation-card'; card.dataset.armSource = arm.source_id;
        card.dataset.armHeld = 'false';
        const status = element('ui-status'); status.setAttribute('state', 'unavailable');
        const values = element('pre');
        const healthDetails = element('details'), healthSummary = element('summary'), healthView = element('section');
        healthSummary.className = 'ui-disclosure-row'; healthDetails.append(healthSummary, healthView);
        const history = element('details'), historySummary = element('summary'), historyList = element('ol');
        historySummary.className = 'ui-disclosure-row'; historySummary.textContent = '고장 이력 없음';
        historyList.className = 'cell-fault-history'; history.append(historySummary, historyList);
        const incidents = element('details'), incidentsSummary = element('summary'), incidentsList = element('ol');
        incidentsSummary.className = 'ui-disclosure-row'; incidentsSummary.textContent = '팔 사건 없음';
        incidentsList.className = 'cell-incident-history'; incidents.append(incidentsSummary, incidentsList);
        const entry = {card, status, values, expires: 0, fresh: Boolean(arm.fresh && arm.positions), openIncidents: 0,
          healthSeverity: 'unknown', focused: false, updateVisibility: refreshCell,
          health: createMotorHealthState(), healthDetails, healthSummary, healthView,
          history, historySummary, historyList, faults: '', incidents, incidentsSummary, incidentsList, incidentKey: ''};
        healthDetails.addEventListener('toggle', () => paintHealth(entry));
        paintHealth(entry); staleArm(entry); arms.set(arm.source_id, entry); cellState.armEntries.push(entry);
        card.append(element('h4', arm.label), status, incidents, healthDetails, element('ui-text', '엔코더 각도 · rad'), values, history); grid.append(card);
        card.append(profiles.detail('arm', arm.source_id, {owner_id: arm.arm_id, sha256: arm.binding_sha256}));
      }
      const rank = camera => ({overhead: 0, side: 1}[camera.role] ?? 2) + (camera.stream === 'depth' ? 0.5 : 0);
      for (const camera of [...cell.cameras].sort((a, b) => rank(a) - rank(b))) {
        const card = element('article'); card.className = 'cell-observation-card'; card.dataset.cameraSource = camera.source_id;
        const status = element('ui-status'); status.setAttribute('state', 'unavailable');
        const image = element('img'); image.alt = `${camera.label} 현재 영상`; image.hidden = true;
        const entry = {card, image, status, expires: 0, pending: false, lease: null, identity: null, url: null,
          live: false, reason: '', updateVisibility: refreshCell};
        image.onerror = () => staleCamera(entry);
        card.title = '눌러서 크게 보기'; card.tabIndex = 0; card.setAttribute('role', 'button');
        card.setAttribute('aria-pressed', 'false'); card.setAttribute('aria-label', `${camera.label} 크게 보기`);
        const zoom = on => { card.classList.toggle('focused', on); card.setAttribute('aria-pressed', String(on)); };
        card.addEventListener('click', () => zoom(!card.classList.contains('focused')));
        card.addEventListener('keydown', event => {
          if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); zoom(!card.classList.contains('focused')); }
          else if (event.key === 'Escape') zoom(false);
        });
        entry.label = camera.label;
        staleCamera(entry); cameras.set(camera.source_id, entry); cellState.camEntries.push(entry);
        card.append(element('h4', camera.stream === 'depth' ? `${camera.label} · 깊이` : camera.label), element('ui-text', camera.role === 'overhead'
          ? '공용 상단 카메라' : camera.role === 'side' ? '공용 측면 카메라' : `설정된 팔: ${camera.arm_id}`), status, image); wall.append(card);
      }
      refreshCell();
      section.append(wall, cellState.armBar, cellState.armEmpty, grid); root.append(section);
    }
  }

  async function picture(source, entry, scope) {
    if (entry.pending) return;
    entry.pending = true;
    const current = () => life === scope && !scope.signal.aborted && cameras.get(source) === entry;
    let url;
    try {
      if (!entry.lease || Date.now() >= entry.lease.expires) {
        const issued = await request('/api/fleet/vision/lease', {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({source_id: source}),
          signal: scope.signal, timeoutMs: 1500,
        });
        if (!current()) return;
        const target = new URL(issued.frame_path, location.origin);
        if (target.origin !== location.origin || target.username || target.password
            || target.pathname !== `/api/vision/sources/${encodeURIComponent(source)}/frame`) throw Error('영상 주소 확인 필요');
        entry.lease = {...issued, frame_path: target.href, expires: Date.now() + 45000};
      }
      const observedAt = performance.now();
      const response = await fetch(entry.lease.frame_path, {
        cache: 'no-store', credentials: 'omit', redirect: 'error',
        headers: {Authorization: `Bearer ${entry.lease.lease}`},
        signal: AbortSignal.any([scope.signal, AbortSignal.timeout(1500)]),
      });
      if (!current()) return;
      // Tabs of one user share Vision's per-source frame budget; the 100 ms expiry timer ages out the image we keep.
      if (response.status === 429) return;
      const badge = frameBadge({ok: response.ok, status: response.status,
        ageMs: response.headers.get('X-Frame-Age-Ms'), frameState: response.headers.get('X-Frame-State'), rectified: false});
      const age = Number(response.headers.get('X-Frame-Age-Ms'));
      const sequence = response.headers.get('X-Frame-Seq');
      if (response.status === 404 && response.headers.get('X-Frame-State') !== 'stale') {
        staleCamera(entry, '카메라 송신기 미연결 (Vision 404)'); return;
      }
      if (badge.state !== 'live' || age > 2000 || !sequence || !/^\d+$/.test(sequence)) {
        if (badge.state === 'unauthorized') entry.lease = null;
        staleCamera(entry, badge.label); return;
      }
      const identity = `${sequence}:${response.headers.get('X-Frame-Captured-At') || ''}`;
      if (entry.identity === identity) return;
      const expires = observedAt + 2000 - age;
      const blob = await response.blob();
      url = URL.createObjectURL(blob);
      const decoded = new Image(); decoded.src = url; await decoded.decode();
      if (!current()) return;
      if (performance.now() >= expires) { staleCamera(entry); return; }
      if (entry.url) URL.revokeObjectURL(entry.url);
      entry.image.src = url; entry.url = url; entry.blob = blob; url = null;
      entry.identity = identity; entry.expires = expires; entry.live = true; entry.reason = '';
      patchHidden(entry.image, false);
      patchAttr(entry.status, 'state', 'ready');
      patchText(entry.status, `원본 최신 영상 · #${sequence}`);
      entry.updateVisibility?.();
    } catch (error) {
      if (current()) {
        if (error.status === 401 || error.status === 403) clear();
        else staleCamera(entry, 'Vision 연결 확인');
      }
    } finally {
      if (url) URL.revokeObjectURL(url);
      entry.pending = false;
    }
  }

  function holdFrames(session) {
    // the tile's own JPEG: the page CSP (connect-src 'self') refuses fetch() of a blob: URL
    faultFrames.set(session, [...cameras.values()].filter(camera => !camera.image.hidden && camera.blob)
      .map(camera => ({label: camera.label, url: URL.createObjectURL(camera.blob)})));
  }

  function paintFaults(entry, faults) {
    const fresh = faults.filter(fault => !seenFaults.has(fault.session_id));
    for (const fault of fresh) {
      seenFaults.add(fault.session_id);
      entry.history.open = true;  // a stop that happens while the page is open is shown, not only counted
      holdFrames(fault.session_id);
    }
    const key = JSON.stringify(faults.map(fault => fault.session_id));
    if (key === entry.faults) return;
    entry.faults = key;
    entry.historySummary.textContent = faults.length ? `고장 이력 ${faults.length}건 · 최근 ${
      new Date(faults[0].captured_at * 1000).toLocaleString('ko-KR')}` : '고장 이력 없음';
    entry.historyList.replaceChildren(...faults.map(fault => {
      const item = element('li');
      item.append(element('time', new Date(fault.captured_at * 1000).toLocaleString('ko-KR')), element('p', faultLine(fault)));
      const frames = faultFrames.get(fault.session_id) || [];
      if (frames.length) {
        const figure = element('div'); figure.className = 'cell-fault-frames';
        for (const frame of frames) {
          const image = element('img'); image.src = frame.url; image.alt = `${frame.label} · 고장을 받은 순간의 영상`;
          figure.append(image);
        }
        item.append(element('ui-text', '고장을 받은 순간 이 화면에 있던 카메라 영상 · 현장 PC 기록과 최대 2초 차이'), figure);
      }
      return item;
    }));
  }

  async function incidentFrame(source, incident, part, image, scope) {  // part: frames/<role> or evidence/<seq>
    const key = `${incident.incident_id}:${part}`;
    if (!incidentFrames.has(key)) {
      try {
        const token = credential();
        const response = await fetch(`${BASE}/arms/${encodeURIComponent(source)}/incidents/${incident.incident_id}/${part}`, {
          cache: 'no-store', credentials: 'same-origin', headers: token ? {Authorization: `Bearer ${token}`} : {}, signal: scope.signal});
        if (!response.ok || life !== scope) return;
        incidentFrames.set(key, URL.createObjectURL(await response.blob()));
      } catch { return; }
    }
    image.src = incidentFrames.get(key);
  }

  function choice(label, options) {
    const select = element('select'); select.className = 'ui-field'; select.setAttribute('aria-label', label);
    for (const [value, text] of options) { const option = element('option', text); option.value = value; select.append(option); }
    return select;
  }

  async function clearIncident(source, incident, note, button, message, label = {}) {
    const text = note.value.trim();
    if (!text) { message.textContent = '확인한 내용을 적어야 해제할 수 있습니다.'; return; }
    button.disabled = true;
    try {
      await request(`${BASE}/arms/${encodeURIComponent(source)}/incidents/${incident.incident_id}/clear`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({note: text, ...label}), timeoutMs: 3000});
      message.textContent = '해제했습니다.';
      const entry = arms.get(source); if (entry) entry.incidentKey = '';
      void refresh();
    } catch (error) {
      message.textContent = error.status === 403 ? '이름 있는 운영자만 해제할 수 있습니다.'
        : error.status === 409 ? '이미 해제된 사건입니다.' : '해제하지 못했습니다. 다시 시도하세요.';
      button.disabled = false;
    }
  }

  function paintIncidents(source, entry, incidents, scope) {
    const key = JSON.stringify(incidents.map(i => [i.incident_id, i.state]));
    if (key === entry.incidentKey) return;
    entry.incidentKey = key;
    // a guard stop the recovery handled comes with decision.hold false: it waits for a person's cause, the arm stays free
    const open = incidents.filter(i => i.state !== 'cleared'), held = open.filter(i => i.decision?.hold !== false);
    const cleared = incidents.filter(i => i.state === 'cleared');
    const naming = open.length - held.length;
    entry.openIncidents = open.length;
    entry.card.dataset.armHeld = String(held.length > 0);
    entry.incidentsSummary.textContent = incidents.length
      ? `팔 사건 ${incidents.length}건 · ${held.length ? `보류 중 ${held.length}건 (세션 시작 불가)` : naming ? '보류 없음' : '모두 해제됨'}`
        + (naming ? ` · 원인 기록 대기 ${naming}건` : '') : '팔 사건 없음';
    if (held.length) entry.incidents.open = true;

    const renderIncidentItem = incident => {
      const item = element('li');
      item.append(element('strong', `${STATE_LABEL[incident.state] || incident.state} · ${when(incident.reported_at)}`),
        ...incidentLines(incident).map(line => element('p', line)));
      if (incident.frames.length) {
        const figure = element('div'); figure.className = 'cell-fault-frames';
        for (const frame of incident.frames) {
          const image = element('img'); image.alt = `${frame.role === 'top' ? '상단' : '측면'} 카메라 · 고장 순간`;
          figure.append(image); void incidentFrame(source, incident, `frames/${frame.role}`, image, scope);
        }
        item.append(figure);
      }
      if ((incident.evidence || []).length) {  // the seconds around the stop: the jaw tip first, loaded only when opened
        const box = element('details'), strip = element('div'); strip.className = 'cell-fault-frames';
        box.append(element('summary', `정지 앞뒤 사진 ${incident.evidence.length}장 (집게 끝 먼저)`), strip);
        box.addEventListener('toggle', () => {
          if (!box.open || strip.childElementCount) return;
          for (const shot of incident.evidence) {
            const figure = element('figure'), image = element('img');
            const at = `${shot.t_rel_s > 0 ? '+' : ''}${shot.t_rel_s.toFixed(1)}초`;
            image.alt = `${shot.camera} 카메라 ${shot.kind === 'tip' ? '집게 끝 확대' : '전체'} · 정지 ${at}`;
            figure.append(image, element('figcaption', `${shot.camera} · ${shot.kind === 'tip' ? '집게 끝' : '전체'} · ${at}`));
            strip.append(figure); void incidentFrame(source, incident, `evidence/${shot.seq}`, image, scope);
          }
        });
        item.append(box);
      }
      if (incident.explanation) {
        const said = [element('ui-text', `AI 설명 (설명일 뿐, 판단이나 동작이 아닙니다 · ${incident.explanation.model})`),
          element('p', `본 것: ${incident.explanation.seen}`), element('p', `추정 원인: ${incident.explanation.suspected_cause}`)];
        // a person's cause is only worth scoring if it was picked before the model's was seen
        if (incident.cleared) item.append(...said);
        else { const box = element('details'); box.append(element('summary', 'AI 설명 보기 (원인을 고른 뒤에 여세요)'), ...said); item.append(box); }
      }
      if (incident.cleared) {
        const label = incident.cleared.cause ? ` · 원인 ${incident.cleared.cause} (근거 ${incident.cleared.basis})` : '';
        item.append(element('p', `해제: ${incident.cleared.by} · ${when(incident.cleared.at)}${label} · ${incident.cleared.note}`));
      } else {
        // the cause and how the person knows it are kept with the clear: the labels learning scores rules and models against
        const cause = choice('원인', INCIDENT_CAUSES), basis = choice('근거', INCIDENT_BASES);
        const note = element('input'); note.className = 'ui-field'; note.maxLength = 400;
        note.setAttribute('aria-label', '확인한 내용'); note.placeholder = '팔과 집게를 확인한 내용 (필수) · 같은 동작을 다시 해 봤다면 그 결과';
        const button = element('ui-button', '확인했습니다 · 해제'); button.setAttribute('type', 'button');
        const message = element('ui-text');
        button.addEventListener('click', () => clearIncident(source, incident, note, button, message,
          {cause: cause.value, basis: basis.value}));
        item.append(cause, basis, note, button, message);
      }
      return item;
    };

    const visibleCleared = open.length > 0 ? [] : cleared.slice(0, 3);
    const foldedCleared = open.length > 0 ? cleared : cleared.slice(3);
    entry.incidentsList.replaceChildren(...[...open, ...visibleCleared].map(renderIncidentItem));
    if (foldedCleared.length > 0) {
      const fold = element('details'); fold.className = 'cell-incident-cleared-fold';
      const summary = element('summary', `해제된 이전 사건 ${foldedCleared.length}건 보기`);
      const list = element('ol'); list.className = 'cell-incident-history';
      list.replaceChildren(...foldedCleared.map(renderIncidentItem));
      fold.append(summary, list);
      entry.incidents.replaceChildren(entry.incidentsSummary, entry.incidentsList, fold);
    } else {
      entry.incidents.replaceChildren(entry.incidentsSummary, entry.incidentsList);
    }
    entry.updateVisibility?.();
  }

  async function refresh() {
    if (disposed || pending) return;
    if (!life) {
      life = createScope();
      profiles = createRobotProfiles({call: request, scope: life});
      const poll = setInterval(refresh, 500);
      const expiry = setInterval(() => {
        for (const entry of arms.values()) {
          if (performance.now() >= entry.expires) staleArm(entry);
          if (performance.now() - entry.healthPaintedAt >= 1000) paintHealth(entry);
        }
        for (const entry of cameras.values()) if (entry.live && performance.now() >= entry.expires) staleCamera(entry);
        // 연결이 끊긴 동안 만료 판정이 옛 팔 목록으로 요약을 되살리지 않는다(번쩍임 없음).
        if (!observedDisconnected) summarize(lastWorkcells);
      }, 100);
      // a background tab stops pulling observations and JPEGs; showing it again refreshes at once
      const wake = () => { if (!document.hidden) void refresh(); };
      document.addEventListener('visibilitychange', wake);
      life.onDispose(() => { clearInterval(poll); clearInterval(expiry); document.removeEventListener('visibilitychange', wake); });
    }
    if (document.hidden) return;
    const scope = life;
    pending = true;
    const observedAt = performance.now();
    const requestedAtMs = Date.now();
    try {
      const state = await request('/api/fleet/workcell-observations', {signal: scope.signal, timeoutMs: 1500});
      if (life !== scope || scope.signal.aborted) return;
      build(state.workcells);
      // stops already in the history when the page opened have no frames here; later ones get this page's frames
      const liveFaults = new Set(state.workcells.flatMap(cell => cell.arms.flatMap(arm => (arm.faults || []).map(f => f.session_id))));
      seenFaults ??= new Set(liveFaults);
      for (const [session, frames] of faultFrames) if (!liveFaults.has(session)) {
        for (const frame of frames) URL.revokeObjectURL(frame.url);
        faultFrames.delete(session);
      }
      patchHidden(empty, state.workcells.length > 0);
      patchText(empty, '등록된 작업 셀 관측이 없습니다.');
      for (const cell of state.workcells) for (const arm of cell.arms) {
        const entry = arms.get(arm.source_id);
        const existingProfile = root.querySelector(`[data-arm-source="${CSS.escape(arm.source_id)}"] [data-robot-profile]`);
        const nextProfile = profiles.detail('arm', arm.source_id, {owner_id: arm.arm_id, sha256: arm.binding_sha256});
        if (existingProfile && existingProfile !== nextProfile) existingProfile.replaceWith(nextProfile);
        // motor_health ages already include source/receipt aging; add only this browser request's transit.
        entry.health.accept(arm.motor_health, {requestedAtMs, receivedAtMs: Date.now()});
        paintHealth(entry);
        paintFaults(entry, arm.faults || []);
        paintIncidents(arm.source_id, entry, arm.incidents || [], scope);
        const age = Math.max(0, arm.source_age_s, arm.receipt_age_s);
        entry.expires = arm.fresh && Number.isFinite(age) ? observedAt + (2 - age) * 1000 : 0;
        if (!arm.positions || performance.now() >= entry.expires) { staleArm(entry); continue; }
        entry.fresh = true;
        patchText(entry.values, JSON.stringify(arm.positions, null, 2));
        patchAttr(entry.status, 'state', 'ready');
        patchText(entry.status, `실제 피드백 · #${arm.sequence}`);
        entry.updateVisibility?.();
      }
      for (const [source, entry] of cameras) void picture(source, entry, scope);
      lastWorkcells = state.workcells; observedDisconnected = false;
      summarize(state.workcells);
    } catch (error) {
      if (life !== scope || scope.signal.aborted) return;
      if (error.status === 401 || error.status === 403) clear();
      else {
        for (const entry of arms.values()) { entry.health.disconnect(); paintHealth(entry); }
        patchHidden(empty, false);
        patchText(empty, error.status === 503 ? '관측 구성을 확인할 수 없습니다.' : '관측 연결 확인 중 · 오래된 값은 표시하지 않습니다.');
        if (error.status === 503 && !lastWorkcells.length) {
          observedDisconnected = false;
          emitSummary([]);
        } else {
          observedDisconnected = true;
          summarize(lastWorkcells, true);
        }
      }
    } finally { if (life === scope) pending = false; }
  }
  // B-3 — 요약 줄의 "관측으로 이동": 그 팔 카드로 화면을 옮기고 말고 집는다.
  function focusArm(sourceId) {
    if (!sourceId) return false;
    const card = root.querySelector(`[data-arm-source="${CSS.escape(sourceId)}"]`);
    if (!card) return false;
    const entry = arms.get(sourceId);
    if (entry) {
      entry.focused = true;
      entry.updateVisibility?.();
      if (entry.openIncidents) entry.incidents.open = true;  // 사람이 확인할 팔 사건은 펼쳐 둔다
    }
    card.tabIndex = -1;
    card.scrollIntoView?.({block: 'nearest'});
    card.focus?.({preventScroll: true});
    return true;
  }
  return {refresh, clear, focusArm, dispose() { clear(); disposed = true; }};
}
