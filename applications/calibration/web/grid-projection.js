export function invert3x3(h) {
  const [[a, b, c], [d, e, f], [g, i, j]] = h;
  const c00 = e * j - f * i;
  const c01 = c * i - b * j;
  const c02 = b * f - c * e;
  const det = a * c00 + d * c01 + g * c02;
  if (Math.abs(det) < 1e-18) return null;
  const inv = 1 / det;
  return [
    [c00 * inv, c01 * inv, c02 * inv],
    [(f * g - d * j) * inv, (a * j - c * g) * inv, (c * d - a * f) * inv],
    [(d * i - e * g) * inv, (b * g - a * i) * inv, (a * e - b * d) * inv],
  ];
}

export function applyH(m, x, y) {
  const w = m[2][0] * x + m[2][1] * y + m[2][2];
  if (!Number.isFinite(w) || Math.abs(w) < 1e-12) return null;
  return [(m[0][0] * x + m[0][1] * y + m[0][2]) / w, (m[1][0] * x + m[1][1] * y + m[1][2]) / w];
}

export function parallaxPixel(pixel, fromZ, toZ, camera) {
  if (!pixel || !camera?.center_px || !Number.isFinite(camera?.height_m)) return pixel;
  if (!Number.isFinite(fromZ) || !Number.isFinite(toZ)) return pixel;
  const denom = camera.height_m - toZ;
  if (Math.abs(denom) < 1e-6) return pixel;
  const scale = (camera.height_m - fromZ) / denom;
  const [cx, cy] = camera.center_px;
  return [cx + (pixel[0] - cx) * scale, cy + (pixel[1] - cy) * scale];
}
