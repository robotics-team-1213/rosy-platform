// D-494 6 지도 가르치기 panel: record a robot's map pose while a driver moves it with Pilot,
// then confirm the simplified line as a draft lane, or add an address at the robot or at a
// fresh floor place marker the ceiling camera sees (D-564).
// Nothing here moves a robot. The draft changes only through the Fleet teach API.
import {
  PLACE_KINDS, PLACE_KIND_LABEL, newestPending, siteMapErrorText, teachConfirmBody, teachStatusText,
} from '/console/assets/site-map-model.js';

const POLL_MS = 1000;

/** `host`: {request, role(), draft(), dirty(), places(), reload(), render()} from site-map.js. */
export function createTeachPanel(host) {
  const $ = id => document.getElementById(id);
  let view = null;
  let drawn = '';
  let markersKey = '';
  for (const kind of PLACE_KINDS) $('teach-place-kind').append(new Option(PLACE_KIND_LABEL[kind], kind));

  function gate(id, reason) {
    $(id).disabled = Boolean(reason);
    if (reason) $(id).setAttribute('reason', reason); else $(id).removeAttribute('reason');
  }
  function status(text, kind) { $('teach-status').textContent = text; $('teach-status').setAttribute('state', kind); }

  function sync() {
    const role = host.role();
    const base = role === 'operator' ? '' : role ? '운영자 권한이 필요합니다' : '관제 접속이 필요합니다';
    const robot = base || ($('teach-robot').value ? '' : '로봇을 고르세요');
    const recording = view?.recording;
    const pending = newestPending(view);
    const draftReason = host.dirty() ? '고친 초안을 먼저 저장하세요' : '';
    gate('teach-start', robot || (recording ? '기록 중입니다' : ''));
    gate('teach-stop', base || (recording ? '' : '기록 중이 아닙니다'));
    const named = $('teach-place-name').value.trim() ? '' : '새 주소 이름을 적으세요';
    gate('teach-place', robot || draftReason || named);
    gate('teach-marker-place', base || draftReason || ($('teach-marker').value ? '' : '보이는 장소 마커가 없습니다') || named);
    $('teach-form').hidden = !pending || Boolean(base);
    gate('teach-confirm', base || draftReason);
  }

  function fillEnd(selectId, candidates) {
    const names = new Map(host.places().map(place => [place.id, place.name]));
    $(selectId).replaceChildren(...candidates.map(c => new Option(`${names.get(c.place_id) || c.name} · ${c.distance_m} m`, c.place_id)),
      new Option('새 주소', ''));
  }

  async function pollMarkers() {
    let fresh = [];
    try {
      fresh = (await host.request('/api/fleet/place-markers')).markers.filter(marker => !marker.stale);
    } catch (_error) { /* no place marker source on this site: the list stays empty */ }
    const ids = [...new Set(fresh.map(marker => marker.marker_id))].sort((a, b) => a - b);
    const key = ids.join(',');
    if (key === markersKey) return;
    markersKey = key;
    const kept = $('teach-marker').value;
    $('teach-marker').replaceChildren(...ids.map(id => {
      const marker = fresh.find(m => m.marker_id === id);
      const deg = Math.round(marker.yaw * 180 / Math.PI);
      return new Option(`마커 ${id} · ${marker.x.toFixed(2)}, ${marker.y.toFixed(2)} m · ${deg}°`, String(id));
    }));
    if (ids.includes(Number(kept))) $('teach-marker').value = kept;
  }

  async function poll() {
    if (host.role()) {
      await pollMarkers();
      try {
        const next = await host.request('/api/fleet/teach');
        const shownBefore = newestPending(view)?.teach_id;
        view = next;
        const pending = newestPending(view);
        if (pending && pending.teach_id !== shownBefore) {
          fillEnd('teach-from', pending.from_candidates);
          fillEnd('teach-to', pending.to_candidates);
        }
        status(teachStatusText(view), view.recording ? 'pending' : pending ? 'ready' : 'empty');
        const key = `${view.recording?.teach_id}:${view.recording?.points.length}:${pending?.teach_id}`;
        if (key !== drawn) { drawn = key; host.render(); }  // redraw the map only when a line changed
      } catch (error) {
        status(`가르치기 상태 확인 불가 · ${siteMapErrorText(error)}`, 'error');
      }
    }
    sync();
    setTimeout(poll, POLL_MS);
  }

  async function act(work, done) {
    try {
      $('notice').textContent = (await work()) || done;
    } catch (error) {
      $('notice').textContent = `가르치기 거절 · ${siteMapErrorText(error)}`;
    }
    sync();
  }
  const post = (path, body) => host.request(path, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {})});

  $('teach-start').addEventListener('click', () => act(async () => {
    view = {recording: (await post('/api/fleet/teach/start', {robot_id: $('teach-robot').value})).recording, pending: view?.pending || []};
  }, '기록을 시작했습니다. Pilot으로 로봇을 모세요. 가르치기는 로봇을 움직이지 않습니다.'));
  $('teach-stop').addEventListener('click', () => act(async () => {
    const result = await post('/api/fleet/teach/stop');
    view = {recording: null, pending: [result, ...(view?.pending || []).filter(p => p.teach_id !== result.teach_id)]};
    fillEnd('teach-from', result.from_candidates);
    fillEnd('teach-to', result.to_candidates);
    host.render();
  }, '기록을 멈췄습니다. 시작·끝 장소와 통행 방식을 정해 초안에 확정하세요.'));
  $('teach-confirm').addEventListener('click', () => act(async () => {
    const pending = newestPending(view);
    if (!pending) return;
    const out = await post('/api/fleet/teach/confirm', teachConfirmBody({
      teachId: pending.teach_id, from: $('teach-from').value, fromName: $('teach-from-name').value,
      to: $('teach-to').value, toName: $('teach-to-name').value, direction: $('teach-direction').value,
      driveMode: $('teach-mode').value, speed: $('teach-speed').value, revision: host.draft()?.revision}));
    view = {...view, pending: view.pending.filter(p => p.teach_id !== pending.teach_id)};
    await host.reload();
    return `초안에 차로 ${out.edge_id}를 더했습니다. 활성화는 따로 합니다.`;
  }));
  $('teach-place').addEventListener('click', () => act(async () => {
    const out = await post('/api/fleet/teach/place', {robot_id: $('teach-robot').value,
      name: $('teach-place-name').value.trim(), kind: $('teach-place-kind').value,
      expected_revision: host.draft()?.revision || null});
    await host.reload();
    $('teach-place-name').value = '';
    return `초안에 주소 ${out.place_id}를 더했습니다. 활성화는 따로 합니다.`;
  }));
  $('teach-marker-place').addEventListener('click', () => act(async () => {
    const out = await post('/api/fleet/teach/place-from-marker', {marker_id: Number($('teach-marker').value),
      name: $('teach-place-name').value.trim(), kind: $('teach-place-kind').value,
      expected_revision: host.draft()?.revision || null});
    await host.reload();
    $('teach-place-name').value = '';
    return `초안에 마커 자리 주소 ${out.place_id}를 더했습니다. 활성화는 따로 합니다.`;
  }));
  for (const id of ['teach-robot', 'teach-place-name', 'teach-marker']) $(id).addEventListener('input', sync);
  poll();

  return {
    sync,
    robots(robots) {
      $('teach-robot').replaceChildren(...robots.map(robot => new Option(robot.robot_id, robot.robot_id)));
    },
    /** Lines in map metres to draw over the map: the live recording, then the newest stopped one. */
    lines() {
      const live = view?.recording?.points;
      return [live, newestPending(view)?.polyline].filter(points => points && points.length > 1);
    },
  };
}
