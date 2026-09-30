// D-375 지도 자동 맞춤(차선 페인트 → homography 제안)의 순수 계산. DOM 없음 — map-fit-view.js 가 그린다.
// 제안·수락한 맞춤은 표시 전용이다. sighting·CameraMap·목표·cmd_vel 로 넘기지 않는다.

export const MAP_FIT_PREFIX = "rosy-map-fit:";

const finite = (value) => typeof value === "number" && Number.isFinite(value);

// [[a,b,c],[d,e,f],[g,h,i]] → 행 우선 9개. 모양·값이 틀리면 null.
export function flatMatrix(rows) {
  if (!Array.isArray(rows) || rows.length !== 3) return null;
  const flat = rows.flatMap((row) => (Array.isArray(row) && row.length === 3 ? row : [Number.NaN]));
  return flat.length === 9 && flat.every(finite) ? flat : null;
}

export function multiply3(a, b) {
  const out = new Array(9).fill(0);
  for (let r = 0; r < 3; r += 1) {
    for (let c = 0; c < 3; c += 1) {
      for (let k = 0; k < 3; k += 1) out[r * 3 + c] += a[r * 3 + k] * b[k * 3 + c];
    }
  }
  return out;
}

export function invert3(m) {
  const [a, b, c, d, e, f, g, h, i] = m;
  const A = e * i - f * h;
  const B = -(d * i - f * g);
  const C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (!finite(det) || Math.abs(det) < 1e-15) return null;
  return [A, -(b * i - c * h), b * f - c * e, B, a * i - c * g, -(a * f - c * d), C, -(a * h - b * g), a * e - b * d]
    .map((v) => v / det);
}

// 점 하나를 옮긴다. 지평선 뒤(w≤0)는 화면에 없는 점이라 null.
export function project(h, x, y) {
  const w = h[6] * x + h[7] * y + h[8];
  if (!(w > 1e-9)) return null;
  return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w];
}

export const scale3 = (sx, sy) => [sx, 0, 0, 0, sy, 0, 0, 0, 1];

// 한 선을 옮기고 지평선 뒤 점에서 끊는다. 두 점 미만 조각은 버린다.
export function projectPolyline(points, h, closed = false) {
  const runs = [];
  let run = [];
  const pts = closed && points.length > 2 ? [...points, points[0]] : points;
  for (const [x, y] of pts) {
    const p = project(h, x, y);
    if (p) run.push(p);
    else { if (run.length > 1) runs.push(run); run = []; }
  }
  if (run.length > 1) runs.push(run);
  return runs;
}

// 페인트 삼각형 [x1,y1,x2,y2,x3,y3] → 세 점. 한 점이라도 지평선 뒤면 버린다.
export function projectTriangles(triangles, h) {
  const out = [];
  for (const t of triangles || []) {
    const a = project(h, t[0], t[1]);
    const b = project(h, t[2], t[3]);
    const c = project(h, t[4], t[5]);
    if (a && b && c) out.push([a, b, c]);
  }
  return out;
}

// Vision map-proposal 응답 검사. accepted 면 proposal, 아니면 rejected_fit(참고용)을 fit 으로 준다.
export function normalizeMapProposal(body) {
  if (!body || typeof body !== "object" || typeof body.accepted !== "boolean") return null;
  const width = body.image?.width;
  const height = body.image?.height;
  if (!finite(width) || !finite(height) || width <= 0 || height <= 0) return null;
  const raw = body.accepted ? body.proposal : body.rejected_fit;
  let fit = null;
  if (raw && typeof raw === "object") {
    const imageToMap = flatMatrix(raw.image_to_map);
    const mapToImage = flatMatrix(raw.map_to_image) || (imageToMap && invert3(imageToMap));
    if (imageToMap && mapToImage) {
      fit = {
        imageToMap, mapToImage,
        score: finite(raw.score) ? raw.score : null,
        precision: finite(raw.precision) ? raw.precision : null,
        coverage: finite(raw.coverage) ? raw.coverage : null,
        cutDirections: Array.isArray(raw.cut_directions)
          ? raw.cut_directions.filter((d) => d in DIRECTION_KO) : [],
        rotation: finite(raw.rotation_deg) ? raw.rotation_deg : null,
        mirrored: raw.mirrored === true,
        margin: finite(raw.orientation_margin) ? raw.orientation_margin : null,
      };
    }
  }
  if (body.accepted && !fit) return null; // 통과라면서 행렬이 없으면 믿지 않는다
  return {
    accepted: body.accepted, fit, reason: typeof body.reason === "string" ? body.reason : "",
    image: { width, height }, seq: body.frame_seq ?? null,
    elapsedMs: finite(body.registrar?.elapsed_ms) ? body.registrar.elapsed_ms : null,
  };
}

const DIRECTION_KO = { east: "동쪽", west: "서쪽", north: "북쪽", south: "남쪽" };
const REASONS = [
  ["ok", "맞춤 통과"],
  ["no white paint", "흰 차선 페인트가 보이지 않습니다"],
  ["no coarse match", "지도와 닮은 선 배치를 찾지 못했습니다"],
  ["too little of the map in view", "화면에 보이는 지도가 너무 적습니다"],
  ["weak paint match", "페인트 일치가 약합니다"],
  ["too many unmatched lines", "지도에 없는 선이 많이 보입니다"],
  ["orientation ambiguous", "방향을 하나로 정하지 못했습니다"],
  ["image is mirrored", "영상이 거울상입니다 — 카메라 앱 설정을 확인하세요"],
];

export function reasonText(reason) {
  const text = typeof reason === "string" ? reason : "";
  const hit = REASONS.find(([key]) => text === key || text.startsWith(`${key} (`) || text.startsWith(`${key};`));
  if (!hit) return text ? `Vision: ${text}` : "이유 없음";
  return hit[0] === "ok" || hit[0] === text ? hit[1] : `${hit[1]} (${text})`;
}

// 잘린 쪽 → 설치 안내. 잘린 쪽이 없으면 null.
export function cutGuidance(directions) {
  const names = (directions || []).map((d) => DIRECTION_KO[d]).filter(Boolean);
  if (!names.length) return null;
  const joined = names.join("·");
  return `지도 ${joined} 끝이 화면 밖입니다 — 카메라를 ${joined}으로 옮기거나 더 넓게 잡으세요.`;
}

const pct = (v) => `${Math.round(v * 100)}%`;

// 상태 줄 두 개: 요약과 안내. 숫자는 Vision 응답 그대로다.
export function fitSummary(norm) {
  if (!norm) return { tone: "warn", headline: "맞춤 응답을 해석하지 못했습니다.", guidance: null };
  const f = norm.fit;
  const parts = [];
  if (f?.score != null) parts.push(`일치 ${f.score.toFixed(2)}`);
  if (f?.precision != null) parts.push(`정밀 ${f.precision.toFixed(2)}`);
  if (f?.coverage != null) parts.push(`지도 ${pct(f.coverage)} 보임`);
  if (f?.rotation != null) parts.push(`지도 +x 화면 ${Math.round(f.rotation)}°`);
  if (norm.seq != null) parts.push(`프레임 ${norm.seq}`);
  if (norm.elapsedMs != null) parts.push(`${Math.round(norm.elapsedMs)} ms`);
  const numbers = parts.length ? ` · ${parts.join(" · ")}` : "";
  if (norm.accepted) {
    return { tone: "good", headline: `맞춤 제안${numbers}. 선이 흰 페인트 위에 있는지 보고 수락하세요. 자동 적용하지 않습니다.`,
      guidance: cutGuidance(f.cutDirections) };
  }
  const tail = f ? " 주황 선은 참고용 최선 적합이며 수락할 수 없습니다." : "";
  return { tone: "warn", headline: `맞춤 거부 — ${reasonText(norm.reason)}${numbers}.${tail}`,
    guidance: cutGuidance(f?.cutDirections) };
}

// /api/fleet/site-lanes 에서 이 source 의 지도. source 를 명시한 항목 → 모든 지도용 항목 → 첫 항목.
export function pickLanes(siteLanes, sourceId) {
  const maps = Array.isArray(siteLanes?.maps) ? siteLanes.maps : [];
  const entry = maps.find((m) => (m.source_ids || []).includes(sourceId))
    || maps.find((m) => m.map_id == null) || maps[0];
  if (!entry) return null;
  const b = entry.bounds_m;
  if (!b || ![b.min_x, b.min_y, b.max_x, b.max_y].every(finite) || b.max_x <= b.min_x || b.max_y <= b.min_y) {
    return null;
  }
  return {
    mapId: entry.map_id ?? null,
    polylines: (entry.polylines || []).filter((l) => Array.isArray(l.points) && l.points.length > 1),
    triangles: (entry.paint_triangles || []).filter((t) => Array.isArray(t) && t.length === 6),
    bounds: b,
  };
}

// 지도(m, y 위) → 캔버스(px, y 아래). 여백은 m. 캔버스는 maxW×maxH 안에 들어간다.
export function topDownLayout(bounds, maxWidth = 640, maxHeight = 400, marginM = 0.1) {
  const w = bounds.max_x - bounds.min_x + 2 * marginM;
  const h = bounds.max_y - bounds.min_y + 2 * marginM;
  const pxPerM = Math.min(maxWidth / w, maxHeight / h);
  const width = Math.max(8, Math.round(w * pxPerM));
  const height = Math.max(8, Math.round(h * pxPerM));
  const x0 = bounds.min_x - marginM;
  const y1 = bounds.max_y + marginM;
  const mapToCanvas = [pxPerM, 0, -x0 * pxPerM, 0, -pxPerM, y1 * pxPerM, 0, 0, 1];
  return { width, height, pxPerM, mapToCanvas, canvasToMap: invert3(mapToCanvas) };
}

// D-360 경기장 뷰의 대체 경로: 경기장 사각형(field, 캔버스 px) ↔ 지도 사각형(bounds, m, y 위).
// 모서리가 프레임 밖이어도 된다 — 0–100% 로 잘리는 모서리 조정값을 거치지 않는다.
export function fieldToMap(bounds, field) {
  const sx = (bounds.max_x - bounds.min_x) / field.width;
  const sy = (bounds.max_y - bounds.min_y) / field.height;
  return [sx, 0, bounds.min_x - field.x * sx, 0, -sy, bounds.max_y + field.y * sy, 0, 0, 1];
}

// 맞춤 요청이 429(계산 중·초당 1회)면 Retry-After 뒤 다시 묻는다. 너무 오래면 null(그만).
export const MAP_FIT_MAX_TRIES = 8;
export function retryDelay(error, attempt, maxTries = MAP_FIT_MAX_TRIES) {
  if (!error?.busy || attempt + 1 >= maxTries) return null;
  const ms = Number(error.retryAfterMs);
  return Number.isFinite(ms) && ms > 0 ? Math.min(ms, 5000) : 1000;
}

// 수락한 맞춤 초안(브라우저 로컬). 모양이 틀리면 null.
export function parseMapDraft(raw) {
  let parsed;
  try { parsed = JSON.parse(raw || "null"); } catch { return null; }
  if (!parsed || typeof parsed !== "object") return null;
  const mapToImage = Array.isArray(parsed.map_to_image) && parsed.map_to_image.length === 9
    && parsed.map_to_image.every(finite) ? parsed.map_to_image : null;
  const width = parsed.image?.width;
  const height = parsed.image?.height;
  if (!mapToImage || !finite(width) || !finite(height) || width <= 0 || height <= 0) return null;
  const imageToMap = invert3(mapToImage);
  if (!imageToMap) return null;
  return { mapToImage, imageToMap, image: { width, height }, acceptedAt: parsed.accepted_at ?? null,
    seq: parsed.frame_seq ?? null, mapId: parsed.map_id ?? null };
}

export function draftFrom(norm, mapId, now = Date.now()) {
  return JSON.stringify({
    map_to_image: norm.fit.mapToImage, image: norm.image, frame_seq: norm.seq,
    map_id: mapId, accepted_at: new Date(now).toISOString(), use: "display-only",
  });
}
