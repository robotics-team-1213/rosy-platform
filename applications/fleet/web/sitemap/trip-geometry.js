import { planPolylines } from "/console/assets/site-map-model.js";

export function flattenPlanPoints(map, plan) {
  if (!map?.edges || !Array.isArray(plan?.segments)) return null;
  const out = [];
  for (const poly of planPolylines(map, plan)) {
    for (const pt of poly) {
      const last = out[out.length - 1];
      if (!last || Math.hypot(pt[0] - last[0], pt[1] - last[1]) >= 1e-6) out.push(pt);
    }
  }
  return out.length >= 2 ? out : null;
}

export const planMetrics = (plan) => ({
  ...(Array.isArray(plan.places) ? { places: plan.places } : {}),
  ...(Number.isFinite(plan.length_m) ? { length_m: plan.length_m } : {}),
  ...(Number.isFinite(plan.eta_s) ? { eta_s: plan.eta_s } : {}),
});

export function canvasWorld(event, view, rect) {
  if (!view.map) {
    const world = view.siteToWorld?.(event.clientX - rect.left, event.clientY - rect.top);
    return world ? { ...world, px: event.clientX, py: event.clientY } : null;
  }
  const scale = Math.min(rect.width / view.map.width, rect.height / view.map.height);
  const offX = (rect.width - view.map.width * scale) / 2, offY = (rect.height - view.map.height * scale) / 2;
  const col = (event.clientX - rect.left - offX) / scale, rowFromTop = (event.clientY - rect.top - offY) / scale;
  if (col < 0 || rowFromTop < 0 || col >= view.map.width || rowFromTop >= view.map.height) return null;
  const row = view.map.height - rowFromTop;
  return { x: view.map.origin.x + col * view.map.resolution, y: view.map.origin.y + row * view.map.resolution,
    px: event.clientX, py: event.clientY };
}
export function distToSegment(px, py, x0, y0, x1, y1) {
  const dx = x1 - x0, dy = y1 - y0, len2 = dx * dx + dy * dy;
  const t = len2 > 1e-12 ? Math.max(0, Math.min(1, ((px - x0) * dx + (py - y0) * dy) / len2)) : 0;
  return Math.hypot(px - (x0 + t * dx), py - (y0 + t * dy));
}
