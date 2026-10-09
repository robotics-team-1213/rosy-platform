// D-488 M1 site map page: view the active map or the draft, edit the draft, activate it,
// and preview a D-490 trip plan. Only the D-494 운행 buttons start or cancel a trip.
import {createFleetClient} from '/common/fleet-client.js';
import {developmentToken} from '/console/assets/development-auth.js';
import {createPasswordLogin} from '/console/assets/password-login.js';
import {confirmIrreversible} from '/common/ui.js';
import {bindEstop, bindTopbarToggle, showSession, showSignedOut, tickClock, watchFleet} from '/console/assets/fleet-header.js';
import {
  PLACE_KINDS, PLACE_KIND_LABEL, actionRows, arrowMarks, editEdge, editPlace, fitView,
  planIsCurrent, planPolylines, siteMapErrorText, tripCancelReason, tripErrorText, tripStartReason,
  tripStatusText, rectangularView, viewTurnOf, editViewTurn, loopCapacityText, repeatTripBody, convoyLeaders,
} from '/console/assets/site-map-model.js';
import {createTeachPanel} from '/console/assets/site-map-teach.js';
import {warpImage} from '/console/assets/field-warp.js';
import {fieldToMap, multiply3, lensesMatch} from '/console/assets/map-fit.js';
import {parseLensHeader} from '/console/assets/vision-view.js';

const $ = id => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
const W = 800, H = 480;

// Read once: a token typed while the page starts is the person's own 접속, not a stored session.
const stored = sessionStorage.getItem('rosy-console-token') || '';
$('console-token').value = stored;
const request = createFleetClient({credential: () => $('console-token').value, origin: location.origin});
const state = {role: null, loadState: 'idle', active: null, draft: null, working: null, dirty: false, selected: null, plan: null, planEpoch: 0, point: null, robotsError: false, running: null, open: []};
const TRIP_POLL_MS = 1000;
let plane = null, planeEpoch = 0;
let calibrations = [];
const teach = createTeachPanel({request, role: () => state.role, draft: () => state.draft, dirty: () => state.dirty,
  places: () => shown()?.places || [], render: () => render(),
  reload: async () => { await load(); $('map-source').value = 'draft'; render(); }});

for (const kind of PLACE_KINDS) $('place-kind').append(new Option(PLACE_KIND_LABEL[kind], kind));

function gate(id, reason) {  // '' enables; otherwise the button says why it is off
  $(id).disabled = Boolean(reason);
  if (reason) $(id).setAttribute('reason', reason);
  else $(id).removeAttribute('reason');
}
function notice(text) { $('notice').textContent = text; }
function status(id, text, kind) { $(id).textContent = text; $(id).setAttribute('state', kind); }
function shown() { return $('map-source').value === 'draft' ? state.working : state.active?.map; }
function operatorReason() { return state.role === 'operator' ? '' : state.role ? '운영자 권한이 필요합니다' : '관제 접속이 필요합니다'; }

function el(name, attrs, parent) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  parent.append(node);
  return node;
}

function render() {
  const svg = $('site-map-svg');
  svg.replaceChildren();
  const map = shown();
  const hasMap = Boolean(map) && state.loadState === 'ready';
  for (const id of ['map-scroll-hint', 'map-viewport', 'map-legend']) $(id).hidden = !hasMap;
  const pending = state.loadState === 'pending';
  const failed = state.loadState === 'error';
  status('map-status', pending ? '지도 조회 중' : failed ? '지도 조회 실패 · 다시 접속하세요'
    : state.loadState === 'idle' ? '관제 접속 필요'
    : $('map-source').value === 'draft'
      ? (state.working ? `초안${state.dirty ? ' · 저장 안 됨' : ''}` : '초안 없음')
      : (state.active ? `활성 지도 v${state.active.version} · ${state.active.activated_by}` : '활성 지도 없음'),
  pending ? 'pending' : failed ? 'error' : map ? 'ready' : 'empty');
  if (!hasMap) return;
  const background = plane?.mapId === map.map_id ? plane : null;
  svg.classList.toggle('has-plane', Boolean(background));
  $('map-view-turn').value = String(viewTurnOf(map));
  const view = background?.view || fitView(map, W, H, 24, viewTurnOf(map));
  state.view = view;
  if (background) {
    el('image', {...background.field, href: background.url, preserveAspectRatio: 'none'}, svg);
    el('rect', {...background.field, class: 'plane-border'}, svg);
  }
  const line = points => points.map(([x, y]) => view.toPx(x, y).join(',')).join(' ');
  for (const edge of map.edges) {
    const path = el('polyline', {points: line(edge.polyline), 'data-edge': edge.id,
      class: `edge ${edge.drive_mode}${state.selected?.edge === edge.id ? ' selected' : ''}`}, svg);
    el('title', {}, path).textContent = `${edge.id} · ${edge.direction === 'two_way' ? '양방' : '일방'} · ${edge.speed_cap_mps} m/s`;
    for (const mark of arrowMarks(edge)) {
      const [px, py] = view.toPx(mark.x, mark.y);
      el('polygon', {class: 'arrow', points: '8,0 -6,-6 -6,6',
        transform: `translate(${px} ${py}) rotate(${view.rotateDeg(mark.angle)})`}, svg);
    }
  }
  if ($('map-source').value === 'active' && planIsCurrent(state.plan, state.active)) {
    for (const points of planPolylines(map, state.plan)) el('polyline', {class: 'plan', points: line(points)}, svg);
  }
  for (const points of teach.lines()) el('polyline', {class: 'teach', points: line(points)}, svg);
  for (const place of map.places) {
    const [px, py] = view.toPx(place.x, place.y);
    const dot = el('circle', {cx: px, cy: py, r: 9, 'data-place': place.id,
      class: `place ${place.kind}${state.selected?.place === place.id ? ' selected' : ''}`}, svg);
    el('title', {}, dot).textContent = `${place.name} (${PLACE_KIND_LABEL[place.kind] || place.kind})`;
    if (place.kind === 'start') {
      el('polygon', {class: 'start-heading', points: '26,0 12,-7 12,7',
        transform: `translate(${px} ${py}) rotate(${view.rotateDeg(place.yaw)})`}, svg);
    }
    el('text', {x: px + 12, y: py - 10, class: 'label'}, svg).textContent = place.name;
  }
  if (state.point && $('map-source').value === 'active') {
    const [px, py] = view.toPx(state.point.x, state.point.y);
    el('circle', {cx: px, cy: py, r: 6, class: 'target'}, svg);
  }
  if (background?.point) {
    const [px, py] = view.toPx(background.point.x, background.point.y);
    el('circle', {cx: px, cy: py, r: 6, class: 'target'}, svg);
  }
}

function select(selection) {
  state.selected = selection;
  const map = state.working;
  const place = selection?.place && map?.places.find(item => item.id === selection.place);
  const edge = selection?.edge && map?.edges.find(item => item.id === selection.edge);
  const reason = operatorReason();
  $('place-form').hidden = !place || Boolean(reason);
  $('edge-form').hidden = !edge || Boolean(reason);
  gate('apply-edit', reason || (place || edge ? '' : '초안 보기에서 장소나 차로를 고르세요'));
  if (place) {
    $('selection').textContent = `장소 ${place.id}`;
    $('place-name').value = place.name;
    $('place-kind').value = place.kind;
  } else if (edge) {
    $('selection').textContent = `차로 ${edge.id} · ${edge.from} → ${edge.to}`;
    $('edge-direction').value = edge.direction;
    $('edge-mode').value = edge.drive_mode;
    $('edge-speed').value = edge.speed_cap_mps;
  } else {
    $('selection').textContent = selection ? '초안에 없는 항목입니다 · 초안 보기에서 고르세요' : '선택 없음';
  }
  render();
}

function syncButtons() {
  const reason = operatorReason();
  // D-517 1: one trip per robot — start, cancel and confirm act on the selected robot's open trip.
  state.running = state.open.find(trip => trip.robot_id === $('trip-robot').value) || null;
  $('trip-start-label').textContent = $('trip-robot').value ? `${$('trip-robot').value} 출발 자리` : '고른 로봇의 출발 자리';
  // D-517 9 M3: 대열 리더는 반복 운행 중이고 아무도 따라가지 않는 로봇만 고른다.
  const leader = $('trip-leader').value, leaders = convoyLeaders(state.open, $('trip-robot').value);
  $('trip-leader').replaceChildren($('trip-leader').options[0], ...leaders.map(id => new Option(`${id} 뒤를 따라감`, id)));
  $('trip-leader').value = leaders.includes(leader) ? leader : '';
  gate('plane-load', !state.role ? '관제 접속이 필요합니다' : !$('plane-source').value ? '이 지도에 맞는 카메라 보정이 없습니다' : '');
  gate('plane-clear', plane ? '' : '불러온 영상이 없습니다');
  gate('plane-pick', plane?.mapId === shown()?.map_id ? '' : '평면 영상을 먼저 불러오세요');
  gate('import-camera-map', reason || (!$('camera-map-file').files.length ? '카메라 지도 JSON 파일을 고르세요' : ''));
  gate('map-view-turn', reason || (!state.working ? '고칠 지도가 없습니다' : ''));
  gate('save-draft', reason || (!state.working ? '고칠 지도가 없습니다' : (state.dirty ? '' : '고친 내용이 없습니다')));
  gate('activate', reason || (!state.draft?.revision ? '저장된 초안이 없습니다' : (state.dirty ? '고친 내용을 먼저 저장하세요' : '')));
  status('draft-status', state.loadState === 'pending' ? '초안 조회 중'
    : state.loadState === 'error' ? '초안 확인 불가 · 다시 접속하세요'
    : state.loadState === 'idle' ? '관제 접속 필요'
    : state.draft?.revision
      ? `저장된 초안 · ${state.draft.saved_by}${state.dirty ? ' · 고친 내용 저장 필요' : ''}`
      : (state.dirty ? '저장 안 된 초안' : '저장된 초안 없음'),
  state.loadState === 'pending' ? 'pending' : state.loadState === 'error' ? 'error'
    : state.draft?.revision ? 'ready' : 'empty');
  const tripRobot = $('trip-robot');
  const robotReason = state.robotsError ? '로봇 상태 확인 불가 · 다시 접속하세요'
    : !tripRobot.options.length ? '등록된 로봇이 없습니다 · 관리자에게 로봇 등록을 요청하세요'
    : ![...tripRobot.options].some(option => option.dataset.online === 'true') ? '연결된 로봇이 없습니다 · 로봇 연결을 확인하세요'
    : !tripRobot.value ? '로봇을 고르세요'
    : tripRobot.selectedOptions[0]?.dataset.online !== 'true' ? '선택한 로봇의 연결을 확인하세요' : '';
  const target = $('trip-pick').checked ? state.point : $('trip-place').value;
  const inspecting = $('plane-pick').checked ? '평면 지도 좌표 확인을 먼저 마치세요' : '';
  gate('trip-plan', inspecting || reason || (!state.active ? '활성 지도가 없습니다' : robotReason || (target ? '' : '목적지를 고르세요')));
  gate('trip-pick', reason);
  gate('trip-start', inspecting || tripStartReason({role: state.role, plan: state.plan, active: state.active, running: state.running}));
  gate('trip-cancel', tripCancelReason({role: state.role, running: state.running}));
  const starts = (state.active?.map.places || []).filter(place => place.kind === 'start');
  gate('trip-repeat', inspecting || reason || (!state.active ? '활성 지도가 없습니다' : robotReason
    || (state.running ? '이 로봇은 이미 운행 중입니다' : '')
    || (starts.length < 2 ? '반복 운행에는 출발 자리가 두 곳 이상 필요합니다'
      : $('trip-start-place').value ? '' : '출발 자리를 고르세요')));
  $('trip-confirm').hidden = !state.running?.hold;
  gate('trip-confirm', inspecting || reason || (state.running?.hold?.plan ? '' : '다시 계산한 경로가 없습니다 · 운행을 취소하세요'));
  teach.sync();
}

async function pollTrips() {
  if (state.loadState === 'ready') {
    try {
      const {running, trips, open} = await request('/api/fleet/trips');
      state.open = open || (running ? [running] : []);
      const mine = state.open.find(trip => trip.robot_id === $('trip-robot').value);
      const shown = mine || running || trips[0] || null;
      const others = state.open.length - (shown && state.open.includes(shown) ? 1 : 0);
      status('trip-run', tripStatusText(shown, state.active?.map) + (others > 0 ? ` · 다른 로봇 ${others}대 운행 중` : ''),
        state.open.includes(shown) ? 'pending' : shown?.state === 'arrived' ? 'ready' : shown ? 'error' : 'empty');
      await pollLoops();
    } catch (error) {
      status('trip-run', `운행 상태 확인 불가 · ${siteMapErrorText(error)}`, 'error');
    }
    syncButtons();
  }
  setTimeout(pollTrips, TRIP_POLL_MS);
}
pollTrips();

// D-517 3: "고리 n/m대" from the Fleet block table; a Fleet without /traffic hides the line.
async function pollLoops() {
  try {
    const text = loopCapacityText(await request('/api/fleet/traffic'));
    $('trip-loop').hidden = false;
    status('trip-loop', text || '반복 운행 없음', text ? 'ready' : 'empty');
  } catch (error) {
    $('trip-loop').hidden = error.status === 404 && !error.code;
    if (!$('trip-loop').hidden) status('trip-loop', `고리 수용 확인 불가 · ${siteMapErrorText(error)}`, 'error');
  }
}

async function load() {
  state.planEpoch += 1;
  let active = null;
  try { active = await request('/api/fleet/site-map/active'); } catch (error) {
    if (error.status !== 404) throw error;
  }
  const draft = await request('/api/fleet/site-map/draft');
  let robots = [];
  state.robotsError = false;
  try { robots = (await request('/api/fleet/state')).robots || []; } catch (error) {
    if (error.status === 401 || error.status === 403) throw error;
    state.robotsError = true;
  }
  state.active = active;
  state.draft = draft;
  state.working = draft.map ? draft.map
    : (active ? JSON.parse(JSON.stringify(active.map)) : null);
  state.dirty = false;
  state.loadState = 'ready';
  try { calibrations = (await request('/api/fleet/calibrations')).calibrations || []; }
  catch { calibrations = []; }
  updatePlaneSources();
  $('trip-place').replaceChildren(...(state.active?.map.places || [])
    .map(place => new Option(`${place.name} (${place.id})`, place.id)));
  $('trip-start-place').replaceChildren(...(state.active?.map.places || []).filter(place => place.kind === 'start')
    .map(place => new Option(`${place.name} (${place.id})`, place.id)));
  $('trip-robot').replaceChildren(...robots.map(robot => {
    const safety = robot.state?.safety?.estop;
    const stateLabel = !robot.online ? '연결 끊김' : safety === true ? '비상 정지'
      : safety === false ? '' : '정지 상태 미확인';
    const option = new Option(stateLabel ? `${robot.robot_id} · ${stateLabel}` : robot.robot_id, robot.robot_id);
    option.dataset.online = robot.online ? 'true' : 'false';
    return option;
  }));
  teach.robots(robots);
  if (state.robotsError) status('trip-summary', '경로 미리보기 불가 · 로봇 상태 확인 불가. 다시 접속하세요.', 'error');
  else if (!robots.length) status('trip-summary', '경로 미리보기 불가 · 등록된 로봇이 없습니다. 관리자에게 로봇 등록을 요청하세요.', 'empty');
  else if (!robots.some(robot => robot.online)) status('trip-summary', '경로 미리보기 불가 · 연결된 로봇이 없습니다. 로봇 연결을 확인하세요.', 'empty');
  select(null);
  syncButtons();
}

async function guarded(work) {
  try { await work(); } catch (error) { notice(siteMapErrorText(error)); }
  syncButtons();
}

$('token-save').addEventListener('click', async () => {
  planeEpoch += 1; plane = null; calibrations = [];
  $('plane-pick').checked = false;
  $('plane-source').replaceChildren();
  gate('token-save', '접속 중');
  const started = Date.now();
  const ticker = setInterval(() => notice(`접속 중 · ${Math.floor((Date.now() - started) / 1000)}초 경과`), 1000);
  state.role = null;
  state.loadState = 'pending';
  state.planEpoch += 1;
  state.robotsError = false;
  state.active = state.draft = state.working = state.selected = state.plan = state.point = state.running = null;
  state.open = [];
  $('trip-start-place').replaceChildren();
  state.dirty = false;
  $('trip-place').replaceChildren();
  $('trip-robot').replaceChildren();
  $('trip-actions').replaceChildren();
  status('trip-summary', '계산 전 · 실행은 하지 않습니다', 'empty');
  select(null);
  syncButtons();
  notice('접속 중 · 0초 경과');
  try {
    const session = await request('/api/fleet/session');
    sessionStorage.setItem('rosy-console-token', $('console-token').value);
    state.role = session.role;
    showSession(session);
    loginForm.refresh(false);
    syncButtons();
    await load();
    notice(state.robotsError ? '지도를 읽었습니다 · 로봇 상태 확인 불가. 다시 접속하세요.'
      : !state.active && !state.working ? '활성 지도와 초안이 없습니다. 관리자에게 현장 지도 가져오기를 요청하세요.'
      : !state.active ? '활성 지도는 없습니다. 초안을 확인하고 활성화하세요.' : '지도를 읽었습니다.');
  } catch (error) {
    state.loadState = error.status === 401 ? 'idle' : 'error';
    if (error.status === 401 || error.status === 403) {
      state.role = null;
      showSignedOut();
    }
    if (error.status === 401) loginForm.refresh(true);
    render();
    syncButtons();
    notice(siteMapErrorText(error));
  } finally {
    clearInterval(ticker);
    gate('token-save', '');
  }
});

function clearPlane() {
  planeEpoch += 1;
  plane = null;
  $('plane-pick').checked = false;
  $('plane-point').textContent = '확인한 좌표 없음 · 운행 목적지로 전달하지 않습니다.';
  $('plane-status').textContent = '카메라 평면 영상과 좌표 확인은 표시 전용입니다.';
}
function updatePlaneSources() {
  clearPlane();
  $('plane-source').replaceChildren(...calibrations.filter(c => c.map_id === shown()?.map_id)
    .map(c => new Option(c.source_id, c.source_id)));
}
$('map-source').addEventListener('change', () => { updatePlaneSources(); render(); syncButtons(); });
$('plane-clear').addEventListener('click', () => { updatePlaneSources(); render(); syncButtons(); });
$('plane-source').addEventListener('change', () => { clearPlane(); render(); syncButtons(); });
$('plane-pick').addEventListener('change', () => {
  if ($('plane-pick').checked) $('trip-pick').checked = false;
  clearPlan(); syncButtons();
});
$('plane-load').addEventListener('click', async () => {
  clearPlane();
  const epoch = ++planeEpoch;
  const record = calibrations.find(c => c.source_id === $('plane-source').value && c.map_id === shown()?.map_id);
  plane = null;
  render();
  syncButtons();
  $('plane-status').textContent = '평면 영상 불러오는 중';
  gate('plane-load', '불러오는 중');
  let url;
  try {
    const {view, field} = rectangularView(record, shown()?.map_id, W, H, viewTurnOf(shown()));
    const lease = await request('/api/fleet/vision/lease', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({source_id: record.source_id})});
    const path = new URL(lease.frame_path, location.origin);
    if (path.origin !== location.origin || path.username || path.password) throw new Error('영상 주소를 확인하세요.');
    const response = await fetch(path, {headers: {Authorization: `Bearer ${lease.lease}`},
      credentials: 'omit', redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(10000)});
    const age = response.headers.get('X-Frame-Age-Ms');
    if (!response.ok || age === null || !Number.isFinite(Number(age)) || Number(age) < 0 || Number(age) > 3000
      || response.headers.get('X-Frame-Rectified') !== 'false') throw new Error('신선한 원본 영상을 확인할 수 없습니다.');
    const lens = parseLensHeader(response.headers.get('X-Source-Lens'));
    if (!lensesMatch(record.lens, lens))
      throw new Error('카메라 렌즈와 보정이 다릅니다.');
    const blob = await response.blob();
    if (blob.size > 8 * 1024 * 1024) throw new Error('영상 크기가 너무 큽니다.');
    url = URL.createObjectURL(blob);
    const image = new Image(); image.src = url; await image.decode();
    if (image.naturalWidth !== record.image?.width || image.naturalHeight !== record.image?.height)
      throw new Error('영상 크기와 보정이 다릅니다.');
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(field.width); canvas.height = Math.ceil(field.height);
    const h = multiply3(record.map_to_image, fieldToMap(record.track_bounds_m,
      {x: 0, y: 0, width: canvas.width, height: canvas.height}));
    warpImage(canvas.getContext('2d'), image, h, canvas.width, canvas.height, document.createElement('canvas'));
    if (epoch !== planeEpoch) return;
    plane = {mapId: record.map_id, view, field, bounds: record.track_bounds_m, url: canvas.toDataURL('image/png')};
    $('plane-status').textContent = `불러온 평면 영상 · ${record.source_id} · ${new Date().toLocaleTimeString()} · 표시 전용`;
    render();
  } catch (error) {
    if (epoch === planeEpoch) $('plane-status').textContent = `평면 영상 확인 실패 · ${siteMapErrorText(error)}`;
  } finally {
    if (url) URL.revokeObjectURL(url);
    if (epoch === planeEpoch) syncButtons();
  }
});

function clearPlan() {
  state.planEpoch += 1;
  state.plan = null;
  status('trip-summary', '계산 전 · 실행은 하지 않습니다', 'empty');
  $('trip-actions').replaceChildren();
  render();
  syncButtons();
}

$('site-map-svg').addEventListener('click', event => {
  if ($('plane-pick').checked) {
    if (plane?.mapId !== shown()?.map_id) return;
    const at = new DOMPoint(event.clientX, event.clientY).matrixTransform(event.currentTarget.getScreenCTM().inverse());
    const [x, y] = plane.view.toMap(at.x, at.y);
    const b = plane.bounds;
    if (x < b.min_x || x > b.max_x || y < b.min_y || y > b.max_y) return;
    plane.point = {x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000};
    $('plane-point').textContent = `확인한 좌표 x ${plane.point.x} m, y ${plane.point.y} m · 표시 전용`;
    render();
    return;
  }
  if ($('trip-pick').checked && $('map-source').value === 'active' && state.view) {
    const svg = event.currentTarget;
    const at = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    const [x, y] = state.view.toMap(at.x, at.y);
    state.point = {x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000};
    $('trip-point').textContent = `찍은 좌표 x ${state.point.x} m, y ${state.point.y} m`;
    clearPlan();
    return;
  }
  const target = event.target.closest('[data-place], [data-edge]');
  if (!target) return;
  select(target.dataset.place ? {place: target.dataset.place} : {edge: target.dataset.edge});
});

$('trip-pick').addEventListener('change', () => {
  $('site-map-svg').classList.toggle('picking', $('trip-pick').checked);
  if ($('trip-pick').checked) $('map-source').value = 'active';  // trips plan on the active map
  clearPlan();
});
$('trip-place').addEventListener('change', clearPlan);
$('trip-robot').addEventListener('change', clearPlan);

$('camera-map-file').addEventListener('change', syncButtons);
$('import-camera-map').addEventListener('click', () => guarded(async () => {
  if (operatorReason()) return;
  const file = $('camera-map-file').files[0];
  if (!file) return;
  if (file.size > 2 * 1024 * 1024 - 1024) throw new Error('지도 초안 파일은 2 MiB보다 작아야 합니다.');
  const map = JSON.parse(await file.text());
  if (map?.schema !== 'rosy.site_map/1') throw new Error('rosy.site_map/1 지도 초안 파일이 필요합니다.');
  const revision = state.draft?.revision || null;
  if (state.dirty || revision) {
    const allowed = await confirmIrreversible({message: '기존 초안을 카메라 지도 초안으로 바꿀까요? 활성 지도는 바뀌지 않습니다.',
      action: '카메라 초안 가져오기', opener: $('import-camera-map')});
    if (!allowed) return;
  }
  // The existing bounded, named-operator endpoint validates every coordinate and reference.
  await request('/api/fleet/site-map/draft', {method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({map, expected_revision: revision})});
  await load();
  $('map-source').value = 'draft';
  clearPlan();
  notice('카메라 지도 초안을 가져왔습니다. 차로 연결·통행 방향을 검토한 뒤 활성화하세요.');
}));

// D-513 7: one orientation for every Fleet map and camera view; saved and activated like any edit.
$('map-view-turn').addEventListener('change', () => guarded(async () => {
  state.working = editViewTurn(state.working, $('map-view-turn').value);
  state.dirty = true;
  $('map-source').value = 'draft';
  clearPlane();
  render(); syncButtons();
  notice('화면 방향을 초안에 반영했습니다. 저장하고 활성화하면 관제 화면 전체가 이 방향을 씁니다.');
}));

$('apply-edit').addEventListener('click', () => guarded(async () => {
  const sel = state.selected;
  state.working = sel?.place
    ? editPlace(state.working, sel.place, {name: $('place-name').value, kind: $('place-kind').value})
    : editEdge(state.working, sel.edge, {direction: $('edge-direction').value,
      drive_mode: $('edge-mode').value, speed_cap_mps: $('edge-speed').value});
  state.dirty = true;
  $('map-source').value = 'draft';
  select(sel);
  notice('초안에 반영했습니다. 저장해야 남습니다.');
}));

$('save-draft').addEventListener('click', () => guarded(async () => {
  state.draft = await request('/api/fleet/site-map/draft', {method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({map: state.working, expected_revision: state.draft?.revision || null})});
  state.dirty = false;
  notice('초안을 저장했습니다. 활성화해야 경로 계획에 쓰입니다.');
}));

$('activate').addEventListener('click', () => guarded(async () => {
  const revision = state.draft?.revision;
  const allowed = await confirmIrreversible({
    message: '저장된 초안을 활성 지도로 바꿀까요? 이후 경로 계획은 새 지도로 합니다. 진행 중인 차선 경로가 있으면 거절됩니다.',
    action: '초안 활성화', opener: $('activate'),
  });
  if (!allowed || revision !== state.draft?.revision) return;
  const view = await request('/api/fleet/site-map/activate', {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_revision: revision})});
  state.plan = null;
  await load();
  notice(`활성 지도 v${view.version}로 바꿨습니다.`);
}));

$('trip-plan').addEventListener('click', () => guarded(async () => {
  const epoch = ++state.planEpoch;
  const to = $('trip-pick').checked ? state.point : $('trip-place').value;
  state.plan = null;
  try {
    const plan = await request(`/api/fleet/robots/${encodeURIComponent($('trip-robot').value)}/trip`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({to})});
    if (epoch !== state.planEpoch) return;
    state.plan = plan;
  } catch (error) {
    if (epoch !== state.planEpoch) return;
    status('trip-summary', error.code ? tripErrorText(error.code, error.detail) : error.message, 'error');
    $('trip-actions').replaceChildren();
    render();
    return;
  }
  const plan = state.plan;
  if (!planIsCurrent(plan, state.active)) {
    state.plan = null;
    await load();
    status('trip-summary', `지도가 v${plan.map_version}로 바뀌었습니다 · 다시 계산하세요`, 'error');
    return;
  }
  status('trip-summary', `${plan.segments.length}개 차로 · ${plan.length_m.toFixed(2)} m · 약 ${Math.round(plan.eta_s)} s`
    + ` · 지도 v${plan.map_version} · 실행하지 않음 · 운행 시작으로 출발`, 'ready');
  $('trip-actions').replaceChildren(...actionRows(plan, state.active.map).map(text => {
    const row = document.createElement('li');
    row.textContent = text;
    return row;
  }));
  $('map-source').value = 'active';
  render();
}));

async function tripAction(path, done) {
  try {
    const trip = await request(path, {method: 'POST'});
    const open = ['started', 'running'].includes(trip.state);
    state.open = [...state.open.filter(item => item.trip_id !== trip.trip_id), ...(open ? [trip] : [])];
    status('trip-run', tripStatusText(trip, state.active?.map), open ? 'pending' : 'ready');
    notice(done);
  } catch (error) {  // the poll rewrites #trip-run each second; the refusal stays in the notice
    notice(`운행 거절 · ${error.code ? tripErrorText(error.code, error.detail) : siteMapErrorText(error)}`);
  }
  syncButtons();
}

$('trip-start').addEventListener('click', () => {
  const plan = state.plan;
  if (plan) tripAction(`/api/fleet/trips/${encodeURIComponent(plan.plan_id)}/start`, '운행을 시작했습니다.');
});
// D-517 2: the selected robot and its start place make one lap trip over every start place; Fleet
// plans it (POST /trip repeat) and the same click starts it. A refusal of either step stays in the notice.
$('trip-start-place').addEventListener('change', syncButtons);
$('trip-repeat').addEventListener('click', async () => {
  const robot = $('trip-robot').value, place = $('trip-start-place').selectedOptions[0]?.textContent;
  gate('trip-repeat', '출발하는 중');
  try {
    const plan = await request(`/api/fleet/robots/${encodeURIComponent(robot)}/trip`, {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(repeatTripBody(state.active?.map, $('trip-start-place').value, $('trip-leader').value))});
    const follows = $('trip-leader').value ? ` · ${$('trip-leader').value} 뒤 대열` : '';
    await tripAction(`/api/fleet/trips/${encodeURIComponent(plan.plan_id)}/start`, `반복 운행을 시작했습니다 · ${robot} · ${place}${follows}`);
  } catch (error) {
    notice(`반복 운행 거절 · ${error.code ? tripErrorText(error.code, error.detail) : siteMapErrorText(error)}`);
    syncButtons();
  }
});
$('trip-confirm').addEventListener('click', () => {
  if (state.running) tripAction(`/api/fleet/trips/${encodeURIComponent(state.running.trip_id)}/confirm-replan`, '바뀐 경로로 계속합니다.');
});
$('trip-cancel').addEventListener('click', async () => {
  const trip = state.running;
  if (!trip) return;
  const allowed = await confirmIrreversible({
    message: '운행을 취소할까요? 로봇은 바로 멈춥니다. 차선 주행이면 차선 주행을 끄고(OFF), 좌표 주행이면 목표를 취소합니다.',
    action: '운행 취소', opener: $('trip-cancel'),
  });
  if (allowed) tripAction(`/api/fleet/trips/${encodeURIComponent(trip.trip_id)}/cancel`, '운행을 취소했습니다.');
});

bindEstop(request);
bindTopbarToggle();
tickClock();
setInterval(tickClock, 1000);
watchFleet(request);
$('console-token').addEventListener('keydown', event => { if (event.key === 'Enter') $('token-save').click(); });

developmentToken($('console-token').value).then(token => {
  if (token) { $('console-token').value = token; $('token-access').hidden = true; $('token-save').click(); }
  // D-540 2 — a stored token (another Fleet tab) or a login cookie connects at once; neither means signed out.
  else loginForm.refresh(true).then(cookie => {
    if (cookie || stored) $('token-save').click(); else showSignedOut();
  });
}).catch(() => {});
// D-519 — login and logout change the cookie; drop any token so the cookie (or a 401) decides.
const loginForm = createPasswordLogin($('password-login'), {onChange: () => {
  $('console-token').value = ''; $('token-save').click();
}});
