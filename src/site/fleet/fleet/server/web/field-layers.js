// D-354 경기장 제안·보정 뷰·레이어 토글의 순수 계산. DOM 없음 — field-view.js 가 그린다.
// 제안과 보정 뷰는 표시 전용이다. sighting·CameraMap·목표·cmd_vel 로 넘기지 않는다.

export const LAYER_KEYS = Object.freeze(["raw", "rectified", "site", "grid", "sightings", "poses"]);
export const LAYER_DEFAULTS = Object.freeze({
  raw: true, rectified: true, site: true, grid: true, sightings: true, poses: true,
});
export const LAYER_STORAGE_KEY = "rosy-console-layers";
export const FIELD_SIZE_PREFIX = "rosy-field-size:";
// 설정 W×H 비와 검출 비가 이만큼(상대) 넘게 다르면 안내한다. 초기값(D-354 5항).
export const ASPECT_TOLERANCE = 0.1;

const finite = (value) => typeof value === "number" && Number.isFinite(value);

// localStorage 문자열 → 레이어 상태. 모르는 키·틀린 값은 기본값으로 둔다.
export function parseLayers(raw) {
  const out = { ...LAYER_DEFAULTS };
  if (typeof raw !== "string" || !raw) return out;
  let parsed;
  try { parsed = JSON.parse(raw); } catch { return out; }
  if (!parsed || typeof parsed !== "object") return out;
  for (const key of LAYER_KEYS) if (typeof parsed[key] === "boolean") out[key] = parsed[key];
  return out;
}

// Vision 응답의 제안을 검사해 [0,1] 정규 좌표 네 점(좌상·우상·우하·좌하)으로 돌려준다.
export function normalizeProposal(body) {
  const p = body?.proposal;
  if (!p || !Array.isArray(p.corners_normalized) || p.corners_normalized.length !== 4) return null;
  const corners = p.corners_normalized.map((pt) => (Array.isArray(pt) && pt.length === 2
    && finite(pt[0]) && finite(pt[1]) ? [clamp01(pt[0]), clamp01(pt[1])] : null));
  if (corners.includes(null) || !finite(p.confidence) || !finite(p.aspect_ratio) || p.aspect_ratio <= 0) {
    return null;
  }
  return {
    corners,
    confidence: p.confidence,
    aspect: p.aspect_ratio,
    shape: p.shape === "square" ? "square" : "rectangle",
  };
}

function clamp01(v) { return Math.max(0, Math.min(1, v)); }

// 네 점(픽셀)의 평균 가로/세로 비. rectify.py 와 같은 규칙이다.
export function quadAspect(corners) {
  const d = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
  const [tl, tr, br, bl] = corners;
  const horizontal = d(tl, tr) + d(bl, br);
  const vertical = d(tl, bl) + d(tr, br);
  return vertical > 0 ? horizontal / vertical : 0;
}

// /api/fleet/site-map 의 source 사각형 치수(W×H m). 없으면 null.
export function configuredSize(siteMap, sourceId) {
  const maps = siteMap?.maps || [];
  const entry = maps.find((m) => (m.sources || []).some((s) => s.source_id === sourceId)) || maps[0];
  const b = entry?.bounds_m;
  if (!b || !finite(b.min_x) || !finite(b.max_x) || !finite(b.min_y) || !finite(b.max_y)) return null;
  const width = b.max_x - b.min_x;
  const height = b.max_y - b.min_y;
  return width > 0 && height > 0 ? { width, height, mapId: entry.map_id || "" } : null;
}

// 설정 비와 검출 비 비교. 카메라가 돌아가 있을 수 있어 방향은 무시하고 긴 변/짧은 변으로 본다.
export function aspectMismatch(configured, detectedAspect, tolerance = ASPECT_TOLERANCE) {
  if (!finite(detectedAspect) || detectedAspect <= 0) return { state: "unknown" };
  const detected = Math.max(detectedAspect, 1 / detectedAspect);
  if (!configured) return { state: "unconfigured", detected };
  const expected = Math.max(configured.width / configured.height, configured.height / configured.width);
  const relative = Math.abs(detected - expected) / expected;
  return { state: relative > tolerance ? "mismatch" : "match", detected, expected, relative };
}

// 운용자 W×H 입력(m). 0.05–100 m 범위의 유한수만 받는다.
export function parseFieldSize(width, height) {
  const w = Number(width);
  const h = Number(height);
  const ok = (v) => Number.isFinite(v) && v >= 0.05 && v <= 100;
  return ok(w) && ok(h) ? { width: w, height: h } : null;
}

// 단위 정사각형 → 사각형 대응(4점)으로 3×3 호모그래피를 푼다. 퇴화하면 null.
// src·dst 는 [[x,y]×4]. 반환 H 는 dst = H·src (행 우선 9개, h33=1).
export function homography(src, dst) {
  const a = [];
  const b = [];
  for (let i = 0; i < 4; i += 1) {
    const [x, y] = src[i];
    const [u, v] = dst[i];
    a.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u);
    a.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v);
  }
  const h = solve(a, b);
  return h ? [...h, 1] : null;
}

function solve(a, b) {
  const n = b.length;
  const m = a.map((row, i) => [...row, b[i]]);
  for (let col = 0; col < n; col += 1) {
    let pivot = col;
    for (let r = col + 1; r < n; r += 1) if (Math.abs(m[r][col]) > Math.abs(m[pivot][col])) pivot = r;
    if (Math.abs(m[pivot][col]) < 1e-12) return null;
    [m[col], m[pivot]] = [m[pivot], m[col]];
    for (let r = 0; r < n; r += 1) {
      if (r === col) continue;
      const f = m[r][col] / m[col][col];
      for (let c = col; c <= n; c += 1) m[r][c] -= f * m[col][c];
    }
  }
  return m.map((row, i) => row[n] / row[i]);
}

export function applyHomography(h, x, y) {
  const w = h[6] * x + h[7] * y + h[8];
  return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w];
}

// 보정 뷰 캔버스 크기와 경기장 사각형 위치. 경기장 둘레에 margin 비율만큼 가린 바깥을 남긴다.
export function rectifiedLayout(aspect, maxWidth = 640, maxHeight = 400, margin = 0.08) {
  const a = finite(aspect) && aspect > 0 ? Math.min(8, Math.max(1 / 8, aspect)) : 1;
  const scaleW = maxWidth / (a * (1 + 2 * margin));
  const scaleH = maxHeight / (1 + 2 * margin);
  const fieldH = Math.max(8, Math.floor(Math.min(scaleW, scaleH)));
  const fieldW = Math.max(8, Math.round(fieldH * a));
  const padX = Math.round(fieldW * margin);
  const padY = Math.round(fieldH * margin);
  return {
    width: fieldW + 2 * padX, height: fieldH + 2 * padY,
    field: { x: padX, y: padY, width: fieldW, height: fieldH },
  };
}
