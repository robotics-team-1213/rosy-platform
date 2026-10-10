// D-488 site map page — pure helpers (no DOM) so node tests cover them.

export const PLACE_KINDS = ['junction', 'park', 'charge', 'stop', 'turnaround', 'start'];
export const PLACE_KIND_LABEL = {
  junction: '교차', park: '주차', charge: '충전', stop: '정차', turnaround: '회차', start: '출발',
};
export const ACTION_LABEL = {straight: '직진', left: '좌회전', right: '우회전', uturn: '회차', stop: '정지'};
/** D-517 5 (M4) Fleet resolver decisions for a wait cycle. */
export const RESOLVER_DECISION_LABEL = {replan: '다른 길 계획', wait: '다른 로봇 대기', human: '운영자 판단'};
/** D-577 3 AI PC fact kinds (shadow: shown, never acted on here). */
export const AI_FACT_LABEL = {
  trip_route_check: 'AI 경로 편차 확인',
  wait_cycle_confirmed: '교착 확인 (모두 멈춤)', wait_cycle_stale_input: '낡은 입력의 교착일 수 있음',
  waiting_but_moving: '대기인데 움직임', livelock: '움직이지만 진행 없음', stalled: '권한이 있는데 멈춤',
  unknown_occupancy_long: '위치 불명 점유 30초 넘음', rear_blocked: '뒤가 막힘', path_blocked_by_robot: '앞에 로봇',
  incident_context: '사건 원인 초안',
};
export const TRIP_ERROR_LABEL = {
  TRIP_START_PLACE_MISMATCH: '선택한 출발 장소에 로봇이 없습니다 · 실제 위치를 확인하세요',
  TRIP_START_PLACE_MOVED: '그 장소에서는 안전하게 정지할 수 없습니다 · 다른 장소를 고르세요',
  TRIP_BODY_UNKNOWN: '로봇 차체 폭을 확인할 수 없어 출발할 수 없습니다',
  TRIP_START_BODY_OUTSIDE_ROUTE: '로봇 차체가 첫 차로 경계를 넘었습니다 · 위치를 조정하세요',
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
  // D-601: 꺼져 있으면 관제가 출발 때 카메라 차선 주행을 켠다; 남는 거절은 IR 차선 주행이나 모르는 상태
  TRIP_LINE_FOLLOW_NOT_ACTIVE: '로봇이 IR 차선 주행 중이거나 차선 주행 상태를 알 수 없습니다 · 차선 주행을 끈 뒤 다시 출발하세요',
  TRIP_LANE_CAMERA_UNAVAILABLE: '로봇 앞 카메라 영상이 들어오지 않아 차선 주행을 할 수 없습니다 · 카메라를 확인하세요',
  TRIP_START_HEADING_MISMATCH: '로봇이 첫 차로 방향과 다르게 서 있습니다 · 차로 방향으로 돌려 세우세요',
  TRIP_START_OFF_LANE: '로봇이 첫 차로 밖에 있습니다 · 차로 위로 옮기세요',
  TRIP_LINE_FOLLOW_START_FAILED: '로봇이 카메라 차선 주행을 켜지 못해 운행을 멈췄습니다',
  TRIP_BUSY: '이 로봇은 이미 운행 중입니다',
  TRIP_LOOP_FULL: '고리 수용 한도를 넘어 출발할 수 없습니다',
  // D-517 9 M3 대열
  TRIP_CONVOY_SELF: '자기 자신을 리더로 고를 수 없습니다',
  TRIP_CONVOY_LEADER_NOT_RUNNING: '리더가 반복 운행 중이 아닙니다 · 리더를 먼저 출발시키세요',
  TRIP_CONVOY_LEADER_IS_FOLLOWER: '고른 리더도 다른 로봇을 따라갑니다 · 대열의 맨 앞 로봇을 고르세요',
  TRIP_CONVOY_OTHER_LOOP: '리더와 다른 고리입니다 · 같은 출발 자리 순환으로 다시 하세요',
  TRIP_CONVOY_NO_AUTHORITY: '이 로봇은 통행권(CORE)을 받지 않아 대열에 들 수 없습니다',
  TRIP_CONVOY_LOOP_FULL: '대열을 더하면 고리 수용 한도를 넘습니다',
  TRIP_CONVOY_NOT_BEHIND: '리더 뒤 같은 고리에 있지 않습니다 · 리더 뒤에 세운 뒤 다시 하세요',
  // D-517 4 통행권: 현장 설정과 로봇 CORE 설정이 맞아야 출발한다
  TRIP_AUTHORITY_SITE_OFF: '이 로봇 CORE는 통행권이 있어야 움직이는데 현장 통행권이 꺼져 있습니다 · 현장 설정을 켜거나 로봇의 통행권 필수를 끄세요',
  TRIP_AUTHORITY_NOT_REQUIRED: '현장은 통행권을 보내는데 이 로봇 CORE는 통행권 없이 움직입니다 · 로봇 설정에서 통행권 필수를 켜세요',
  // D-525 가상 신호
  TRIP_SIGNAL_START_IN_ZONE: '신호 교차로 안에서는 출발할 수 없습니다 · 교차로 밖으로 옮긴 뒤 다시 하세요',
  // D-517 3: 구역 안에서는 서지 않는다
  TRIP_STOP_IN_ZONE: '경로 위에 구역(교차로) 밖에 설 장소가 없습니다 · 다른 목적지를 고르세요',
  TRIP_SIGNAL_NEEDS_AUTHORITY: '경로가 신호 교차로를 지나는데 이 로봇은 통행권(CORE)을 받지 않습니다 · 적색에서 선다는 보장이 없습니다',
  TRIP_ROBOT_BUSY: '이 로봇은 운행 중입니다 · 운행을 먼저 취소하세요',
  TRIP_ALREADY_STARTED: '이미 출발시킨 경로입니다',
  TRIP_NOT_RUNNING: '진행 중인 운행이 아닙니다',
  TRIP_UNKNOWN: '없는 운행입니다',
  TRIP_NO_REPLAN: '확인할 바뀐 경로가 없습니다',
  TRIP_REPLAN_FAILED: '다시 계산한 경로가 없습니다 · 운행을 취소하세요',
  TRIP_EXECUTION_NOT_AVAILABLE: '출발은 운행 시작 버튼으로 따로 합니다',
  // D-541 7 trip lease: CORE가 운행 중 로봇을 쥐게 한다
  TRIP_LEASE_UNSUPPORTED: '이 로봇 CORE는 운행 점유(trip lease)를 모릅니다 · 현장이 점유를 요구합니다 · 새 이미지가 필요합니다',
  TRIP_ROBOT_LEASED: '다른 운행이 이 로봇을 쥐고 있습니다 · 그 운행이 끝난 뒤 다시 하세요',
  TRIP_LEASED: '다른 운행이 이 로봇을 쥐고 있습니다',  // CORE's code (D-541 2), as Fleet's TRIP_ROBOT_LEASED
  TRIP_ROBOT_MANUAL: '로봇이 수동(MANUAL) 모드입니다 · 로봇을 멈춤(IDLE)으로 둔 뒤 다시 출발하세요',
  CALIBRATION_ACTIVE: '로봇이 보정 중입니다 · 보정이 끝난 뒤 다시 출발하세요',
  TRIP_LEASE_REFUSED: '로봇 CORE가 운행 점유를 거절했습니다(비상 정지·도킹 등) · 로봇 상태를 확인하세요',
  TRIP_ROBOT_UNREACHABLE: '로봇에 지시를 보내지 못했습니다',
};
/** D-541 5/7: why CORE ended the trip lease (``detail.lease_reason``). */
const LEASE_END_LABEL = {
  taken_over: '로봇 화면·Pilot에서 넘겨받음', expired: '점유가 만료됨(관제 연결이 끊겼던 듯)',
  mode_left: '로봇이 운행 모드를 떠남(멈춤·수동·도킹·막힘 중단)', estop: '비상 정지', released: '점유를 놓음',
  core_restarted: '로봇 CORE가 다시 시작됨', leased: '다른 운행이 로봇을 쥠', renew_timeout: '점유 갱신 응답이 없음',
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
  junction_corner_hold: '지시한 교차로 바로 앞에서 차선 모서리로 돌지 않게 멈췄습니다 · 차선 주행을 껐습니다 · 현장을 확인하세요',
  junction_no_window: '교차로 위치를 확인할 기대 창이 없어 좌·우 회전 지시를 보내지 않고 멈췄습니다 · 차선 주행을 껐습니다',
  stall: '경로를 따라 나아가지 않아 멈췄습니다 · 현장을 확인하세요',
  lane_arc: '회전교차로 호를 달리던 로봇이 멈췄습니다 · 차선 주행을 껐습니다 · 현장을 확인하세요',
  TRIP_LOOP_ERROR: '관제 운행 처리에 오류가 나 멈췄습니다 · 로봇 정지를 확인하고 관리자에게 알리세요',
  restart: '관제 서버가 다시 시작돼 멈췄습니다 · 자동으로 다시 출발하지 않습니다',
  TRIP_ROBOT_JUNCTION_UNSUPPORTED: '로봇 CORE가 교차로 지시를 모릅니다 · 새 이미지가 필요합니다',
  TRIP_ROBOT_UNREACHABLE: '로봇에 지시를 보내지 못했습니다',
  TRIP_GOAL_REFUSED: '로봇이 목적지 지시를 거절해 멈췄습니다 · 현장을 확인하세요',
  LINE_FOLLOW_NOT_ACTIVE: '로봇의 차선 주행이 켜져 있지 않습니다',
  lease_lost: '운행 끝 · 다시 몰려면 새 운행을 시작하세요',
  TRIP_LINE_FOLLOW_START_FAILED: '로봇이 카메라 차선 주행을 켜지 못해 운행을 멈췄습니다',
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
  SITE_MAP_NO_LANE_GRAPH: '가져올 lane_graph가 설정되지 않았거나 읽을 수 없습니다',
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

/** D-601 D: "출발 가능" / "방향 반대(178°)" / "차선 밖 5 cm" from a plan's ``start_check``. */
export function startCheckText(check) {
  if (!check?.code) return '출발 가능';
  if (check.code === 'TRIP_START_OFF_LANE') return `차선 밖 ${Math.round((check.off_lane_m || 0) * 100)} cm`;
  const err = Math.abs(check.heading_err_deg ?? NaN);
  if (!Number.isFinite(err)) return '방향 모름';
  return `${err > 90 ? '방향 반대' : '방향 어긋남'}(${err.toFixed(0)}°)`;
}

export function tripErrorText(code, detail = {}) {
  const base = TRIP_ERROR_LABEL[code] || `경로 계획 거절 (${code || '알 수 없음'})`;
  if (/HEADING_CONFLICT|START_HEADING_MISMATCH/.test(code || '') && detail?.heading_err_deg != null)
    return `${base} · ${startCheckText({...detail, code: 'heading'})}`;
  if (/START_OFF_(LANE|MAP)/.test(code || '') && detail?.off_lane_m != null)
    return `${base} · ${startCheckText({...detail, code: 'TRIP_START_OFF_LANE'})}`;
  if (code?.endsWith('LOOP_FULL') && Number.isInteger(detail.robots) && Number.isInteger(detail.capacity))
    return `${base} · 고리 ${detail.robots}/${detail.capacity}대`;  // robots counts this one too
  if (code !== 'TRIP_NO_ROUTE') return base;
  const leg = Number.isInteger(detail.segment) ? ` · ${detail.segment + 1}번째 구간` : '';
  return base + leg + (detail.unblock_would_help ? ' · 막은 차로를 풀면 길이 있습니다' : '');
}

/** Map metres <-> SVG pixels; map y goes up, SVG y goes down. ``turn`` (0/90/180/270) turns the
 * whole view clockwise on screen (D-513 7) so the map reads the way the turned camera picture does.
 * ``discs`` ({x, y, r} metres, D-540 4 robot rings) are kept inside the view too. */
export function fitView(map, width, height, pad = 24, turn = 0, discs = []) {
  const q = turn * Math.PI / 180, c = Math.round(Math.cos(q)), s = Math.round(Math.sin(q));
  const rot = (x, y) => [x * c + y * s, -x * s + y * c];
  const xs = [], ys = [];
  const add = (x, y) => { const [rx, ry] = rot(x, y); xs.push(rx); ys.push(ry); };
  for (const place of map.places) add(place.x, place.y);
  for (const edge of map.edges) for (const [x, y] of edge.polyline) add(x, y);
  for (const {x, y, r} of discs) for (const [dx, dy] of [[-r, -r], [r, r]]) add(x + dx, y + dy);  // any 90° turn of a box
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
  return planeView(b, width, height, turn);
}

// A map-aligned picture of bounds ``b`` (m): the view, and its rectangle drawn unturned around its
// centre, then turned (D-513 7).
export function planeView(b, width, height, turn = 0) {
  const places = [{x: b.min_x, y: b.min_y}, {x: b.max_x, y: b.max_y}];
  const view = fitView({places, edges: []}, width, height, 24, turn);
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

/** D-541 7: e.g. "로봇 화면·Pilot에서 넘겨받음(kim-tablet)". */
function leaseEndText(trip) {
  const why = LEASE_END_LABEL[trip.detail?.lease_reason] || trip.detail?.lease_reason || '점유를 잃음';
  return trip.detail?.lease_by ? `${why}(${trip.detail.lease_by})` : why;
}

/** D-540 (d): why a trip stopped or failed, for the card line and the queue; '' for any other state. */
export function tripEndText(trip) {
  if (trip?.state !== 'stopped' && trip?.state !== 'failed') return '';
  const why = trip.reason === 'lease_lost' ? leaseEndText(trip) : TRIP_REASON_LABEL[trip.reason] || trip.reason;
  return [`운행 ${TRIP_STATE_LABEL[trip.state]}`, why].filter(Boolean).join(' · ');
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
  if (trip.stop_moved) {  // D-517 3 (2026-10-09 "다음 지점까지 가서 섬"): never stands inside a zone
    const {from, to} = trip.stop_moved;
    parts.push(`목적지 ${names.get(from) || from || '좌표'} → ${names.get(to) || to} · 교차로 안에 서지 않도록 다음 지점에서 섭니다`);
  }
  if (trip.reason === 'stall' && Number.isFinite(trip.detail?.stall_s)) {
    parts.push(`${trip.detail.stall_s}초 넘게 ${TRIP_REASON_LABEL.stall}`);
  } else if (trip.reason) {
    parts.push(TRIP_REASON_LABEL[trip.reason] || trip.reason);
  }
  if (trip.reason === 'lease_lost') parts.push(leaseEndText(trip));
  else if (trip.lease?.state === 'held') parts.push('CORE 점유 중');
  if (trip.detail?.junction_retry) parts.push(TRIP_REASON_LABEL[trip.detail.junction_retry] || trip.detail.junction_retry);
  if (trip.detail?.junction_fields_dropped) parts.push('활성 지도가 바뀌어 교차로 기대 값을 보내지 않았습니다');
  if (trip.reason === 'lane_arc' && trip.detail?.arc_reason) parts.push(`사유 ${trip.detail.arc_reason}`);  // D-520 2
  if (trip.detail?.junction_reason === 'arc_mismatch') parts.push('호 끝 장소와 다른 장소의 지시라 로봇이 버렸습니다');
  if (trip.detail?.arc_end_unarmed) parts.push('호 끝에 다음 지시가 없어 로봇이 일반 차선 추종으로 돌아갔습니다');
  if (trip.reason === 'junction_unexpected') {  // D-507 3: where it stopped and why CORE held
    const {x, y} = trip.pose || {};
    if (Number.isFinite(x) && Number.isFinite(y)) parts.push(`지도 자세 (${x.toFixed(2)}, ${y.toFixed(2)})`);
    const why = trip.detail?.junction_reason || trip.detail?.line_reason;
    if (why) parts.push(`사유 ${why}`);
  }
  return parts.join(' · ');
}

/** D-517 2: a lap over the start places, beginning and ending at ``start`` (the robot's own place). */
export function repeatTripBody(map, start, leader = '') {
  const starts = (map?.places || []).filter(place => place.kind === 'start').map(place => place.id);
  if (!starts.includes(start)) throw new Error('출발 자리를 고르세요');
  const via = starts.filter(id => id !== start);
  if (!via.length) throw new Error('반복 운행에는 출발 자리가 두 곳 이상 필요합니다');
  const at = starts.indexOf(start);
  return {to: start, via: [...starts.slice(at + 1), ...starts.slice(0, at)], repeat: true,
    ...(leader ? {convoy: {leader}} : {})};
}

/** A finite circuit through another stop, ending at the selected starting place. */
export function oneLapBody(map, start, via) {
  const stops = (map?.places || []).filter(place => ['start', 'stop'].includes(place.kind)).map(place => place.id);
  if (!stops.includes(start) || !stops.includes(via) || start === via) {
    throw new Error('출발·경유 정지 장소를 서로 다르게 고르세요');
  }
  return {to: start, via: [via], repeat: false, start_at: start};
}

export function oneLapReason({active, running, start, via}) {
  if (!active) return '활성 지도가 없습니다';
  if (running) return '이 로봇은 이미 운행 중입니다';
  const stops = (active.map?.places || []).filter(place => ['start', 'stop'].includes(place.kind));
  if (stops.length < 2) return '한 바퀴에는 정지 장소가 두 곳 이상 필요합니다';
  return start && via && start !== via ? '' : '서로 다른 출발·경유 장소를 고르세요';
}

// D-540 (d): the one trip path — plan (a preview on the site map and the 관제 card, nothing moves), then
// the card starts that plan. Server routes are the D-494 ones; the card cancels through roster.js.
const JSON_POST = {method: 'POST', headers: {'Content-Type': 'application/json'}};
export function planTrip(request, robotId, body) {
  return request(`/api/fleet/robots/${encodeURIComponent(robotId)}/trip`, {...JSON_POST, body: JSON.stringify(body)});
}
export function startTrip(request, planId) {
  return request(`/api/fleet/trips/${encodeURIComponent(planId)}/start`, {method: 'POST'});
}
/** Why a trip request was refused, in operator words. */
export function tripRefusalText(error) {
  return error.code ? tripErrorText(error.code, error.detail) : siteMapErrorText(error);
}
/** "3개 차로 · 2.10 m · 약 14 s · 지도 v4" for a computed plan. */
export function planSummaryText(plan) {
  return `${plan.segments.length}개 차로 · ${plan.length_m.toFixed(2)} m · 약 ${Math.round(plan.eta_s)} s · 지도 v${plan.map_version}`
    + (plan.start_check ? ` · ${startCheckText(plan.start_check)}` : '');
}
/** '' when a repeat trip may start from ``start``; otherwise why not (role and robot checks are the caller's). */
export function repeatTripReason({active, running, start}) {
  if (!active) return '활성 지도가 없습니다';
  if (running) return '이 로봇은 이미 운행 중입니다';
  if ((active.map?.places || []).filter(place => place.kind === 'start').length < 2)
    return '반복 운행에는 출발 자리가 두 곳 이상 필요합니다';
  return start ? '' : '출발 자리를 고르세요';
}

/** D-517 9 M3: robots ``robotId`` may follow — open repeat trips that follow nobody. */
export function convoyLeaders(open, robotId) {
  return (open || []).filter(trip => trip.repeat && !trip.convoy && trip.robot_id !== robotId)
    .map(trip => trip.robot_id);
}

/** '' when the plan may start now; otherwise why the start button is off. */
export function tripStartReason({role, plan, active, running, now = Date.now() / 1000}) {
  if (role !== 'operator') return role ? '운영자 권한이 필요합니다' : '관제 접속이 필요합니다';
  if (running) return '이 로봇은 이미 운행 중입니다';
  if (!plan) return '먼저 경로를 계산하세요';
  if (!planIsCurrent(plan, active)) return '활성 지도가 바뀌었습니다 · 다시 계산하세요';
  if (plan.expires_at && now > plan.expires_at) return '계산한 지 30초가 지났습니다 · 다시 계산하세요';
  if (plan.start_check?.code) return `${startCheckText(plan.start_check)} · ${TRIP_ERROR_LABEL[plan.start_check.code]}`;
  return '';
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
// 관제 화면(map-view.js·roster.js·card-trip.js)이 쓴다.
// 표가 말하는 것만 옮긴다. M1 에서 Fleet 은 블록 표를 계산해 보이기만 하고 로봇에 보내지 않는다.
// 좌표는 활성 지도 미터다. 화면 방향(D-513 7)과 위에서 본 보기(D-515)는 그리는 쪽의 toPx 가 맡는다.

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
  const bands = [], zones = [], ticks = [], convoys = [];
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
      const signal = (traffic.signals || []).find((s) => s.zone === unit.id);  // D-525 8
      zones.push({ unit: unit.id, lines, anchor: pointAt(lines[0], knots, knots.at(-1) / 2),
        label: `점유 ${(unit.holders || []).length}/${unit.capacity} · 대기 ${(unit.waiting || []).length}${signal ? ` · ${signalText(signal)}` : ""}` });
    }
  }
  const plans = new Map(trips.map((trip) => [trip.robot_id, trip.plan?.segments]));
  for (const robot of traffic.robots || []) {
    if (typeof robot.authority_end_m !== "number") continue;
    const at = routePoint(plans.get(robot.robot_id), edges, robot.authority_end_m);
    if (at) ticks.push({ ...at, robot: robot.robot_id });
  }
  // D-517 10: 대열은 앞 로봇(따라가는 대상, 모르면 리더)에서 팔로워로 가는 가는 선 하나.
  const front = (id) => {
    const row = (traffic.robots || []).find((r) => r.robot_id === id);
    return typeof row?.front_d_m === "number" ? routePoint(plans.get(id), edges, row.front_d_m) : null;
  };
  for (const robot of traffic.robots || []) {
    const ahead = robot.convoy && (robot.convoy.follows || robot.convoy.leader);
    const from = ahead && front(ahead), to = ahead && front(robot.robot_id);
    if (from && to) convoys.push({ from, to, robot: robot.robot_id, leader: robot.convoy.leader });
  }
  // D-525 8: 가상 신호 — 접근로마다 정지선 막대와 등 색, 신호마다 "가상 신호 · 녹 5 s" 한 줄.
  const signals = [];
  for (const signal of traffic.signals || []) {
    for (const row of signal.approaches || []) {
      if (!row.stop_line) continue;
      const count = countdownText(row);
      const occupancy = occupancyLampText(signal, row);  // D-525 rev 6: the zone state in words
      signals.push({ x: row.stop_line.x, y: row.stop_line.y, angle: row.stop_line.yaw, lamp: row.lamp,
        label: `${signal.signal_id} · ${signalLampText(row.lamp)}`, signal: signal.signal_id,
        count, approach: row.approach,
        text: occupancy || (count ? `${signalLampText(row.lamp)} ${count}` : signalLampText(row.lamp)) });
    }
  }
  const xs = [...edges.values()].flatMap((edge) => edge.polyline.map((p) => p[0]));
  const ys = [...edges.values()].flatMap((edge) => edge.polyline.map((p) => p[1]));
  const centre = xs.length ? [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2] : [0, 0];
  return { bands, zones, ticks, convoys, centre, signals };
}

const LAMP_TEXT = { green: "녹", yellow: "황", red: "적" };
export const signalLampText = (lamp) => LAMP_TEXT[lamp] || "적";

/** D-525 rev 6 the occupancy-mode zone state: "비어 있음", "점유 예정 · rosy_01", "점유 중 · rosy_01". */
function occupancyStateText(occupancy) {
  const who = occupancy?.holder ? ` · ${occupancy.holder}` : "";
  return { free: "비어 있음", reserved: `점유 예정${who}`, occupied: `점유 중${who}` }[occupancy?.state]
    || "상태 모름 · 적색";
}

/** D-525 rev 6: one approach's lamp in words in occupancy mode (never colour alone): "초록 · 비어 있음",
 * "주황 · 점유 예정 · rosy_01", "적 · 점유 중 · rosy_01"; the holder's own approach while reserved is
 * "초록 · 진입 차례 · rosy_01". null outside occupancy mode or with a config error. */
export function occupancyLampText(signal, row) {
  if (signal?.mode !== "occupancy" || signal.errors?.length) return null;
  const occupancy = signal.occupancy || {};
  if (row?.lamp === "green") {
    return occupancy.state === "reserved" ? `초록 · 진입 차례${occupancy.holder ? ` · ${occupancy.holder}` : ""}`
      : "초록 · 비어 있음";
  }
  if (row?.lamp === "yellow") return `주황 · ${occupancyStateText(occupancy)}`;
  return `적 · ${occupancyStateText(occupancy)}`;
}

/** D-525 rev 3 T-map style seconds for one approach: "7" (exact), "≥7" (a lower bound), "" (unknown). */
export function countdownText(row) {
  const s = row?.lamp === "red" ? row?.green_in_s ?? row?.left_s : row?.left_s;
  if (typeof s !== "number") return "";
  return `${row.exact ? "" : "≥"}${Math.ceil(s)}`;
}

/** Robot card text for the next signal on its route: "신호 sig 적 · 녹색까지 ≥7 s · 정지선 0.40 m". */
export function signalAheadText(ahead) {
  if (!ahead) return "";
  const lamp = ahead.mode === "occupancy"
    ? occupancyLampText(ahead, { lamp: ahead.lamp }) : signalLampText(ahead.lamp);
  const wait = ahead.lamp !== "green" && typeof ahead.green_in_s === "number"
    ? ` · 녹색까지 ${ahead.exact ? "" : "≥"}${Math.ceil(ahead.green_in_s)} s` : "";
  const where = ahead.distance_m >= 0 ? ` · 정지선 ${ahead.distance_m.toFixed(2)} m` : " · 교차로 안";
  return `가상 신호 ${ahead.signal_id} ${lamp}${wait}${where}${ahead.may_enter ? " · 진입 허가" : ""}`;
}

/** D-525: the virtual signal a robot waits at (its waiting_for is `signal:<zone>`), or null. */
export function signalWait(traffic, robotId) {
  const robot = (traffic?.robots || []).find((row) => row.robot_id === robotId);
  const node = (robot?.waiting_for || []).find((id) => id.startsWith("signal:"));
  if (!node) return null;
  return (traffic.signals || []).find((s) => s.zone === node.slice(7)) || { signal_id: node.slice(7), zone: node.slice(7) };
}

/** "가상 신호 · 녹 5 s" for one signal row of /traffic. */
export function signalText(signal) {
  if (signal.errors?.length) return `${signal.signal_id} · 설정 오류 · 늘 적색`;
  if (signal.mode === "occupancy") return `가상 신호 ${signal.signal_id} · 점유 기반(기본) · ${occupancyStateText(signal.occupancy)}`;
  const word = { green: "녹", yellow: "황", all_red: "전체 적색" }[signal.aspect] || signal.aspect;
  const left = typeof signal.left_s === "number" ? ` ${Math.ceil(signal.left_s)} s` : "";
  const mode = { hold: " · 유지", all_red: " · 운영자 전체 적색" }[signal.mode] || "";
  return `가상 신호 ${signal.signal_id} · ${word}${left}${mode}`;
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
  const convoy = robot.convoy;  // D-517 10: "대열 · rosy_01 뒤 0.5 m"; 앞 로봇을 모르면 고정 블록
  if (convoy) {
    parts.push(convoy.follows ? `대열 · ${convoy.follows} 뒤${typeof convoy.gap_m === "number" ? ` ${convoy.gap_m.toFixed(1)} m` : ""}`
      : `대열 · ${convoy.leader} 위치 모름 · 고정 블록`);
  }
  // D-517 9: the leader's card names who laps behind it (the follower's card names the leader above).
  const behind = (traffic.robots || []).filter((row) => row.convoy?.leader === robotId).map((row) => row.robot_id);
  if (behind.length) parts.push(`대열 리더 · ${behind.join(", ")} 따라옴`);
  const held = (traffic.units || []).some((unit) => unit.state === "UNKNOWN" && (unit.holders || []).includes(robotId));
  const unit = waitingUnit(traffic, robotId);
  const signal = signalWait(traffic, robotId);
  if (held) parts.push("위치 불명 · 블록 유지");
  else if (robot.signal_ahead && robot.signal_ahead.distance_m < 1.5) parts.push(signalAheadText(robot.signal_ahead));
  else if (signal) parts.push(`신호 대기 · ${signal.signal_id} 적색`);
  else if (unit && isZone(unit)) {
    const ahead = (unit.holders || []).filter((id) => id !== robotId);
    parts.push(`${twoWay(unit) ? "양방 차로" : "교차로"} 대기${ahead.length ? ` · ${ahead.join(", ")} 통과 중` : ""}`);
  } else if (robot.waiting_for?.length && !(convoy?.follows && robot.waiting_for.join() === convoy.follows)) parts.push(`앞 블록 대기 · ${robot.waiting_for.join(", ")}`);
  const resolver = (traffic.resolver || []).find((row) => row.robot_id === robotId);  // D-517 5 (M4)
  if (resolver?.trigger === "wait_cycle") {
    parts.push(`교착 · ${RESOLVER_DECISION_LABEL[resolver.decision] || RESOLVER_DECISION_LABEL.human}`);
  } else if (traffic.wait_cycle?.includes(robotId)) {
    parts.push("대기 순환 후보 · 지속 여부 확인 중");
  }
  if (!parts.length) parts.push(robot.trip_state === "started" ? "운행 출발 대기" : "운행 중");
  const advice = robot.advice;  // D-551: display-only signal advice to CORE
  if (advice?.signal) parts.push(`신호 참고 전송 · seq ${advice.sent_seq}${advice.accepted ? "" : ` · ${advice.reason || "미수락"}`}`);
  return parts.join(" · ");
}

/** When the console first saw each robot wait at a zone entry (UNKNOWN 30 s is Fleet's resolver row). */
export function trafficClock(prev, traffic, now) {
  const next = { merge: {} };
  for (const unit of traffic?.units || []) {  // D-525 3: a red wait is not a merge wait
    if (isZone(unit)) for (const id of unit.waiting || []) if (!signalWait(traffic, id)) next.merge[id] = prev?.merge?.[id] ?? now;
  }
  return next;
}

/**
 * Exception-queue rows (D-493 one rule) for one robot. A block wait itself is normal and is not a row.
 * D-517 5 (M4): a wait cycle and a 30 s UNKNOWN carry Fleet's resolver decision (`traffic.resolver`).
 * ponytail: the merge clock starts when this console first saw the wait (a reload restarts it);
 * move it to /traffic if the 20 s row must survive a reload.
 */
export function trafficAttention(traffic, robotId, clock, now) {
  const items = [];
  const cycle = traffic?.wait_cycle;
  const resolver = traffic?.resolver || [];
  const mine = resolver.find((row) => row.robot_id === robotId);
  if (Array.isArray(cycle) && cycle.includes(robotId)) {
    const replanned = resolver.find((row) => row.trigger === "wait_cycle" && row.decision === "replan");
    const then = mine?.decision === "replan" ? "해결기: 다른 길 계획 · 다음 장소에서 운영자 확인"
      : mine?.decision === "wait" && replanned ? `해결기: ${replanned.robot_id} 다른 길 대기` : "운영자 판단 필요";
    const confirmed = resolver.some((row) => row.trigger === "wait_cycle");
    items.push(confirmed
      ? { severity: "crit", decision: "deadlock", text: `: 교착 — ${[...cycle, cycle[0]].join(" → ")} 서로 기다림 · ${then}` }
      : { severity: "warn", text: `: 대기 순환 후보 — ${[...cycle, cycle[0]].join(" → ")} · 지속 여부 확인 중` });
  }
  if (mine?.trigger === "unknown") {
    items.push({ severity: "crit", text: ": 위치 불명 30초 넘음 — 블록을 풀지 않습니다 · 로봇 위치를 확인하세요" });
  }
  const mergeSince = clock?.merge?.[robotId];
  if (mergeSince !== undefined && now - mergeSince > MERGE_MAX_WAIT_MS) {
    items.push({ severity: "warn", text: `: 합류 대기 ${Math.floor((now - mergeSince) / 1000)}초 — 구역 ${waitingUnit(traffic, robotId)?.id || ""} 입구` });
  }
  const signal = signalWait(traffic, robotId);  // D-525 8: rows only for robots held at that signal
  if (signal?.errors?.length) items.push({ severity: "crit", text: `: 신호 ${signal.signal_id} 설정 오류 — 구역이 늘 적색입니다 · ${signal.errors[0]}` });
  else if (signal?.alert === "all_red_stretched") items.push({ severity: "crit", text: `: 신호 ${signal.signal_id} 전체 적색 30초 넘음 — 구역이 비지 않습니다 · 구역 안 로봇을 확인하세요` });
  else if (signal?.alert === "hold_long") items.push({ severity: "warn", text: `: 신호 ${signal.signal_id} 유지 2분 넘음 — 다른 입구가 기다립니다` });
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

/** D-573 1: append one waiting band (map metres, mm-rounded) to crosswalk ``id``; the server
 * checks it reaches the lane and stays on the site floor when the draft is saved. */
export function addApproach(map, id, points) {
  if (points.length < 3) throw new Error('대기 띠는 점이 세 개 이상이어야 합니다');
  const next = copy(map);
  const crosswalk = (next.crosswalks || []).find(item => item.id === id);
  if (!crosswalk) throw new Error(`없는 횡단보도 ${id}`);
  if ((crosswalk.approach || []).length >= 4) throw new Error('대기 띠는 횡단보도마다 4개까지입니다');
  const mm = value => Math.round(value * 1000) / 1000;
  crosswalk.approach = [...(crosswalk.approach || []), points.map(([x, y]) => [mm(x), mm(y)])];
  return next;
}

export function removeApproach(map, id, index) {
  const next = copy(map);
  const crosswalk = (next.crosswalks || []).find(item => item.id === id);
  if (!crosswalk?.approach?.[index]) throw new Error('지울 대기 띠가 없습니다');
  crosswalk.approach.splice(index, 1);
  return next;
}

/** D-573 1: lane_graph crosswalks replace the draft's polygons by id; drawn bands are kept. */
export function mergeCrosswalks(map, imported) {
  const next = copy(map);
  const had = new Map((next.crosswalks || []).map(item => [item.id, item]));
  next.crosswalks = imported.map(item => ({...copy(item), approach: had.get(item.id)?.approach || []}));
  return next;
}
