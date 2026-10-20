// D-655 draft edits and survey teach context; no DOM, robot command or activation.
import {PLACE_KINDS} from './site-map-model.js';

function copy(map) { return JSON.parse(JSON.stringify(map)); }
function category(kind) { return PLACE_KINDS.includes(kind) ? 'places' : kind === 'road' ? 'edges' : 'facilities'; }

export function createSurveyDraft(mapId, reference) {
  if (!/^[A-Za-z0-9_.-]{1,64}$/.test(mapId) || !/^[A-Za-z0-9_.-]{1,64}$/.test(reference.revision || ''))
    throw new Error('지도 ID와 기준 버전을 확인하세요');
  if (!Array.isArray(reference.origin) || reference.origin.length !== 2
      || !reference.origin.every(v => Number.isFinite(v) && Math.abs(v) <= 1000)
      || !Number.isFinite(reference.heading_rad) || Math.abs(reference.heading_rad) > 2 * Math.PI)
    throw new Error('기준점 좌표와 방향을 확인하세요');
  if (!['odometry', 'measured'].includes(reference.scale_source)
      || (reference.scale_source === 'measured' && !(Number.isFinite(reference.measured_distance_m)
        && reference.measured_distance_m > 0 && reference.measured_distance_m <= 2000)))
    throw new Error('실측 축척에는 확인한 거리가 필요합니다');
  if (!reference.description?.trim() || reference.description.length > 1000)
    throw new Error('시작점·방향·축척 근거를 적으세요');
  return {schema: 'rosy.site_map/1', map_id: mapId, places: [], edges: [],
    survey: {...copy(reference), reviewed: false, review_note: ''}};
}

export function appendSurveyElement(map, item) {
  if (!map?.survey) throw new Error('조사 기준이 있는 초안을 먼저 만드세요');
  const {id, name, kind, geometry} = item;
  if (!/^[A-Za-z0-9_.-]{1,32}$/.test(id) || typeof name !== 'string' || name.length > 64
      || (kind !== 'road' && !name.trim()))
    throw new Error('요소 ID와 이름을 확인하세요');
  if (!Array.isArray(geometry) || !geometry.length || geometry.length > 32
      || !geometry.every(p => Array.isArray(p) && p.length === 2
        && p.every(v => Number.isFinite(v) && Math.abs(v) <= 1000)))
    throw new Error('지도에서 위치를 찍거나 유한한 좌표를 입력하세요');
  const next = copy(map);
  next.survey = {...next.survey, reviewed: false, review_note: ''};
  if ((next[category(kind)] || []).some(row => row.id === id))
    throw new Error('이미 쓰는 요소 ID입니다');
  if (PLACE_KINDS.includes(kind)) {
    if (geometry.length !== 1 || (kind === 'start' && !Number.isFinite(item.yaw)))
      throw new Error('장소는 한 점이며 출발 장소는 확인한 방향이 필요합니다');
    const [x, y] = geometry[0];
    next.places.push({id, name: name.trim(), kind, x, y, ...(Number.isFinite(item.yaw) ? {yaw: item.yaw} : {})});
  } else if (kind === 'road') {
    const start = next.places.find(p => p.id === item.from), end = next.places.find(p => p.id === item.to);
    if (!start || !end || start.id === end.id || geometry.length < 2)
      throw new Error('서로 다른 시작·끝 장소와 도로 선을 지정하세요');
    if (!(item.width_m > 0 && item.width_m <= 10) || !Number.isFinite(item.width_m)
        || !['one_way', 'two_way'].includes(item.direction)) throw new Error('차로 폭과 통행 방향을 확인하세요');
    if (Math.hypot(geometry[0][0] - start.x, geometry[0][1] - start.y) > .05
        || Math.hypot(geometry.at(-1)[0] - end.x, geometry.at(-1)[1] - end.y) > .05)
      throw new Error('도로 선의 양 끝을 지정한 장소에 맞추세요');
    next.edges.push({id, ...(name.trim() ? {name: name.trim()} : {}), from: start.id, to: end.id, polyline: [[start.x, start.y], ...geometry.slice(1, -1), [end.x, end.y]],
      width_m: item.width_m, direction: item.direction, drive_mode: 'lane', speed_cap_mps: .03,
      evidence: {source: 'operator', status: 'observed', reference_revision: next.survey.revision, note: ''}});
  } else if (['traffic_signal', 'stop_line', 'landmark', 'exclusion'].includes(kind)) {
    const required = {traffic_signal: 1, stop_line: 2, landmark: 1}[kind];
    if (required ? geometry.length !== required : geometry.length < 3) throw new Error('요소 종류에 맞게 점을 찍으세요');
    const approaches = item.approaches || [];
    if (approaches.some(a => !next.edges.some(e => e.id === a.edge_id))) throw new Error('연결할 도로가 없습니다');
    if (kind === 'traffic_signal' && (!item.signal_id || !['physical', 'virtual'].includes(item.signal_kind) || !approaches.length))
      throw new Error('신호등 ID·종류와 제어 진입 차로를 지정하세요');
    next.facilities = [...(next.facilities || []), {id, name: name.trim(), kind, geometry: copy(geometry), approaches: copy(approaches),
      ...(kind === 'traffic_signal' ? {signal_id: item.signal_id, signal_kind: item.signal_kind} : {})}];
  } else throw new Error('알 수 없는 지도 요소입니다');
  return next;
}

export function reviewSurveyDraft(map, note) {
  if ((!map?.survey && !map?.edges?.some(e => e.evidence)) || !note?.trim() || note.length > 1000) throw new Error('좌표 기준과 도로를 확인한 검토 근거를 적으세요');
  const next = copy(map);
  if (next.survey) next.survey = {...next.survey, reviewed: true, review_note: note.trim()};
  for (const edge of next.edges) {
    if (!next.survey && !edge.evidence) continue;
    const evidenceNote = [edge.evidence?.note, note.trim()].filter(Boolean).join('\n');
    if (evidenceNote.length > 1000) throw new Error('관측 근거와 검토 메모의 합계는 1000자 이내여야 합니다');
    edge.evidence = {...(edge.evidence || {source: 'operator'}),
      status: 'reviewed', reference_revision: next.survey?.revision || edge.evidence.reference_revision, note: evidenceNote};
  }
  return next;
}

export function editSurveyElement(map, item) {
  const key = category(item.kind), group = map[key];
  if (!group) throw new Error('수정할 요소가 없습니다');
  const old = group.find(row => row.id === item.id);
  if (!old) throw new Error('Unknown element category or ID');
  if ((group === map.places && !PLACE_KINDS.includes(item.kind))
      || (group === map.edges && item.kind !== 'road')
      || (group === map.facilities && item.kind !== old.kind)) throw new Error('기존 요소의 분류를 유지하세요');
  const base = copy(map);
  base[key] = base[key].filter(row => row.id !== item.id);
  const next = appendSurveyElement(base, item);
  if (group === map.edges) {
    const edge = next.edges.find(row => row.id === item.id);
    edge.evidence.note = old.evidence?.note || '';
    edge.drive_mode = old.drive_mode;
    edge.speed_cap_mps = old.speed_cap_mps;
    if (old.robot_kinds !== undefined) edge.robot_kinds = copy(old.robot_kinds);
  }
  if (group === map.places && item.yaw === undefined && old.yaw !== undefined)
    next.places.find(row => row.id === item.id).yaw = old.yaw;
  if (group === map.places) {
    const [x, y] = item.geometry[0];
    for (const edge of next.edges) {
      if (edge.from === item.id) edge.polyline[0] = [x, y];
      if (edge.to === item.id) edge.polyline[edge.polyline.length - 1] = [x, y];
      if (edge.from === item.id || edge.to === item.id) edge.evidence = {source: 'operator',
        status: 'observed', reference_revision: next.survey.revision, note: edge.evidence?.note || ''};
    }
  }
  return next;
}

export function removeSurveyElement(map, id, key) {
  if (!key) {
    const matches = ['places', 'edges', 'facilities'].filter(k => map[k]?.some(row => row.id === id));
    if (matches.length !== 1) throw new Error('Choose an unambiguous element category');
    [key] = matches;
  }
  if (!['places', 'edges', 'facilities'].includes(key) || !map[key]?.some(row => row.id === id))
    throw new Error('Unknown element category or ID');
  if ((key === 'places' && (map.edges.some(edge => edge.from === id || edge.to === id)
      || (map.turn_bans || []).some(b => b.at === id)))
      || (key === 'edges' && ((map.facilities || []).some(f => f.approaches?.some(a => a.edge_id === id))
      || (map.turn_bans || []).some(b => b.from_edge === id || b.to_edge === id))))
    throw new Error('연결된 차로·시설·통행 규칙을 먼저 수정하거나 삭제하세요');
  const next = copy(map);
  next[key] = next[key].filter(row => row.id !== id);
  if (next.survey) next.survey = {...next.survey, reviewed: false, review_note: ''};
  return next;
}

export function editPlace(map, id, {name, kind}) {
  const next = copy(map);
  const place = next.places.find(item => item.id === id);
  if (!place) throw new Error(`없는 장소 ${id}`);
  if (name !== undefined) {
    if (!String(name).trim() || String(name).length > 64) throw new Error('주소 이름은 1–64자입니다');
    place.name = String(name).trim();
  }
  if (kind !== undefined) {
    if (!PLACE_KINDS.includes(kind)) throw new Error('알 수 없는 장소 종류');
    // D-513: the heading comes from a robot set down on the spot (teach "place"), never a guess
    if (kind === 'start' && typeof place.yaw !== 'number') throw new Error('출발 자리는 방향이 필요합니다 · 로봇을 그 자리에 놓고 기록 모드에서 출발 장소로 남기세요');
    place.kind = kind;
  }
  if (next.survey) next.survey = {...next.survey, reviewed: false, review_note: ''};
  return next;
}

export function editEdge(map, id, {name, direction, drive_mode: driveMode, speed_cap_mps: speed}) {
  const next = copy(map);
  const edge = next.edges.find(item => item.id === id);
  if (!edge) throw new Error(`없는 차로 ${id}`);
  if (name !== undefined) {
    if (name.length > 64) throw new Error('도로 이름은 64자 이내입니다');
    if (name.trim()) edge.name = name.trim();
    else delete edge.name;
  }
  if (direction !== undefined) {
    if (!['one_way', 'two_way'].includes(direction)) throw new Error('통행 방향은 일방/양방입니다');
    edge.direction = direction;
  }
  if (driveMode !== undefined) {
    if (!['lane', 'free'].includes(driveMode)) throw new Error('주행 방식은 차선/좌표입니다');
    edge.drive_mode = driveMode;
  }
  if (speed !== undefined) {
    const value = Number(speed);
    if (!Number.isFinite(value) || value <= 0 || value > 5) throw new Error('속도 상한은 0–5 m/s입니다');
    edge.speed_cap_mps = value;
  }
  if (next.survey) {
    next.survey = {...next.survey, reviewed: false, review_note: ''};
  }
  if (next.survey || edge.evidence) edge.evidence = {source: 'operator', status: 'observed',
    reference_revision: next.survey?.revision || edge.evidence.reference_revision, note: edge.evidence?.note || ''};
  return next;
}

export function teachStartBody({robotId, mode, draft, confirmed}) {
  if (!robotId) throw new Error('로봇을 고르세요');
  if (mode === 'map') return {robot_id: robotId};
  if (mode !== 'survey') throw new Error('기록 좌표 방식을 고르세요');
  if (!draft?.revision || !draft.map?.survey) throw new Error('조사 기준이 있는 초안을 먼저 저장하세요');
  if (!confirmed) throw new Error('로봇이 조사 시작점과 방향에 놓였는지 확인하세요');
  return {robot_id: robotId, mode: 'survey', map_id: draft.map.map_id,
    reference_revision: draft.map.survey.revision, expected_revision: draft.revision};
}

export function surveyTeachMatches(record, map) {
  return Boolean(record?.survey_reference && record.map_id === (map?.map_id || 'site') && map?.survey
    && Object.entries(record.survey_reference).every(([key, value]) => JSON.stringify(map.survey[key]) === JSON.stringify(value)));
}

export function teachFrameMatches(record, map) {
  if (!record || !map || record.map_id !== (map.map_id || 'site')) return false;
  if (record.mode === 'survey' || record.survey_reference) return surveyTeachMatches(record, map);
  return !map.survey;
}

function validateCameraMap(base, observation) {
  const reference = map => Object.entries(map?.survey || {}).filter(([k]) => !['reviewed', 'review_note'].includes(k))
    .sort(([a], [b]) => a.localeCompare(b));
  if (observation?.schema !== 'rosy.site_map/1' || !base?.survey
      || observation.map_id !== base.map_id || JSON.stringify(reference(observation)) !== JSON.stringify(reference(base)))
    throw new Error('카메라 관측과 초안의 지도 ID·전체 조사 기준을 맞추세요');
  if (!Array.isArray(observation.places) || !Array.isArray(observation.edges) || !observation.edges.length
      || ['facilities', 'crosswalks', 'turn_bans'].some(k => observation[k]?.length)
      || observation.edges.some(e => e.evidence?.source !== 'camera' || e.evidence.status !== 'observed'
        || e.evidence.reference_revision !== base.survey.revision))
    throw new Error('관측 근거가 있는 카메라 차로 초안이 필요합니다');
}

const cameraSignature = e => JSON.stringify([e.polyline, e.direction, e.width_m, e.drive_mode, e.speed_cap_mps, e.robot_kinds ?? null]);

export function cameraConnectionCandidates(base, observation) {
  validateCameraMap(base, observation);
  const used = new Set(observation.edges.filter(e => !base.edges.some(old => cameraSignature(old) === cameraSignature(e)))
    .flatMap(e => [e.from, e.to]));
  return observation.places.filter(p => used.has(p.id)).map(p => ({observation_id: p.id, name: p.name, x: p.x, y: p.y,
    candidates: base.places.map(old => ({id: old.id, name: old.name, x: old.x, y: old.y,
      distance_m: Math.hypot(old.x - p.x, old.y - p.y)})).filter(old => old.distance_m <= .05)}))
    .filter(row => row.candidates.length);
}

export function mergeCameraMap(base, observation, connections = {}) {
  validateCameraMap(base, observation);
  observation = copy(observation);
  const joins = new Map(Object.entries(connections));
  for (const [id, target] of joins) {
    const point = observation.places.find(p => p.id === id), old = base.places.find(p => p.id === target);
    if (!point || !old || !Number.isFinite(point.x) || !Number.isFinite(point.y)
        || Math.hypot(point.x - old.x, point.y - old.y) > .05)
      throw new Error('연결 후보의 장소와 0.05 m 이내 거리를 확인하세요');
    point.x = old.x; point.y = old.y;
    for (const edge of observation.edges.filter(e => e.from === id || e.to === id)) {
      if (edge.from === id) edge.polyline[0] = [old.x, old.y];
      if (edge.to === id) edge.polyline[edge.polyline.length - 1] = [old.x, old.y];
      edge.evidence.status = 'inferred';
      edge.evidence.note = [edge.evidence.note, `connection ${id} -> ${target}`].filter(Boolean).join('\n');
      if (edge.evidence.note.length > 1000) throw new Error('관측과 연결 근거는 1000자 이내여야 합니다');
    }
  }
  const next = copy(base), ids = new Map();
  let addedEvidence = false;
  const fresh = observation.edges.filter(e => {
    const old = next.edges.find(row => cameraSignature(row) === cameraSignature(e)
      && ['from', 'to'].every(end => !joins.has(e[end]) || joins.get(e[end]) === row[end]));
    if (!old) return true;
    const note = e.evidence.note || '';
    if (note && !old.evidence?.note?.includes(note)) {
      const combined = [old.evidence?.note, note].filter(Boolean).join('\n');
      if (combined.length > 1000) throw new Error('관측 근거가 1000자를 넘습니다 · 초안을 분리하거나 근거를 검토하세요');
      old.evidence = {...(old.evidence || e.evidence), status: e.evidence.status, note: combined};
      addedEvidence = true;
    }
    return false;
  });
  const free = rows => { let n = 1; while (rows.some(r => r.id === `camera_${n}`)) n++; return `camera_${n}`; };
  for (const id of new Set(fresh.flatMap(e => [e.from, e.to]))) {
    const place = observation.places.find(p => p.id === id);
    if (!place || !Number.isFinite(place.x) || !Number.isFinite(place.y)) throw new Error('카메라 장소 좌표를 확인하세요');
    if (joins.has(id)) { ids.set(id, joins.get(id)); continue; }
    if (next.places.some(p => Math.hypot(p.x - place.x, p.y - place.y) <= .05))
      throw new Error('기존 장소와 가까운 관측은 연결이 모호합니다 · 장소와 차로를 직접 검토하세요');
    const mapped = free(next.places);
    ids.set(id, mapped); next.places.push({...copy(place), id: mapped});
  }
  for (const edge of fresh) {
    if (ids.get(edge.from) === ids.get(edge.to)) throw new Error('도로의 두 끝을 같은 장소에 연결할 수 없습니다');
    next.edges.push({...copy(edge), id: free(next.edges), from: ids.get(edge.from), to: ids.get(edge.to)});
  }
  if (fresh.length || addedEvidence) next.survey = {...next.survey, reviewed: false, review_note: ''};
  return next;
}

