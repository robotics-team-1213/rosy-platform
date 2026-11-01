import {svgElement as el} from '/console/assets/map-editor.js';
import {randomUUID} from '/console/assets/uuid.js';
import {soccerProfileMap, rectangularView, viewTurnOf, planeView, siteMapErrorText} from '/console/assets/site-map-model.js';
import {copyMapTemplate} from '/console/assets/drawing-import.js';
import {warpImage} from '/console/assets/field-warp.js';
import {fieldToMap, multiply3, lensesMatch} from '/console/assets/map-fit.js';
import {parseLensHeader, fetchMapPlane, planeFitsImage} from '/console/assets/vision-view.js';

const $ = id => document.getElementById(id);

// Map sources are read-only until the existing profile-to-draft CAS action is confirmed.
export function createMapSourcesPanel({request, state, shown, calibrations, operatorReason,
  render, syncButtons, gate, guarded, select, clearPlan, status, W, H}) {
  let profiles = [], plane = null, planeEpoch = 0;
  const selectedProfile = () => profiles.find(row => row.profile_id === $('map-profile').value);
  function clearPlane() {
    planeEpoch += 1;
    if (plane?.url.startsWith('blob:')) URL.revokeObjectURL(plane.url);
    plane = null;
    $('plane-pick').checked = false;
    $('plane-point').textContent = '확인한 좌표 없음 · 운행 목적지로 전달하지 않습니다.';
    $('plane-status').textContent = '카메라 평면 영상과 좌표 확인은 표시 전용입니다.';
  }
  function updatePlaneSources() {
    clearPlane();
    $('plane-source').replaceChildren(...calibrations().filter(c => $('map-source').value !== 'profile' && c.map_id === shown()?.map_id)
      .map(c => new Option(c.source_id, c.source_id)));
  }
  $('map-source').addEventListener('change', () => { updatePlaneSources(); render(); syncButtons(); });
  async function loadProfiles(preferred = $('map-profile').value) {
    profiles = (await request('/api/fleet/site-map/profiles')).profiles;
    $('map-profile').replaceChildren(new Option('지도 설정 선택', ''),
      ...profiles.map(row => new Option(`${row.name} · ${{lane_course: '차선 코스', soccer: '축구장', general: '일반 지도'}[row.kind || 'lane_course']} (${row.map.map_id})`, row.profile_id)));
    $('map-profile').value = profiles.some(row => row.profile_id === preferred) ? preferred : '';
  }
  function profileInfo() {
    return {kind: $('profile-kind').value, description: $('profile-description').value,
      soccer_field: $('profile-kind').value === 'soccer' ? {length_m: Number($('profile-length').value),
        width_m: Number($('profile-width').value), goal_width_m: Number($('profile-goal-width').value)} : null};
  }
  function profileInputs(map, id = randomUUID(), name = '', info = {}) {
    $('profile-id').value = id;
    $('profile-name').value = name;
    $('profile-kind').value = info.kind || 'lane_course';
    $('profile-description').value = info.description || '';
    $('profile-length').value = info.soccer_field?.length_m ?? 2;
    $('profile-width').value = info.soccer_field?.width_m ?? 1.4;
    $('profile-goal-width').value = info.soccer_field?.goal_width_m ?? 0.35;
    $('profile-soccer').hidden = $('profile-kind').value !== 'soccer';
    $('profile-rules').value = JSON.stringify(map, null, 2);
    syncButtons();
  }
  $('map-profile').addEventListener('change', () => {
    const row = selectedProfile();
    if (row) profileInputs(row.map, row.profile_id, row.name, row);
    $('map-source').value = 'profile';
    updatePlaneSources(); select(null); syncButtons();
  });
  for (const id of ['profile-id', 'profile-name', 'profile-rules']) $(id).addEventListener('input', syncButtons);
  $('profile-kind').addEventListener('change', () => { $('profile-soccer').hidden = $('profile-kind').value !== 'soccer'; });
  $('profile-copy').addEventListener('click', () => profileInputs(copyMapTemplate(shown()), randomUUID(), '',
    $('map-source').value === 'profile' ? selectedProfile() : {}));
  $('profile-new').addEventListener('click', () => guarded(async () => {
    const id = randomUUID();
    const info = profileInfo();
    if (info.kind === 'soccer') {
      profileInputs(soccerProfileMap(info.soccer_field, id), id, '새 축구장', info);
      $('profile-rules').closest('details').open = true;
      return;
    }
    profileInputs({schema: 'rosy.site_map/1', map_id: id, places: [], edges: []}, id, '새 지도', info);
    $('profile-rules').closest('details').open = true;
  }));
  $('profile-file').addEventListener('change', () => guarded(async () => {
    const file = $('profile-file').files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024 - 1024) throw new Error('지도 파일은 2 MiB보다 작아야 합니다.');
    const input = JSON.parse(await file.text());
    const map = input.map || input;
    if (map?.schema !== 'rosy.site_map/1') throw new Error('rosy.site_map/1 지도 JSON 파일이 필요합니다.');
    profileInputs(map, randomUUID(), (input.name || file.name).slice(0, 64), input.map ? input : {});
    $('profile-status').textContent = '파일을 읽었습니다. 검증하고 지도 설정 저장을 누르면 좌표·차로 규칙을 검사합니다.';
  }));
  $('plane-clear').addEventListener('click', () => { updatePlaneSources(); render(); syncButtons(); });
  $('plane-source').addEventListener('change', () => { clearPlane(); render(); syncButtons(); });
  $('plane-pick').addEventListener('change', () => {
    if ($('plane-pick').checked) $('trip-pick').checked = false;
    clearPlan(); syncButtons();
  });
  $('plane-load').addEventListener('click', async () => {
    clearPlane();
    const epoch = ++planeEpoch;
    const record = calibrations().find(c => c.source_id === $('plane-source').value && c.map_id === shown()?.map_id);
    plane = null;
    render();
    syncButtons();
    $('plane-status').textContent = '평면 영상 불러오는 중';
    gate('plane-load', '불러오는 중');
    let url;
    try {
      const turn = viewTurnOf(shown());
      const {view, field} = rectangularView(record, shown()?.map_id, W, H, turn);
      // D-560: Vision's map plane first; the browser warp below only when Vision cannot make one.
      const got = await fetchMapPlane(request, record.source_id, null, AbortSignal.timeout(10000));
      if (got.state === 'error') throw new Error(`Vision 응답 ${got.status}`);
      if (got.state === 'live') {
        // The plane's coordinates are only as good as the calibration this page picked them against.
        if (!got.calibrationRevision || got.calibrationRevision !== record.calibration_revision)
          throw new Error('보정 revision이 다릅니다 — 다시 불러오세요.');
        if (!(got.ageMs >= 0 && got.ageMs <= 3000)) throw new Error('신선한 평면 영상을 확인할 수 없습니다.');
        if (got.blob.size > 8 * 1024 * 1024) throw new Error('영상 크기가 너무 큽니다.');
        url = URL.createObjectURL(got.blob);
        const image = new Image(); image.src = url; await image.decode();
        if (epoch !== planeEpoch) return;
        if (planeFitsImage(got.plane, image.naturalWidth, image.naturalHeight)) {
          // Header rectangle = picture, so the view's toMap is x = min_x + u/ppm, y = max_y - v/ppm (D-560 4).
          plane = {mapId: record.map_id, ...planeView(got.plane, W, H, turn), bounds: got.plane, url};
          url = null;  // the plane owns it until clearPlane
          $('plane-status').textContent = `불러온 평면 영상 · Rosy Cam 평면 영상 · ${record.source_id} · ${got.calibrationRevision} · 영상 유효 영역 ${Number.isFinite(got.observedFraction) ? `${Math.round(got.observedFraction * 100)}%` : '미확인'} · ${new Date().toLocaleTimeString()} · 표시 전용`;
          render();
          return;
        }
        URL.revokeObjectURL(url);  // a picture that is not its rectangle is no plane: use the browser warp
        url = null;
      }
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
      $('plane-status').textContent = `불러온 평면 영상 · 브라우저 보정(대체) · ${record.source_id} · ${new Date().toLocaleTimeString()} · 표시 전용`;
      render();
    } catch (error) {
      if (epoch === planeEpoch) $('plane-status').textContent = `평면 영상 확인 실패 · ${siteMapErrorText(error)}`;
    } finally {
      if (url) URL.revokeObjectURL(url);
      if (epoch === planeEpoch) syncButtons();
    }
  });

  function drawBackground(svg, map, fallbackView) {
    const background = plane?.mapId === map.map_id ? plane : null;
    svg.classList.toggle('has-plane', Boolean(background));
    $('map-view-turn').value = String(viewTurnOf(map));
    const view = background?.view || fallbackView();
    if (background) {
      el('image', {...background.field, href: background.url, preserveAspectRatio: 'none'}, svg);
      el('rect', {...background.field, class: 'plane-border'}, svg);
    }
    const line = points => points.map(([x, y]) => view.toPx(x, y).join(',')).join(' ');
    const pitch = $('map-source').value === 'profile' ? selectedProfile()?.soccer_field : null;
    if (pitch && !map.edges.length && soccerProfileMap(pitch, map.map_id).places.every(mark =>
      map.places.some(p => p.x === mark.x && p.y === mark.y))) {
      const x = pitch.length_m / 2, y = pitch.width_m / 2, goal = pitch.goal_width_m / 2;
      for (const points of [[[-x, -y], [x, -y], [x, y], [-x, y], [-x, -y]], [[0, -y], [0, y]],
        [[-x, -goal], [-x, goal]], [[x, -goal], [x, goal]]]) {
        const mark = el('polyline', {points: line(points), class: 'edge free', 'data-pitch-mark': 'true'}, svg);
        el('title', {}, mark).textContent = '축구장 기준선 · 주행 차로 아님';
      }
    }
    return {view, point: background?.point};
  }

  function renderStatus(map) {
    const hasMap = Boolean(map) && state.loadState === 'ready';
    for (const id of ['map-scroll-hint', 'map-viewport', 'map-legend']) $(id).hidden = !hasMap;
    const pending = state.loadState === 'pending';
    const failed = state.loadState === 'error';
    status('map-status', pending ? '지도 조회 중' : failed ? '지도 조회 실패 · 다시 접속하세요'
      : state.loadState === 'idle' ? '관제 접속 필요'
      : $('map-source').value === 'profile' ? (selectedProfile()?.name || '지도 설정 없음')
      : $('map-source').value === 'draft'
        ? (state.working ? `초안${state.dirty ? ' · 저장 안 됨' : ''}` : '초안 없음')
        : (state.active ? `활성 지도 v${state.active.version} · ${state.active.activated_by}` : '활성 지도 없음'),
    pending ? 'pending' : failed ? 'error' : map ? 'ready' : 'empty');
    return hasMap;
  }

  function pick(event) {
    if (!$('plane-pick').checked) return false;
    if (plane?.mapId !== shown()?.map_id) return true;
    const at = new DOMPoint(event.clientX, event.clientY).matrixTransform(event.currentTarget.getScreenCTM().inverse());
    const [x, y] = plane.view.toMap(at.x, at.y);
    const b = plane.bounds;
    if (x < b.min_x || x > b.max_x || y < b.min_y || y > b.max_y) return true;
    plane.point = {x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000};
    $('plane-point').textContent = `확인한 좌표 x ${plane.point.x} m, y ${plane.point.y} m · 표시 전용`;
    render();
    return true;
  }

  function sync() {
    const reason = operatorReason();
    gate('profile-new', reason);
    gate('profile-copy', reason || (!shown() ? '복사할 지도가 없습니다' : ''));
    gate('profile-save', reason || (!$('profile-id').value || !$('profile-name').value.trim() || !$('profile-rules').value ? 'ID·이름·지도 규칙을 입력하세요' : ''));
    gate('profile-draft', reason || (!selectedProfile() ? '저장된 지도 설정을 고르세요' : ''));
    if (selectedProfile()?.kind === 'soccer') gate('profile-draft', '축구장 기본 정보는 Games 설정용입니다. 차로 초안으로 불러오지 않습니다.');
    gate('plane-load', !state.role ? '관제 접속이 필요합니다' : !$('plane-source').value ? '이 지도에 맞는 카메라 보정이 없습니다' : '');
    gate('plane-clear', plane ? '' : '불러온 영상이 없습니다');
    gate('plane-pick', plane?.mapId === shown()?.map_id ? '' : '평면 영상을 먼저 불러오세요');
  }

  function reset() {
    planeEpoch += 1; plane = null; profiles = [];
    $('plane-pick').checked = false;
    $('plane-source').replaceChildren();
    $('map-profile').replaceChildren();
  }
  return {selectedProfile, loadProfiles, clearPlane, updatePlaneSources, drawBackground, renderStatus, pick, sync, reset, profileInputs, profileInfo,
    profile: id => profiles.find(row => row.profile_id === id)};
}
