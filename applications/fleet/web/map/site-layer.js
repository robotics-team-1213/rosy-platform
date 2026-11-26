// 천장 카메라 사이트 층 (D-257). DOM 없는 순수 계산만 둔다 — map-view.js 가 그린다.
import { evidenceAgeText } from "/common/core_ui_logic.js";
import { project as projectHomography } from "/console/assets/map-fit.js";

// 대형 릴레이 증거(streamEvidence)도 같은 순수 계산이라 여기 있다(D-359 US-009).
// 관측(sighting)은 표시·대조용이다. CORE TF pose 와 합치지 않고, 목표 좌표로 쓰지 않는다.

// 서버 lease(1 s)를 넘기면 `stale` 로 온다. 여기 임계는 그 위의 화면 규칙이다.
// 증거 어휘는 닫힌 네 상태다(D-359): 서버의 `stale` 는 화면에서 `delayed`(지연)로 그린다.
export const SIGHTING_STALE_MS = 3000;
export const SIGHTING_HIDE_MS = 30000;
export const GRID_STEP_M = 0.5;

const finite = (value) => typeof value === "number" && Number.isFinite(value);

// GET /api/fleet/sightings 응답 → 로봇당 최신 1건. 30 s 넘은 것은 뺀다.
export function classifySightings(snapshot) {
  const latest = new Map();
  for (const row of snapshot?.sightings || []) {
    if (!row || typeof row.robot_id !== "string" || !finite(row.x) || !finite(row.y)
        || !finite(row.yaw) || !finite(row.age_ms)) continue;
    const prior = latest.get(row.robot_id);
    if (prior && finite(prior.captured_at) && finite(row.captured_at)
        && prior.captured_at >= row.captured_at) continue;
    latest.set(row.robot_id, row);
  }
  const out = [];
  for (const row of latest.values()) {
    if (row.age_ms > SIGHTING_HIDE_MS) continue;
    out.push({
      robot_id: row.robot_id,
      x: row.x,
      y: row.y,
      yaw: row.yaw,
      source_id: row.source_id || "",
      age_ms: row.age_ms,
      state: row.stale === true || row.age_ms > SIGHTING_STALE_MS ? "delayed" : "fresh",
    });
  }
  return out.sort((a, b) => a.robot_id.localeCompare(b.robot_id));
}

// GET /api/fleet/site-map 의 모든 사각형을 감싸는 범위(여백 margin m 포함).
export function siteBounds(siteMap, margin = 0.25) {
  const maps = siteMap?.maps || [];
  if (!maps.length) return null;
  const b = { min_x: Infinity, min_y: Infinity, max_x: -Infinity, max_y: -Infinity };
  for (const entry of maps) {
    for (const [x, y] of entry.polygon_m || []) {
      b.min_x = Math.min(b.min_x, x);
      b.min_y = Math.min(b.min_y, y);
      b.max_x = Math.max(b.max_x, x);
      b.max_y = Math.max(b.max_y, y);
    }
  }
  if (!finite(b.min_x) || !finite(b.max_y)) return null;
  return { min_x: b.min_x - margin, min_y: b.min_y - margin,
           max_x: b.max_x + margin, max_y: b.max_y + margin };
}

// 긴 변을 base px 로 두고 종횡비를 따른다. 캔버스는 CSS object-fit: contain 으로 맞춰진다.
export function canvasSizeFor(bounds, base = 1200) {
  const w = Math.max(bounds.max_x - bounds.min_x, 1e-6);
  const h = Math.max(bounds.max_y - bounds.min_y, 1e-6);
  const ratio = Math.min(1.5, Math.max(0.35, h / w));
  return { width: base, height: Math.round(base * ratio) };
}

// [lo, hi] 안에 드는 step 의 배수들. 부동소수 오차로 끝 값을 놓치지 않게 여유를 둔다.
export function gridLines(lo, hi, step = GRID_STEP_M) {
  const out = [];
  const eps = step * 1e-6;
  for (let k = Math.ceil((lo - eps) / step); k * step <= hi + eps; k += 1) {
    out.push(Math.round(k * step * 1e6) / 1e6 + 0); // + 0 normalises -0
  }
  return out;
}

// 릴레이 건강을 D-72 증거로 옮긴다. fresh 는 아무것도 붙이지 않는다(§7.3 정상은 안 보임).
// D-359 US-009 — 알약은 로봇 카드에 홀로 붙으므로 무엇의 증거인지("릴레이")를 말한다.
// D-398 — 증거 어휘 표는 core_ui_logic.js의 EVIDENCE_LABEL 이지만 이 파일은 노드 순수
// 시험이 돌아야 해서 /common import를 못 한다. 같은 문구를 로컬로 둔다(표를 참조한다).
export function streamEvidence(formation, robotId) {
  if (!formation?.active) return null;
  const evidence = formation.stream_evidence?.[robotId];
  if (!evidence) return { text: "릴레이 증거 없음", cls: "warn", evidence: "unavailable" };
  if (evidence.state === "fresh") return null;
  if (evidence.state === "disconnected") return { text: "릴레이 끊김", cls: "crit", evidence: "disconnected" };
  if (evidence.state === "delayed") {
    const age = finite(evidence.age_s)
      ? evidenceAgeText(Math.round(Math.max(0, evidence.age_s) * 10) / 10) : "";
    const reason = evidence.reason === "rate_below_floor" ? " · 송신 빈도 낮음" : "";
    return { text: `릴레이 지연${age}${reason}`, cls: "warn", evidence: "delayed" };
  }
  return { text: "릴레이 증거 없음", cls: "warn", evidence: "unavailable" };
}

// D-513 7: 실영상은 지도 방향으로 보인다 — 지도 +y 가 화면 위로 오는 가장 가까운 quarter turn(시계 방향 도).
// 방향의 근거는 지도 좌표계와 보정 하나뿐이다. 설치 키를 따로 두지 않는다. 보정이 없으면 0(원본 그대로).
export function mapUpTurn(record) {
  const h = record?.map_to_image, b = record?.track_bounds_m;
  if (!Array.isArray(h) || h.length !== 9 || !b) return 0;
  const cx = (b.min_x + b.max_x) / 2, cy = (b.min_y + b.max_y) / 2;
  const a = projectHomography(h, cx, cy), c = projectHomography(h, cx, cy + 0.1);
  if (!a || !c) return 0;
  const up = Math.atan2(c[1] - a[1], c[0] - a[0]) * 180 / Math.PI; // map +y on the raw picture, clockwise
  return ((Math.round((-90 - up) / 90) * 90) % 360 + 360) % 360;
}
// The physical charging lead-ins are straight (D-1013). Preserve stored geometry for routing and editing.
export function roadOverlayPoints(mapId, edge) {
  const bay = /^bay_([123])$/.exec(edge.id)?.[1];
  const points = edge.polyline;
  if (mapId === "world_261026" && bay && edge.from === `P${bay}` && edge.to === `C${bay}` && points.length > 2) {
    return [points[0], points.at(-1)];
  }
  return points;
}

// 2026-11-26: the measured line comes from the server's map record (display_polyline + display_source,
// a floor survey). A relocated edge needs a new survey, so only coordinate rounding (1 mm) is allowed.
const near = ([x, y], [u, v]) => Math.hypot(x - u, y - v) <= 0.001;
export function surveyedRoadPoints(edge) {
  const line = edge.display_polyline, anchors = edge.display_source?.anchors;
  if (edge.display_source?.kind !== "survey" || !(line?.length >= 2) || anchors?.length !== 2 || edge.polyline.length < 2) return null;
  return near(edge.polyline[0], anchors[0]) && near(edge.polyline.at(-1), anchors[1]) ? line : null;
}

// The stored line up to display_source.stored_until stays drawn as not surveyed (an unpainted U-turn).
export function unmeasuredRoadPoints(edge) {
  const until = edge.display_source?.stored_until;
  if (!until || !surveyedRoadPoints(edge)) return null;
  const tangent = edge.polyline.findIndex((point) => near(point, until));
  return tangent > 0 ? edge.polyline.slice(0, tangent + 1) : edge.polyline;
}

export const surveyText = (source) => `측량 ${source.surveyed_at} · ${source.plane}${source.note ? ` · ${source.note}` : ""}`;
