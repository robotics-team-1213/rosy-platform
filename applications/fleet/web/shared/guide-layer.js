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

import { roadPolylineBetween, expandWaypointsOnRoad } from "./route-attention.js";
export { roadPolylineBetween, expandWaypointsOnRoad };

export function drawGuide(ctx, toPoint, { guide, css, colorOf, drawChip, on, focusedRobotId = null, view = null }) {
  const scaleAt = (x, y, m) => {
    const a = toPoint(x, y), b = toPoint(x + m, y);
    return Math.hypot(b.x - a.x, b.y - a.y);
  };
  const ahead = (x, y, yaw, m) => toPoint(x + Math.cos(yaw) * m, y + Math.sin(yaw) * m);
  const labelsOn = view?.layers?.labels !== false;
  const omxOn = view?.layers?.omx !== false;
  const hovered = view?.hoverEntity || null;

  const primaryCol = css("--series-primary");
  const selCol = css("--selection") || primaryCol;
  const warnCol = css("--status-warn");
  const goalCol = css("--series-goal");
  const inkCol = css("--ink");
  const recessedCol = css("--surface-recessed");
  const scrimCol = css("--scrim-solid");

  // 1. Draw anchored OMX-AI arms (base anchor + 4x zoomed tracked head/gripper vector)
  const anchors = omxOn ? (Array.isArray(view?.anchors) ? view.anchors : Array.isArray(view?.guide?.anchors) ? view.guide.anchors : []) : [];
  for (const anc of anchors) {
    if (anc.kind !== "omx_ai") continue;
    const baseP = toPoint(anc.base_x, anc.base_y);
    const headP = toPoint(anc.head_x ?? anc.base_x, anc.head_y ?? anc.base_y);
    const reachPx = Math.max(14, scaleAt(anc.base_x, anc.base_y, anc.reach_m || 0.28));
    const isHoveredOmx = hovered?.kind === "omx_ai" && hovered.id === anc.target_id;
    const isFocusedOmx = focusedRobotId === anc.target_id || view?.focusAnchorId === anc.target_id;
    const isSelectedOmx = isHoveredOmx || isFocusedOmx || view?.anchorPinTarget === anc.target_id;
    const armColor = isSelectedOmx ? primaryCol : warnCol;
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
    ctx.fillStyle = recessedCol;
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
    const headR = isSelectedOmx ? 5.5 : 4;
    ctx.beginPath();
    ctx.arc(headP.x, headP.y, headR, 0, Math.PI * 2);
    ctx.fillStyle = primaryCol;
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = inkCol;
    ctx.stroke();
    if (isFocusedOmx) {
      ctx.beginPath();
      ctx.arc(headP.x, headP.y, headR + 6, 0, Math.PI * 2);
      ctx.lineWidth = 2.2;
      ctx.strokeStyle = selCol;
      ctx.stroke();
    }
    if (typeof anc.head_yaw === "number") {
      const hTip = ahead(anc.head_x ?? anc.base_x, anc.head_y ?? anc.base_y, anc.head_yaw, 0.055);
      ctx.beginPath();
      ctx.moveTo(headP.x, headP.y);
      ctx.lineTo(hTip.x, hTip.y);
      ctx.lineWidth = 1.8;
      ctx.strokeStyle = primaryCol;
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

  // 1b. Draw locked Selected Goal Pin + Active Road + Nav2 trajectory strictly along lane_graph.yaml polylines
  const selectedGoal = on ? view?.selectedGoal : null;
  const roadPlan = on ? view?.activeRoadPlan : null;
  const siteMapObj = view?.activeSiteMap?.map;
  const activeRouteSource = selectedGoal || roadPlan;
  if (activeRouteSource && Date.now() - (activeRouteSource.at || 0) < 120000) {
    const planRobotId = activeRouteSource.robotId || focusedRobotId || "rosy_46";
    const planRobot = (guide?.robots || []).find((r) => r.robot_id === planRobotId);
    const rawWaypoints = roadPlan?.waypoints_site?.length >= 2
      ? roadPlan.waypoints_site
      : (selectedGoal?.points?.length >= 2 ? selectedGoal.points : null);
    let densePts = rawWaypoints ? expandWaypointsOnRoad(siteMapObj, rawWaypoints) : [];
    if (densePts.length < 2 && planRobot?.pose && typeof activeRouteSource.x === "number") {
      const fallbackRoad = roadPolylineBetween(siteMapObj, planRobot.pose, activeRouteSource);
      densePts = fallbackRoad?.points?.length >= 2
        ? fallbackRoad.points
        : [[planRobot.pose.x, planRobot.pose.y], [activeRouteSource.x, activeRouteSource.y]];
    }
    const goalX = typeof selectedGoal?.x === "number" ? selectedGoal.x : (densePts.length ? densePts[densePts.length - 1][0] : null);
    const goalY = typeof selectedGoal?.y === "number" ? selectedGoal.y : (densePts.length ? densePts[densePts.length - 1][1] : null);
    if (planRobot?.pose && goalX !== null && Date.now() - (activeRouteSource.at || 0) > 3500 && Math.hypot(planRobot.pose.x - goalX, planRobot.pose.y - goalY) < 0.055) {
      if (selectedGoal) selectedGoal.statusText = "도착 완료";
    }
    const routeColor = selectedGoal?.status === "PREVIEW" ? warnCol : goalCol;
    ctx.save();
    if (densePts.length >= 2) {
      // High-contrast dark halo underneath selected road polyline
      ctx.beginPath();
      densePts.forEach(([wx, wy], idx) => {
        const pt = toPoint(wx, wy);
        if (idx === 0) ctx.moveTo(pt.x, pt.y);
        else ctx.lineTo(pt.x, pt.y);
      });
      ctx.lineWidth = 5.4;
      ctx.strokeStyle = scrimCol;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.stroke();

      // Main locked road trajectory line
      ctx.beginPath();
      densePts.forEach(([wx, wy], idx) => {
        const pt = toPoint(wx, wy);
        if (idx === 0) ctx.moveTo(pt.x, pt.y);
        else ctx.lineTo(pt.x, pt.y);
      });
      ctx.lineWidth = 3.2;
      ctx.strokeStyle = routeColor;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.stroke();

      // Directional flow chevrons every ~0.32 m along the road polyline
      let distAcc = 0;
      for (let i = 0; i < densePts.length - 1; i++) {
        const [x0, y0] = densePts[i], [x1, y1] = densePts[i + 1];
        const segM = Math.hypot(x1 - x0, y1 - y0);
        distAcc += segM;
        if (distAcc >= 0.32) {
          distAcc = 0;
          const p0 = toPoint(x0, y0), p1 = toPoint(x1, y1);
          const ang = Math.atan2(p0.y - p1.y, p0.x - p1.x);
          ctx.beginPath();
          for (const turn of [-0.55, 0.55]) {
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p1.x + Math.cos(ang + turn) * 6.5, p1.y + Math.sin(ang + turn) * 6.5);
          }
          ctx.lineWidth = 2.2;
          ctx.strokeStyle = inkCol;
          ctx.stroke();
        }
      }

      // Draw start dot on road
      const [sx, sy] = densePts[0];
      const sPt = toPoint(sx, sy);
      ctx.beginPath();
      ctx.arc(sPt.x, sPt.y, 4, 0, Math.PI * 2);
      ctx.fillStyle = routeColor;
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = recessedCol;
      ctx.stroke();
    }

    // Draw unmistakable Selected Target Bullseye Pin at the clicked coordinate
    if (goalX !== null && goalY !== null) {
      const gp = toPoint(goalX, goalY);
      if (densePts.length >= 2) {
        const [lastRx, lastRy] = densePts[densePts.length - 1];
        if (Math.hypot(lastRx - goalX, lastRy - goalY) > 0.02) {
          const lPt = toPoint(lastRx, lastRy);
          ctx.beginPath();
          ctx.moveTo(lPt.x, lPt.y);
          ctx.lineTo(gp.x, gp.y);
          ctx.setLineDash([4, 3]);
          ctx.lineWidth = 2.2;
          ctx.strokeStyle = routeColor;
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }
      // Outer bullseye target ring
      ctx.beginPath();
      ctx.arc(gp.x, gp.y, 10.5, 0, Math.PI * 2);
      ctx.globalAlpha = 0.18;
      ctx.fillStyle = routeColor;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = 2.4;
      ctx.strokeStyle = routeColor;
      ctx.stroke();
      // Crosshair ticks around the target pin
      ctx.beginPath();
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        ctx.moveTo(gp.x + dx * 7, gp.y + dy * 7);
        ctx.lineTo(gp.x + dx * 14, gp.y + dy * 14);
      }
      ctx.lineWidth = 2.0;
      ctx.strokeStyle = routeColor;
      ctx.stroke();
      // Inner bullseye dot
      ctx.beginPath();
      ctx.arc(gp.x, gp.y, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = routeColor;
      ctx.fill();
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = inkCol;
      ctx.stroke();

      if (labelsOn) {
        const placesList = roadPlan?.places?.length ? roadPlan.places : selectedGoal?.places;
        const viaStr = Array.isArray(placesList) && placesList.length ? ` · ${placesList.join("→")}` : "";
        const lenVal = roadPlan?.length_m ?? selectedGoal?.length_m;
        const lenStr = typeof lenVal === "number" ? ` · ${lenVal.toFixed(2)}m` : "";
        const statusStr = selectedGoal?.statusText ? ` · ${selectedGoal.statusText}` : "";
        const goalTitle = selectedGoal?.label || `(${goalX.toFixed(2)}, ${goalY.toFixed(2)})`;
        drawChip(ctx, null, gp.x, gp.y - 18, `목표 ${goalTitle}${lenStr}${viaStr}${statusStr}`, "good");
      }
    }
    ctx.restore();
  }

  // 1c. Highlight hovered place node and persistent map selection (place or empty point)
  if (hovered?.kind === "place" && hovered.place) {
    const pp = toPoint(hovered.place.x, hovered.place.y);
    ctx.save();
    ctx.beginPath();
    ctx.arc(pp.x, pp.y, 9, 0, Math.PI * 2);
    ctx.strokeStyle = primaryCol;
    ctx.lineWidth = 2.2;
    ctx.stroke();
    ctx.restore();
  }

  const mapSel = view?.mapSelection || null;
  if (mapSel?.kind === "place" && mapSel.place && typeof mapSel.place.x === "number" && typeof mapSel.place.y === "number") {
    const sp = toPoint(mapSel.place.x, mapSel.place.y);
    ctx.save();
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, 10, 0, Math.PI * 2);
    ctx.strokeStyle = selCol;
    ctx.lineWidth = 2.4;
    ctx.stroke();
    ctx.beginPath();
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      ctx.moveTo(sp.x + dx * 4, sp.y + dy * 4);
      ctx.lineTo(sp.x + dx * 7, sp.y + dy * 7);
    }
    ctx.lineWidth = 1.6;
    ctx.strokeStyle = selCol;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = selCol;
    ctx.fill();
    ctx.restore();
  }

  const selPt = mapSel?.kind === "point" ? (mapSel.point || mapSel) : null;
  if (selPt && typeof selPt.x === "number" && typeof selPt.y === "number") {
    const goalActive = selectedGoal && Date.now() - (selectedGoal.at || 0) < 120000;
    const goalPinsSpot = Boolean(goalActive && typeof selectedGoal.x === "number" && typeof selectedGoal.y === "number"
      && Math.hypot(selectedGoal.x - selPt.x, selectedGoal.y - selPt.y) < 0.03);
    if (!goalPinsSpot) {
      const pp = toPoint(selPt.x, selPt.y);
      ctx.save();
      ctx.beginPath();
      ctx.arc(pp.x, pp.y, 10, 0, Math.PI * 2);
      ctx.setLineDash([3, 3]);
      ctx.lineWidth = 1.8;
      ctx.strokeStyle = selCol;
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        ctx.moveTo(pp.x + dx * 4, pp.y + dy * 4);
        ctx.lineTo(pp.x + dx * 13, pp.y + dy * 13);
      }
      ctx.lineWidth = 2.0;
      ctx.strokeStyle = selCol;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(pp.x, pp.y, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = selCol;
      ctx.fill();
      ctx.restore();
      if (labelsOn && typeof drawChip === "function") {
        drawChip(ctx, null, pp.x, pp.y - 18, `(${selPt.x.toFixed(2)}, ${selPt.y.toFixed(2)}) m`, "info");
      }
    }
  }

  if (!on || !guide?.robots?.length) return;
  const marks = guideMarks(guide, toPoint);
  for (const { row, p, r, ring, alert: worst, tip, target } of marks) {
    const colour = colorOf(row.robot_id);
    const alert = worst ? css(SEVERITY_TOKEN[worst]) : null;
    const isHoveredRobot = hovered?.kind === "pinky" && hovered.id === row.robot_id;
    const isSelectedRobot = Boolean(focusedRobotId && row.robot_id === focusedRobotId);
    const isFocused = isSelectedRobot || isHoveredRobot;
    ctx.save();
    ctx.globalAlpha = row.online ? 1 : 0.45;

    // Tight selection/hover ring right around the true physical chassis (no giant radar rings)
    if (isFocused) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, r + 4, 0, Math.PI * 2);
      ctx.lineWidth = 2.2;
      ctx.strokeStyle = isHoveredRobot ? primaryCol : colour;
      ctx.stroke();
    }
    if (isSelectedRobot) {
      ctx.save();
      ctx.globalAlpha = 1;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r + 6, 0, Math.PI * 2);
      ctx.lineWidth = 2.2;
      ctx.strokeStyle = selCol;
      ctx.stroke();
      ctx.restore();
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
    ctx.strokeStyle = isHoveredRobot ? primaryCol : (alert || colour);
    ctx.stroke();
    ctx.setLineDash([]);

    // Forward heading vector (nose arrow)
    if (tip) {
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(tip.x, tip.y);
      ctx.lineWidth = 2.4;
      ctx.strokeStyle = primaryCol;
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
    const nearSelectedGoal = selectedGoal && view?.hoverWorld && Math.hypot(selectedGoal.x - view.hoverWorld.x, selectedGoal.y - view.hoverWorld.y) < 0.06;
    if (isFocused && view?.hoverWorld && !nearSelectedGoal && !view?.pinning && !view?.anchorPinTarget && hovered?.kind !== "pinky" && hovered?.kind !== "omx_ai") {
      const hw = view.hoverWorld;
      const roadHover = roadPolylineBetween(siteMapObj, row.pose, hw);
      if (roadHover && roadHover.points.length >= 2 && roadHover.length_m > 0.03) {
        ctx.save();
        ctx.globalAlpha = 0.58;
        ctx.beginPath();
        roadHover.points.forEach(([wx, wy], idx) => {
          const pt = toPoint(wx, wy);
          if (idx === 0) ctx.moveTo(pt.x, pt.y);
          else ctx.lineTo(pt.x, pt.y);
        });
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1.7;
        ctx.lineJoin = "round";
        ctx.strokeStyle = primaryCol;
        ctx.stroke();
        ctx.setLineDash([]);
        const hp = toPoint(hw.x, hw.y);
        ctx.beginPath();
        ctx.arc(hp.x, hp.y, 4, 0, Math.PI * 2);
        ctx.strokeStyle = primaryCol;
        ctx.lineWidth = 1.6;
        ctx.stroke();
        ctx.restore();
        if (labelsOn) {
          const viaTxt = roadHover.places?.length ? ` · ${roadHover.places.join("→")}` : "";
          const hoverLabel = hw.place
            ? `미리보기: ${hw.place.id} (${roadHover.length_m.toFixed(2)}m${viaTxt})`
            : `클릭 시 목표 고정 (${roadHover.length_m.toFixed(2)}m${viaTxt})`;
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
        ? `${row.robot_id} (${row.pose.x.toFixed(2)}, ${row.pose.y.toFixed(2)}m · HEAD ${Math.round(((row.pose.yaw || 0) * 180) / Math.PI)}°)`
        : poseLabel(row);
      drawChip(ctx, null, p.x, p.y - ring - 10, labelText, worst);
    }
  }
  if (typeof window !== "undefined") {
    window.__guideLayer = { robots: marks.length, findings: guide.robots.reduce((n, r) => n + (r.findings || []).length, 0) };
  }
}
