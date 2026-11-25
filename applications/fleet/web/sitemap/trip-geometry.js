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
