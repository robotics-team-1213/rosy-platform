// D-536 로봇 상황 층 — GET /api/fleet/guide 의 지도 자세를 실제 물리 축척 몸체·방향·불확실성 고리로, 안내 목표와
// 주행 경로를 도로 폴리라인(lane_graph.yaml)을 따라 그린다.

const SEVERITY_TOKEN = { crit: "--status-crit", warn: "--status-warn", info: "--ink-quiet" };

/** Findings a robot has, worst first (crit, warn, info). */
export function guideFindings(guide, robotId) {
  const row = (guide?.robots || []).find((r) => r.robot_id === robotId);
  const order = { crit: 0, warn: 1, info: 2 };
  return [...(row?.findings || [])].sort((a, b) => order[a.severity] - order[b.severity]);
}

/** Exception-queue rows (D-493 one rule) for one robot; info rows are not queued. */
export function guideAttention(guide, robotId) {
  return guideFindings(guide, robotId).filter((f) => f.severity !== "info")
    .map((f) => ({ severity: f.severity, text: `: ${f.text}`, code: f.code, target: f.target || null }));
}

/** "rosy_26 · LOCALIZED · ±0.12 m" for the chip next to the body circle. */
export function poseLabel(row) {
  const gone = row.online === false ? " · 연결 끊김" : "";
  if (!row.pose) return `${row.robot_id} · 위치 모름${gone}`;
  const pin = row.pose.anchor_source === "operator_pin"
    ? ` · 운영자 핀${typeof row.pose.anchor_age_s === "number" ? ` ${Math.round(row.pose.anchor_age_s)} s` : ""}` : "";
  if (typeof row.pose.u_m === "number") {
    return `${row.robot_id} · ±${row.pose.u_m.toFixed(2)} m${row.pose.state === "DEGRADED" ? " · 추정" : ""}${pin}${gone}`;
  }
  const deg = typeof row.pose.yaw === "number" ? ` · ${Math.round((row.pose.yaw * 180) / Math.PI)}°` : "";
  return `${row.robot_id}${deg}${row.pose.state === "DEGRADED" ? " · 추정" : ""}${pin}${gone}`;
}

/** D-540 4: screen geometry of each placed robot at exact physical scale (~5.2 cm radius for Pinky Pro). */
export function guideMarks(guide, toPoint) {
  const scaleAt = (x, y, m) => {
    const a = toPoint(x, y), b = toPoint(x + m, y);
    return Math.hypot(b.x - a.x, b.y - a.y);
  };
  const ahead = (x, y, yaw, m) => toPoint(x + Math.cos(yaw) * m, y + Math.sin(yaw) * m);
  return (guide?.robots || []).flatMap((row, index) => {
    if (!row.pose) return [];
    const { x, y, yaw, u_m: u } = row.pose;
    const bodyM = Math.min(typeof row.body_radius_m === "number" && row.body_radius_m > 0 ? row.body_radius_m : 0.052, 0.055);
    const uClamped = Math.min(typeof u === "number" && u >= 0 ? u : 0.02, 0.035);
    const r = Math.max(5, scaleAt(x, y, bodyM));
    const ring = Math.max(r + 2, scaleAt(x, y, bodyM + uClamped));
    const target = (row.findings || []).find((f) => f.target)?.target;
    return [{
      row,
      index,
      p: toPoint(x, y),
      r,
      ring,
      bodyM,
      alert: row.worst && row.worst !== "info" ? row.worst : "",
      tip: typeof yaw === "number" ? ahead(x, y, yaw, bodyM * 1.45) : null,
      target: target ? { x: target.x, y: target.y, yaw: target.yaw, q: toPoint(target.x, target.y), tip: ahead(target.x, target.y, target.yaw, 0.07) } : null,
    }];
  });
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

/** Compute road-constrained polyline between startPose and targetXY on siteMap.
 *  Evaluates all candidate edges near junctions so shortest valid road routes are always chosen. */
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
  if (!snaps.length || minGoalDist > 0.35) return null;
  const startCands = snaps.filter((s) => s.sp.dist <= minStartDist + 0.06);
  const goalCands = snaps.filter((s) => s.gp.dist <= minGoalDist + 0.06);

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
    if (e.direction === "two_way") {
      addArc(S, e.from, sp.s + pen, slicePoly(e.polyline, sp.s, 0), e.from);
    }
  }
  for (const gc of goalCands) {
    const e = gc.edge, gp = gc.gp, pen = (gp.dist - minGoalDist) * 1.5;
    addArc(e.from, G, gp.s + pen, slicePoly(e.polyline, 0, gp.s), null);
    if (e.direction === "two_way") {
      addArc(e.to, G, Math.max(0, gp.totalLen - gp.s) + pen, slicePoly(e.polyline, gp.totalLen, gp.s), null);
    }
  }
  // Direct same-edge arcs when start and goal lie on the same edge
  for (const sc of startCands) {
    const gc = goalCands.find((g) => g.edge.id === sc.edge.id);
    if (!gc) continue;
    const e = sc.edge, sp = sc.sp, gp = gc.gp;
    if (gp.s >= sp.s - 1e-4 || e.direction === "two_way") {
      const pts = slicePoly(e.polyline, sp.s, gp.s);
      const d = Math.abs(gp.s - sp.s) + (sp.dist - minStartDist) + (gp.dist - minGoalDist);
      addArc(S, G, d, pts, null);
    }
  }

  const dist = new Map([[S, 0]]), prev = new Map(), visited = new Set();
  while (true) {
    let u = null, bestD = Infinity;
    for (const [node, d] of dist.entries()) {
      if (!visited.has(node) && d < bestD) { bestD = d; u = node; }
    }
    if (u === null || u === G) break;
    visited.add(u);
    for (const edge of adj.get(u) || []) {
      const nd = bestD + edge.cost;
      if (nd < (dist.get(edge.to) ?? Infinity)) {
        dist.set(edge.to, nd);
        prev.set(edge.to, { from: u, ...edge });
      }
    }
  }
  if (!prev.has(G)) return null;
  const steps = [];
  for (let cur = G; cur !== S; ) {
    const st = prev.get(cur);
    if (!st) break;
    steps.push(st);
    cur = st.from;
  }
  steps.reverse();
  const points = [];
  const places = [];
  for (const st of steps) {
    if (st.place) places.push(st.place);
    for (const pt of st.poly) {
      if (!points.length || Math.hypot(points[points.length - 1][0] - pt[0], points[points.length - 1][1] - pt[1]) > 1e-4) {
        points.push(pt);
      }
    }
  }
  return { points, places, length_m: dist.get(G) || 0, startSnap: startCands[0]?.sp, goalSnap: goalCands[0]?.gp };
}

/** Expand any sparse waypoint array along the siteMap road polylines so lines never cut across corners/medians. */
function expandWaypointsOnRoad(siteMap, waypoints) {
  if (!Array.isArray(waypoints) || waypoints.length < 2) return [];
  const dense = [];
  const pushPt = (x, y) => {
    if (!dense.length || Math.hypot(dense[dense.length - 1][0] - x, dense[dense.length - 1][1] - y) > 1e-4) {
      dense.push([x, y]);
    }
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
    pushPt(ax, ay);
    pushPt(bx, by);
  }
  return dense;
}

export function drawGuide(ctx, toPoint, { guide, css, colorOf, drawChip, on, focusedRobotId = null, view = null }) {
  const scaleAt = (x, y, m) => {
    const a = toPoint(x, y), b = toPoint(x + m, y);
    return Math.hypot(b.x - a.x, b.y - a.y);
  };
  const ahead = (x, y, yaw, m) => toPoint(x + Math.cos(yaw) * m, y + Math.sin(yaw) * m);
  const labelsOn = view?.layers?.labels !== false;
  const omxOn = view?.layers?.omx !== false;
  const hovered = view?.hoverEntity || null;

  // 1. Draw anchored OMX-AI arms (base anchor + 4x zoomed tracked head/gripper vector)
  const anchors = omxOn && Array.isArray(view?.anchors) ? view.anchors : [];
  for (const anc of anchors) {
    if (anc.kind !== "omx_ai") continue;
    const baseP = toPoint(anc.base_x, anc.base_y);
    const headP = toPoint(anc.head_x ?? anc.base_x, anc.head_y ?? anc.base_y);
    const reachPx = Math.max(14, scaleAt(anc.base_x, anc.base_y, anc.reach_m || 0.28));
    const isHoveredOmx = hovered?.kind === "omx_ai" && hovered.id === anc.target_id;
    const isSelectedOmx = isHoveredOmx || view?.focusAnchorId === anc.target_id || view?.anchorPinTarget === anc.target_id;
    const armColor = isSelectedOmx ? "#00e5ff" : "#ffb300";
    ctx.save();
    // Workspace reach circle (subtle unless hovered/selected)
    ctx.beginPath();
    ctx.arc(baseP.x, baseP.y, reachPx, 0, Math.PI * 2);
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = isSelectedOmx ? 2.0 : 1.0;
    ctx.strokeStyle = armColor;
    ctx.globalAlpha = isSelectedOmx ? 0.8 : 0.28;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
    // Base anchor square
    const bs = isSelectedOmx ? 6.5 : 4.5;
    ctx.fillStyle = "#18202c";
    ctx.strokeStyle = armColor;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.rect(baseP.x - bs, baseP.y - bs, bs * 2, bs * 2);
    ctx.fill();
    ctx.stroke();
    // Base -> Head link vector
    ctx.beginPath();
    ctx.moveTo(baseP.x, baseP.y);
    ctx.lineTo(headP.x, headP.y);
    ctx.lineWidth = isSelectedOmx ? 3.2 : 2.2;
    ctx.strokeStyle = armColor;
    ctx.stroke();
    // Distal Head / Gripper marker + orientation tip
    ctx.beginPath();
    ctx.arc(headP.x, headP.y, isSelectedOmx ? 5.5 : 4, 0, Math.PI * 2);
    ctx.fillStyle = "#00e5ff";
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#ffffff";
    ctx.stroke();
    if (typeof anc.head_yaw === "number") {
      const hTip = ahead(anc.head_x ?? anc.base_x, anc.head_y ?? anc.base_y, anc.head_yaw, 0.055);
      ctx.beginPath();
      ctx.moveTo(headP.x, headP.y);
      ctx.lineTo(hTip.x, hTip.y);
      ctx.lineWidth = 1.8;
      ctx.strokeStyle = "#00e5ff";
      ctx.stroke();
    }
    ctx.restore();
    if (labelsOn || isHoveredOmx) {
      const deg = typeof anc.head_yaw === "number" ? ` ${Math.round((anc.head_yaw * 180) / Math.PI)}°` : "";
      const shortText = isHoveredOmx
        ? `${anc.target_id.toUpperCase()} · (${(anc.head_x ?? anc.base_x).toFixed(2)}, ${(anc.head_y ?? anc.base_y).toFixed(2)}m)${deg}`
        : `${anc.target_id.toUpperCase()}${deg}`;
      drawChip(ctx, null, headP.x, headP.y - 12, shortText, isSelectedOmx ? "warn" : "");
    }
  }

  // 1b. Draw active Road + Nav2 planned trajectory strictly along lane_graph.yaml polylines
  const roadPlan = on ? view?.activeRoadPlan : null;
  const siteMapObj = view?.activeSiteMap?.map;
  if (roadPlan && Array.isArray(roadPlan.waypoints_site) && roadPlan.waypoints_site.length >= 2 && Date.now() - (roadPlan.at || 0) < 45000) {
    const planRobot = (guide?.robots || []).find((r) => r.robot_id === roadPlan.robotId);
    const lastRaw = roadPlan.waypoints_site[roadPlan.waypoints_site.length - 1];
    const lx = Array.isArray(lastRaw) ? lastRaw[0] : lastRaw.x;
    const ly = Array.isArray(lastRaw) ? lastRaw[1] : lastRaw.y;
    if (planRobot?.pose && Date.now() - (roadPlan.at || 0) > 2500 && Math.hypot(planRobot.pose.x - lx, planRobot.pose.y - ly) < 0.065) {
      view.activeRoadPlan = null;
    } else {
      const densePts = expandWaypointsOnRoad(siteMapObj, roadPlan.waypoints_site);
      if (densePts.length >= 2) {
        ctx.save();
        ctx.beginPath();
        densePts.forEach(([wx, wy], idx) => {
          const pt = toPoint(wx, wy);
          if (idx === 0) ctx.moveTo(pt.x, pt.y);
          else ctx.lineTo(pt.x, pt.y);
        });
        ctx.lineWidth = 3.0;
        ctx.strokeStyle = "#00e5ff";
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.setLineDash([7, 4]);
        ctx.stroke();
        ctx.setLineDash([]);

        // Directional flow chevrons every ~0.35 m along the road polyline
        let distAcc = 0;
        for (let i = 0; i < densePts.length - 1; i++) {
          const [x0, y0] = densePts[i], [x1, y1] = densePts[i + 1];
          const segM = Math.hypot(x1 - x0, y1 - y0);
          distAcc += segM;
          if (distAcc >= 0.35) {
            distAcc = 0;
            const p0 = toPoint(x0, y0), p1 = toPoint(x1, y1);
            const ang = Math.atan2(p0.y - p1.y, p0.x - p1.x);
            ctx.beginPath();
            for (const turn of [-0.55, 0.55]) {
              ctx.moveTo(p1.x, p1.y);
              ctx.lineTo(p1.x + Math.cos(ang + turn) * 6, p1.y + Math.sin(ang + turn) * 6);
            }
            ctx.lineWidth = 2;
            ctx.strokeStyle = "#00e5ff";
            ctx.stroke();
          }
        }

        // Draw start & goal markers
        const endIndices = [0, densePts.length - 1];
        for (const idx of endIndices) {
          const [wx, wy] = densePts[idx];
          const pt = toPoint(wx, wy);
          ctx.beginPath();
          ctx.arc(pt.x, pt.y, idx === densePts.length - 1 ? 5 : 3.5, 0, Math.PI * 2);
          ctx.fillStyle = "#00e5ff";
          ctx.fill();
          ctx.lineWidth = 1.5;
          ctx.strokeStyle = "#101824";
          ctx.stroke();
        }
        if (labelsOn) {
          const [lastWx, lastWy] = densePts[densePts.length - 1];
          const lastPt = toPoint(lastWx, lastWy);
          const placesStr = Array.isArray(roadPlan.places) && roadPlan.places.length ? roadPlan.places.join("→") : "도로경로";
          drawChip(ctx, null, lastPt.x, lastPt.y - 16, `🛣️ ${placesStr}`, "");
        }
        ctx.restore();
      }
    }
  }

  // 1c. Highlight hovered place node on map
  if (hovered?.kind === "place" && hovered.place) {
    const pp = toPoint(hovered.place.x, hovered.place.y);
    ctx.save();
    ctx.beginPath();
    ctx.arc(pp.x, pp.y, 9, 0, Math.PI * 2);
    ctx.strokeStyle = "#00e5ff";
    ctx.lineWidth = 2.2;
    ctx.stroke();
    ctx.restore();
  }

  if (!on || !guide?.robots?.length) return;
  const marks = guideMarks(guide, toPoint);
  for (const { row, p, r, ring, alert: worst, tip, target } of marks) {
    const colour = colorOf(row.robot_id);
    const alert = worst ? css(SEVERITY_TOKEN[worst]) : null;
    const isHoveredRobot = hovered?.kind === "pinky" && hovered.id === row.robot_id;
    const isFocused = (focusedRobotId && row.robot_id === focusedRobotId) || isHoveredRobot;
    ctx.save();
    ctx.globalAlpha = row.online ? 1 : 0.45;

    // Tight selection/hover ring right around the true physical chassis (no giant radar rings)
    if (isFocused) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, r + 4, 0, Math.PI * 2);
      ctx.lineWidth = 2.2;
      ctx.strokeStyle = isHoveredRobot ? "#00e5ff" : colour;
      ctx.stroke();
    }
    // Tight uncertainty ring (body + 2cm camera tolerance)
    if (ring > r + 1.5) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, ring, 0, Math.PI * 2);
      ctx.setLineDash([2, 3]);
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = colour;
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // Physical robot body circle (radius = 5.2 cm in world coordinates)
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fillStyle = colour;
    ctx.globalAlpha *= row.pose.state === "LOCALIZED" ? 0.55 : 0.32;
    ctx.fill();
    ctx.globalAlpha = row.online ? 1 : 0.45;
    if (row.pose.state !== "LOCALIZED") ctx.setLineDash([3, 2]);
    ctx.lineWidth = isFocused ? 2.5 : (alert ? 2.2 : 1.8);
    ctx.strokeStyle = isHoveredRobot ? "#00e5ff" : (alert || colour);
    ctx.stroke();
    ctx.setLineDash([]);

    // Forward heading vector (nose arrow)
    if (tip) {
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(tip.x, tip.y);
      ctx.lineWidth = 2.4;
      ctx.strokeStyle = "#00e5ff";
      ctx.lineCap = "round";
      ctx.stroke();
      const back = Math.atan2(p.y - tip.y, p.x - tip.x);
      ctx.beginPath();
      for (const turn of [-0.52, 0.52]) {
        ctx.moveTo(tip.x, tip.y);
        ctx.lineTo(tip.x + Math.cos(back + turn) * 5.5, tip.y + Math.sin(back + turn) * 5.5);
      }
      ctx.stroke();
    }

    // Live hover trajectory preview line from focused Pinky to cursor strictly along road graph
    if (isFocused && view?.hoverWorld && !view?.pinning && !view?.anchorPinTarget && hovered?.kind !== "pinky" && hovered?.kind !== "omx_ai") {
      const hw = view.hoverWorld;
      const roadHover = roadPolylineBetween(siteMapObj, row.pose, hw);
      if (roadHover && roadHover.points.length >= 2 && roadHover.length_m > 0.03) {
        ctx.beginPath();
        roadHover.points.forEach(([wx, wy], idx) => {
          const pt = toPoint(wx, wy);
          if (idx === 0) ctx.moveTo(pt.x, pt.y);
          else ctx.lineTo(pt.x, pt.y);
        });
        ctx.setLineDash([5, 4]);
        ctx.lineWidth = 2.2;
        ctx.lineJoin = "round";
        ctx.strokeStyle = "#00e5ff";
        ctx.stroke();
        ctx.setLineDash([]);
        const endPt = roadHover.points[roadHover.points.length - 1];
        const hp = toPoint(endPt[0], endPt[1]);
        ctx.beginPath();
        ctx.arc(hp.x, hp.y, 4.5, 0, Math.PI * 2);
        ctx.strokeStyle = "#00e5ff";
        ctx.lineWidth = 2;
        ctx.stroke();
        if (labelsOn) {
          const viaTxt = roadHover.places?.length ? ` · ${roadHover.places.join("→")}` : "";
          const hoverLabel = hw.place
            ? `${hw.place.id} (${roadHover.length_m.toFixed(2)}m${viaTxt})`
            : `${roadHover.length_m.toFixed(2)}m${viaTxt}`;
          drawChip(ctx, null, hp.x, hp.y - 14, hoverLabel, "");
        }
      }
    }

    // Guide target (e.g. charger return): always routed along road graph instead of cutting straight across
    if (target) {
      const roadTarget = roadPolylineBetween(siteMapObj, row.pose, target);
      ctx.beginPath();
      if (roadTarget && roadTarget.points.length >= 2) {
        roadTarget.points.forEach(([wx, wy], idx) => {
          const pt = toPoint(wx, wy);
          if (idx === 0) ctx.moveTo(pt.x, pt.y);
          else ctx.lineTo(pt.x, pt.y);
        });
      } else {
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(target.q.x, target.q.y);
      }
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 1.8;
      ctx.strokeStyle = alert || colour;
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(target.q.x, target.q.y, 3.5, 0, Math.PI * 2);
      ctx.fillStyle = alert || colour;
      ctx.fill();
    }
    ctx.restore();

    if (labelsOn || isHoveredRobot) {
      const labelText = isHoveredRobot && row.pose
        ? `★ ${row.robot_id} (${row.pose.x.toFixed(2)}, ${row.pose.y.toFixed(2)}m · HEAD ${Math.round(((row.pose.yaw || 0) * 180) / Math.PI)}°)`
        : poseLabel(row);
      drawChip(ctx, null, p.x, p.y - ring - 10, labelText, worst);
    }
  }
  window.__guideLayer = { robots: marks.length, findings: guide.robots.reduce((n, r) => n + (r.findings || []).length, 0) };
}


