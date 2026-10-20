/** Newest live AI observation for this open trip; UNKNOWN clears an older deviation. */
export function routeAttention(trip, facts, now) {
  if (!trip) return [];
  const newest = (facts || []).filter(fact => fact.kind === 'trip_route_check'
    && fact.robot_ids?.includes(trip.robot_id) && fact.evidence?.trip_id === trip.trip_id
    && fact.evidence?.map_version === trip.map_version && Number.isFinite(fact.observed_at))
    .reduce((last, fact) => !last || fact.observed_at >= last.observed_at ? fact : last, null);
  if (!newest || !Number.isFinite(newest.ttl_s) || newest.ttl_s <= 0 || newest.ttl_s > 5
    || newest.observed_at > now / 1000 + 1 || newest.observed_at + newest.ttl_s < now / 1000
    || newest.value?.status !== 'OFF_ROUTE') return [];
  const {offset_m, limit_m} = newest.value;
  if (!Number.isFinite(offset_m) || offset_m < 0 || !Number.isFinite(limit_m) || offset_m <= limit_m) return [];
  const cm = Math.round((offset_m - limit_m) * 100);
  return [{severity: 'warn', text: `: AI 경로 편차 관찰 — 허용 경계보다 ${cm} cm 밖 · 위치 확인 필요`}];
}
