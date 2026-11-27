// Active site-map stop_zone geometry, server-authoritative zone verdict, and map canvas drawing (PR 1).
import { robotMapPose } from "./localization-badge.js";

export const PLACE_SNAP_M = 0.14;
const NEAREST_ZONE_M = 0.60;

const finite = (v) => typeof v === "number" && Number.isFinite(v);

export function pointInPolygon(x, y, polygon) {
  if (!finite(x) || !finite(y) || !Array.isArray(polygon) || polygon.length < 3) return false;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i], b = polygon[j];
    if (!Array.isArray(a) || !Array.isArray(b) || !finite(a[0]) || !finite(a[1]) || !finite(b[0]) || !finite(b[1])) {
      return false;
    }
    const [xi, yi] = a, [xj, yj] = b;
    if ((yi > y) !== (yj > y)) {
      const xIntersect = ((xj - xi) * (y - yi)) / (yj - yi) + xi;
      if (x < xIntersect) inside = !inside;
    }
  }
  return inside;
}

export function polygonCentroid(polygon) {
  if (!Array.isArray(polygon) || !polygon.length) return null;
  let sx = 0, sy = 0, n = 0;
  for (const pt of polygon) {
    if (!Array.isArray(pt) || !finite(pt[0]) || !finite(pt[1])) continue;
    sx += pt[0]; sy += pt[1]; n += 1;
  }
  return n ? { x: sx / n, y: sy / n } : null;
}

function stopZonePlaces(siteMap) {
  return (siteMap?.places || []).filter((p) => Array.isArray(p?.stop_zone) && p.stop_zone.length >= 3);
}

/** Server-authoritative stop verdict from open trip detail or CORE docking state (never sightings). */
export function serverStopVerdict(robot, trips = []) {
  const rid = robot?.robot_id;
  if (!rid) return null;
  const trip = (trips || []).find((t) => t?.robot_id === rid) || null;
  const detail = trip?.detail || {};
  const prec = detail.named_stop_precision;
  const placeId = detail.named_stop_dispatch?.place || trip?.to || null;
  if (prec?.decision === "IN_TOLERANCE") {
    return { state: "in", tone: "good", label: "정지 구역 진입 확인", source: "server", placeId };
  }
  if (prec?.decision === "REPARK") {
    return { state: "repark", tone: "warn", label: "재정렬 필요", source: "server", placeId };
  }
  if (prec?.decision === "HOLD") {
    return { state: "hold", tone: "warn", label: "정밀 정지 보류", source: "server", placeId };
  }
  if (prec?.decision === "WAIT") {
    return { state: "wait", tone: "neutral", label: "정지 확인 대기", source: "server", placeId };
  }
  if (detail.named_stop_completion) {
    return { state: "in", tone: "good", label: "정지 구역 진입 확인", source: "server", placeId };
  }
  if (detail.named_stop_operation) {
    return { state: "correcting", tone: "neutral", label: "정밀 정지 보정 중", source: "server", placeId };
  }
  const docking = robot?.state?.docking;
  if (docking?.state === "DOCKED") {
    return { state: "in", tone: "good", label: "도킹 완료", source: "server", placeId: docking.bay || docking.station || null };
  }
  return null;
}

/** Robot-scoped zone summary: server verdict wins; client ray-casting stays neutral ("표시 계산"). */
export function stopZoneSummaryForRobot(robot, guideRow, siteMap, trips = []) {
  const server = serverStopVerdict(robot || guideRow, trips);
  if (server) return server;
  const pose = guideRow?.pose || robotMapPose(robot);
  if (!finite(pose?.x) || !finite(pose?.y)) return null;
  const zones = stopZonePlaces(siteMap);
  let nearest = null, bestDist = Infinity;
  for (const p of zones) {
    if (pointInPolygon(pose.x, pose.y, p.stop_zone)) {
      return { state: "estimate_in", tone: "neutral", label: `${p.id} 구역 안 (표시 계산)`, source: "display", placeId: String(p.id) };
    }
    const c = polygonCentroid(p.stop_zone) || (finite(p.x) && finite(p.y) ? { x: p.x, y: p.y } : null);
    if (!c) continue;
    const d = Math.hypot(pose.x - c.x, pose.y - c.y);
    if (d < bestDist) { bestDist = d; nearest = p; }
  }
  if (nearest && bestDist <= NEAREST_ZONE_M) {
    return {
      state: "estimate_out",
      tone: "neutral",
      label: `${nearest.id} 구역 밖 (${bestDist.toFixed(2)}m · 표시 계산)`,
      source: "display",
      placeId: String(nearest.id),
      distanceM: bestDist,
    };
  }
  return null;
}

export function stopZoneOccupants(place, robots = [], guideRobots = [], trips = []) {
  const pid = String(place?.id || "");
  const serverIn = [], serverWarn = [], displayIn = [];
  for (const robot of robots || []) {
    const rid = robot?.robot_id;
    const verdict = serverStopVerdict(robot, trips);
    if (!rid || !verdict || String(verdict.placeId || "") !== pid) continue;
    if (verdict.state === "in") serverIn.push(rid);
    else if (verdict.tone === "warn") serverWarn.push(rid);
  }
  for (const row of guideRobots || []) {
    const rid = row?.robot_id;
    const pose = row?.pose;
    if (!rid || serverIn.includes(rid) || !finite(pose?.x) || !finite(pose?.y)) continue;
    if (pointInPolygon(pose.x, pose.y, place?.stop_zone)) displayIn.push(rid);
  }
  const tone = serverIn.length ? "good" : serverWarn.length ? "warn" : "neutral";
  const label = serverIn.length ? `정지 구역 진입 확인 · ${serverIn.join(", ")}`
    : serverWarn.length ? `정지 보정·보류 · ${serverWarn.join(", ")}`
    : displayIn.length ? `구역 안 (표시 계산) · ${displayIn.join(", ")}`
    : `비어 있음 (표시 계산 · ${place?.stop_zone?.length || 0}꼭짓점)`;
  return { serverIn, serverWarn, displayIn, tone, label };
}

export function drawStopZones(ctx, toPoint, { activeMap, robots = [], guideRobots = [], trips = [], hoverPlaceId = null, css, on = true, labelsOn = true, lineWidth = 1.5, drawChip = null }) {
  if (!on || !ctx || !activeMap) return;
  const zones = stopZonePlaces(activeMap);
  if (!zones.length) return;
  ctx.save();
  for (const place of zones) {
    const occ = stopZoneOccupants(place, robots, guideRobots, trips);
    const hovered = String(place.id) === String(hoverPlaceId || "");
    const color = occ.tone === "good" ? css("--status-good")
      : occ.tone === "warn" ? css("--status-warn")
      : hovered && !occ.displayIn.length ? css("--series-primary")
      : css("--ink-quiet");
    ctx.beginPath();
    place.stop_zone.forEach(([x, y], i) => {
      const pt = toPoint(x, y);
      if (i === 0) ctx.moveTo(pt.x, pt.y); else ctx.lineTo(pt.x, pt.y);
    });
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.globalAlpha = occ.tone === "good" ? 0.16 : occ.tone === "warn" ? 0.14 : occ.displayIn.length ? 0.12 : (hovered ? 0.12 : 0.06);
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.lineWidth = hovered ? lineWidth * 1.3 : lineWidth;
    ctx.setLineDash(occ.tone === "good" ? [] : occ.tone === "warn" ? [5, 3] : [4, 3]);
    ctx.strokeStyle = color;
    ctx.stroke();

    if (labelsOn && drawChip) {
      const c = polygonCentroid(place.stop_zone);
      if (c) {
        const cp = toPoint(c.x, c.y);
        if (occ.serverIn.length) drawChip(ctx, null, cp.x, cp.y, `${place.id} IN · ${occ.serverIn.join(",")}`, "good", false);
        else if (occ.serverWarn.length) drawChip(ctx, null, cp.x, cp.y, `${place.id} 보정 필요`, "warn", false);
        else if (occ.displayIn.length) drawChip(ctx, null, cp.x, cp.y, `${place.id} 구역 안 (표시 계산)`, undefined, false);
        else if (hovered) drawChip(ctx, null, cp.x, cp.y, `${place.id} 정지 구역`, undefined, false);
      }
    }
  }
  ctx.setLineDash([]);
  ctx.restore();
}
