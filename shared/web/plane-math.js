// 3×3 평면 투영 하나(행 우선 9개). Fleet 관제·보정과 Calibration 이 같이 쓴다(2026-11-26 패널 C-1).
// 예전 네 사본 가운데 가장 엄격한 규칙을 쓴다: 모양·유한값이 틀리거나 |det| < 1e-15 이면 null,
// 지평선 뒤(w ≤ 1e-9)의 점은 화면에 없으므로 null. 차이는 operations/fleet/test/web/plane-math.test.mjs 가 고정한다.
export function invert3(m) {
  if (!Array.isArray(m) || m.length !== 9 || !m.every(Number.isFinite)) return null;
  const [a, b, c, d, e, f, g, h, i] = m;
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (!Number.isFinite(det) || Math.abs(det) < 1e-15) return null;
  return [A, -(b * i - c * h), b * f - c * e, B, a * i - c * g, -(a * f - c * d), C, -(a * h - b * g), a * e - b * d]
    .map((v) => v / det);
}

export function project(h, x, y) {
  const w = h[6] * x + h[7] * y + h[8];
  if (!(w > 1e-9)) return null;
  return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w];
}
