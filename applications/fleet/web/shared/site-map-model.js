import {DRAWING_ERROR_LABEL} from './drawing-errors.js';
import {ACTION_LABEL, RESOLVER_DECISION_LABEL, TRIP_ERROR_LABEL, startCheckText, tripErrorText} from './trip-display.js';
export {routeAttention} from './route-attention.js';

export const PLACE_KINDS = ['junction', 'park', 'charge', 'stop', 'slow', 'turnaround', 'start'];
export const PLACE_KIND_LABEL = { junction: '교차', park: '주차', charge: '충전', stop: '정차', slow: '감속', turnaround: '회차', start: '출발' };
export const SITE_MAP_ERROR_LABEL = {
  SITE_MAP_NOT_ACTIVE: '활성 지도가 없습니다', SITE_MAP_NO_DRAFT: '저장된 초안이 없습니다',
  SITE_MAP_DRAFT_CHANGED: '다른 운영자가 초안을 바꿨습니다. 현재 수정은 저장되지 않았습니다. 현재 변경 내용을 별도로 기록한 뒤 화면을 새로고침해 최신 초안을 확인하세요. 저장하지 않은 편집은 사라집니다.',
  SITE_MAP_PROFILE_CHANGED: '다른 운영자가 프로필을 바꿨습니다. 수정한 규칙을 복사해 둔 뒤 다시 접속하세요.',
  SITE_MAP_PROFILE_LIMIT: '지도 프로필은 최대 100개입니다. 기존 프로필을 선택해 수정하세요.',
  SITE_MAP_ROUTE_ACTIVE: '운행·대형·지도 기록이 진행 중입니다 · 끝난 뒤 활성화하세요',
  SITE_MAP_UNPLANNABLE: '경로 계산에 쓸 수 없는 지도입니다', SITE_MAP_SURVEY_UNREVIEWED: '조사 좌표 기준과 축척 근거를 먼저 검토하세요',
  SITE_MAP_ROAD_UNREVIEWED: '관측·추정한 도로·시설을 검토하고 근거를 남기세요',
  SITE_MAP_EXCLUSION_OVERLAP: '금지 구역과 겹치는 주행 차로를 수정하세요',
  SITE_MAP_START_INVALID: '출발 자리가 차로 위에 없거나 차로 방향과 다르게 놓였습니다',
  SITE_MAP_TOO_LARGE: '지도가 너무 큽니다', SITE_MAP_INVALID: '지도에 맞지 않는 값이 있습니다',
  SITE_MAP_NO_LANE_GRAPH: '가져올 lane_graph가 설정되지 않았거나 읽을 수 없습니다',
  TEACH_BUSY: '다른 로봇을 기록하는 중입니다 · 한 번에 한 대만 가르칩니다', TEACH_NOT_RECORDING: '기록 중이 아닙니다',
  TEACH_POSE_UNTRUSTED: '로봇 지도 위치가 LOCALIZED가 아닙니다 · Rosy Cam이 로봇을 보는 곳에서 다시 하세요',
  TEACH_SURVEY_REQUIRED: '조사 기준이 있는 초안을 먼저 만들어 저장하세요',
  TEACH_SURVEY_CHANGED: '기록의 조사 기준과 현재 초안이 다릅니다 · 기존 기준을 확인하세요',
  TEACH_MAP_CHANGED: '로봇 위치와 초안의 지도 기준이 다릅니다 · 활성 지도와 기록 기준을 확인하세요',
  TEACH_ODOM_UNAVAILABLE: '신선한 로봇 주행 좌표를 읽을 수 없습니다 · 로봇 연결과 odom을 확인하세요',
  TEACH_MODE_INVALID: '기록 좌표 방식과 조사 기준을 확인하세요', TEACH_TOO_SHORT: '기록한 길이 0.1 m보다 짧아 버렸습니다',
  TEACH_UNKNOWN: '확정할 기록이 없습니다 · 10분이 지났거나 이미 확정했습니다',
  TEACH_UNKNOWN_PLACE: '없는 장소입니다', TEACH_PLACE_TOO_FAR: '고른 장소가 기록 끝에서 0.15 m보다 멉니다',
  UNKNOWN_ROBOT: '등록되지 않은 로봇입니다',
};

export function siteMapErrorText(error) {
  if (error.code === 'PASSWORD_CHANGE_REQUIRED') return '첫 로그인 비밀번호 변경이 필요합니다 · 우상단 비밀번호 변경을 누르세요';
  if (error.status === 401) return '관제 토큰을 확인하고 다시 접속하세요';
  if (error.status === 403) return '운영자 권한이 필요합니다 · 계정을 확인하세요';
  if (error.status >= 500) return '관제 서버 응답을 확인할 수 없습니다 · 잠시 뒤 다시 접속하세요';
  if (!error.status && /Failed to fetch|NetworkError|ERR_/.test(error.message || '')) return '관제 연결이 끊겼습니다 · 네트워크를 확인하고 다시 접속하세요';
  const base = DRAWING_ERROR_LABEL[error.code] || SITE_MAP_ERROR_LABEL[error.code] || error.message || String(error);
  const fields = (error.detail?.errors || []).map(item => `${(item.loc || []).join('.')}: ${item.msg}`);
  return fields.length ? `${base} — ${fields.join(' · ')}` : base;
}

export function actionRows(plan, map) {
  const names = new Map((map?.places || []).map(place => [place.id, place.name]));
  return plan.actions.map(item => `${item.place_id ? (names.get(item.place_id) || item.place_id) : '찍은 좌표'} · ${ACTION_LABEL[item.action] || item.action}`);
}
export function planIsCurrent(plan, active) { return Boolean(plan && active && plan.map_version === active.version); }

export function fitView(map, width, height, pad = 24, turn = 0, discs = []) {
  const q = turn * Math.PI / 180, c = Math.round(Math.cos(q)), s = Math.round(Math.sin(q));
  const rot = (x, y) => [x * c + y * s, -x * s + y * c], xs = [], ys = [];
  const add = (x, y) => { const [rx, ry] = rot(x, y); xs.push(rx); ys.push(ry); };
  for (const place of map.places) add(place.x, place.y);
  for (const edge of map.edges) for (const [x, y] of edge.polyline) add(x, y);
  for (const facility of map.facilities || []) for (const [x, y] of facility.geometry) add(x, y);
  for (const {x, y, r} of discs) for (const [dx, dy] of [[-r, -r], [r, r]]) add(x + dx, y + dy);
  if (!xs.length) { const [x, y] = map.survey?.origin || [0, 0]; add(x - 1, y - 1); add(x + 1, y + 1); }
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const scale = Math.min((width - 2 * pad) / Math.max(maxX - minX, 1e-6), (height - 2 * pad) / Math.max(maxY - minY, 1e-6));
  const ox = pad + ((width - 2 * pad) - (maxX - minX) * scale) / 2, oy = pad + ((height - 2 * pad) - (maxY - minY) * scale) / 2;
  return {
    scale, turn,
    toPx: (x, y) => { const [rx, ry] = rot(x, y); return [ox + (rx - minX) * scale, oy + (maxY - ry) * scale]; },
    toMap: (px, py) => { const rx = minX + (px - ox) / scale, ry = maxY - (py - oy) / scale; return [rx * c - ry * s, rx * s + ry * c]; },
    rotateDeg: (angle) => -angle * 180 / Math.PI + turn,
  };
}

export function rectangularView(record, mapId, width, height, turn = 0) {
  const b = record?.track_bounds_m, h = record?.map_to_image;
  if (record?.map_id !== mapId || !b || !Array.isArray(h) || h.length !== 9
    || !h.every(Number.isFinite) || !Object.values(b).every(Number.isFinite)
    || !(b.max_x > b.min_x && b.max_y > b.min_y)) throw new Error('지도와 카메라 보정을 확인하세요.');
  const determinant = h[0] * (h[4] * h[8] - h[5] * h[7]) - h[1] * (h[3] * h[8] - h[5] * h[6]) + h[2] * (h[3] * h[7] - h[4] * h[6]);
  if (Math.abs(determinant) < 1e-12 || ![b.min_x, b.max_x].every(x => [b.min_y, b.max_y].every(y => h[6] * x + h[7] * y + h[8] > 1e-9)))
    throw new Error('카메라 보정의 평면 범위를 확인하세요.');
  return planeView(b, width, height, turn);
}

export function planeView(b, width, height, turn = 0) {
  const places = [{x: b.min_x, y: b.min_y}, {x: b.max_x, y: b.max_y}];
  const view = fitView({places, edges: []}, width, height, 24, turn);
  const [cx, cy] = view.toPx((b.min_x + b.max_x) / 2, (b.min_y + b.max_y) / 2);
  const fw = (b.max_x - b.min_x) * view.scale, fh = (b.max_y - b.min_y) * view.scale;
  return {view, field: {x: cx - fw / 2, y: cy - fh / 2, width: fw, height: fh, transform: `rotate(${turn} ${cx} ${cy})`}};
}

export function lengths(points) {
  const knots = [0];
  for (let i = 1; i < points.length; i += 1) knots.push(knots[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]));
  return knots;
}

export function pointAt(points, knots, s) {
  for (let i = 1; i < points.length; i += 1) {
    if (s <= knots[i] || i === points.length - 1) {
      const span = knots[i] - knots[i - 1], t = span > 0 ? Math.min(Math.max((s - knots[i - 1]) / span, 0), 1) : 0;
      const [ax, ay] = points[i - 1], [bx, by] = points[i];
      return {x: ax + t * (bx - ax), y: ay + t * (by - ay), angle: Math.atan2(by - ay, bx - ax)};
    }
  }
  return {x: points[0][0], y: points[0][1], angle: 0};
}

export function arrowMarks(edge) {
  const knots = lengths(edge.polyline), total = knots[knots.length - 1];
  const middle = pointAt(edge.polyline, knots, total / 2);
  if (edge.direction !== 'two_way') return [middle];
  const reversed = [...edge.polyline].reverse();
  return [pointAt(edge.polyline, knots, total * 0.4), pointAt(reversed, lengths(reversed), total * 0.4)];
}

export function segmentPoints(edge, forward, sFrom, sTo) {
  const line = forward ? edge.polyline : [...edge.polyline].reverse(), knots = lengths(line);
  const inside = line.filter((_p, i) => knots[i] > sFrom && knots[i] < sTo);
  const a = pointAt(line, knots, sFrom), b = pointAt(line, knots, sTo);
  return [[a.x, a.y], ...inside, [b.x, b.y]];
}

export function planPolylines(map, plan) {
  const edges = new Map(map.edges.map(edge => [edge.id, edge]));
  return plan.segments.filter(seg => edges.has(seg.edge_id)).map(seg => segmentPoints(edges.get(seg.edge_id), seg.forward, seg.s_from, seg.s_to));
}

function copy(map) { return JSON.parse(JSON.stringify(map)); }
export const VIEW_TURNS = [0, 90, 180, 270];
export function viewTurnOf(map) { return VIEW_TURNS.includes(map?.view_turn_deg) ? map.view_turn_deg : 0; }
export function editViewTurn(map, turn) {
  const value = Number(turn);
  if (!VIEW_TURNS.includes(value)) throw new Error('화면 방향은 0·90·180·270° 중 하나입니다');
  return {...copy(map), view_turn_deg: value};
}

export function repeatTripBody(map, start, leader = '') {
  const starts = (map?.places || []).filter(place => place.kind === 'start').map(place => place.id);
  if (!starts.includes(start)) throw new Error('출발 자리를 고르세요');
  const via = starts.filter(id => id !== start);
  if (!via.length) throw new Error('반복 운행에는 출발 자리가 두 곳 이상 필요합니다');
  const at = starts.indexOf(start);
  return {to: start, via: [...starts.slice(at + 1), ...starts.slice(0, at)], repeat: true, ...(leader ? {convoy: {leader}} : {})};
}

export function oneLapBody(map, start, via) {
  const stops = (map?.places || []).filter(place => ['start', 'stop'].includes(place.kind)).map(place => place.id);
  if (!stops.includes(start) || !stops.includes(via) || start === via) throw new Error('출발·경유 정지 장소를 서로 다르게 고르세요');
  return {to: start, via: [via], repeat: false, start_at: start};
}

export function oneLapReason({active, running, start, via}) {
  if (!active) return '활성 지도가 없습니다';
  if (running) return '이 로봇은 이미 운행 중입니다';
  const stops = (active.map?.places || []).filter(place => ['start', 'stop'].includes(place.kind));
  if (stops.length < 2) return '한 바퀴에는 정지 장소가 두 곳 이상 필요합니다';
  return start && via && start !== via ? '' : '서로 다른 출발·경유 장소를 고르세요';
}

const JSON_POST = {method: 'POST', headers: {'Content-Type': 'application/json'}};
export function robotMapPose(robot) {
  const state = robot?.state, pose = state?.pose;
  if (!pose || ![pose.x, pose.y, pose.yaw].every(Number.isFinite)) return null;
  const frame = robot.localization?.pose_frame || state.localization?.pose_frame || (state.map_id ? 'map' : 'odom');
  if (frame !== 'map') return null;
  const loc = state.localization;
  return loc?.state === 'LOCALIZED' && loc.pose_frame === 'map' ? pose : null;
}
export function tripPoseReason(guide, robotId, active, corePose = null) {
  if (!guide) return '';
  if (guide.map_version !== active?.version) return '현장 지도 위치의 지도 버전이 다릅니다 · 다시 조회하세요';
  const pose = (guide.robots || []).find(row => row.robot_id === robotId)?.pose;
  if (corePose || (pose?.state === 'LOCALIZED' && [pose.x, pose.y, pose.yaw].every(Number.isFinite))) return '';
  return TRIP_ERROR_LABEL.TRIP_POSE_UNTRUSTED;
}
export function planTrip(request, robotId, body) { return request(`/api/fleet/robots/${encodeURIComponent(robotId)}/trip`, {...JSON_POST, body: JSON.stringify(body)}); }
export function startTrip(request, planId) { return request(`/api/fleet/trips/${encodeURIComponent(planId)}/start`, {method: 'POST'}); }
export function tripRefusalText(error) { return error.code ? tripErrorText(error.code, error.detail) : siteMapErrorText(error); }
export function planSummaryText(plan) {
  return `${plan.segments.length}개 차로 · ${plan.length_m.toFixed(2)} m · 약 ${Math.round(plan.eta_s)} s · 지도 v${plan.map_version}`
    + (plan.start_check ? ` · ${startCheckText(plan.start_check)}` : '');
}
export function repeatTripReason({active, running, start}) {
  if (!active) return '활성 지도가 없습니다';
  if (running) return '이 로봇은 이미 운행 중입니다';
  if ((active.map?.places || []).filter(place => place.kind === 'start').length < 2) return '반복 운행에는 출발 자리가 두 곳 이상 필요합니다';
  return start ? '' : '출발 자리를 고르세요';
}
export function convoyLeaders(open, robotId) { return (open || []).filter(trip => trip.repeat && !trip.convoy && trip.robot_id !== robotId).map(trip => trip.robot_id); }

export function tripStartReason({role, plan, active, running, now = Date.now() / 1000}) {
  if (role !== 'operator') return role ? '운영자 권한이 필요합니다' : '관제 접속이 필요합니다';
  if (running) return '이 로봇은 이미 운행 중입니다';
  if (!plan) return '먼저 경로를 계산하세요';
  if (!planIsCurrent(plan, active)) return '활성 지도가 바뀌었습니다 · 다시 계산하세요';
  if (plan.expires_at && now > plan.expires_at) return '계산한 지 30초가 지났습니다 · 다시 계산하세요';
  if (plan.start_check?.code && !plan.start_check.auto_align) return `${startCheckText(plan.start_check)} · ${TRIP_ERROR_LABEL[plan.start_check.code]}`;
  return '';
}

export function teachStatusText(view) {
  const live = view?.recording;
  if (live) return `${live.mode === 'survey' ? '조사 ' : ''}기록 중 · ${live.robot_id} · ${live.points.length}점 · ${live.started_by}`;
  const reason = {pose_lost: '위치 단절', odom_lost: '주행 좌표 단절', odom_reset: '주행 좌표 초기화',
    survey_changed: '조사 초안 변경', map_changed: '활성 지도 또는 초안 좌표계 변경'}[newestPending(view)?.reason];
  if (reason) return `기록 중단 · ${reason} · 유효한 앞부분만 확정 대기 · 로봇 정지는 별도로 확인하세요`;
  if (view?.pending?.length) return `확정 대기 ${view.pending.length}건 · 멈춘 뒤 10분 안에 확정하세요`;
  return '기록 없음';
}

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

export function newestPending(view) { return (view?.pending || []).reduce((best, item) => (!best || item.expires_at > best.expires_at ? item : best), null); }

export const MERGE_MAX_WAIT_MS = 20000;
const BLOCK_GAP_M = 0.03;
const isZone = (unit) => unit.zone === true;
const twoWay = (unit) => unit.id.startsWith("lane:");

export function unitParts(unitId, traffic) {
  if (unitId.startsWith("lane:")) return [[unitId.slice(5), 0, Infinity]];
  const hash = unitId.lastIndexOf("#");
  if (hash > 0) {
    const edge = unitId.slice(0, hash), index = Number(unitId.slice(hash + 1)), step = traffic.block_length_m?.[edge];
    return Number.isInteger(index) && step > 0 ? [[edge, index * step, (index + 1) * step]] : [];
  }
  const zones = (traffic.units || []).filter((unit) => isZone(unit) && !twoWay(unit));
  if (zones.length !== 1) return [];
  const ids = new Set((traffic.units || []).map((unit) => unit.id));
  return Object.keys(traffic.block_length_m || {}).filter((edge) => !ids.has(`${edge}#0`) && !ids.has(`lane:${edge}`)).map((edge) => [edge, 0, Infinity]);
}

function partPoints(edge, s0, s1, gap) {
  const total = lengths(edge.polyline).at(-1), a = Math.max(0, s0) + gap, b = Math.min(total, s1) - gap;
  return b > a ? segmentPoints(edge, true, a, b) : null;
}

export function routePoint(segments, edges, r) {
  let base = 0;
  for (const seg of segments || []) {
    const edge = edges.get(seg.edge_id);
    if (!edge) return null;
    const line = seg.forward ? edge.polyline : [...edge.polyline].reverse(), knots = lengths(line);
    if (r <= base + seg.s_to + 1e-9) return pointAt(line, knots, Math.min(Math.max(r - base, seg.s_from), seg.s_to));
    base += knots.at(-1);
  }
  return null;
}

export function trafficDrawing(traffic, active, trips = []) {
  if (!traffic || !active?.map || traffic.map_version !== active.version) return null;
  const edges = new Map((active.map.edges || []).map((edge) => [edge.id, edge]));
  const bands = [], zones = [], ticks = [], convoys = [], signals = [];
  for (const unit of traffic.units || []) {
    const parts = unitParts(unit.id, traffic).filter(([edge]) => edges.has(edge)), zone = isZone(unit);
    if (unit.state !== "FREE") {
      for (const [edge, s0, s1] of parts) {
        const points = partPoints(edges.get(edge), s0, s1, zone ? 0 : BLOCK_GAP_M);
        if (points) bands.push({ points, state: unit.state, robot: unit.holders?.[0] || null, unit: unit.id });
      }
    }
    if (zone && parts.length) {
      const lines = parts.map(([edge, s0, s1]) => partPoints(edges.get(edge), s0, s1, 0)).filter(Boolean);
      const knots = lengths(lines[0]), signal = (traffic.signals || []).find((s) => s.zone === unit.id);
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
  const front = (id) => {
    const row = (traffic.robots || []).find((r) => r.robot_id === id);
    return typeof row?.front_d_m === "number" ? routePoint(plans.get(id), edges, row.front_d_m) : null;
  };
  for (const robot of traffic.robots || []) {
    const ahead = robot.convoy && (robot.convoy.follows || robot.convoy.leader);
    const from = ahead && front(ahead), to = ahead && front(robot.robot_id);
    if (from && to) convoys.push({ from, to, robot: robot.robot_id, leader: robot.convoy.leader });
  }
  for (const signal of traffic.signals || []) {
    for (const row of signal.approaches || []) {
      if (!row.stop_line) continue;
      const count = countdownText(row), occupancy = occupancyLampText(signal, row);
      signals.push({ x: row.stop_line.x, y: row.stop_line.y, angle: row.stop_line.yaw, lamp: row.lamp,
        label: `${signal.signal_id} · ${signalLampText(row.lamp)}`, signal: signal.signal_id, count, approach: row.approach,
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

function occupancyStateText(occupancy) {
  const who = occupancy?.holder ? ` · ${occupancy.holder}` : "";
  return { free: "비어 있음", reserved: `점유 예정${who}`, occupied: `점유 중${who}` }[occupancy?.state] || "상태 모름 · 적색";
}

export function occupancyLampText(signal, row) {
  if (signal?.mode !== "occupancy" || signal.errors?.length) return null;
  const occupancy = signal.occupancy || {};
  if (row?.lamp === "green") return occupancy.state === "reserved" ? `초록 · 진입 차례${occupancy.holder ? ` · ${occupancy.holder}` : ""}` : "초록 · 비어 있음";
  if (row?.lamp === "yellow") return `주황 · ${occupancyStateText(occupancy)}`;
  return `적 · ${occupancyStateText(occupancy)}`;
}

export function countdownText(row) {
  const s = row?.lamp === "red" ? row?.green_in_s ?? row?.left_s : row?.left_s;
  return typeof s === "number" ? `${row.exact ? "" : "≥"}${Math.ceil(s)}` : "";
}

export function signalAheadText(ahead) {
  if (!ahead) return "";
  const lamp = ahead.mode === "occupancy" ? occupancyLampText(ahead, { lamp: ahead.lamp }) : signalLampText(ahead.lamp);
  const wait = ahead.lamp !== "green" && typeof ahead.green_in_s === "number" ? ` · 녹색까지 ${ahead.exact ? "" : "≥"}${Math.ceil(ahead.green_in_s)} s` : "";
  const where = ahead.distance_m >= 0 ? ` · 정지선 ${ahead.distance_m.toFixed(2)} m` : " · 교차로 안";
  return `가상 신호 ${ahead.signal_id} ${lamp}${wait}${where}${ahead.may_enter ? " · 진입 허가" : ""}`;
}

export function signalWait(traffic, robotId) {
  const robot = (traffic?.robots || []).find((row) => row.robot_id === robotId);
  const node = (robot?.waiting_for || []).find((id) => id.startsWith("signal:"));
  if (!node) return null;
  return (traffic.signals || []).find((s) => s.zone === node.slice(7)) || { signal_id: node.slice(7), zone: node.slice(7) };
}

export function signalText(signal) {
  if (signal.errors?.length) return `${signal.signal_id} · 설정 오류 · 늘 적색`;
  if (signal.mode === "occupancy") return `가상 신호 ${signal.signal_id} · 점유 기반(기본) · ${occupancyStateText(signal.occupancy)}`;
  const word = { green: "녹", yellow: "황", all_red: "전체 적색" }[signal.aspect] || signal.aspect;
  const left = typeof signal.left_s === "number" ? ` ${Math.ceil(signal.left_s)} s` : "";
  const mode = { hold: " · 유지", all_red: " · 운영자 전체 적색" }[signal.mode] || "";
  return `가상 신호 ${signal.signal_id} · ${word}${left}${mode}`;
}

function waitingUnit(traffic, robotId) { return (traffic?.units || []).find((unit) => (unit.waiting || []).includes(robotId)) || null; }

export function trafficCardLine(traffic, robotId) {
  const robot = (traffic?.robots || []).find((row) => row.robot_id === robotId);
  if (!robot) return "";
  const parts = [];
  if (typeof robot.lap === "number") parts.push(`반복 운행 ${robot.lap}바퀴째`);
  const convoy = robot.convoy;
  if (convoy) parts.push(convoy.follows ? `대열 · ${convoy.follows} 뒤${typeof convoy.gap_m === "number" ? ` ${convoy.gap_m.toFixed(1)} m` : ""}` : `대열 · ${convoy.leader} 위치 모름 · 고정 블록`);
  const behind = (traffic.robots || []).filter((row) => row.convoy?.leader === robotId).map((row) => row.robot_id);
  if (behind.length) parts.push(`대열 리더 · ${behind.join(", ")} 따라옴`);
  const held = (traffic.units || []).some((unit) => unit.state === "UNKNOWN" && (unit.holders || []).includes(robotId));
  const unit = waitingUnit(traffic, robotId), signal = signalWait(traffic, robotId);
  if (held) parts.push("위치 불명 · 블록 유지");
  else if (robot.signal_ahead && robot.signal_ahead.distance_m < 1.5) parts.push(signalAheadText(robot.signal_ahead));
  else if (signal) parts.push(`신호 대기 · ${signal.signal_id} 적색`);
  else if (unit && isZone(unit)) {
    const ahead = (unit.holders || []).filter((id) => id !== robotId);
    parts.push(`${twoWay(unit) ? "양방 차로" : "교차로"} 대기${ahead.length ? ` · ${ahead.join(", ")} 통과 중` : ""}`);
  } else if (robot.waiting_for?.length && !(convoy?.follows && robot.waiting_for.join() === convoy.follows)) parts.push(`앞 블록 대기 · ${robot.waiting_for.join(", ")}`);
  const resolver = (traffic.resolver || []).find((row) => row.robot_id === robotId);
  if (resolver?.trigger === "wait_cycle") parts.push(`교착 · ${RESOLVER_DECISION_LABEL[resolver.decision] || RESOLVER_DECISION_LABEL.human}`);
  else if (traffic.wait_cycle?.includes(robotId)) parts.push("대기 순환 후보 · 지속 여부 확인 중");
  if (!parts.length) parts.push(robot.trip_state === "started" ? "운행 출발 대기" : "운행 중");
  if (robot.advice?.signal) parts.push(`신호 참고 전송 · seq ${robot.advice.sent_seq}${robot.advice.accepted ? "" : ` · ${robot.advice.reason || "미수락"}`}`);
  if (robot.preview?.events?.length) parts.push(`예고: ${robot.preview.events.slice(0, 2).map((e) => `${e.at_m.toFixed(2)} m ${{left: "왼쪽 회전", right: "오른쪽 회전", straight: "교차로 직진", stop: "정지", bend: "굽이", arc: "호", crosswalk: "횡단보도", signal: "신호", authority_end: "통행권 끝"}[e.kind === "turn" ? e.params.action : e.kind] || e.kind}`).join(" · ")}`);
  return parts.join(" · ");
}

export function trafficClock(prev, traffic, now) {
  const next = { merge: {} };
  for (const unit of traffic?.units || []) {
    if (isZone(unit)) for (const id of unit.waiting || []) if (!signalWait(traffic, id)) next.merge[id] = prev?.merge?.[id] ?? now;
  }
  return next;
}

export function trafficAttention(traffic, robotId, clock, now) {
  const items = [], cycle = traffic?.wait_cycle, resolver = traffic?.resolver || [], mine = resolver.find((row) => row.robot_id === robotId);
  if (Array.isArray(cycle) && cycle.includes(robotId)) {
    const replanned = resolver.find((row) => row.trigger === "wait_cycle" && row.decision === "replan");
    const then = mine?.reason?.startsWith("auto_hold:") ? "해결기: 자동 대기 · 상태 관측 중"
      : mine?.decision === "replan" ? "해결기: 다른 길 계획 · 다음 장소에서 운영자 확인"
      : mine?.decision === "wait" && replanned ? `해결기: ${replanned.robot_id} 다른 길 대기` : "운영자 판단 필요";
    items.push(resolver.some((row) => row.trigger === "wait_cycle")
      ? { severity: "crit", decision: "deadlock", text: `: 교착 — ${[...cycle, cycle[0]].join(" → ")} 서로 기다림 · ${then}` }
      : { severity: "warn", text: `: 대기 순환 후보 — ${[...cycle, cycle[0]].join(" → ")} · 지속 여부 확인 중` });
  }
  if (mine?.trigger === "unknown") items.push({ severity: "crit", text: ": 위치 불명 30초 넘음 — 블록을 풀지 않습니다 · 로봇 위치를 확인하세요" });
  const mergeSince = clock?.merge?.[robotId];
  if (mergeSince !== undefined && now - mergeSince > MERGE_MAX_WAIT_MS) {
    items.push({ severity: "warn", text: `: 합류 대기 ${Math.floor((now - mergeSince) / 1000)}초 — 구역 ${waitingUnit(traffic, robotId)?.id || ""} 입구` });
  }
  const signal = signalWait(traffic, robotId);
  if (signal?.errors?.length) items.push({ severity: "crit", text: `: 신호 ${signal.signal_id} 설정 오류 — 구역이 늘 적색입니다 · ${signal.errors[0]}` });
  else if (signal?.alert === "all_red_stretched") items.push({ severity: "crit", text: `: 신호 ${signal.signal_id} 전체 적색 30초 넘음 — 구역이 비지 않습니다 · 구역 안 로봇을 확인하세요` });
  else if (signal?.alert === "hold_long") items.push({ severity: "warn", text: `: 신호 ${signal.signal_id} 유지 2분 넘음 — 다른 입구가 기다립니다` });
  for (const loop of traffic?.loop_capacity || []) {
    if ((loop.robots || []).includes(robotId) && loop.robots.length > loop.capacity) items.push({ severity: "warn", text: `: 고리 수용 초과 — 고리 ${loop.robots.length}/${loop.capacity}대` });
  }
  return items;
}

export function loopCapacityText(traffic) { return (traffic?.loop_capacity || []).map((loop) => `고리 ${loop.robots.length}/${loop.capacity}대`).join(" · "); }

export function addApproach(map, id, points) {
  if (points.length < 3) throw new Error('대기 띠는 점이 세 개 이상이어야 합니다');
  const next = copy(map), crosswalk = (next.crosswalks || []).find(item => item.id === id);
  if (!crosswalk) throw new Error(`없는 횡단보도 ${id}`);
  if ((crosswalk.approach || []).length >= 4) throw new Error('대기 띠는 횡단보도마다 4개까지입니다');
  const mm = value => Math.round(value * 1000) / 1000;
  crosswalk.approach = [...(crosswalk.approach || []), points.map(([x, y]) => [mm(x), mm(y)])];
  return next;
}

export function removeApproach(map, id, index) {
  const next = copy(map), crosswalk = (next.crosswalks || []).find(item => item.id === id);
  if (!crosswalk?.approach?.[index]) throw new Error('지울 대기 띠가 없습니다');
  crosswalk.approach.splice(index, 1);
  return next;
}

export function mergeCrosswalks(map, imported) {
  const next = copy(map), had = new Map((next.crosswalks || []).map(item => [item.id, item]));
  next.crosswalks = imported.map(item => ({...copy(item), approach: had.get(item.id)?.approach || []}));
  return next;
}
export function soccerProfileMap(field, mapId) {
  if (![field.length_m, field.width_m, field.goal_width_m].every(v => Number.isFinite(v) && v > 0) || field.goal_width_m > field.width_m)
    throw new Error('경기장 치수는 양수이며 골대 폭은 경기장 폭 이하여야 합니다.');
  const x = field.length_m / 2, y = field.width_m / 2;
  return {schema: 'rosy.site_map/1', map_id: mapId,
    places: [[-x, -y], [x, -y], [x, y], [-x, y]].map(([px, py], i) => ({id: `corner_${i}`, name: `경기장 모서리 ${i + 1}`, kind: 'park', x: px, y: py})), edges: []};
}
