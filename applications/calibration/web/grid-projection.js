export function parallaxPixel(pixel, fromZ, toZ, camera) {
  if (!pixel || !camera?.center_px || !Number.isFinite(camera?.height_m)) return pixel;
  if (!Number.isFinite(fromZ) || !Number.isFinite(toZ)) return pixel;
  const denom = camera.height_m - toZ;
  if (Math.abs(denom) < 1e-6) return pixel;
  const scale = (camera.height_m - fromZ) / denom;
  const [cx, cy] = camera.center_px;
  return [cx + (pixel[0] - cx) * scale, cy + (pixel[1] - cy) * scale];
}
