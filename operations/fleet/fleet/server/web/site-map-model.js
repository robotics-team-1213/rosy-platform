// D-488 site map page — pure helpers (no DOM) so node tests cover them.

export const PLACE_KINDS = ['junction', 'park', 'charge', 'stop', 'turnaround'];
export const PLACE_KIND_LABEL = {
  junction: '교차', park: '주차', charge: '충전', stop: '정차', turnaround: '회차',
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
};
export const SITE_MAP_ERROR_LABEL = {
  SITE_MAP_NOT_ACTIVE: '활성 지도가 없습니다',
  SITE_MAP_NO_DRAFT: '저장된 초안이 없습니다',
  SITE_MAP_DRAFT_CHANGED: '다른 운영자가 초안을 바꿨습니다. 현재 수정은 저장되지 않았습니다. 변경 내용을 기록한 뒤 다시 접속하세요.',
  SITE_MAP_ROUTE_ACTIVE: '차선 경로가 진행 중입니다 · 끝난 뒤 활성화하세요',
  SITE_MAP_UNPLANNABLE: '경로 계산에 쓸 수 없는 지도입니다',
  SITE_MAP_TOO_LARGE: '지도가 너무 큽니다',
  SITE_MAP_INVALID: '지도에 맞지 않는 값이 있습니다',
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
  if (code !== 'TRIP_NO_ROUTE') return base;
  const leg = Number.isInteger(detail.segment) ? ` · ${detail.segment + 1}번째 구간` : '';
  return base + leg + (detail.unblock_would_help ? ' · 막은 차로를 풀면 길이 있습니다' : '');
}

/** Map metres <-> SVG pixels; map y goes up, SVG y goes down. */
export function fitView(map, width, height, pad = 24) {
  const xs = [], ys = [];
  for (const place of map.places) { xs.push(place.x); ys.push(place.y); }
  for (const edge of map.edges) for (const [x, y] of edge.polyline) { xs.push(x); ys.push(y); }
  if (!xs.length) { xs.push(0); ys.push(0); }
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const scale = Math.min((width - 2 * pad) / Math.max(maxX - minX, 1e-6),
    (height - 2 * pad) / Math.max(maxY - minY, 1e-6));
  const ox = pad + ((width - 2 * pad) - (maxX - minX) * scale) / 2;
  const oy = pad + ((height - 2 * pad) - (maxY - minY) * scale) / 2;
  return {
    scale,
    toPx: (x, y) => [ox + (x - minX) * scale, oy + (maxY - y) * scale],
    toMap: (px, py) => [minX + (px - ox) / scale, maxY - (py - oy) / scale],
  };
}

function lengths(points) {
  const knots = [0];
  for (let i = 1; i < points.length; i += 1) {
    knots.push(knots[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]));
  }
  return knots;
}

function pointAt(points, knots, s) {
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
    place.kind = kind;
  }
  return next;
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
