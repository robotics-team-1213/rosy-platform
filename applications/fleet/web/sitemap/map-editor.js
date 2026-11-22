import { setOffBy } from "/common/cause-line.js";
import {randomUUID} from "/console/assets/uuid.js";
// Fleet adapter: generic point edits enter the existing draft validators here.
import {appendSurveyElement, editSurveyElement, removeSurveyElement} from '/console/assets/site-map-edit.js';
import {replaceVertex, removeVertex, mapPoint, nearestVertex} from '/console/assets/geometry-edit.js';
import {splitRoad, joinRoads} from '/console/assets/map-topology.js';

const $ = id => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
export function svgElement(name, attrs, parent) {
  const doc = parent?.ownerDocument || document;
  const node = doc.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  parent.append(node);
  return node;
}

const finitePose = (pose) => Boolean(pose && Number.isFinite(pose.x) && Number.isFinite(pose.y));

export function drawSitePointsOverlay(svg, sitePoints, view) {
  svg.querySelector('#site-points-layer')?.remove();
  if (!sitePoints || !view) return;
  const layer = svgElement('g', {id: 'site-points-layer'}, svg);
  const lineOf = pts => pts.map(([x, y]) => view.toPx(x, y).join(',')).join(' ');
  const wp = sitePoints.coordinate_frames?.vehicle_world?.waypoints || {};
  const stopsById = Object.fromEntries((sitePoints.vehicle_stops || []).map(s => [s.id, s]));

  // Planned S3 intake approach chain
  const s3Stop = stopsById.S3;
  const s3App = s3Stop?.berth?.approach_pose || wp.S3_intake?.planned_approach_ref_m;
  if (finitePose(wp.S3_intake?.pose) && finitePose(s3App)) {
    svgElement('polyline', {class: 'sp-planned-link', points: lineOf([[s3App.x, s3App.y], [wp.S3_intake.pose.x, wp.S3_intake.pose.y]])}, layer);
    if (!s3Stop?.berth?.nav2_berth_ready) {
      const [ax, ay] = view.toPx(s3App.x, s3App.y);
      svgElement('polygon', {class: 'sp-planned-stop', points: `${ax},${ay - 6} ${ax + 6},${ay} ${ax},${ay + 6} ${ax - 6},${ay}`}, layer);
      svgElement('text', {class: 'sp-label', x: ax + 8, y: ay - 6}, layer).textContent = 'S3_app(예정)';
    }
  }

  // Outbound branch chain: J_stand -> S_OUT_app -> S_OUT
  const jPose = wp.J_stand_branch?.pose;
  const outApp = wp.S_OUT_outbound?.planned_approach_ref_m;
  const outPose = wp.S_OUT_outbound?.pose || wp.S_OUT_outbound?.ceiling_ref_m;
  if (finitePose(jPose) && finitePose(outPose)) {
    const chain = finitePose(outApp) ? [[jPose.x, jPose.y], [outApp.x, outApp.y], [outPose.x, outPose.y]]
      : [[jPose.x, jPose.y], [outPose.x, outPose.y]];
    svgElement('polyline', {class: 'sp-planned-link', points: lineOf(chain)}, layer);
    if (wp.J_stand_branch?.planned) {
      const [jx, jy] = view.toPx(jPose.x, jPose.y);
      svgElement('polygon', {class: 'sp-planned-stop', points: `${jx},${jy - 5} ${jx + 5},${jy} ${jx},${jy + 5} ${jx - 5},${jy}`}, layer);
      svgElement('text', {class: 'sp-label', x: jx - 40, y: jy + 14}, layer).textContent = 'J_stand';
    }
    if (!wp.S_OUT_outbound?.in_active_map) {
      const [ox, oy] = view.toPx(outPose.x, outPose.y);
      svgElement('circle', {class: 'sp-planned-stop', cx: ox, cy: oy, r: 6}, layer);
      svgElement('text', {class: 'sp-label', x: ox + 9, y: oy + 4}, layer).textContent = 'S_OUT(예정)';
    }
  }

  // Stop role tags for verified intake/pickup stops
  const roleTag = (id, stop) => {
    if (id === 'S1') return wp.S1_pickup?.dual_role_exit_place ? '수령·출구' : '수령';
    if (id === 'S3') return stop?.berth?.nav2_berth_ready ? '하역(접안)' : '하역(존미등록)';
    if (id === 'S_OUT') return stop?.in_active_map ? '반출' : null;
    return null;
  };
  for (const id of ['S1', 'S3', 'S_OUT']) {
    const stop = stopsById[id];
    const tag = roleTag(id, stop);
    if (tag && finitePose(stop?.pose)) {
      const [px, py] = view.toPx(stop.pose.x, stop.pose.y);
      svgElement('text', {class: 'sp-role-tag', x: px + 12, y: py + 12}, layer).textContent = `[${tag}]`;
    }
  }

  // Workcell reference marker (arm_s_base 180° / cell_ab_fixture -90° separated mm frames)
  const hint = sitePoints.coordinate_frames?.cell_s_arm_base?.world_origin_hint_m;
  if (Array.isArray(hint) && hint.length === 2 && Number.isFinite(hint[0]) && Number.isFinite(hint[1])) {
    const [cx, cy] = view.toPx(hint[0], hint[1]);
    const refDot = svgElement('polygon', {class: 'sp-cell-ref', points: `${cx},${cy - 6} ${cx + 6},${cy} ${cx},${cy + 6} ${cx - 6},${cy}`}, layer);
    svgElement('title', {}, refDot).textContent = 'arm_s(180°)·cell_ab(-90°) 독립 mm 원점 · vehicle_tray는 arm_s_top 호모그래피 보정(+12.85 cm 오차) 필요';
    svgElement('text', {class: 'sp-label', x: cx + 8, y: cy - 6}, layer).textContent = 'arm_s 180°·cell_ab -90°';
  }
}

export function renderSitePointsSummary(panelEl, bodyEl, sitePoints) {
  if (!panelEl || !bodyEl) return;
  if (!sitePoints) {
    panelEl.hidden = true;
    bodyEl.replaceChildren();
    return;
  }
  const doc = panelEl.ownerDocument || document;
  panelEl.hidden = false;
  const dl = doc.createElement('dl');
  dl.className = 'legend-terms';
  const zr = sitePoints.zone_rules || {};
  const lc = zr.layer_counts || {};
  const conv = sitePoints.conveyor_transfer || {};
  const rows = [
    ['3좌표계 축 변환', 'world_261026(m) · arm_s_base(180°, mm, tray X+12.85 cm 호모그래피) · cell_ab_fixture(-90°, mm, top.jpg 180°, s1=h2·s2=h1)'],
    ['컨베이어 브리지', `belt-in(x≥134 mm) → v24 스토퍼(x=${conv.out_point?.stop_x_mm ?? 158} mm) → belt-out · Handover/Occ 연결 ${conv.handover_state_machine?.wired_to_runtime ? '완료' : '전'} · D-429 제어 금지`],
    ['3단 37자리·재취급', `1층 ${lc.t1 ?? 13} + 2층 ${lc.t2 ?? 12} + 3층 ${lc.t3 ?? 12} = ${lc.total ?? 37}자리 · temp_a/b 각 9칸 LIFO · belt·stand 대피 금지`],
  ];
  for (const [k, v] of rows) {
    const dt = doc.createElement('dt');
    dt.textContent = k;
    const dd = doc.createElement('dd');
    dd.textContent = v;
    dl.append(dt, dd);
  }
  const ul = doc.createElement('ul');
  ul.className = 'sp-stage-list';
  for (const st of sitePoints.end_to_end_stages || []) {
    const li = doc.createElement('li');
    const gapText = (st.gaps || []).length ? st.gaps.join(' · ') : '준비됨';
    li.textContent = `${st.label || st.stage} (${st.runtime_status}): ${gapText}`;
    ul.append(li);
  }
  bodyEl.replaceChildren(dl, ul);
}

export async function loadSitePointsOverlay(request, active, panelEl, bodyEl) {
  let data = null;
  try { data = active ? await request('/api/fleet/site-points') : null; } catch { data = null; }
  renderSitePointsSummary(panelEl, bodyEl, data);
  return data;
}

export function drawFacilities(svg, map, view) {
  for (const facility of map.facilities || []) {
    const points = facility.geometry.map(([x, y]) => view.toPx(x, y));
    const attrs = {'data-facility': facility.id};
    const mark = facility.kind === 'exclusion'
      ? svgElement('polygon', {...attrs, points: points.map(p => p.join(',')).join(' '), class: 'facility exclusion'}, svg)
      : facility.kind === 'stop_line'
        ? svgElement('polyline', {...attrs, points: points.map(p => p.join(',')).join(' '), class: 'facility stop-line'}, svg)
        : svgElement('circle', {...attrs, cx: points[0][0], cy: points[0][1], r: 6, class: `facility ${facility.kind}`}, svg);
    svgElement('title', {}, mark).textContent = facility.name;
  }
}

export function createMapEditor({svg, map, view, changed, reason}) {
  let points = [], redo = [], selected = null, selectedVertex = 0, drag = null, suppressClick = false;
  let lastMapId = null;
  const enabled = () => $('editor-enabled').checked && !reason();
  const message = text => { $('editor-status').textContent = text; };
  const rows = () => [...(map()?.places || []).map(p => ({...p, key: 'places', geometry: [[p.x, p.y]]})),
    ...(map()?.edges || []).map(e => ({...e, key: 'edges', kind: 'road', geometry: e.polyline})),
    ...(map()?.facilities || []).map(f => ({...f, key: 'facilities'}))];
  const current = () => rows().find(row => row.key === selected?.key && row.id === selected?.id);
  const act = operation => {
    if (!enabled()) { message(reason() || '직접 편집을 먼저 켜세요'); return; }
    try { operation(); } catch (error) { message(error.message); }
  };
  const coordinate = event => {
    if ($('editor-snap').checked && $('editor-kind').value === 'road') {
      const candidates = [$('editor-from').value, $('editor-to').value]
        .filter((id, i, all) => all.indexOf(id) === i).map(id => map()?.places.find(p => p.id === id)).filter(Boolean);
      const screen = candidates.map(p => {
        const [x, y] = view().toPx(p.x, p.y);
        const at = new DOMPoint(x, y).matrixTransform(svg.getScreenCTM()); return [at.x, at.y];
      });
      const index = nearestVertex([event.clientX, event.clientY], screen);
      if (index !== null) return [candidates[index].x, candidates[index].y];
    }
    return mapPoint(svg, view(), new DOMPoint(event.clientX, event.clientY));
  };
  const item = (row, geometry) => ({...row, name: row.name || (row.kind === 'road' ? '' : row.id), geometry});
  const changedGeometry = geometry => {
    const row = current();
    if (row) changed(editSurveyElement(map(), item(row, geometry)));
  };
  function addPoint(value) {
    if (!value.every(v => Number.isFinite(v) && Math.abs(v) <= 1000)) throw new Error('지도 좌표 범위는 -1000~1000 m입니다');
    const kind = $('editor-kind').value;
    if (kind === 'select') throw new Error('그릴 요소 종류를 먼저 고르세요');
    if (points.length >= 32) throw new Error('요소의 꼭짓점은 최대 32개입니다');
    const pt = [Math.round(value[0] * 1000) / 1000, Math.round(value[1] * 1000) / 1000];
    if (points.length && Math.hypot(points.at(-1)[0] - pt[0], points.at(-1)[1] - pt[1]) < 0.005) return;
    points.push(pt); redo = [];
    if (kind === 'park') finish();
    else {
      sync();
      message(`점 ${points.length}개 찍음 (${pt[0]}, ${pt[1]} m) — 계속 찍거나 [그리기 완료] / Enter / 더블클릭으로 완성하세요`);
    }
  }
  function finish() {
    const kind = $('editor-kind').value;
    const id = `e_${randomUUID().replaceAll('-', '').slice(0, 12)}`;
    const rawName = $('editor-name').value.trim();
    const defaultName = (!rawName || rawName === '새 요소')
      ? (kind === 'park' ? `장소 ${(map()?.places?.length || 0) + 1}`
        : kind === 'road' ? `도로 ${(map()?.edges?.length || 0) + 1}`
        : `구역 ${(map()?.facilities?.length || 0) + 1}`)
      : rawName;
    const element = {id, kind, name: defaultName, geometry: points,
      from: $('editor-from').value, to: $('editor-to').value,
      width_m: Number($('editor-width').value), direction: $('editor-direction').value};
    const next = appendSurveyElement(map(), element);
    selected = {key: kind === 'road' ? 'edges' : kind === 'park' ? 'places' : 'facilities', id};
    selectedVertex = 0; points = []; redo = [];
    changed(next);
    message('초안에 그렸습니다. [초안 저장]을 누르면 서버 초안에 저장됩니다');
  }
  function cancel() { points = []; redo = []; drag = null; selected = null; sync(); }
  function erase(vertexOnly = false) {
    const row = current();
    if (!row) throw new Error('삭제할 요소를 고르세요');
    if (vertexOnly && row.key !== 'places') {
      if (row.kind === 'road' && (selectedVertex === 0 || selectedVertex === row.geometry.length - 1))
        throw new Error('도로 끝점은 장소와 연결됩니다. 장소를 수정하세요');
      const geometry = removeVertex(row.geometry, selectedVertex, row.kind === 'exclusion' ? 3 : 2);
      selectedVertex = Math.min(selectedVertex, geometry.length - 1);
      changedGeometry(geometry);
    } else {
      const next = removeSurveyElement(map(), row.id, row.key);
      selected = null; changed(next);
    }
  }
  const options = (id, entries) => {
    const field = $(id), value = field.value, signature = JSON.stringify(entries);
    if (field.dataset.options === signature) return;
    field.dataset.options = signature;
    field.replaceChildren(...entries.map(([key, label]) => new Option(label, key)));
    if ([...field.options].some(option => option.value === value)) field.value = value;
  };
  function sync() {
    const siteMap = map();
    if (lastMapId !== siteMap?.map_id) {
      points = []; redo = []; selected = null; drag = null; lastMapId = siteMap?.map_id;
    }
    svg.querySelector('#editor-layer')?.remove();
    options('editor-from', (siteMap?.places || []).map(p => [p.id, p.name]));
    options('editor-to', (siteMap?.places || []).map(p => [p.id, p.name]));
    if ($('editor-from').value && $('editor-to').value === $('editor-from').value && (siteMap?.places?.length || 0) > 1) {
      $('editor-to').value = siteMap.places.find(p => p.id !== $('editor-from').value)?.id || $('editor-to').value;
    }
    options('editor-element', [['', '요소 선택'], ...rows().map(r => [`${r.key}:${r.id}`, r.name || r.id])]);
    options('editor-join-target', [['', '연결할 다음 도로'], ...(siteMap?.edges || [])
      .filter(e => e.id !== selected?.id).map(e => [e.id, e.name || e.id])]);
    $('editor-element').value = selected ? `${selected.key}:${selected.id}` : '';
    const blocked = reason() || (!$('editor-enabled').checked ? '직접 편집을 먼저 켜세요' : '');
    for (const id of ['editor-finish', 'editor-add-point', 'editor-apply', 'editor-delete', 'editor-delete-vertex',
      'editor-split', 'editor-join']) {
      setOffBy($(id), blocked);
    }
    svg.setAttribute('tabindex', '0');
    const row = current();
    options('editor-vertex', (row?.geometry || []).map((_, i) => [String(i), `꼭짓점 ${i + 1}`]));
    $('editor-vertex').value = String(selectedVertex);
    if (!enabled() || !view()) { if (blocked) message(blocked); return; }
    const layer = svgElement('g', {id: 'editor-layer'}, svg);
    if (points.length) svgElement('polyline', {class: 'editor-preview',
      points: points.map(p => view().toPx(...p).join(',')).join(' ')}, layer);
    if (row) for (const [index, point] of row.geometry.entries()) {
      const [cx, cy] = view().toPx(...point);
      svgElement('circle', {cx, cy, r: 7, class: 'editor-vertex', 'data-editor-vertex': index,
        'aria-label': `꼭짓점 ${index + 1}`}, layer);
    }
    const point = row?.geometry[selectedVertex];
    if (point && !drag) { $('editor-x').value = point[0]; $('editor-y').value = point[1]; }
    if (reason()) message(reason());
  }
  function click(event) {
    if (!enabled()) return;
    event.stopImmediatePropagation();
    if (suppressClick) { suppressClick = false; return; }
    act(() => {
      if ($('editor-kind').value !== 'select') { selected = null; addPoint(coordinate(event)); return; }
      const target = event.target.closest('[data-place], [data-edge], [data-facility]');
      if (target) {
        selected = target.dataset.place ? {key: 'places', id: target.dataset.place}
          : target.dataset.edge ? {key: 'edges', id: target.dataset.edge} : {key: 'facilities', id: target.dataset.facility};
        selectedVertex = 0; sync();
        $('editor-name').value = current()?.name || '';
      }
    });
  }
  function down(event) {
    const handle = event.target.closest('[data-editor-vertex]');
    if (!enabled() || !handle || !current()) return;
    event.preventDefault(); event.stopPropagation();
    selectedVertex = Number(handle.dataset.editorVertex);
    drag = {pointer: event.pointerId, x: event.clientX, y: event.clientY, value: null, handle};
    svg.setPointerCapture(event.pointerId);
  }
  function move(event) {
    if (!drag || event.pointerId !== drag.pointer) return;
    act(() => {
      if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 3) return;
      drag.value = coordinate(event);
      const [cx, cy] = view().toPx(...drag.value);
      drag.handle.setAttribute('cx', cx); drag.handle.setAttribute('cy', cy);
    });
  }
  function up(event) {
    if (!drag || event.pointerId !== drag.pointer) return;
    const value = drag.value; drag = null; suppressClick = true;
    if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    act(() => { if (value && current()) changedGeometry(replaceVertex(current().geometry, selectedVertex, value)); });
    sync();
  }
  function key(event) {
    if (!enabled() || event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
    if (event.key === 'Escape') { event.preventDefault(); cancel(); }
    else if (event.key === 'Enter' && points.length) { event.preventDefault(); act(finish); }
    else if (event.key === 'Delete') { event.preventDefault(); act(() => erase(true)); }
    else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && (points.length || redo.length)) {
      event.preventDefault(); event.stopImmediatePropagation();
      if (event.shiftKey) { if (redo.length) points.push(redo.pop()); }
      else if (points.length) redo.push(points.pop());
      sync();
    }
  }
  $('editor-kind').addEventListener('change', cancel);
  $('editor-finish').addEventListener('click', () => act(finish));
  $('editor-cancel').addEventListener('click', cancel);
  $('editor-add-point').addEventListener('click', () => act(() => addPoint([Number($('editor-x').value), Number($('editor-y').value)])));
  $('editor-apply').addEventListener('click', () => act(() => {
    const row = current();
    if (!row) throw new Error('수정할 요소를 고르세요');
    const value = [Number($('editor-x').value), Number($('editor-y').value)];
    changed(editSurveyElement(map(), {...item(row, replaceVertex(row.geometry, selectedVertex, value)), name: $('editor-name').value}));
  }));
  $('editor-element').addEventListener('change', () => {
    const [key, id] = $('editor-element').value.split(':'); selected = id ? {key, id} : null;
    selectedVertex = 0; $('editor-name').value = current()?.name || ''; sync();
  });
  $('editor-vertex').addEventListener('change', () => { selectedVertex = Number($('editor-vertex').value); sync(); });
  $('editor-delete').addEventListener('click', () => act(() => erase()));
  $('editor-delete-vertex').addEventListener('click', () => act(() => erase(true)));
  $('editor-split').addEventListener('click', () => act(() => {
    const row = current();
    if (row?.kind !== 'road') throw new Error('분할할 도로를 고르세요');
    const id = () => `e_${randomUUID().replaceAll('-', '').slice(0, 12)}`;
    const next = splitRoad(map(), row.id, selectedVertex, id(), id());
    selectedVertex = 0; changed(next); message('도로와 새 분할점을 초안에 만들었습니다. 검토 후 저장하세요');
  }));
  $('editor-join').addEventListener('click', () => act(() => {
    const row = current();
    if (row?.kind !== 'road') throw new Error('먼저 시작 도로를 고르세요');
    const next = joinRoads(map(), row.id, $('editor-join-target').value);
    selectedVertex = 0; changed(next); message('선택한 두 도로를 연결했습니다. 중간 장소는 유지되며 연결 관계를 다시 검토하세요');
  }));
  function dblclick(event) {
    if (!enabled() || $('editor-kind').value === 'select') return;
    const minPts = $('editor-kind').value === 'exclusion' ? 3 : 2;
    if (points.length >= minPts) {
      event.preventDefault(); event.stopImmediatePropagation();
      act(finish);
    }
  }
  const listeners = [[svg, 'click', click, true], [svg, 'dblclick', dblclick, true], [svg, 'pointerdown', down], [svg, 'pointermove', move],
    [svg, 'pointerup', up], [svg, 'pointercancel', () => { drag = null; sync(); }], [document, 'keydown', key, true]];
  for (const [target, name, handler, capture] of listeners) target.addEventListener(name, handler, capture);
  return {sync, cancel, drawing: () => Boolean(points.length || redo.length),
    destroy() { for (const [target, name, handler, capture] of listeners) target.removeEventListener(name, handler, capture); }};
}
