import {createScope} from '/common/scope.js';
import {frameBadge} from '/console/assets/vision-view.js';
import {createMotorHealthState, renderMotorHealth, renderMotorHealthSummary} from '/common/motor-health.js';

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

export function createCellObservation({request, root}) {
  const empty = element('ui-empty', '접속하면 작업 셀의 실제 관측을 확인할 수 있습니다.');
  let life = null, pending = false, layout = '', disposed = false;
  const arms = new Map(), cameras = new Map();
  root.replaceChildren(empty);
  function paintHealth(entry) {
    const health = entry.health.read();
    renderMotorHealthSummary(entry.healthSummary, health);
    if (entry.healthDetails.open) renderMotorHealth(entry.healthView, health);
    entry.healthPaintedAt = performance.now();
  }

  function reset() {
    for (const entry of cameras.values()) if (entry.url) URL.revokeObjectURL(entry.url);
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
      const grid = element('div'); grid.className = 'cell-observation-grid';
      for (const arm of cell.arms) {
        const card = element('article'); card.className = 'cell-observation-card'; card.dataset.armSource = arm.source_id;
        const status = element('ui-status'); status.setAttribute('state', 'unavailable');
        const values = element('pre');
        const healthDetails = element('details'), healthSummary = element('summary'), healthView = element('section');
        healthSummary.className = 'ui-disclosure-row'; healthDetails.append(healthSummary, healthView);
        const entry = {status, values, expires: 0, health: createMotorHealthState(), healthDetails, healthSummary, healthView};
        healthDetails.addEventListener('toggle', () => paintHealth(entry));
        paintHealth(entry); staleArm(entry); arms.set(arm.source_id, entry);
        card.append(element('h4', arm.label), healthDetails, element('ui-text', '엔코더 각도 · rad'), status, values); grid.append(card);
      }
      for (const camera of cell.cameras) {
        const card = element('article'); card.className = 'cell-observation-card'; card.dataset.cameraSource = camera.source_id;
        const status = element('ui-status'); status.setAttribute('state', 'unavailable');
        const image = element('img'); image.alt = `${camera.label} 현재 영상`; image.hidden = true;
        const entry = {image, status, expires: 0, pending: false, lease: null, identity: null, url: null};
        image.onerror = () => staleCamera(entry);
        staleCamera(entry); cameras.set(camera.source_id, entry);
        card.append(element('h4', camera.label), element('ui-text', camera.role === 'overhead'
          ? '공용 상단 카메라' : `설정된 팔: ${camera.arm_id}`), status, image); grid.append(card);
      }
      section.append(grid); root.append(section);
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
      url = URL.createObjectURL(await response.blob());
      const decoded = new Image(); decoded.src = url; await decoded.decode();
      if (!current()) return;
      if (performance.now() >= expires) { staleCamera(entry); return; }
      if (entry.url) URL.revokeObjectURL(entry.url);
      entry.image.src = url; entry.url = url; url = null;
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

  async function refresh() {
    if (disposed || pending) return;
    if (!life) {
      life = createScope();
      const poll = setInterval(refresh, 500);
      const expiry = setInterval(() => {
        for (const entry of arms.values()) {
          if (performance.now() >= entry.expires) staleArm(entry);
          if (performance.now() - entry.healthPaintedAt >= 200) paintHealth(entry);
        }
        for (const entry of cameras.values()) if (performance.now() >= entry.expires) staleCamera(entry);
      }, 100);
      life.onDispose(() => { clearInterval(poll); clearInterval(expiry); });
    }
    const scope = life;
    pending = true;
    const observedAt = performance.now();
    const requestedAtMs = Date.now();
    try {
      const state = await request('/api/fleet/workcell-observations', {signal: scope.signal, timeoutMs: 1500});
      if (life !== scope || scope.signal.aborted) return;
      build(state.workcells);
      empty.hidden = state.workcells.length > 0;
      empty.textContent = '등록된 작업 셀 관측이 없습니다.';
      for (const cell of state.workcells) for (const arm of cell.arms) {
        const entry = arms.get(arm.source_id);
        // motor_health ages already include source/receipt aging; add only this browser request's transit.
        entry.health.accept(arm.motor_health, {requestedAtMs, receivedAtMs: Date.now()});
        paintHealth(entry);
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
