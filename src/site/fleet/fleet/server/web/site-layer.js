// 천장 카메라 사이트 층 (D-257). DOM 없는 순수 계산만 둔다 — map-view.js 가 그린다.
// 대형 릴레이 증거(streamEvidence)도 같은 순수 계산이라 여기 있다(D-359 US-009).
// 관측(sighting)은 표시·대조용이다. CORE TF pose 와 합치지 않고, 목표 좌표로 쓰지 않는다.

// 서버 lease(1 s)를 넘기면 `stale` 로 온다. 여기 임계는 그 위의 화면 규칙이다.
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
      state: row.stale === true || row.age_ms > SIGHTING_STALE_MS ? "stale" : "fresh",
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

// map 프레임 m → 캔버스 px. 캔버스 y 는 아래로 자라므로 뒤집는다(격자 뷰와 같은 규칙).
export function fitTransform(bounds, width, height, pad = 48) {
  const bw = Math.max(bounds.max_x - bounds.min_x, 1e-6);
  const bh = Math.max(bounds.max_y - bounds.min_y, 1e-6);
  const scale = Math.min((width - 2 * pad) / bw, (height - 2 * pad) / bh);
  const ox = pad + ((width - 2 * pad) - bw * scale) / 2 - bounds.min_x * scale;
  const oy = height - pad - ((height - 2 * pad) - bh * scale) / 2 + bounds.min_y * scale;
  return { scale, ox, oy };
}

export function project(t, x, y) {
  return { px: t.ox + x * t.scale, py: t.oy - y * t.scale };
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
export function streamEvidence(formation, robotId) {
  if (!formation?.active) return null;
  const evidence = formation.stream_evidence?.[robotId];
  if (!evidence) return { text: "릴레이 증거 없음", cls: "warn", evidence: "unavailable" };
  if (evidence.state === "fresh") return null;
  if (evidence.state === "disconnected") return { text: "릴레이 끊김", cls: "crit", evidence: "disconnected" };
  if (evidence.state === "delayed") {
    const age = finite(evidence.age_s) ? ` · ${evidence.age_s.toFixed(1)}초` : "";
    const reason = evidence.reason === "rate_below_floor" ? " · 송신 빈도 낮음" : "";
    return { text: `릴레이 지연${age}${reason}`, cls: "warn", evidence: "delayed" };
  }
  return { text: "릴레이 증거 없음", cls: "warn", evidence: "unavailable" };
}
