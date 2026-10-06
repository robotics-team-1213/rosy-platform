// D-484 M1 site map page: view the active map or the draft, edit the draft, activate it,
// and preview a D-486 trip plan. Nothing here moves a robot.
import {createFleetClient} from '/common/fleet-client.js';
import {confirmIrreversible} from '/common/ui.js';
import {
  ACTION_LABEL, PLACE_KINDS, PLACE_KIND_LABEL, arrowMarks, editEdge, editPlace, fitView,
  planPolylines, tripErrorText,
} from '/console/assets/site-map-model.js';

const $ = id => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
const W = 800, H = 480;

$('credential').value = sessionStorage.getItem('rosy-console-token') || '';
const request = createFleetClient({credential: () => $('credential').value, origin: location.origin});
const state = {active: null, draft: null, working: null, dirty: false, selected: null, plan: null, point: null};

for (const kind of PLACE_KINDS) $('place-kind').append(new Option(PLACE_KIND_LABEL[kind], kind));

function notice(text) { $('notice').textContent = text; }
function status(id, text, kind) { $(id).textContent = text; $(id).setAttribute('state', kind); }
function shown() { return $('map-source').value === 'draft' ? state.working : state.active?.map; }

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
  status('map-status', $('map-source').value === 'draft'
    ? (state.working ? `초안${state.dirty ? ' · 저장 안 됨' : ''}` : '초안 없음')
    : (state.active ? `활성 지도 v${state.active.version} · ${state.active.activated_by}` : '활성 지도 없음'),
  map ? 'ready' : 'empty');
  if (!map) return;
  const view = fitView(map, W, H);
  state.view = view;
  const line = points => points.map(([x, y]) => view.toPx(x, y).join(',')).join(' ');
  for (const edge of map.edges) {
    const path = el('polyline', {points: line(edge.polyline), 'data-edge': edge.id,
      class: `edge ${edge.drive_mode}${state.selected?.edge === edge.id ? ' selected' : ''}`}, svg);
    el('title', {}, path).textContent = `${edge.id} · ${edge.direction === 'two_way' ? '양방' : '일방'} · ${edge.speed_cap_mps} m/s`;
    for (const mark of arrowMarks(edge)) {
      const [px, py] = view.toPx(mark.x, mark.y);
      el('polygon', {class: 'arrow', points: '8,0 -6,-6 -6,6',
        transform: `translate(${px} ${py}) rotate(${-mark.angle * 180 / Math.PI})`}, svg);
    }
  }
  if ($('map-source').value === 'active' && state.plan) {
    for (const points of planPolylines(map, state.plan)) el('polyline', {class: 'plan', points: line(points)}, svg);
  }
  for (const place of map.places) {
    const [px, py] = view.toPx(place.x, place.y);
    const dot = el('circle', {cx: px, cy: py, r: 9, 'data-place': place.id,
      class: `place ${place.kind}${state.selected?.place === place.id ? ' selected' : ''}`}, svg);
    el('title', {}, dot).textContent = `${place.name} (${PLACE_KIND_LABEL[place.kind] || place.kind})`;
    el('text', {x: px + 12, y: py - 10, class: 'label'}, svg).textContent = place.name;
  }
  if (state.point && $('map-source').value === 'active') {
    const [px, py] = view.toPx(state.point.x, state.point.y);
    el('circle', {cx: px, cy: py, r: 6, class: 'target'}, svg);
  }
}

function select(selection) {
  state.selected = selection;
  const map = state.working;
  const place = selection?.place && map?.places.find(item => item.id === selection.place);
  const edge = selection?.edge && map?.edges.find(item => item.id === selection.edge);
  $('place-form').hidden = !place;
  $('edge-form').hidden = !edge;
  $('apply-edit').disabled = !(place || edge);
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
  $('save-draft').disabled = !state.working || !state.dirty;
  $('activate').disabled = !state.draft?.revision || state.dirty;
  status('draft-status', state.draft?.revision
    ? `저장된 초안 · ${state.draft.saved_by}${state.dirty ? ' · 고친 내용 저장 필요' : ''}`
    : (state.dirty ? '저장 안 된 초안' : '저장된 초안 없음'), state.draft?.revision ? 'ready' : 'empty');
  $('trip-plan').disabled = !state.active || !$('trip-robot').value
    || !($('trip-pick').checked ? state.point : $('trip-place').value);
}

async function load() {
  try { state.active = await request('/api/fleet/site-map/active'); } catch (error) {
    if (error.status !== 404) throw error;
    state.active = null;
  }
  state.draft = await request('/api/fleet/site-map/draft');
  state.working = state.draft.map ? state.draft.map
    : (state.active ? JSON.parse(JSON.stringify(state.active.map)) : null);
  state.dirty = false;
  $('trip-place').replaceChildren(...(state.active?.map.places || [])
    .map(place => new Option(`${place.name} (${place.id})`, place.id)));
  const robots = (await request('/api/fleet/state')).robots || [];
  $('trip-robot').replaceChildren(...robots.map(robot => new Option(robot.robot_id, robot.robot_id)));
  select(null);
  syncButtons();
}

async function guarded(work) {
  try { await work(); } catch (error) { notice(error.message || String(error)); }
  syncButtons();
}

$('connect').addEventListener('click', () => guarded(async () => {
  sessionStorage.setItem('rosy-console-token', $('credential').value);
  const session = await request('/api/fleet/session');
  $('session').textContent = `${session.principal_id} · ${session.role}`;
  await load();
  notice('지도를 읽었습니다.');
}));

$('map-source').addEventListener('change', () => render());

$('site-map-svg').addEventListener('click', event => {
  if ($('trip-pick').checked && $('map-source').value === 'active' && state.view) {
    const svg = event.currentTarget;
    const at = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    const [x, y] = state.view.toMap(at.x, at.y);
    state.point = {x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000};
    $('trip-point').textContent = `찍은 좌표 x ${state.point.x} m, y ${state.point.y} m`;
    render();
    syncButtons();
    return;
  }
  const target = event.target.closest('[data-place], [data-edge]');
  if (!target) return;
  select(target.dataset.place ? {place: target.dataset.place} : {edge: target.dataset.edge});
});

$('trip-pick').addEventListener('change', () => {
  $('site-map-svg').classList.toggle('picking', $('trip-pick').checked);
  if ($('trip-pick').checked) $('map-source').value = 'active';  // trips plan on the active map
  render();
  syncButtons();
});
$('trip-place').addEventListener('change', syncButtons);
$('trip-robot').addEventListener('change', syncButtons);

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
  const to = $('trip-pick').checked ? state.point : $('trip-place').value;
  state.plan = null;
  try {
    state.plan = await request(`/api/fleet/robots/${encodeURIComponent($('trip-robot').value)}/trip`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({to})});
  } catch (error) {
    status('trip-summary', error.code ? tripErrorText(error.code, error.detail) : error.message, 'error');
    $('trip-actions').replaceChildren();
    render();
    return;
  }
  const plan = state.plan;
  status('trip-summary', `${plan.segments.length}개 차로 · ${plan.length_m.toFixed(2)} m · 약 ${Math.round(plan.eta_s)} s`
    + ` · 지도 v${plan.map_version} · 실행하지 않음`, 'ready');
  $('trip-actions').replaceChildren(...plan.actions.map(item => {
    const row = document.createElement('li');
    row.textContent = `${item.place_id || '찍은 좌표'} · ${ACTION_LABEL[item.action] || item.action}`;
    return row;
  }));
  $('map-source').value = 'active';
  render();
}));

$('estop').addEventListener('click', async () => {
  const feedback = $('estop-feedback');
  feedback.hidden = false;
  try {
    const result = await request('/api/fleet/estop', {method: 'POST'});
    feedback.textContent = `정지 요청 응답: ${result.stopped}/${result.total} · 물리 정지 미확인`;
    feedback.setAttribute('state', 'warning');
  } catch (error) {
    feedback.textContent = `비상 정지 결과 확인 불가 — ${error.message}`;
    feedback.setAttribute('state', 'error');
  }
});
