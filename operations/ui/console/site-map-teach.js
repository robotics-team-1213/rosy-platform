// D-494 6 지도 가르치기 panel: record a robot's map pose while a driver moves it with Pilot,
// then confirm the simplified line as a draft lane, or add an address at the robot or at a
// fresh floor place marker the ceiling camera sees (D-564).
// Nothing here moves a robot. The draft changes only through the Fleet teach API.
import {
  PLACE_KINDS, PLACE_KIND_LABEL, newestPending, siteMapErrorText, teachConfirmBody, teachStatusText,
} from '/console/assets/site-map-model.js';
import {teachStartBody, surveyTeachMatches, teachFrameMatches} from '/console/assets/site-map-edit.js';

const POLL_MS = 1000;

/** `host`: {request, role(), draft(), dirty(), places(), reload(), render()} from site-map.js. */
export function createTeachPanel(host) {
  const $ = id => document.getElementById(id);
  let view = null;
  let drawn = '';
  let markersKey = '';
  let basisKey = '';
  const requestedRobot = new URLSearchParams(location.search).get('robot');
  let robotsFilled = false;
  let roster = [];
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
    if (recording) $('teach-robot').value = roster.some(row => row.robot_id === recording.robot_id) ? recording.robot_id : '';
    const target = roster.find(row => row.robot_id === $('teach-robot').value);
    const pending = newestPending(view);
    const draftReason = host.dirty() ? '고친 초안을 먼저 저장하세요' : '';
    const draft = host.draft(), reference = draft?.map?.survey;
    const survey = $('teach-frame').value === 'survey';
    const key = `${$('teach-robot').value}:${$('teach-frame').value}:${draft?.revision}`;
    if (key !== basisKey) { basisKey = key; $('teach-origin-confirm').checked = false; }
    $('teach-origin-check').hidden = !survey;
    gate('teach-frame', recording ? '기록 중 · 중단 뒤 좌표 기준을 바꾸세요' : '');
    gate('teach-robot', recording ? '기록 중 · 중단 뒤 대상을 바꾸세요' : '');
    $('teach-target').textContent = recording ? `기록 중인 로봇 ${recording.robot_id} · 중단 뒤 대상과 좌표 기준을 바꿀 수 있습니다`
      : target ? `기록 대상 ${target.robot_id} · ${target.online === false ? '연결 끊김 · ' : ''}시작 전 실제 로봇을 확인하세요`
        : requestedRobot && !roster.some(row => row.robot_id === requestedRobot) ? `요청한 로봇 ${requestedRobot}이 등록 목록에 없습니다 · 기록할 로봇을 직접 선택하세요`
          : '기록할 로봇을 선택하세요';
    $('teach-reference').textContent = reference
      ? `조사 기준 ${reference.revision} · 시작 ${reference.origin.map(v => v.toFixed(2)).join(', ')} m · 방향 ${Math.round(reference.heading_rad * 180 / Math.PI)}° · ${reference.description}`
      : '조사 기준 없음 · 지도 만들기에서 기준을 정해 저장하세요';
    const surveyReason = survey ? draftReason || (!reference || !draft?.revision ? '조사 기준이 있는 초안을 먼저 저장하세요' : '')
      || ($('teach-origin-confirm').checked ? '' : '로봇이 조사 시작점과 방향에 놓였는지 확인하세요') : '';
    gate('teach-start', robot || (recording ? '기록 중입니다' : '') || surveyReason);
    gate('teach-stop', base || (recording ? '' : '기록 중이 아닙니다'));
    const named = $('teach-place-name').value.trim() ? '' : '새 주소 이름을 적으세요';
    gate('teach-place', robot || draftReason || named);
    gate('teach-marker-place', base || draftReason || ($('teach-marker').value ? '' : '보이는 장소 마커가 없습니다') || named);
    $('teach-form').hidden = !pending || Boolean(base);
    gate('teach-confirm', base || draftReason || (pending?.mode === 'survey' && !surveyTeachMatches(pending, draft?.map)
      ? '기록의 조사 기준과 현재 초안이 다릅니다 · 기존 기준을 확인하세요' : ''));
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
    const newest = new Map();  // per id the newest sighting, the one Fleet teaches from
    for (const marker of fresh) {
      if (!(newest.get(marker.marker_id)?.captured_at >= marker.captured_at)) newest.set(marker.marker_id, marker);
    }
    const ids = [...newest.keys()].sort((a, b) => a - b);
    const labels = ids.map(id => {
      const marker = newest.get(id);
      const deg = Math.round(marker.yaw * 180 / Math.PI);
      return `마커 ${id} · ${marker.x.toFixed(2)}, ${marker.y.toFixed(2)} m · ${deg}°`;
    });
    const key = labels.join('|');  // rounded pose too, so a moved sticker relabels
    if (key === markersKey) return;
    markersKey = key;
    const kept = $('teach-marker').value;
    $('teach-marker').replaceChildren(...ids.map((id, i) => new Option(labels[i], String(id))));
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
    view = {recording: (await post('/api/fleet/teach/start', teachStartBody({robotId: $('teach-robot').value,
      mode: $('teach-frame').value, draft: host.draft(), confirmed: $('teach-origin-confirm').checked}))).recording,
      pending: view?.pending || []};
    $('teach-origin-confirm').checked = false;
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
  for (const id of ['teach-robot', 'teach-place-name', 'teach-marker', 'teach-frame', 'teach-origin-confirm']) $(id).addEventListener('input', sync);
  poll();

  return {
    sync,
    robots(robots) {
      roster = robots;
      const selected = view?.recording?.robot_id ?? (robotsFilled ? $('teach-robot').value : requestedRobot ?? robots[0]?.robot_id);
      $('teach-robot').replaceChildren(new Option('기록할 로봇 선택', ''),
        ...robots.map(robot => new Option(robot.robot_id, robot.robot_id)));
      $('teach-robot').value = robots.some(robot => robot.robot_id === selected) ? selected : '';
      robotsFilled = true;
      sync();
    },
    /** Lines in map metres to draw over the map: the live recording, then the newest stopped one. */
    lines() {
      return [view?.recording, newestPending(view)]
        .filter(record => teachFrameMatches(record, host.map()))
        .map(record => Array.isArray(record.points) ? record.points : record.polyline)
        .filter(points => points && points.length > 1);
    },
  };
}
