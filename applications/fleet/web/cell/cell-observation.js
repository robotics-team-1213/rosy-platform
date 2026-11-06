import {createScope} from '/common/scope.js';
import {frameBadge} from '/console/assets/vision-view.js';
import {createRobotProfiles} from '/console/assets/robot-profile-view.js';
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
  entry.values.textContent = '최신 피드백 없음'; entry.status.textContent = '수신 대기 · 원본 만료';
  entry.status.setAttribute('state', 'unavailable');
};
const staleCamera = entry => {
  entry.image.hidden = true; entry.status.textContent = '최신 영상 없음';
  entry.status.setAttribute('state', 'unavailable');
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

export function createCellObservation({request, root, credential = () => ''}) {
  const empty = element('ui-empty', '접속하면 작업 셀의 실제 관측을 확인할 수 있습니다.');
  let life = null, pending = false, layout = '', disposed = false;
  let profiles = null;
  const arms = new Map(), cameras = new Map();
  // camera frames this browser held when a guard stop arrived, by session; the field PC keeps its own copies
  const faultFrames = new Map();
  const incidentFrames = new Map();  // D-971: blob URL of each incident frame, fetched once
  let seenFaults = null;
  root.replaceChildren(empty);
  function paintHealth(entry) {
    const health = entry.health.read();
    renderMotorHealthSummary(entry.healthSummary, health);
    if (entry.healthDetails.open) renderMotorHealth(entry.healthView, health);
    entry.healthPaintedAt = performance.now();
  }

  function reset() {
    for (const entry of cameras.values()) if (entry.url) URL.revokeObjectURL(entry.url);
    for (const frames of faultFrames.values()) for (const frame of frames) URL.revokeObjectURL(frame.url);
    faultFrames.clear(); seenFaults = null;
    for (const url of incidentFrames.values()) URL.revokeObjectURL(url);
    incidentFrames.clear();
    arms.clear(); cameras.clear(); layout = '';
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
      section.append(element('h3', cell.label));
      // every camera of the cell side by side, the shared views first; a click enlarges one (2026-11-01)
      const wall = element('div'); wall.className = 'cell-camera-wall';
      const grid = element('div'); grid.className = 'cell-observation-grid';
      for (const arm of cell.arms) {
        const card = element('article'); card.className = 'cell-observation-card'; card.dataset.armSource = arm.source_id;
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
        const entry = {status, values, expires: 0, health: createMotorHealthState(), healthDetails, healthSummary, healthView,
          history, historySummary, historyList, faults: '', incidents, incidentsSummary, incidentsList, incidentKey: ''};
        healthDetails.addEventListener('toggle', () => paintHealth(entry));
        paintHealth(entry); staleArm(entry); arms.set(arm.source_id, entry);
        card.append(element('h4', arm.label), healthDetails, incidents, history, element('ui-text', '엔코더 각도 · rad'), status, values); grid.append(card);
        card.append(profiles.detail('arm', arm.source_id, {owner_id: arm.arm_id, sha256: arm.binding_sha256}));
      }
      const rank = camera => ({overhead: 0, side: 1}[camera.role] ?? 2) + (camera.stream === 'depth' ? 0.5 : 0);
      for (const camera of [...cell.cameras].sort((a, b) => rank(a) - rank(b))) {
        const card = element('article'); card.className = 'cell-observation-card'; card.dataset.cameraSource = camera.source_id;
        const status = element('ui-status'); status.setAttribute('state', 'unavailable');
        const image = element('img'); image.alt = `${camera.label} 현재 영상`; image.hidden = true;
        const entry = {image, status, expires: 0, pending: false, lease: null, identity: null, url: null};
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
        staleCamera(entry); cameras.set(camera.source_id, entry);
        card.append(element('h4', camera.stream === 'depth' ? `${camera.label} · 깊이` : camera.label), element('ui-text', camera.role === 'overhead'
          ? '공용 상단 카메라' : camera.role === 'side' ? '공용 측면 카메라' : `설정된 팔: ${camera.arm_id}`), status, image); wall.append(card);
      }
      section.append(wall, grid); root.append(section);
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
      if (badge.state !== 'live' || age > 2000 || !sequence || !/^\d+$/.test(sequence)) {
        if (badge.state === 'unauthorized') entry.lease = null;
        staleCamera(entry); return;
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
      entry.identity = identity; entry.expires = expires; entry.image.hidden = false;
      entry.status.setAttribute('state', 'ready');
      entry.status.textContent = `원본 최신 영상 · #${sequence}`;
    } catch (error) {
      if (current()) {
        if (error.status === 401 || error.status === 403) clear();
        else staleCamera(entry);
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

  async function incidentFrame(source, incident, frame, image, scope) {
    const key = `${incident.incident_id}:${frame.role}`;
    if (!incidentFrames.has(key)) {
      try {
        const token = credential();
        const response = await fetch(`${BASE}/arms/${encodeURIComponent(source)}/incidents/${incident.incident_id}/frames/${frame.role}`, {
          cache: 'no-store', credentials: 'same-origin', headers: token ? {Authorization: `Bearer ${token}`} : {}, signal: scope.signal});
        if (!response.ok || life !== scope) return;
        incidentFrames.set(key, URL.createObjectURL(await response.blob()));
      } catch { return; }
    }
    image.src = incidentFrames.get(key);
  }

  async function clearIncident(source, incident, note, button, message) {
    const text = note.value.trim();
    if (!text) { message.textContent = '확인한 내용을 적어야 해제할 수 있습니다.'; return; }
    button.disabled = true;
    try {
      await request(`${BASE}/arms/${encodeURIComponent(source)}/incidents/${incident.incident_id}/clear`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({note: text}), timeoutMs: 3000});
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
    const held = incidents.filter(i => i.state !== 'cleared');
    entry.incidentsSummary.textContent = incidents.length
      ? `팔 사건 ${incidents.length}건 · ${held.length ? `보류 중 ${held.length}건 (세션 시작 불가)` : '모두 해제됨'}` : '팔 사건 없음';
    if (held.length) entry.incidents.open = true;
    entry.incidentsList.replaceChildren(...incidents.map(incident => {
      const item = element('li');
      item.append(element('strong', `${STATE_LABEL[incident.state] || incident.state} · ${when(incident.reported_at)}`),
        ...incidentLines(incident).map(line => element('p', line)));
      if (incident.frames.length) {
        const figure = element('div'); figure.className = 'cell-fault-frames';
        for (const frame of incident.frames) {
          const image = element('img'); image.alt = `${frame.role === 'top' ? '상단' : '측면'} 카메라 · 고장 순간`;
          figure.append(image); void incidentFrame(source, incident, frame, image, scope);
        }
        item.append(figure);
      }
      if (incident.explanation) {
        item.append(element('ui-text', `AI 설명 (설명일 뿐, 판단이나 동작이 아닙니다 · ${incident.explanation.model})`),
          element('p', `본 것: ${incident.explanation.seen}`), element('p', `추정 원인: ${incident.explanation.suspected_cause}`));
      }
      if (incident.cleared) {
        item.append(element('p', `해제: ${incident.cleared.by} · ${when(incident.cleared.at)} · ${incident.cleared.note}`));
      } else {
        const note = element('input'); note.className = 'ui-field'; note.maxLength = 400;
        note.setAttribute('aria-label', '확인한 내용'); note.placeholder = '팔과 집게를 확인한 내용 (필수)';
        const button = element('ui-button', '확인했습니다 · 해제'); button.setAttribute('type', 'button');
        const message = element('ui-text');
        button.addEventListener('click', () => clearIncident(source, incident, note, button, message));
        item.append(note, button, message);
      }
      return item;
    }));
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
          if (performance.now() - entry.healthPaintedAt >= 200) paintHealth(entry);
        }
        for (const entry of cameras.values()) if (performance.now() >= entry.expires) staleCamera(entry);
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
      empty.hidden = state.workcells.length > 0;
      empty.textContent = '등록된 작업 셀 관측이 없습니다.';
      for (const cell of state.workcells) for (const arm of cell.arms) {
        const entry = arms.get(arm.source_id);
        root.querySelector(`[data-arm-source="${CSS.escape(arm.source_id)}"] [data-robot-profile]`)
          ?.replaceWith(profiles.detail('arm', arm.source_id, {owner_id: arm.arm_id, sha256: arm.binding_sha256}));
        // motor_health ages already include source/receipt aging; add only this browser request's transit.
        entry.health.accept(arm.motor_health, {requestedAtMs, receivedAtMs: Date.now()});
        paintHealth(entry);
        paintFaults(entry, arm.faults || []);
        paintIncidents(arm.source_id, entry, arm.incidents || [], scope);
        const age = Math.max(0, arm.source_age_s, arm.receipt_age_s);
        entry.expires = arm.fresh && Number.isFinite(age) ? observedAt + (2 - age) * 1000 : 0;
        if (!arm.positions || performance.now() >= entry.expires) { staleArm(entry); continue; }
        entry.values.textContent = JSON.stringify(arm.positions, null, 2);
        entry.status.setAttribute('state', 'ready');
        entry.status.textContent = `실제 피드백 · #${arm.sequence}`;
      }
      for (const [source, entry] of cameras) void picture(source, entry, scope);
    } catch (error) {
      if (life !== scope || scope.signal.aborted) return;
      if (error.status === 401 || error.status === 403) clear();
      else {
        for (const entry of arms.values()) { entry.health.disconnect(); paintHealth(entry); }
        empty.hidden = false;
        empty.textContent = error.status === 503 ? '관측 구성을 확인할 수 없습니다.' : '관측 연결 확인 중 · 오래된 값은 표시하지 않습니다.';
      }
    } finally { if (life === scope) pending = false; }
  }
  return {refresh, clear, dispose() { clear(); disposed = true; }};
}
