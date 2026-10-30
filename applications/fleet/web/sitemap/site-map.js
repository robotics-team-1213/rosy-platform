import {createMapSourcesPanel} from '/console/assets/site-map-sources.js';
import {OPERATOR_REASON} from "/console/assets/authorization.js";
// D-488 M1 site map page: view the active map or the draft, edit the draft, activate it,
// and preview a D-490 trip plan. D-540 4: robots are drawn read-only; trips start and stop on the 관제 robot card.
import {createFleetClient} from '/common/fleet-client.js';
import {developmentToken} from '/console/assets/development-auth.js';
import {createPasswordLogin} from '/console/assets/password-login.js';
import {confirmIrreversible} from '/common/ui.js';
import {bindEstop, bindTopbarToggle, showSession, showSignedOut, tickClock, watchFleet} from '/console/assets/fleet-header.js';
import {PLACE_KINDS, PLACE_KIND_LABEL, actionRows, arrowMarks, fitView, planIsCurrent, planPolylines, siteMapErrorText, viewTurnOf, editViewTurn, planTrip, tripRefusalText, planSummaryText, tripPoseReason, robotMapPose, addApproach, removeApproach, mergeCrosswalks} from '/console/assets/site-map-model.js';
import {tripStatusText} from '/console/assets/trip-display.js';
import {editEdge, editPlace} from '/console/assets/site-map-edit.js';
import {bindScreens} from '/console/assets/subnav-screens.js';
import {guideMarks, poseLabel} from '/console/assets/guide-layer.js';
import {createTeachPanel} from '/console/assets/site-map-teach.js';
import {createSurveyPanel} from '/console/assets/site-map-survey.js';
import {createCameraMapPanel} from '/console/assets/site-map-camera.js';
import {createMapAuthoring} from '/console/assets/map-authoring.js';
import {drawFacilities, svgElement as el} from '/console/assets/map-editor.js';

const $ = id => document.getElementById(id);
const W = 800, H = 480;

// Read once: a token typed while the page starts is the person's own 접속, not a stored session.
const stored = sessionStorage.getItem('rosy-console-token') || '';
$('console-token').value = stored;
const request = createFleetClient({credential: () => $('console-token').value, origin: location.origin});
const state = {role: null, loadState: 'idle', active: null, draft: null, working: null, dirty: false, selected: null, plan: null, planEpoch: 0, point: null, robotsError: false, robots: [], open: [], guide: null, guideUnavailable: false, band: null};
const ROBOT_POLL_MS = 1000;
let calibrations = [];
const teach = createTeachPanel({request, role: () => state.role, draft: () => state.draft, dirty: () => state.dirty,
  map: () => shown(),
  places: () => shown()?.places || [], render: () => render(),
  reload: async () => { await load(); $('map-source').value = 'draft'; render(); }});
const survey = createSurveyPanel({map: () => shown(), source: () => $('map-source').value, view: () => state.view,
  render: () => render(),
  reason: () => operatorReason(), hasDraft: () => Boolean(state.dirty || state.draft?.revision),
  begin: () => { clearPlane(); $('trip-pick').checked = false; state.band = null; },
  changed: map => { state.working = map; state.dirty = true; $('map-source').value = 'draft';
    clearPlane(); state.selected = null; state.band = null; clearPlan(); updatePlaneSources(); }});

const cameraMap = createCameraMapPanel({request, guarded, reason: () => operatorReason(),
  context: () => [state.working, state.sessionEpoch],
  draft: () => state.draft, dirty: () => state.dirty, notice,
  reload: async () => { await load(); $('map-source').value = 'draft'; clearPlan(); }});
const authoring = createMapAuthoring({request, svg: $('site-map-svg'), map: shown, draft: () => state.working,
  source: () => $('map-source').value, view: () => state.view, reason: operatorReason, dirty: () => state.dirty,
  begin: () => { survey.cancel(); clearPlane(); $('trip-pick').checked = false; state.band = null; },
  changed: map => { state.working = map; state.dirty = true; $('map-source').value = 'draft';
    state.selected = null; state.band = null; updatePlaneSources(); clearPlan(); },
  render, notice, epoch: () => state.sessionEpoch});

for (const kind of PLACE_KINDS) $('place-kind').append(new Option(PLACE_KIND_LABEL[kind], kind));

function gate(id, reason) {  // '' enables; otherwise the button says why it is off
  $(id).disabled = Boolean(reason);
  if (reason) $(id).setAttribute('reason', reason);
  else $(id).removeAttribute('reason');
}
function notice(text) { $('notice').textContent = text; }
function status(id, text, kind) { $(id).textContent = text; $(id).setAttribute('state', kind); }
const sourcePanel = createMapSourcesPanel({request, state, shown, calibrations: () => calibrations,
  operatorReason, render, syncButtons, gate, guarded, select, clearPlan, status, W, H});
const {selectedProfile, loadProfiles, clearPlane, updatePlaneSources} = sourcePanel;
function shown() {
  if ($('map-source').value === 'profile') return selectedProfile()?.map;
  return $('map-source').value === 'draft' ? state.working : state.active?.map;
}
function operatorReason() { return state.role === 'operator' ? '' : state.role ? OPERATOR_REASON : '관제 접속이 필요합니다'; }

function render() {
  authoring.sync();
  survey.sync();
  const svg = $('site-map-svg');
  svg.replaceChildren();
  const map = shown();
  if (!sourcePanel.renderStatus(map)) return;
  const {view, point: backgroundPoint} = sourcePanel.drawBackground(svg, map, () => fitView(map, W, H, LABEL_PAD, viewTurnOf(map), authoring.discs()));
  state.view = view;
  const line = points => points.map(([x, y]) => view.toPx(x, y).join(',')).join(' ');
  // D-573 1/7: crosswalk areas under the lanes (read-only polygons) and their waiting bands.
  for (const crosswalk of map.crosswalks || []) {
    const zone = el('polygon', {points: line(crosswalk.polygon), 'data-crosswalk': crosswalk.id,
      class: `crosswalk${state.selected?.crosswalk === crosswalk.id ? ' selected' : ''}`}, svg);
    el('title', {}, zone).textContent = `횡단보도 ${crosswalk.id} · 차로 ${(crosswalk.lanes || []).join(', ') || '저장 때 계산'}`;
    for (const band of crosswalk.approach || []) el('polygon', {class: 'crosswalk-approach', points: line(band)}, svg);
  }
  if (state.band?.length) el('polyline', {class: 'band-draft', points: line(state.band)}, svg);
  for (const edge of map.edges) {
    const path = el('polyline', {points: line(edge.polyline), 'data-edge': edge.id,
      class: `edge ${edge.drive_mode}${state.selected?.edge === edge.id ? ' selected' : ''}`}, svg);
    el('title', {}, path).textContent = `${edge.id} · ${edge.direction === 'two_way' ? '양방' : '일방'} · ${edge.speed_cap_mps} m/s`;
    if (edge.evidence?.status === 'inferred') path.classList.add('inferred');
    for (const mark of arrowMarks(edge)) {
      const [px, py] = view.toPx(mark.x, mark.y);
      el('polygon', {class: 'arrow', points: '8,0 -6,-6 -6,6',
        transform: `translate(${px} ${py}) rotate(${view.rotateDeg(mark.angle)})`}, svg);
    }
  }
  if ($('map-source').value === 'active' && planIsCurrent(state.plan, state.active)) {
    for (const points of planPolylines(map, state.plan)) el('polyline', {class: 'plan', points: line(points)}, svg);
  }
  if ($('map-source').value !== 'profile')
    for (const points of teach.lines()) el('polyline', {class: 'teach', points: line(points)}, svg);
  for (const [index, place] of map.places.entries()) {
    const [px, py] = view.toPx(place.x, place.y);
    const dot = el('circle', {cx: px, cy: py, r: 9, 'data-place': place.id,
      class: `place ${place.kind}${state.selected?.place === place.id ? ' selected' : ''}`}, svg);
    el('title', {}, dot).textContent = `${place.name} (${PLACE_KIND_LABEL[place.kind] || place.kind})`;
    if (place.kind === 'start') {
      el('polygon', {class: 'start-heading', points: '26,0 12,-7 12,7',
        transform: `translate(${px} ${py}) rotate(${view.rotateDeg(place.yaw)})`}, svg);
    }
    el('text', {x: px + 12, y: py - 10, class: 'label'}, svg).textContent = index + 1;
  }
  drawFacilities(svg, map, view);
  if (survey.points().length) el('polyline', {points: line(survey.points()), class: 'teach'}, svg);
  svg.classList.toggle('picking', survey.picking() || $('trip-pick').checked);
  if (state.point && $('map-source').value === 'active') {
    const [px, py] = view.toPx(state.point.x, state.point.y);
    el('circle', {cx: px, cy: py, r: 6, class: 'target'}, svg);
  }
  if (backgroundPoint) {
    const [px, py] = view.toPx(backgroundPoint.x, backgroundPoint.y);
    el('circle', {cx: px, cy: py, r: 6, class: 'target'}, svg);
  }
  drawRobots();
  authoring.paint();
}

// D-595: the fit depends only on the map and its view turn, never on robot poses or their uncertainty
// rings, so a 1 s poll never re-fits (zooms) the map. A ring past the map edge is clipped; its label is
// clamped onto the map (D-540 4).
const LABEL_PAD = 24;  // a label with no room above its ring goes below it

// D-540 4: the 관제 map's /guide marks (body, heading, uncertainty ring) and each open trip's line and
// next place, in this map's frame and view turn. Read-only; redrawn alone so a poll never eats a click.
function drawRobots() {
  const svg = $('site-map-svg'), map = shown();
  svg.querySelector('#robot-layer')?.remove();
  if (!map || !state.view || $('map-source').value !== 'active') return;
  const layer = el('g', {id: 'robot-layer'}, svg);
  const order = (state.guide?.robots || []).map(row => row.robot_id);
  const tint = id => `c${Math.max(0, order.indexOf(id)) % 3 + 1}`;
  const line = points => points.map(([x, y]) => state.view.toPx(x, y).join(',')).join(' ');
  for (const trip of state.open.filter(item => item.map_version === state.active.version && item.plan)) {
    for (const points of planPolylines(map, trip.plan))
      el('polyline', {class: `trip-line ${tint(trip.robot_id)}`, 'data-trip-robot': trip.robot_id, points: line(points)}, layer);
    const next = map.places.find(place => place.id === trip.next_place);
    if (next) {
      const [px, py] = state.view.toPx(next.x, next.y);
      el('circle', {class: `next-place ${tint(trip.robot_id)}`, cx: px, cy: py, r: 14}, layer);
    }
  }
  const toPoint = (x, y) => { const [px, py] = state.view.toPx(x, y); return {x: px, y: py}; };
  for (const {row, p, r, ring, alert, tip} of guideMarks(state.guide, toPoint)) {
    const g = el('g', {class: `robot ${tint(row.robot_id)} ${row.pose.state.toLowerCase()}${row.online ? '' : ' offline'}`,
      'data-robot': row.robot_id, ...(alert ? {'data-alert': alert} : {})}, layer);
    el('circle', {class: 'robot-ring', cx: p.x, cy: p.y, r: ring}, g);
    el('circle', {class: 'robot-body', cx: p.x, cy: p.y, r}, g);
    if (tip) {
      el('line', {class: 'robot-heading', x1: p.x, y1: p.y, x2: tip.x, y2: tip.y}, g);
      const deg = Math.atan2(tip.y - p.y, tip.x - p.x) * 180 / Math.PI;
      el('polygon', {class: 'robot-tip', points: '2,0 -7,-5 -7,5', transform: `translate(${tip.x} ${tip.y}) rotate(${deg})`}, g);
    }
    const label = el('text', {class: 'robot-label', x: p.x, y: p.y - ring - 6}, g);
    label.textContent = poseLabel(row);
    const half = label.getComputedTextLength() / 2 + 4;  // keep the whole label on the map
    label.setAttribute('x', Math.min(Math.max(p.x, half), W - half));
    if (p.y - ring - 6 < 16) label.setAttribute('y', p.y + ring + 16);
  }
}

function select(selection) {
  state.selected = selection;
  const map = state.working;
  const place = selection?.place && map?.places.find(item => item.id === selection.place);
  const edge = selection?.edge && map?.edges.find(item => item.id === selection.edge);
  const crosswalk = selection?.crosswalk && (map?.crosswalks || []).find(item => item.id === selection.crosswalk);
  const reason = operatorReason() || ($('map-source').value === 'profile' ? '지도 설정은 규칙 JSON으로 고치거나 초안으로 불러오세요' : '');
  $('place-form').hidden = !place || Boolean(reason);
  $('edge-form').hidden = !edge || Boolean(reason);
  $('crosswalk-form').hidden = !crosswalk || Boolean(reason);
  if (!crosswalk) state.band = null;
  gate('apply-edit', reason || (place || edge ? '' : '초안 보기에서 장소나 차로를 고르세요'));
  if (place) {
    $('selection').textContent = `장소 ${place.id}`;
    $('place-name').value = place.name;
    $('place-kind').value = place.kind;
  } else if (crosswalk) {
    $('selection').textContent = `횡단보도 ${crosswalk.id} · 대기 띠 ${(crosswalk.approach || []).length}개`;
    $('crosswalk-lanes').textContent = `덮는 차로 ${(crosswalk.lanes || []).join(', ') || '저장할 때 계산합니다'} · 출처 ${crosswalk.revision}`;
    $('crosswalk-band').replaceChildren(...(crosswalk.approach || []).map((band, index) =>
      new Option(`띠 ${index + 1} · 점 ${band.length}개`, String(index))));
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
  authoring.sync();
  cameraMap.sync();
  survey.sync();
  const reason = operatorReason();
  sourcePanel.sync();
  gate('map-view-turn', reason || ($('map-source').value === 'profile' ? '지도 설정을 초안으로 불러오세요' : '') || (!state.working ? '고칠 지도가 없습니다' : ''));
  gate('save-draft', reason || (!state.working ? '고칠 지도가 없습니다' : (state.dirty ? '' : '고친 내용이 없습니다')));
  const crosswalk = state.selected?.crosswalk;
  const bands = (state.working?.crosswalks || []).find(item => item.id === crosswalk)?.approach || [];
  $('site-map-svg').classList.toggle('drawing', state.band !== null);
  gate('band-draw', reason || (!crosswalk ? '횡단보도를 고르세요' : state.band !== null ? '띠를 그리는 중입니다' : bands.length >= 4 ? '대기 띠는 4개까지입니다' : ''));
  gate('band-finish', reason || (state.band === null ? '대기 띠 그리기를 먼저 누르세요' : state.band.length < 3 ? '지도에서 점을 세 개 이상 찍으세요' : ''));
  gate('band-delete', reason || (!bands.length ? '지울 대기 띠가 없습니다' : ''));
  gate('import-crosswalks', reason || (!state.working ? '고칠 지도가 없습니다' : ''));
  gate('activate', reason || (!state.draft?.revision ? '저장된 초안이 없습니다' : (state.dirty ? '고친 내용을 먼저 저장하세요' : '')));
  status('draft-status', state.loadState === 'pending' ? '초안 조회 중'
    : state.loadState === 'error' ? '초안 확인 불가 · 다시 접속하세요'
    : state.loadState === 'idle' ? '관제 접속 필요'
    : state.draft?.revision
      ? `저장된 초안${state.draft.saved_by ? ` · ${state.draft.saved_by}` : ''}${state.dirty ? ' · 고친 내용 저장 필요' : ''}`
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
  const poseReason = state.guideUnavailable ? '현장 지도 위치 확인 불가' : tripPoseReason(state.guide, tripRobot.value,
    state.active, robotMapPose(state.robots.find(robot => robot.robot_id === tripRobot.value)));
  gate('trip-plan', inspecting || reason || (!state.active ? '활성 지도가 없습니다' : robotReason || poseReason || (target ? '' : '목적지를 고르세요')));
  gate('trip-pick', reason);
  teach.sync();
}

// D-540 4: one read line and the robot layer; operating a trip is the 관제 card's (D-540 3).
async function pollRobots() {
  if (state.loadState === 'ready') {
    try {
      state.open = (await request('/api/fleet/trips')).open || [];
      status('trip-run', state.open.length ? `이 지도로 운행 중 · ${state.open.map(trip => tripStatusText(trip, state.active?.map)).join(' / ')}`
        : '진행 중인 운행 없음', state.open.length ? 'pending' : 'empty');
    } catch (error) {
      status('trip-run', `운행 상태 확인 불가 · ${siteMapErrorText(error)}`, 'error');
    }
    try { state.guide = await request('/api/fleet/guide'); state.guideUnavailable = false; }
    catch (error) { state.guide = null; state.guideUnavailable = error.status !== 404; }
    drawRobots();
    syncButtons();
  }
  setTimeout(pollRobots, ROBOT_POLL_MS);
}
pollRobots();

async function load() {
  state.planEpoch += 1;
  let active = null;
  try { active = await request('/api/fleet/site-map/active'); } catch (error) {
    if (error.status !== 404) throw error;
  }
  const draft = await request('/api/fleet/site-map/draft');
  await loadProfiles();
  let robots = [];
  state.robotsError = false;
  try { robots = (await request('/api/fleet/state')).robots || []; } catch (error) {
    if (error.status === 401 || error.status === 403) throw error;
    state.robotsError = true;
  }
  state.active = active;
  state.robots = robots;
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

async function connect(credentialChange = false) {
  if ($('token-save').disabled) return;
  const localEdit = state.dirty || state.band !== null || state.selected ? {working: state.working,
    draft: state.draft, selected: state.selected, band: state.band, dirty: state.dirty} : null;
  const editFields = [...document.querySelectorAll(
    '[aria-labelledby="edit-heading"] input:not([type="file"]), [aria-labelledby="edit-heading"] select, '
    + '[aria-labelledby="edit-heading"] textarea')].map(field => ({field, value: field.value, checked: field.checked}));
  state.sessionEpoch = (state.sessionEpoch || 0) + 1;
  sourcePanel.reset(); calibrations = [];
  gate('token-save', '접속 중');
  const started = Date.now();
  const ticker = setInterval(() => notice(`접속 중 · ${Math.floor((Date.now() - started) / 1000)}초 경과`), 1000);
  state.role = null;
  state.loadState = 'pending';
  state.planEpoch += 1;
  state.robotsError = false;
  state.active = state.draft = state.working = state.selected = state.plan = state.point = state.guide = state.band = null;
  state.open = [];
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
    showSession(session, {credentialChange});
    loginForm.refresh(false);
    syncButtons();
    await load();
    if (localEdit) {
      // Keep the original revision: a changed server draft must fail CAS, never overwrite unseen edits.
      Object.assign(state, localEdit);
      render(); select(state.selected); syncButtons();
    }
    notice(localEdit ? '재접속 확인 · 편집 중인 초안을 보존했습니다. 저장 전 최신 서버 초안과 비교하세요.'
      : state.robotsError ? '지도를 읽었습니다 · 로봇 상태 확인 불가. 다시 접속하세요.'
      : !state.active && !state.working ? '활성 지도와 초안이 없습니다. 지도 만들기에서 기준을 정하거나 저장된 지도 설정을 불러오세요.'
      : !state.active ? '활성 지도는 없습니다. 초안을 확인하고 활성화하세요.' : '지도를 읽었습니다.');
  } catch (error) {
    if (localEdit) Object.assign(state, localEdit);
    state.loadState = error.status === 401 ? 'idle' : 'error';
    if (error.status === 401 || error.status === 403) {
      state.role = null;
      showSignedOut();
    }
    if (error.status === 401 || error.code === 'PASSWORD_CHANGE_REQUIRED') loginForm.refresh(true);
    render();
    if (localEdit) select(state.selected);
    syncButtons();
    notice(siteMapErrorText(error));
  } finally {
    for (const {field, value, checked} of editFields) { field.value = value; field.checked = checked; }
    clearInterval(ticker);
    gate('token-save', '');
  }
}
$('token-save').addEventListener('click', () => connect(true));

$('profile-save').addEventListener('click', () => guarded(async () => {
  if (operatorReason()) return;
  const id = $('profile-id').value;
  const current = sourcePanel.profile(id);
  const row = await request(`/api/fleet/site-map/profiles/${encodeURIComponent(id)}`, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: $('profile-name').value.trim(), map: JSON.parse($('profile-rules').value), ...sourcePanel.profileInfo(),
      expected_revision: current?.revision || null})});
  await loadProfiles(id);
  sourcePanel.profileInputs(row.map, id, row.name, row);
  $('map-source').value = 'profile';
  updatePlaneSources(); select(null);
  $('profile-status').textContent = '지도 설정을 저장했습니다. 활성 지도는 그대로입니다.';
}));
$('profile-draft').addEventListener('click', () => guarded(async () => {
  if (operatorReason() || !selectedProfile() || selectedProfile().kind === 'soccer') return;
  if (state.dirty || state.draft?.revision) {
    const allowed = await confirmIrreversible({message: '기존 초안을 선택한 지도 설정으로 바꿀까요?',
      action: '지도 설정을 초안으로', opener: $('profile-draft')});
    if (!allowed) return;
  }
  await request('/api/fleet/site-map/draft', {method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({map: selectedProfile().map, expected_revision: state.draft?.revision || null})});
  await load(); $('map-source').value = 'draft'; clearPlan(); updatePlaneSources(); render();
  notice('지도 설정을 초안으로 불러왔습니다. 운행에 쓰려면 초안을 확인한 뒤 활성화하세요.');
}));

function clearPlan() {
  state.planEpoch += 1;
  state.plan = null;
  status('trip-summary', '계산 전 · 실행은 하지 않습니다', 'empty');
  $('trip-actions').replaceChildren();
  render();
  syncButtons();
}

$('site-map-svg').addEventListener('click', event => {
  if (survey.pick(event)) return;
  if (sourcePanel.pick(event)) return;
  if ($('trip-pick').checked && $('map-source').value === 'active' && state.view) {
    const svg = event.currentTarget;
    const at = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    const [x, y] = state.view.toMap(at.x, at.y);
    state.point = {x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000};
    $('trip-point').textContent = `찍은 좌표 x ${state.point.x} m, y ${state.point.y} m`;
    clearPlan();
    return;
  }
  if (state.band !== null && state.view) {  // D-573: drawing a waiting band on the draft
    const at = new DOMPoint(event.clientX, event.clientY).matrixTransform(event.currentTarget.getScreenCTM().inverse());
    state.band.push(state.view.toMap(at.x, at.y));
    render(); syncButtons();
    return;
  }
  const target = event.target.closest('[data-place], [data-edge], [data-crosswalk]');
  if (!target) return;
  select(target.dataset.place ? {place: target.dataset.place}
    : target.dataset.crosswalk ? {crosswalk: target.dataset.crosswalk} : {edge: target.dataset.edge});
  syncButtons();
});

// D-573 1/7: waiting bands are drawn on the draft; the polygon itself is lane_graph's.
$('band-draw').addEventListener('click', () => {
  state.band = [];
  $('map-source').value = 'draft';
  render(); syncButtons();
  notice('지도에서 대기 띠의 꼭짓점을 차례로 찍고 띠 닫기를 누르세요.');
});
$('band-finish').addEventListener('click', () => guarded(async () => {
  const sel = state.selected;
  state.working = addApproach(state.working, sel.crosswalk, state.band);
  state.band = null;
  state.dirty = true;
  select(sel);
  notice('대기 띠를 초안에 넣었습니다. 저장할 때 차로에 닿는지, 바닥 안인지 확인합니다.');
}));
$('band-delete').addEventListener('click', () => guarded(async () => {
  const sel = state.selected;
  state.working = removeApproach(state.working, sel.crosswalk, Number($('crosswalk-band').value || 0));
  state.dirty = true;
  $('map-source').value = 'draft';
  select(sel);
  notice('대기 띠를 초안에서 지웠습니다. 저장해야 남습니다.');
}));
$('import-crosswalks').addEventListener('click', () => guarded(async () => {
  const got = await request('/api/fleet/site-map/lane-graph-crosswalks');
  state.working = mergeCrosswalks(state.working, got.crosswalks || []);
  state.dirty = true;
  $('map-source').value = 'draft';
  select(null);
  notice(`${got.source}에서 횡단보도 ${(got.crosswalks || []).length}개를 초안에 넣었습니다. 그린 대기 띠는 그대로 둡니다. 저장해야 남습니다.`);
}));

$('trip-pick').addEventListener('change', () => {
  $('site-map-svg').classList.toggle('picking', $('trip-pick').checked);
  if ($('trip-pick').checked) $('map-source').value = 'active';  // trips plan on the active map
  clearPlan();
});
$('trip-place').addEventListener('change', clearPlan);
$('trip-robot').addEventListener('change', clearPlan);

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
  syncButtons();
  if ($('trip-plan').disabled) return;
  const epoch = ++state.planEpoch;
  const to = $('trip-pick').checked ? state.point : $('trip-place').value;
  state.plan = null;
  try {
    const plan = await planTrip(request, $('trip-robot').value, {to});
    if (epoch !== state.planEpoch) return;
    state.plan = plan;
  } catch (error) {
    if (epoch !== state.planEpoch) return;
    status('trip-summary', tripRefusalText(error), 'error');
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
  status('trip-summary', `${planSummaryText(plan)} · 실행하지 않음`, 'ready');
  $('trip-actions').replaceChildren(...actionRows(plan, state.active.map).map(text => {
    const row = document.createElement('li');
    row.textContent = text;
    return row;
  }));
  $('map-source').value = 'active';
  render();
}));

bindEstop(request);
bindTopbarToggle();
tickClock();
setInterval(tickClock, 1000);
watchFleet(request);
const screens = bindScreens({nav: document.querySelector('.ui-subnav-nav'), home: 'map-heading', stage: 'map-heading',
  groups: {'survey-heading': ['survey-heading', 'drawing-heading']}});
// The map legend promises that picking a place or lane on the view screen opens it for editing.
$('site-map-svg').addEventListener('click', event => {
  if (screens.current() === 'map-heading' && event.target.closest('[data-place], [data-edge], [data-crosswalk]')) location.hash = '#edit-heading';
});
$('console-token').addEventListener('keydown', event => { if (event.key === 'Enter') $('token-save').click(); });

developmentToken($('console-token').value).then(token => {
  if (token) { $('console-token').value = token; connect(); }
  // D-540 2 — a stored token (another Fleet tab) or a login cookie connects at once; neither means signed out.
  else loginForm.refresh(true).then(cookie => {
    if (cookie || stored) connect();
    else if (!state.role && state.loadState === 'idle') showSignedOut();  // not if someone connected meanwhile
  });
}).catch(() => {});
// D-519 — login and logout change the cookie; drop any token so the cookie (or a 401) decides.
const loginForm = createPasswordLogin($('password-login'), {onChange: () => {
  $('console-token').value = ''; connect(true);
}});
