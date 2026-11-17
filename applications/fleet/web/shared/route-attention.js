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

function projectToPoly(poly, px, py) {
  let best = { dist: Infinity, segIdx: 0, t: 0, x: px, y: py, s: 0, totalLen: 0 };
  let acc = 0;
  for (let i = 0; i < poly.length - 1; i++) {
    const [x0, y0] = poly[i], [x1, y1] = poly[i + 1];
    const dx = x1 - x0, dy = y1 - y0, len2 = dx * dx + dy * dy, segLen = Math.sqrt(len2);
    const t = len2 > 1e-12 ? Math.max(0, Math.min(1, ((px - x0) * dx + (py - y0) * dy) / len2)) : 0;
    const cx = x0 + t * dx, cy = y0 + t * dy, d = Math.hypot(px - cx, py - cy);
    if (d < best.dist) best = { dist: d, segIdx: i, t, x: cx, y: cy, s: acc + t * segLen, totalLen: 0 };
    acc += segLen;
  }
  best.totalLen = acc;
  return best;
}

function slicePoly(poly, sFrom, sTo) {
  const forward = sTo >= sFrom;
  const pts = forward ? poly : [...poly].reverse();
  let total = 0;
  for (let i = 0; i < pts.length - 1; i++) total += Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
  const a = forward ? sFrom : Math.max(0, total - sFrom);
  const b = forward ? sTo : Math.max(0, total - sTo);
  const out = [];
  let acc = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[i + 1];
    const seg = Math.hypot(x1 - x0, y1 - y0);
    if (seg < 1e-9) continue;
    const nextAcc = acc + seg;
    if (nextAcc >= a - 1e-6 && acc <= b + 1e-6) {
      const t0 = Math.max(0, Math.min(1, (a - acc) / seg));
      const t1 = Math.max(0, Math.min(1, (b - acc) / seg));
      const p0 = [x0 + t0 * (x1 - x0), y0 + t0 * (y1 - y0)];
      const p1 = [x0 + t1 * (x1 - x0), y0 + t1 * (y1 - y0)];
      if (!out.length || Math.hypot(out[out.length - 1][0] - p0[0], out[out.length - 1][1] - p0[1]) > 1e-4) out.push(p0);
      if (Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) > 1e-4) out.push(p1);
    }
    acc = nextAcc;
  }
  return out;
}

export function roadPolylineBetween(siteMap, startPose, targetXY) {
  const edges = siteMap?.edges;
  if (!Array.isArray(edges) || !edges.length || !startPose || !targetXY) return null;
  const snaps = [];
  let minStartDist = Infinity, minGoalDist = Infinity;
  for (const e of edges) {
    if (!Array.isArray(e.polyline) || e.polyline.length < 2) continue;
    const sp = projectToPoly(e.polyline, startPose.x, startPose.y);
    const gp = projectToPoly(e.polyline, targetXY.x, targetXY.y);
    if (sp.dist < minStartDist) minStartDist = sp.dist;
    if (gp.dist < minGoalDist) minGoalDist = gp.dist;
    snaps.push({ edge: e, sp, gp });
  }
  if (!snaps.length || minGoalDist > 1.5) return null;
  const startCands = snaps.filter((s) => s.sp.dist <= minStartDist + 0.08);
  const goalCands = snaps.filter((s) => s.gp.dist <= minGoalDist + 0.08);
  const adj = new Map();
  const addArc = (u, v, cost, poly, place) => {
    if (!adj.has(u)) adj.set(u, []);
    adj.get(u).push({ to: v, cost, poly, place });
  };
  for (const { edge: e, sp } of snaps) {
    addArc(e.from, e.to, sp.totalLen, e.polyline, e.to);
    if (e.direction === "two_way") addArc(e.to, e.from, sp.totalLen, [...e.polyline].reverse(), e.from);
  }
  const S = "__start__", G = "__goal__";
  for (const sc of startCands) {
    const e = sc.edge, sp = sc.sp, pen = (sp.dist - minStartDist) * 1.5;
    addArc(S, e.to, Math.max(0, sp.totalLen - sp.s) + pen, slicePoly(e.polyline, sp.s, sp.totalLen), e.to);
    if (e.direction === "two_way") addArc(S, e.from, sp.s + pen, slicePoly(e.polyline, sp.s, 0), e.from);
  }
  for (const gc of goalCands) {
    const e = gc.edge, gp = gc.gp, pen = (gp.dist - minGoalDist) * 1.5;
    addArc(e.from, G, gp.s + pen, slicePoly(e.polyline, 0, gp.s), null);
    if (e.direction === "two_way") addArc(e.to, G, Math.max(0, gp.totalLen - gp.s) + pen, slicePoly(e.polyline, gp.totalLen, gp.s), null);
  }
  for (const sc of startCands) {
    const gc = goalCands.find((g) => g.edge.id === sc.edge.id);
    if (!gc) continue;
    const e = sc.edge, sp = sc.sp, gp = gc.gp;
    if (gp.s >= sp.s - 1e-4 || e.direction === "two_way") {
      addArc(S, G, Math.abs(gp.s - sp.s) + (sp.dist - minStartDist) + (gp.dist - minGoalDist), slicePoly(e.polyline, sp.s, gp.s), null);
    }
  }
  const dist = new Map([[S, 0]]), prev = new Map(), visited = new Set();
  while (true) {
    let u = null, bestD = Infinity;
    for (const [node, d] of dist.entries()) if (!visited.has(node) && d < bestD) { bestD = d; u = node; }
    if (u === null || u === G) break;
    visited.add(u);
    for (const edge of adj.get(u) || []) {
      const nd = bestD + edge.cost;
      if (nd < (dist.get(edge.to) ?? Infinity)) { dist.set(edge.to, nd); prev.set(edge.to, { from: u, ...edge }); }
    }
  }
  if (!prev.has(G)) return null;
  const steps = [];
  for (let cur = G; cur !== S; ) { const st = prev.get(cur); if (!st) break; steps.push(st); cur = st.from; }
  steps.reverse();
  const points = [], places = [];
  for (const st of steps) {
    if (st.place) places.push(st.place);
    for (const pt of st.poly) {
      if (!points.length || Math.hypot(points[points.length - 1][0] - pt[0], points[points.length - 1][1] - pt[1]) > 1e-4) points.push(pt);
    }
  }
  return { points, places, length_m: dist.get(G) || 0, startSnap: startCands[0]?.sp, goalSnap: goalCands[0]?.gp };
}

export function expandWaypointsOnRoad(siteMap, waypoints) {
  if (!Array.isArray(waypoints) || waypoints.length < 2) return [];
  const dense = [];
  const pushPt = (x, y) => {
    if (!dense.length || Math.hypot(dense[dense.length - 1][0] - x, dense[dense.length - 1][1] - y) > 1e-4) dense.push([x, y]);
  };
  for (let i = 0; i < waypoints.length - 1; i++) {
    const a = waypoints[i], b = waypoints[i + 1];
    const ax = Array.isArray(a) ? a[0] : a.x, ay = Array.isArray(a) ? a[1] : a.y;
    const bx = Array.isArray(b) ? b[0] : b.x, by = Array.isArray(b) ? b[1] : b.y;
    if (Math.hypot(bx - ax, by - ay) > 0.11 && siteMap?.edges?.length) {
      const seg = roadPolylineBetween(siteMap, { x: ax, y: ay }, { x: bx, y: by });
      if (seg && seg.points.length >= 2) {
        for (const [px, py] of seg.points) pushPt(px, py);
        continue;
      }
    }
    pushPt(ax, ay); pushPt(bx, by);
  }
  return dense;
}
