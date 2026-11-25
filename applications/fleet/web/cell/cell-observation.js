import {createCameraFrameHold, decodeImageUrl, paintCameraFrameHold} from '/common/camera-frame-hold.js';
import {action, node, patchAttr, patchHidden, patchText} from '/common/control-dom.js';
import {setOff} from '/common/cause-line.js';
import {createScope} from '/common/scope.js';
import {confirmIrreversible} from '/common/ui.js';
import {frameBadge} from '/console/assets/vision-view.js';
import {createRobotProfiles} from '/console/assets/robot-profile-view.js';
import {INCIDENT_BASES, INCIDENT_CAUSES, bindFocusZoom, issueVisionLease} from '/console/assets/cell-frames.js';
import {OBS_BASE, compareCameras, formatIncidentCountSummary, incidentLines, partitionIncidents} from '/console/assets/cell-obs-model.js';
import {createMotorHealthState, renderMotorHealth, renderMotorHealthSummary} from '/common/motor-health.js';
import {faultLine} from './cell-observation-text.js';

const staleArm = entry => {
  entry.fresh = false;
  patchText(entry.values, '최신 피드백 없음');
  patchText(entry.status, '수신 대기 · 원본 만료');
  patchAttr(entry.status, 'state', 'unavailable');
  entry.updateVisibility?.();
};
const staleCamera = (entry, detail = '', {dropFrame = false} = {}) => {
  entry.hold.disconnect({kind: 'warn', label: detail || '영상 연결 끊김', dropFrame});
  const snap = entry.hold.snapshot();
  entry.live = false;
  entry.hasFrame = snap.hasFrame;
  entry.reason = detail;
  entry.lastTickSec = Math.floor(snap.disconnectedMs / 1000);
  paintCameraFrameHold(entry.frameWrap, entry.image, entry.overlay, snap);
  patchText(entry.status, snap.hasFrame ? snap.overlayText : (detail ? `최신 영상 없음 · ${detail}` : '최신 영상 없음'));
  patchAttr(entry.status, 'state', 'unavailable');
  entry.updateVisibility?.();
};

const STATE_LABEL = {open: '열림 · 사람 확인 필요', explained: '열림 · AI 설명 있음', cleared: '해제됨'};
const when = seconds => new Date(seconds * 1000).toLocaleString('ko-KR');

export {incidentLines};

export function createCellObservation({request, root, credential = () => '', onSummary = null,
  quickClearSource = null, canQuickClear = () => false}) {
  const empty = node('ui-empty', '접속하면 작업 셀의 실제 관측을 확인할 수 있습니다.');
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
    const visibleCams = cellState.camEntries.filter(cam => cam.live || cam.hasFrame);
    const idleCams = cellState.camEntries.length - visibleCams.length;
    const firstReason = cellState.camEntries.map(cam => cam.reason).find(Boolean) || '';
    const hideIdleCams = !cellState.showAllCameras && visibleCams.length > 0;
    for (const camEntry of cellState.camEntries) {
      patchHidden(camEntry.card, hideIdleCams && !(camEntry.live || camEntry.hasFrame));
    }
    patchHidden(cellState.camBar, cellState.camEntries.length === 0 || visibleCams.length === 0 || (idleCams === 0 && !cellState.showAllCameras));
    patchText(cellState.camSummary, cellState.showAllCameras
      ? `전체 셀 카메라 ${cellState.camEntries.length}대 표시 중`
      : `실시간 카메라 ${liveCams.length}/${cellState.camEntries.length}대 · 대기 ${idleCams}대 숨김`);
    patchText(cellState.camToggle, cellState.showAllCameras ? '실시간 카메라만 보기' : `대기 카메라 ${idleCams}대 보기`);
    patchHidden(cellState.camEmpty, cellState.camEntries.length === 0 || visibleCams.length > 0);
    patchText(cellState.camEmptyText, firstReason
      ? `실시간 카메라 0/${cellState.camEntries.length}대 · ${firstReason}`
      : `실시간 카메라 0/${cellState.camEntries.length}대 · 영상 연결 확인 중`);

    const activeArms = cellState.armEntries.filter(isArmEntryActive);
    const idleArms = cellState.armEntries.length - activeArms.length;
    const hideIdleArms = !cellState.showAllArms && activeArms.length > 0;
    for (const armEntry of cellState.armEntries) {
      patchHidden(armEntry.card, hideIdleArms && !isArmEntryActive(armEntry));
    }
    patchHidden(cellState.armBar, cellState.armEntries.length === 0 || activeArms.length === 0 || (idleArms === 0 && !cellState.showAllArms));
    patchText(cellState.armSummary, cellState.showAllArms
      ? `전체 팔 ${cellState.armEntries.length}대 표시 중`
      : activeArms.length
        ? `활성·주의 팔 ${activeArms.length}대 표시 · 대기 팔 ${idleArms}대 숨김`
        : `활성·주의 팔 없음 · 대기 팔 ${idleArms}대 숨김`);
    patchText(cellState.armToggle, cellState.showAllArms ? '활성·주의 팔만 보기' : `대기 팔 ${idleArms}대 보기`);
    patchHidden(cellState.armEmpty, cellState.armEntries.length === 0 || activeArms.length > 0);
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
      const {open, held, namingCount} = partitionIncidents(arm.incidents);
      if (held.length) items.push({key: `inc:${arm.source_id}`, severity: 'danger', label: arm.label || arm.source_id,
        detail: `보류 사건 ${held.length}건 · 확인 후 해제 필요`, sourceId: arm.source_id});
      if (namingCount > 0) items.push({key: `name:${arm.source_id}`, severity: 'warn', label: arm.label || arm.source_id,
        detail: `원인 기록 대기 ${namingCount}건`, sourceId: arm.source_id});
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
    for (const entry of cameras.values()) entry.hold?.dispose();
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
      cell.arms.map(arm => [arm.source_id, arm.arm_id, arm.label]),
      cell.cameras.map(cam => [cam.source_id, cam.label, cam.role, cam.stream, cam.arm_id])]));
    if (next === layout) return;
    reset(); layout = next;
    empty.hidden = workcells.length > 0;
    empty.textContent = '등록된 작업 셀 관측이 없습니다.';
    for (const cell of workcells) {
      const section = node('section');
      const cellState = {
        showAllArms: false,
        showAllCameras: false,
        armEntries: [],
        camEntries: [],
        armBar: node('div', '', 'cell-obs-toolbar'),
        armSummary: node('p'),
        armEmpty: node('div', '', 'cell-obs-empty-strip'),
        armEmptyText: node('p'),
        camBar: node('div', '', 'cell-obs-toolbar'),
        camSummary: node('p'),
        camEmpty: node('div', '', 'cell-obs-empty-strip'),
        camEmptyText: node('p'),
      };
      const refreshCell = () => updateCellVisibility(cellState);
      cellState.camToggle = action('', () => { cellState.showAllCameras = !cellState.showAllCameras; refreshCell(); });
      cellState.camToggle.setAttribute('data-work-read', '');
      cellState.camBar.append(cellState.camSummary, cellState.camToggle);
      cellState.camEmpty.append(cellState.camEmptyText);

      cellState.armToggle = action('', () => { cellState.showAllArms = !cellState.showAllArms; refreshCell(); });
      cellState.armToggle.setAttribute('data-work-read', '');
      cellState.armBar.append(cellState.armSummary, cellState.armToggle);
      cellState.armEmpty.append(cellState.armEmptyText);

      section.append(node('h3', cell.label), cellState.camBar, cellState.camEmpty);
      // every camera of the cell side by side, the shared views first; a click enlarges one (2026-11-01)
      const wall = node('div', '', 'cell-camera-wall');
      const grid = node('div', '', 'cell-observation-grid');
      for (const arm of cell.arms) {
        const card = node('article', '', 'cell-observation-card'); card.dataset.armSource = arm.source_id;
        card.dataset.armHeld = 'false';
        const status = node('ui-status'); status.setAttribute('state', 'unavailable');
        const values = node('pre');
        const healthDetails = node('details'), healthSummary = node('summary', '', 'ui-disclosure-row'), healthView = node('section');
        healthDetails.append(healthSummary, healthView);
        const history = node('details'), historySummary = node('summary', '고장 이력 없음', 'ui-disclosure-row'), historyList = node('ol', '', 'cell-fault-history');
        history.append(historySummary, historyList);
        const incidents = node('details'), incidentsSummary = node('summary', '팔 사건 없음', 'ui-disclosure-row'), incidentsList = node('ol', '', 'cell-incident-history');
        incidents.append(incidentsSummary, incidentsList);
        const entry = {card, status, values, expires: 0, fresh: Boolean(arm.fresh && arm.positions), openIncidents: 0,
          healthSeverity: 'unknown', focused: false, updateVisibility: refreshCell,
          health: createMotorHealthState(), healthDetails, healthSummary, healthView,
          history, historySummary, historyList, faults: '', incidents, incidentsSummary, incidentsList, incidentKey: ''};
        healthDetails.addEventListener('toggle', () => paintHealth(entry));
        paintHealth(entry); staleArm(entry); arms.set(arm.source_id, entry); cellState.armEntries.push(entry);
        card.append(node('h4', arm.label), status, incidents, healthDetails, node('ui-text', '엔코더 각도 · rad'), values, history); grid.append(card);
        card.append(profiles.detail('arm', arm.source_id, {owner_id: arm.arm_id, sha256: arm.binding_sha256}));
      }
      for (const camera of [...cell.cameras].sort(compareCameras)) {
        const card = node('article', '', 'cell-observation-card'); card.dataset.cameraSource = camera.source_id;
        const status = node('ui-status'); status.setAttribute('state', 'unavailable');
        const frameWrap = node('div', '', 'cam-frame-hold');
        const image = node('img'); image.alt = `${camera.label} 현재 영상`; image.hidden = true;
        const overlay = node('span', '', 'cam-frame-overlay'); overlay.setAttribute('role', 'status'); overlay.hidden = true;
        frameWrap.append(image, overlay);
        const entry = {card, frameWrap, image, overlay, status, hold: createCameraFrameHold(),
          expires: 0, pending: false, lease: null, identity: null, live: false, hasFrame: false, lastTickSec: -1,
          reason: '', updateVisibility: refreshCell};
        image.onerror = () => staleCamera(entry);
        card.title = '눌러서 크게 보기'; card.tabIndex = 0; card.setAttribute('role', 'button');
        card.setAttribute('aria-pressed', 'false'); card.setAttribute('aria-label', `${camera.label} 크게 보기`);
        bindFocusZoom(card, {onToggle: on => card.setAttribute('aria-pressed', String(on))});
        entry.label = camera.label;
        staleCamera(entry); cameras.set(camera.source_id, entry); cellState.camEntries.push(entry);
        card.append(node('h4', camera.stream === 'depth' ? `${camera.label} · 깊이` : camera.label), node('ui-text', camera.role === 'overhead'
          ? '공용 상단 카메라' : camera.role === 'side' ? '공용 측면 카메라' : `설정된 팔: ${camera.arm_id}`), status, frameWrap); wall.append(card);
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
        const lease = await issueVisionLease(request, source, {signal: scope.signal, timeoutMs: 1500, strictFramePath: true});
        if (!current()) return;
        entry.lease = lease;
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
        staleCamera(entry, badge.label, {dropFrame: badge.state === 'unauthorized'}); return;
      }
      const identity = `${sequence}:${response.headers.get('X-Frame-Captured-At') || ''}`;
      if (entry.identity === identity) {
        entry.expires = observedAt + 2000 - age;
        if (!entry.live && entry.hasFrame) {
          entry.live = true;
          entry.hold.markLive({label: `원본 최신 영상 · #${sequence}`});
          paintCameraFrameHold(entry.frameWrap, entry.image, entry.overlay, entry.hold.snapshot());
          patchAttr(entry.status, 'state', 'ready');
          patchText(entry.status, `원본 최신 영상 · #${sequence}`);
          entry.updateVisibility?.();
        }
        return;
      }
      const expires = observedAt + 2000 - age;
      const blob = await response.blob();
      url = URL.createObjectURL(blob);
      const decoded = await decodeImageUrl(url);
      if (!current() || !decoded) return;
      if (performance.now() >= expires) { staleCamera(entry); return; }
      entry.hold.acceptFrame({url, seq: sequence, label: `원본 최신 영상 · #${sequence}`});
      entry.blob = blob; url = null;
      entry.identity = identity; entry.expires = expires; entry.live = true; entry.hasFrame = true; entry.reason = '';
      paintCameraFrameHold(entry.frameWrap, entry.image, entry.overlay, entry.hold.snapshot());
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
    faultFrames.set(session, [...cameras.values()].filter(camera => camera.live && camera.blob)
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
      const item = node('li');
      item.append(node('time', new Date(fault.captured_at * 1000).toLocaleString('ko-KR')), node('p', faultLine(fault)));
      const frames = faultFrames.get(fault.session_id) || [];
      if (frames.length) {
        const figure = node('div', '', 'cell-fault-frames');
        for (const frame of frames) {
          const image = node('img'); image.src = frame.url; image.alt = `${frame.label} · 고장을 받은 순간의 영상`;
          figure.append(image);
        }
        item.append(node('ui-text', '고장을 받은 순간 이 화면에 있던 카메라 영상 · 현장 PC 기록과 최대 2초 차이'), figure);
      }
      return item;
    }));
  }

  async function incidentFrame(source, incident, part, image, scope) {  // part: frames/<role> or evidence/<seq>
    const key = `${incident.incident_id}:${part}`;
    if (!incidentFrames.has(key)) {
      try {
        const token = credential();
        const response = await fetch(`${OBS_BASE}/arms/${encodeURIComponent(source)}/incidents/${encodeURIComponent(incident.incident_id)}/${part}`, {
          cache: 'no-store', credentials: 'same-origin', headers: token ? {Authorization: `Bearer ${token}`} : {}, signal: scope.signal});
        if (!response.ok || life !== scope) return;
        incidentFrames.set(key, URL.createObjectURL(await response.blob()));
      } catch { return; }
    }
    image.src = incidentFrames.get(key);
  }

  function choice(label, options) {
    const select = node('select'); select.className = 'ui-field'; select.setAttribute('aria-label', label);
    for (const [value, text] of options) { const option = node('option', text); option.value = value; select.append(option); }
    return select;
  }

  async function clearIncident(source, incident, note, button, message, label = {}) {
    const text = (typeof note === 'string' ? note : note.value).trim();
    if (!text) { message.textContent = '확인한 내용을 적어야 해제할 수 있습니다.'; return; }
    button.disabled = true;
    try {
      await request(`${OBS_BASE}/arms/${encodeURIComponent(source)}/incidents/${encodeURIComponent(incident.incident_id)}/clear`, {
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
    const {open, held, cleared, namingCount} = partitionIncidents(incidents);
    entry.openIncidents = open.length;
    entry.card.dataset.armHeld = String(held.length > 0);
    entry.incidentsSummary.textContent = formatIncidentCountSummary(incidents.length, held.length, namingCount);
    if (held.length) entry.incidents.open = true;

    const renderIncidentItem = incident => {
      const item = node('li');
      item.append(node('strong', `${STATE_LABEL[incident.state] || incident.state} · ${when(incident.reported_at)}`),
        ...incidentLines(incident).map(line => node('p', line)));
      if (incident.frames.length) {
        const figure = node('div', '', 'cell-fault-frames');
        for (const frame of incident.frames) {
          const image = node('img'); image.alt = `${frame.role === 'top' ? '상단' : '측면'} 카메라 · 고장 순간`;
          figure.append(image); void incidentFrame(source, incident, `frames/${frame.role}`, image, scope);
        }
        item.append(figure);
      }
      if ((incident.evidence || []).length) {  // the seconds around the stop: the jaw tip first, loaded only when opened
        const box = node('details'), strip = node('div', '', 'cell-fault-frames');
        box.append(node('summary', `정지 앞뒤 사진 ${incident.evidence.length}장 (집게 끝 먼저)`), strip);
        box.addEventListener('toggle', () => {
          if (!box.open || strip.childElementCount) return;
          for (const shot of incident.evidence) {
            const figure = node('figure'), image = node('img');
            const at = `${shot.t_rel_s > 0 ? '+' : ''}${shot.t_rel_s.toFixed(1)}초`;
            image.alt = `${shot.camera} 카메라 ${shot.kind === 'tip' ? '집게 끝 확대' : '전체'} · 정지 ${at}`;
            figure.append(image, node('figcaption', `${shot.camera} · ${shot.kind === 'tip' ? '집게 끝' : '전체'} · ${at}`));
            strip.append(figure); void incidentFrame(source, incident, `evidence/${shot.seq}`, image, scope);
          }
        });
        item.append(box);
      }
      if (incident.explanation) {
        const said = [node('ui-text', `AI 설명 (설명일 뿐, 판단이나 동작이 아닙니다 · ${incident.explanation.model})`),
          node('p', `본 것: ${incident.explanation.seen}`), node('p', `추정 원인: ${incident.explanation.suspected_cause}`)];
        // a person's cause is only worth scoring if it was picked before the model's was seen
        if (incident.cleared) item.append(...said);
        else { const box = node('details'); box.append(node('summary', 'AI 설명 보기 (원인을 고른 뒤에 여세요)'), ...said); item.append(box); }
      }
      if (incident.cleared) {
        const label = incident.cleared.cause ? ` · 원인 ${incident.cleared.cause} (근거 ${incident.cleared.basis})` : '';
        item.append(node('p', `해제: ${incident.cleared.by} · ${when(incident.cleared.at)}${label} · ${incident.cleared.note}`));
      } else if (source === quickClearSource && incident.decision?.hold !== false) {
        if (!canQuickClear()) {
          item.append(node('ui-text', '해제하려면 Fleet 운영자 계정으로 로그인하세요.'));
        } else {
          const note = '현장에서 정지 원인을 확인하고 조치했습니다. 팔과 집게, 이동 경로에 걸림이 없음을 확인했습니다.';
          const QUICK_CLEAR_REASON = '현장 확인 체크박스를 먼저 선택하세요.';
          const confirmation = node('label', '', 'ui-check');
          const check = node('input'); check.type = 'checkbox'; check.className = 'ui-field';
          confirmation.append(check, document.createTextNode(' ' + note));
          const message = node('ui-text'); message.setAttribute('role', 'status');
          let confirming = false;
          const button = action('사고 해제…', async () => {
            if (confirming || !check.checked || button.disabled || !canQuickClear()) return;
            confirming = true;
            const allowed = await confirmIrreversible({
              message: `사건 "${incident.incident_id}"의 보류를 해제할까요?`,
              action: '사고 해제', opener: button, signal: scope.signal});
            confirming = false;
            if (!allowed || !button.isConnected || !check.checked || button.disabled || !canQuickClear()) return;
            setOff(check, true, '사고 해제 요청을 처리하는 중입니다.');
            await clearIncident(source, incident, note, button, message);
            if (!button.disabled) {
              check.checked = false;
              setOff(check, false);
              setOff(button, true, QUICK_CLEAR_REASON);
            }
          });
          setOff(button, true, QUICK_CLEAR_REASON);
          check.addEventListener('change', () => { setOff(button, !check.checked, QUICK_CLEAR_REASON); });
          item.append(confirmation, button, message);
        }
      } else {
        // the cause and how the person knows it are kept with the clear: the labels learning scores rules and models against
        const cause = choice('원인', INCIDENT_CAUSES), basis = choice('근거', INCIDENT_BASES);
        const note = node('input'); note.className = 'ui-field'; note.maxLength = 400;
        note.setAttribute('aria-label', '확인한 내용'); note.placeholder = '팔과 집게를 확인한 내용 (필수) · 같은 동작을 다시 해 봤다면 그 결과';
        const message = node('ui-text');
        const button = action('확인했습니다 · 해제', () => clearIncident(source, incident, note, button, message,
          {cause: cause.value, basis: basis.value}));
        item.append(cause, basis, note, button, message);
      }
      return item;
    };

    const visibleCleared = open.length > 0 ? [] : cleared.slice(0, 3);
    const foldedCleared = open.length > 0 ? cleared : cleared.slice(3);
    entry.incidentsList.replaceChildren(...[...open, ...visibleCleared].map(renderIncidentItem));
    if (foldedCleared.length > 0) {
      const fold = node('details', '', 'cell-incident-cleared-fold');
      const summary = node('summary', `해제된 이전 사건 ${foldedCleared.length}건 보기`);
      const list = node('ol', '', 'cell-incident-history');
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
        for (const entry of cameras.values()) {
          if (entry.live && performance.now() >= entry.expires) staleCamera(entry);
          else if (!entry.live && entry.hasFrame) {
            const snap = entry.hold.snapshot();
            const sec = Math.floor(snap.disconnectedMs / 1000);
            if (sec !== entry.lastTickSec) {
              entry.lastTickSec = sec;
              paintCameraFrameHold(entry.frameWrap, entry.image, entry.overlay, snap);
              patchText(entry.status, snap.overlayText);
            }
          }
        }
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
  function freshJointArmIds() {
    if (observedDisconnected) return [];
    const now = performance.now();
    return lastWorkcells.flatMap(cell => cell.arms
      .filter(arm => arm.positions && (arms.get(arm.source_id)?.expires ?? 0) > now)
      .map(arm => arm.arm_id));
  }
  return {refresh, clear, focusArm, freshJointArmIds, dispose() { clear(); disposed = true; }};
}
