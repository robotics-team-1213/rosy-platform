import {planSummaryText} from '/console/assets/site-map-model.js';

import {dockPlanIssues} from '/console/assets/trip-wait.js';

export function tripPreviewSummary(plan) {
  const parking = plan.parking_handoff;
  const distance = parking && Number.isFinite(plan.staging_distance_m)
    ? `차로 경로 ${plan.length_m.toFixed(2)} m · 계획 시 위치에서 ${parking.staging_place_id}까지 직선 ${plan.staging_distance_m.toFixed(2)} m`
    : undefined;
  return planSummaryText(plan, distance) + dockPlanIssues(parking);
}
