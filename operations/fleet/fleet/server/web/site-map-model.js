// D-488 site map page — pure helpers (no DOM) so node tests cover them.

export const PLACE_KINDS = ['junction', 'park', 'charge', 'stop', 'turnaround', 'start'];
export const PLACE_KIND_LABEL = {
  junction: '교차', park: '주차', charge: '충전', stop: '정차', turnaround: '회차', start: '출발',
};
export const ACTION_LABEL = {straight: '직진', left: '좌회전', right: '우회전', uturn: '회차', stop: '정지'};
export const TRIP_ERROR_LABEL = {
  TRIP_START_OFF_MAP: '로봇이 차로 위에 없습니다',
  TRIP_HEADING_CONFLICT: '로봇이 차로 반대 방향을 보고 있습니다 · Pilot으로 돌려 세우세요',
  TRIP_OFF_MAP: '찍은 점에서 차로 폭 두 배 안에 차로가 없습니다',
  TRIP_UNKNOWN_PLACE: '없는 주소입니다',
  TRIP_NO_ROUTE: '갈 수 있는 길이 없습니다',
  TRIP_ARRIVE_YAW_UNREACHABLE: '그 방향으로 도착하는 차로가 없습니다',
  TRIP_NO_ACTIVE_MAP: '활성 지도가 없습니다',
  TRIP_POSE_UNTRUSTED: '로봇 위치가 LOCALIZED가 아닙니다',
  TRIP_PLAN_FAILED: '이 지도에서 경로 계산이 실패했습니다 · 관리자에게 알리세요',
  UNKNOWN_ROBOT: '등록되지 않은 로봇입니다',
  // D-494 5 trip start / control
  TRIP_PLAN_UNKNOWN: '저장된 경로가 없습니다 · 다시 계산하세요',
  TRIP_PLAN_EXPIRED: '계산한 지 30초가 지났습니다 · 다시 계산하세요',
  TRIP_MAP_CHANGED: '계산 뒤 활성 지도가 바뀌었습니다 · 다시 계산하세요',
  TRIP_ROBOT_CAPS_UNKNOWN: '로봇이 주행 능력(종류·주행 방식)을 알리지 않습니다 · 새 이미지가 필요합니다',
  TRIP_MODE_UNSUPPORTED: '이 로봇의 주행 방식으로 갈 수 없는 차로가 경로에 있습니다',
  TRIP_SITE_FLOOR_MISMATCH: '로봇의 현장 바닥 선언이 활성 지도와 다릅니다 · 로봇 설정을 확인하세요',
  TRIP_LINE_FOLLOW_NOT_ACTIVE: '로봇의 차선 주행(카메라 또는 IR)이 켜져 있지 않습니다 · 켠 뒤 다시 출발하세요',
  TRIP_BUSY: '이 로봇은 이미 운행 중입니다',
  TRIP_LOOP_FULL: '고리 수용 한도를 넘어 출발할 수 없습니다',
  TRIP_ALREADY_STARTED: '이미 출발시킨 경로입니다',
  TRIP_NOT_RUNNING: '진행 중인 운행이 아닙니다',
  TRIP_UNKNOWN: '없는 운행입니다',
  TRIP_NO_REPLAN: '확인할 바뀐 경로가 없습니다',
  TRIP_REPLAN_FAILED: '다시 계산한 경로가 없습니다 · 운행을 취소하세요',
  TRIP_EXECUTION_NOT_AVAILABLE: '출발은 운행 시작 버튼으로 따로 합니다',
};
export const TRIP_STATE_LABEL = {
  started: '출발 대기', running: '운행 중', arrived: '도착', stopped: '멈춤', failed: '실패', canceled: '취소됨',
};
const TRIP_POSE_STATE_LABEL = {LOCALIZED: '위치 확정', DEGRADED: '위치 정확도 저하', UNKNOWN: '위치 확인 불가'};
export const TRIP_REASON_LABEL = {
  pose: '위치를 믿을 수 없어 멈췄습니다',
  junction: '로봇이 교차로 동작을 마치지 못해 멈췄습니다 · 차선 주행을 껐습니다 · 현장을 확인하세요',
  JUNCTION_ODOM_STALE: '로봇 odom이 낡아 교차로 지시를 다음 주기에 다시 보냅니다',
  junction_unexpected: '지도에 없는 자리에서 교차로를 봐 멈췄습니다 · 차선 주행을 껐습니다 · 현장을 확인하세요',
  stall: '경로를 따라 나아가지 않아 멈췄습니다 · 현장을 확인하세요',
  TRIP_LOOP_ERROR: '관제 운행 처리에 오류가 나 멈췄습니다 · 로봇 정지를 확인하고 관리자에게 알리세요',
  restart: '관제 서버가 다시 시작돼 멈췄습니다 · 자동으로 다시 출발하지 않습니다',
  TRIP_ROBOT_JUNCTION_UNSUPPORTED: '로봇 CORE가 교차로 지시를 모릅니다 · 새 이미지가 필요합니다',
  TRIP_ROBOT_UNREACHABLE: '로봇에 지시를 보내지 못했습니다',
  LINE_FOLLOW_NOT_ACTIVE: '로봇의 차선 주행이 켜져 있지 않습니다',
};
export const SITE_MAP_ERROR_LABEL = {
  SITE_MAP_NOT_ACTIVE: '활성 지도가 없습니다',
  SITE_MAP_NO_DRAFT: '저장된 초안이 없습니다',
  SITE_MAP_DRAFT_CHANGED: '다른 운영자가 초안을 바꿨습니다. 현재 수정은 저장되지 않았습니다. 변경 내용을 기록한 뒤 다시 접속하세요.',
  SITE_MAP_ROUTE_ACTIVE: '차선 경로가 진행 중입니다 · 끝난 뒤 활성화하세요',
  SITE_MAP_UNPLANNABLE: '경로 계산에 쓸 수 없는 지도입니다',
  SITE_MAP_START_INVALID: '출발 자리가 차로 위에 없거나 차로 방향과 다르게 놓였습니다',
  SITE_MAP_TOO_LARGE: '지도가 너무 큽니다',
  SITE_MAP_INVALID: '지도에 맞지 않는 값이 있습니다',
  // D-494 6 teach
  TEACH_BUSY: '다른 로봇을 기록하는 중입니다 · 한 번에 한 대만 가르칩니다',
  TEACH_NOT_RECORDING: '기록 중이 아닙니다',
  TEACH_POSE_UNTRUSTED: '로봇 지도 위치가 LOCALIZED가 아닙니다 · Rosy Cam이 로봇을 보는 곳에서 다시 하세요',
  TEACH_TOO_SHORT: '기록한 길이 0.1 m보다 짧아 버렸습니다',
  TEACH_UNKNOWN: '확정할 기록이 없습니다 · 10분이 지났거나 이미 확정했습니다',
  TEACH_UNKNOWN_PLACE: '없는 장소입니다',
  TEACH_PLACE_TOO_FAR: '고른 장소가 기록 끝에서 0.15 m보다 멉니다',
  UNKNOWN_ROBOT: '등록되지 않은 로봇입니다',
};

export function siteMapErrorText(error) {
  if (error.status === 401) return '관제 토큰을 확인하고 다시 접속하세요';
  if (error.status === 403) return '운영자 권한이 필요합니다 · 계정을 확인하세요';
  if (error.status >= 500) return '관제 서버 응답을 확인할 수 없습니다 · 잠시 뒤 다시 접속하세요';
  if (!error.status && /Failed to fetch|NetworkError|ERR_/.test(error.message || ''))
    return '관제 연결이 끊겼습니다 · 네트워크를 확인하고 다시 접속하세요';
  const base = SITE_MAP_ERROR_LABEL[error.code] || error.message || String(error);
  const fields = (error.detail?.errors || []).map(item => `${(item.loc || []).join('.')}: ${item.msg}`);
  return fields.length ? `${base} — ${fields.join(' · ')}` : base;
}

/** Action rows with the address name; a plan made on another map version is stale. */
export function actionRows(plan, map) {
  const names = new Map((map?.places || []).map(place => [place.id, place.name]));
  return plan.actions.map(item => `${item.place_id ? (names.get(item.place_id) || item.place_id) : '찍은 좌표'}`
    + ` · ${ACTION_LABEL[item.action] || item.action}`);
}

export function planIsCurrent(plan, active) {
  return Boolean(plan && active && plan.map_version === active.version);
}

export function tripErrorText(code, detail = {}) {
  const base = TRIP_ERROR_LABEL[code] || `경로 계획 거절 (${code || '알 수 없음'})`;
  if (code === 'TRIP_LOOP_FULL' && Number.isInteger(detail.robots) && Number.isInteger(detail.capacity))
    return `${base} · 고리 ${detail.robots}/${detail.capacity}대`;  // robots counts this one too
  if (code !== 'TRIP_NO_ROUTE') return base;
  const leg = Number.isInteger(detail.segment) ? ` · ${detail.segment + 1}번째 구간` : '';
  return base + leg + (detail.unblock_would_help ? ' · 막은 차로를 풀면 길이 있습니다' : '');
}

/** Map metres <-> SVG pixels; map y goes up, SVG y goes down. ``turn`` (0/90/180/270) turns the
 * whole view clockwise on screen (D-513 7) so the map reads the way the turned camera picture does. */
export function fitView(map, width, height, pad = 24, turn = 0) {
  const q = turn * Math.PI / 180, c = Math.round(Math.cos(q)), s = Math.round(Math.sin(q));
  const rot = (x, y) => [x * c + y * s, -x * s + y * c];
  const xs = [], ys = [];
  const add = (x, y) => { const [rx, ry] = rot(x, y); xs.push(rx); ys.push(ry); };
  for (const place of map.places) add(place.x, place.y);
  for (const edge of map.edges) for (const [x, y] of edge.polyline) add(x, y);
  if (!xs.length) { xs.push(0); ys.push(0); }
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const scale = Math.min((width - 2 * pad) / Math.max(maxX - minX, 1e-6),
    (height - 2 * pad) / Math.max(maxY - minY, 1e-6));
  const ox = pad + ((width - 2 * pad) - (maxX - minX) * scale) / 2;
  const oy = pad + ((height - 2 * pad) - (maxY - minY) * scale) / 2;
  return {
    scale, turn,
    toPx: (x, y) => { const [rx, ry] = rot(x, y); return [ox + (rx - minX) * scale, oy + (maxY - ry) * scale]; },
    toMap: (px, py) => {
      const rx = minX + (px - ox) / scale, ry = maxY - (py - oy) / scale;
      return [rx * c - ry * s, rx * s + ry * c];
    },
    /** SVG rotate() degrees for a map-frame direction ``angle`` (radians). */
    rotateDeg: (angle) => -angle * 180 / Math.PI + turn,
  };
}

// Rectified photographs are display evidence; their clicks never create trip targets.
export function rectangularView(record, mapId, width, height, turn = 0) {
  const b = record?.track_bounds_m;
  const h = record?.map_to_image;
  if (record?.map_id !== mapId || !b || !Array.isArray(h) || h.length !== 9
    || !h.every(Number.isFinite) || !Object.values(b).every(Number.isFinite)
    || !(b.max_x > b.min_x && b.max_y > b.min_y)) throw new Error('지도와 카메라 보정을 확인하세요.');
  const determinant = h[0] * (h[4] * h[8] - h[5] * h[7])
    - h[1] * (h[3] * h[8] - h[5] * h[6]) + h[2] * (h[3] * h[7] - h[4] * h[6]);
  if (Math.abs(determinant) < 1e-12 || ![b.min_x, b.max_x].every(x =>
    [b.min_y, b.max_y].every(y => h[6] * x + h[7] * y + h[8] > 1e-9)))
    throw new Error('카메라 보정의 평면 범위를 확인하세요.');
  const places = [{x: b.min_x, y: b.min_y}, {x: b.max_x, y: b.max_y}];
  const view = fitView({places, edges: []}, width, height, 24, turn);
  // The rectified picture is map-aligned: draw it unturned around its centre, then turn it.
  const [cx, cy] = view.toPx((b.min_x + b.max_x) / 2, (b.min_y + b.max_y) / 2);
  const fw = (b.max_x - b.min_x) * view.scale, fh = (b.max_y - b.min_y) * view.scale;
  return {view, field: {x: cx - fw / 2, y: cy - fh / 2, width: fw, height: fh,
    transform: `rotate(${turn} ${cx} ${cy})`}};
}

export function lengths(points) {
  const knots = [0];
  for (let i = 1; i < points.length; i += 1) {
    knots.push(knots[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]));
  }
  return knots;
}

export function pointAt(points, knots, s) {
  for (let i = 1; i < points.length; i += 1) {
    if (s <= knots[i] || i === points.length - 1) {
      const span = knots[i] - knots[i - 1];
      const t = span > 0 ? Math.min(Math.max((s - knots[i - 1]) / span, 0), 1) : 0;
      const [ax, ay] = points[i - 1], [bx, by] = points[i];
      return {x: ax + t * (bx - ax), y: ay + t * (by - ay), angle: Math.atan2(by - ay, bx - ax)};
    }
  }
  return {x: points[0][0], y: points[0][1], angle: 0};
}

/** Arrow marks at the middle of an edge: one for one_way, two opposite ones for two_way. */
export function arrowMarks(edge) {
  const knots = lengths(edge.polyline);
  const total = knots[knots.length - 1];
  const middle = pointAt(edge.polyline, knots, total / 2);
  if (edge.direction !== 'two_way') return [middle];
  const reversed = [...edge.polyline].reverse();
  const back = pointAt(reversed, lengths(reversed), total * 0.4);
  return [pointAt(edge.polyline, knots, total * 0.4), back];
}

/** The part of an edge a plan segment drives, in driving order (s along the travel direction). */
export function segmentPoints(edge, forward, sFrom, sTo) {
  const line = forward ? edge.polyline : [...edge.polyline].reverse();
  const knots = lengths(line);
  const inside = line.filter((_p, i) => knots[i] > sFrom && knots[i] < sTo);
  const a = pointAt(line, knots, sFrom), b = pointAt(line, knots, sTo);
  return [[a.x, a.y], ...inside, [b.x, b.y]];
}

export function planPolylines(map, plan) {
  const edges = new Map(map.edges.map(edge => [edge.id, edge]));
  return plan.segments.filter(seg => edges.has(seg.edge_id))
    .map(seg => segmentPoints(edges.get(seg.edge_id), seg.forward, seg.s_from, seg.s_to));
}

function copy(map) { return JSON.parse(JSON.stringify(map)); }

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
  return next;
}

/** D-513 7: the one screen orientation of this map (clockwise turn of the plain +y-up view). */
export const VIEW_TURNS = [0, 90, 180, 270];
export function viewTurnOf(map) { return VIEW_TURNS.includes(map?.view_turn_deg) ? map.view_turn_deg : 0; }
export function editViewTurn(map, turn) {
  const value = Number(turn);
  if (!VIEW_TURNS.includes(value)) throw new Error('화면 방향은 0·90·180·270° 중 하나입니다');
  return {...copy(map), view_turn_deg: value};
}

export function editEdge(map, id, {direction, drive_mode: driveMode, speed_cap_mps: speed}) {
  const next = copy(map);
  const edge = next.edges.find(item => item.id === id);
  if (!edge) throw new Error(`없는 차로 ${id}`);
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
  return next;
}

/** One line for the trip panel: state, current lane, next place and action, pose source. */
export function tripStatusText(trip, map) {
  if (!trip) return '진행 중인 운행 없음';
  const names = new Map((map?.places || []).map(place => [place.id, place.name]));
  const parts = [`${TRIP_STATE_LABEL[trip.state] || trip.state} · ${trip.robot_id}`];
  if (trip.current_edge) parts.push(`차로 ${trip.current_edge}`);
  if (trip.next_place) parts.push(`다음 ${names.get(trip.next_place) || trip.next_place} ${ACTION_LABEL[trip.next_action] || trip.next_action || ''}`.trim());
  if (trip.pose) parts.push(`자세 ${TRIP_POSE_STATE_LABEL[trip.pose.state] || trip.pose.state} · ${trip.pose.source === 'sighting' ? 'Rosy Cam' : trip.pose.source === 'bridged' ? 'odom 다리' : trip.pose.source}`);
  if (trip.hold) parts.push('바뀐 경로 확인 대기 · 장소에서 서 있음');
  if (trip.reason === 'stall' && Number.isFinite(trip.detail?.stall_s)) {
    parts.push(`${trip.detail.stall_s}초 넘게 ${TRIP_REASON_LABEL.stall}`);
  } else if (trip.reason) {
    parts.push(TRIP_REASON_LABEL[trip.reason] || trip.reason);
  }
  if (trip.detail?.junction_retry) parts.push(TRIP_REASON_LABEL[trip.detail.junction_retry] || trip.detail.junction_retry);
  if (trip.detail?.junction_fields_dropped) parts.push('활성 지도가 바뀌어 교차로 기대 값을 보내지 않았습니다');
  if (trip.reason === 'junction_unexpected') {  // D-507 3: where it stopped and why CORE held
    const {x, y} = trip.pose || {};
    if (Number.isFinite(x) && Number.isFinite(y)) parts.push(`지도 자세 (${x.toFixed(2)}, ${y.toFixed(2)})`);
    const why = trip.detail?.junction_reason || trip.detail?.line_reason;
    if (why) parts.push(`사유 ${why}`);
  }
  return parts.join(' · ');
}

/** D-517 2: a lap over the start places, beginning and ending at ``start`` (the robot's own place). */
export function repeatTripBody(map, start) {
  const starts = (map?.places || []).filter(place => place.kind === 'start').map(place => place.id);
  if (!starts.includes(start)) throw new Error('출발 자리를 고르세요');
  const via = starts.filter(id => id !== start);
  if (!via.length) throw new Error('반복 운행에는 출발 자리가 두 곳 이상 필요합니다');
  const at = starts.indexOf(start);
  return {to: start, via: [...starts.slice(at + 1), ...starts.slice(0, at)], repeat: true};
}

/** '' when the plan may start now; otherwise why the start button is off. */
export function tripStartReason({role, plan, active, running, now = Date.now() / 1000}) {
  if (role !== 'operator') return role ? '운영자 권한이 필요합니다' : '관제 접속이 필요합니다';
  if (running) return '이 로봇은 이미 운행 중입니다';
  if (!plan) return '먼저 경로를 계산하세요';
  if (!planIsCurrent(plan, active)) return '활성 지도가 바뀌었습니다 · 다시 계산하세요';
  if (plan.expires_at && now > plan.expires_at) return '계산한 지 30초가 지났습니다 · 다시 계산하세요';
  return '';
}

export function tripCancelReason({role, running}) {
  if (role !== 'operator') return role ? '운영자 권한이 필요합니다' : '관제 접속이 필요합니다';
  return running ? '' : '진행 중인 운행이 없습니다';
}

/** One line for the teach panel from `GET /api/fleet/teach`. */
export function teachStatusText(view) {
  const live = view?.recording;
  if (live) return `기록 중 · ${live.robot_id} · ${live.points.length}점 · ${live.started_by}`;
  if (view?.pending?.length) return `확정 대기 ${view.pending.length}건 · 멈춘 뒤 10분 안에 확정하세요`;
  return '기록 없음';
}

/** `POST /api/fleet/teach/confirm` body; an empty place id means a new address named `name`. */
export function teachConfirmBody({teachId, from, fromName, to, toName, direction, driveMode, speed, revision}) {
  const end = (id, name, label) => {
    if (id) return id;
    if (!String(name || '').trim() || String(name).length > 64) throw new Error(`${label} 새 주소 이름은 1–64자입니다`);
    return {name: String(name).trim(), kind: 'junction'};
  };
  const value = Number(speed);
  if (!Number.isFinite(value) || value <= 0 || value > 5) throw new Error('속도 상한은 0–5 m/s입니다');
  return {teach_id: teachId, from: end(from, fromName, '시작'), to: end(to, toName, '끝'), direction,
    drive_mode: driveMode, speed_cap_mps: value, expected_revision: revision || null};
}

/** The recording the confirm form acts on: the newest stopped one (latest `expires_at`). */
export function newestPending(view) {
  return (view?.pending || []).reduce((best, item) => (!best || item.expires_at > best.expires_at ? item : best), null);
}

// ---- D-517 10 교통 층 — GET /api/fleet/traffic 을 그릴 것·카드 한 줄·예외 큐 행으로 바꾼다 ----
// 관제 화면(map-view.js·roster.js)과 이 페이지의 운행 칸이 같이 쓴다.
// 표가 말하는 것만 옮긴다. M1 에서 Fleet 은 블록 표를 계산해 보이기만 하고 로봇에 보내지 않는다.
// 좌표는 활성 지도 미터다. 화면 방향(D-513 7)과 위에서 본 보기(D-515)는 그리는 쪽의 toPx 가 맡는다.

// D-517 3: UNKNOWN 점유가 이만큼 이어지면 해결기 → 사람이다.
export const UNKNOWN_ALARM_MS = 30000;
// D-517 3 `merge_max_wait_s` 기본값. Fleet 은 이 값을 /traffic 에 싣지 않는다.
export const MERGE_MAX_WAIT_MS = 20000;
// 블록 사이 틈(m) — 이웃 블록이 한 띠로 붙어 보이지 않게 양 끝을 줄인다.
const BLOCK_GAP_M = 0.03;

const isZone = (unit) => unit.zone === true;
const twoWay = (unit) => unit.id.startsWith("lane:");

/** A unit's stretches as [edge id, s0, s1] in the edge's own forward metres. */
export function unitParts(unitId, traffic) {
  if (unitId.startsWith("lane:")) return [[unitId.slice(5), 0, Infinity]];
  const hash = unitId.lastIndexOf("#");
  if (hash > 0) {
    const edge = unitId.slice(0, hash), index = Number(unitId.slice(hash + 1));
    const step = traffic.block_length_m?.[edge];
    return Number.isInteger(index) && step > 0 ? [[edge, index * step, (index + 1) * step]] : [];
  }
  // A zone: the edges that have no block or two-way unit of their own.
  // ponytail: /traffic does not name a zone's edges, so only a one-zone site can be drawn; add
  // `edges` to the zone unit when a site configures two zones.
  const zones = (traffic.units || []).filter((unit) => isZone(unit) && !twoWay(unit));
  if (zones.length !== 1) return [];
  const ids = new Set((traffic.units || []).map((unit) => unit.id));
  return Object.keys(traffic.block_length_m || {})
    .filter((edge) => !ids.has(`${edge}#0`) && !ids.has(`lane:${edge}`))
    .map((edge) => [edge, 0, Infinity]);
}

function partPoints(edge, s0, s1, gap) {
  const total = lengths(edge.polyline).at(-1);
  const a = Math.max(0, s0) + gap, b = Math.min(total, s1) - gap;
  return b > a ? segmentPoints(edge, true, a, b) : null;
}

/** A point on a trip's plan at route metres ``r`` (the first arc starts at 0, as /traffic counts). */
export function routePoint(segments, edges, r) {
  let base = 0;
  for (const seg of segments || []) {
    const edge = edges.get(seg.edge_id);
    if (!edge) return null;
    const line = seg.forward ? edge.polyline : [...edge.polyline].reverse();
    const knots = lengths(line);
    if (r <= base + seg.s_to + 1e-9) return pointAt(line, knots, Math.min(Math.max(r - base, seg.s_from), seg.s_to));
    base += knots.at(-1);
  }
  return null;
}

/**
 * What the 교통 layer draws, in map metres, or null when the table is for another map version.
 * bands: non-FREE blocks {points, state, robot}; zones: {lines, label, anchor}; ticks: authority ends;
 * centre: the middle of the lanes, so a zone label can sit on the inner side.
 */
export function trafficDrawing(traffic, active, trips = []) {
  if (!traffic || !active?.map || traffic.map_version !== active.version) return null;
  const edges = new Map((active.map.edges || []).map((edge) => [edge.id, edge]));
  const bands = [], zones = [], ticks = [];
  for (const unit of traffic.units || []) {
    const parts = unitParts(unit.id, traffic).filter(([edge]) => edges.has(edge));
    const zone = isZone(unit);
    if (unit.state !== "FREE") {
      for (const [edge, s0, s1] of parts) {
        const points = partPoints(edges.get(edge), s0, s1, zone ? 0 : BLOCK_GAP_M);
        if (points) bands.push({ points, state: unit.state, robot: unit.holders?.[0] || null, unit: unit.id });
      }
    }
    if (zone && parts.length) {
      const lines = parts.map(([edge, s0, s1]) => partPoints(edges.get(edge), s0, s1, 0)).filter(Boolean);
      const knots = lengths(lines[0]);
      zones.push({ unit: unit.id, lines, anchor: pointAt(lines[0], knots, knots.at(-1) / 2),
        label: `점유 ${(unit.holders || []).length}/${unit.capacity} · 대기 ${(unit.waiting || []).length}` });
    }
  }
  const plans = new Map(trips.map((trip) => [trip.robot_id, trip.plan?.segments]));
  for (const robot of traffic.robots || []) {
    if (typeof robot.authority_end_m !== "number") continue;
    const at = routePoint(plans.get(robot.robot_id), edges, robot.authority_end_m);
    if (at) ticks.push({ ...at, robot: robot.robot_id });
  }
  const xs = [...edges.values()].flatMap((edge) => edge.polyline.map((p) => p[0]));
  const ys = [...edges.values()].flatMap((edge) => edge.polyline.map((p) => p[1]));
  const centre = xs.length ? [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2] : [0, 0];
  return { bands, zones, ticks, centre };
}

function waitingUnit(traffic, robotId) {
  return (traffic?.units || []).find((unit) => (unit.waiting || []).includes(robotId)) || null;
}

/** One card line for a trip robot, '' for a robot without an open trip. */
export function trafficCardLine(traffic, robotId) {
  const robot = (traffic?.robots || []).find((row) => row.robot_id === robotId);
  if (!robot) return "";
  const parts = [];
  if (typeof robot.lap === "number") parts.push(`반복 운행 ${robot.lap}바퀴째`);
  const held = (traffic.units || []).some((unit) => unit.state === "UNKNOWN" && (unit.holders || []).includes(robotId));
  const unit = waitingUnit(traffic, robotId);
  if (held) parts.push("위치 불명 · 블록 유지");
  else if (unit && isZone(unit)) {
    const ahead = (unit.holders || []).filter((id) => id !== robotId);
    parts.push(`${twoWay(unit) ? "양방 차로" : "교차로"} 대기${ahead.length ? ` · ${ahead.join(", ")} 통과 중` : ""}`);
  } else if (robot.waiting_for?.length) parts.push(`앞 블록 대기 · ${robot.waiting_for.join(", ")}`);
  if (!parts.length) parts.push(robot.trip_state === "started" ? "운행 출발 대기" : "운행 중");
  return parts.join(" · ");
}

/** When the console first saw each robot hold an UNKNOWN block or wait at a zone entry. */
export function trafficClock(prev, traffic, now) {
  const next = { unknown: {}, merge: {} };
  for (const unit of traffic?.units || []) {
    if (unit.state === "UNKNOWN") for (const id of unit.holders || []) next.unknown[id] = prev?.unknown?.[id] ?? now;
    if (isZone(unit)) for (const id of unit.waiting || []) next.merge[id] = prev?.merge?.[id] ?? now;
  }
  return next;
}

/**
 * Exception-queue rows (D-493 one rule) for one robot. A block wait itself is normal and is not a row.
 * ponytail: the wait clocks start when this console first saw the state (a reload restarts them);
 * move them to /traffic if the 30 s / 20 s rows must survive a reload.
 */
export function trafficAttention(traffic, robotId, clock, now) {
  const items = [];
  const cycle = traffic?.wait_cycle;
  if (Array.isArray(cycle) && cycle.includes(robotId)) {
    items.push({ severity: "crit", text: `: 교착 — ${[...cycle, cycle[0]].join(" → ")} 서로 기다림 · 운영자 판단 필요` });
  }
  const unknownSince = clock?.unknown?.[robotId];
  if (unknownSince !== undefined && now - unknownSince > UNKNOWN_ALARM_MS) {
    items.push({ severity: "crit",
      text: `: 위치 불명 ${Math.floor((now - unknownSince) / 1000)}초 — 블록을 풀지 않습니다 · 로봇 위치를 확인하세요` });
  }
  const mergeSince = clock?.merge?.[robotId];
  if (mergeSince !== undefined && now - mergeSince > MERGE_MAX_WAIT_MS) {
    items.push({ severity: "warn", text: `: 합류 대기 ${Math.floor((now - mergeSince) / 1000)}초 — 구역 ${waitingUnit(traffic, robotId)?.id || ""} 입구` });
  }
  for (const loop of traffic?.loop_capacity || []) {
    if ((loop.robots || []).includes(robotId) && loop.robots.length > loop.capacity) {
      items.push({ severity: "warn", text: `: 고리 수용 초과 — 고리 ${loop.robots.length}/${loop.capacity}대` });
    }
  }
  return items;
}

/** "고리 2/3대" per repeat loop, or '' when no repeat trip runs. */
export function loopCapacityText(traffic) {
  return (traffic?.loop_capacity || []).map((loop) => `고리 ${loop.robots.length}/${loop.capacity}대`).join(" · ");
}
