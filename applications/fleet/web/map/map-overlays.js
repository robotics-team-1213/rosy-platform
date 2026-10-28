// 현장 지도 오버레이(D-798 3.2, map-view.js에서 나눔): 칩 자리 잡기, 대형 슬롯·추적 오차, 중재 관계선,
// 카메라 관측·관제 카메라 추적, 사이트 사각형·횡단보도. 격자 paint·좌표 변환·그리기 순서는 map-view.js가 쥔다.
import { offsetLabel, preferMarkers } from "./tracking-layer.js";
import { robotMapPose } from "./localization-badge.js";

export function createMapOverlays({ view, css, font, layerOn, worldToCell, colorOf }) {
  // Map tracking visualization only; relay evidence comes from the Fleet server.
  const TRACK_WARN_M = 0.3;     // 기본 간격(0.6 m)의 절반을 넘으면 주의 색을 쓴다.

  // fleet.formation.geometry.slot_world_position 과 같은 식이다 — distance 는
  // 리더 뒤(+), lateral 은 리더 왼쪽(+)이다.
  function slotWorld(offset, pose) {
    const hx = Math.cos(pose.yaw);
    const hy = Math.sin(pose.yaw);
    const lx = -Math.sin(pose.yaw);
    const ly = Math.cos(pose.yaw);
    return {
      x: pose.x - offset.distance * hx + offset.lateral * lx,
      y: pose.y - offset.distance * hy + offset.lateral * ly,
    };
  }

  // D-359 US-008 — 이번 그리기에 놓인 칩(캔버스 픽셀, 시험은 window.__mapChips). 추적 오차와
  // 중재 칩이 겹쳐 못 읽었다: 새 칩은 빈 자리가 날 때까지 아래·위로 한 칸씩 번갈아 비킨다.
  // US-009 — 칩은 자리만 먼저 정하고(로봇 표식 상자도 피한다) 선을 다 그린 뒤 flushChips가 칠한다.
  let placedChips = [], pendingChips = [], markerBoxes = [], optionalChips = []; const CHIP_GAP = 2, CHIP_TRIES = 12;
  const chipsOverlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

  // Declutter: a chip not `important` (and without tone) never shifts; it shows only where still free.
  function chipFontSize(ctx) {
    const displayedWidth = ctx.canvas.getBoundingClientRect().width || ctx.canvas.width;
    return window.RosyPalette.canvasTextSize("micro") * Math.max(1, ctx.canvas.width / displayedWidth);
  }

  function drawChip(ctx, grid, cx, cy, text, tone, important = true) {
    const point = ctx.getTransform().transformPoint({ x: cx, y: cy });
    const fontSize = chipFontSize(ctx);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.font = font("micro", fontSize / window.RosyPalette.canvasTextSize("micro"));
    const padding = fontSize * 0.4;
    const maxTextWidth = Math.max(fontSize, ctx.canvas.width - padding * 2 - 8);
    while (ctx.measureText(text).width > maxTextWidth && text.length > 1) {
      text = `${text.slice(0, -2)}…`;
    }
    const width = ctx.measureText(text).width + padding * 2;
    const height = fontSize + padding * 2;
    const x = Math.max(width / 2 + 4, Math.min(ctx.canvas.width - width / 2 - 4, point.x));
    const clampY = (value) => Math.max(height / 2 + 4, Math.min(ctx.canvas.height - height / 2 - 4, value));
    const rectAt = (centreY) => ({ x: x - width / 2, y: centreY - height / 2, w: width, h: height, text });
    const anchorY = clampY(point.y);
    if (!important && !tone) {
      optionalChips.push({ rect: rectAt(anchorY), chip: { x, y: anchorY, width, height, fontSize, text, tone } });
      ctx.restore();
      return;
    }
    let y = anchorY;
    const taken = (r) => [...placedChips, ...markerBoxes].some((o) => chipsOverlap(r, o));
    for (let step = 1; step <= CHIP_TRIES && taken(rectAt(y)); step += 1) {
      const rows = Math.ceil(step / 2);
      y = clampY(anchorY + (step % 2 ? 1 : -1) * rows * (height + CHIP_GAP));
    }
    placedChips.push(rectAt(y));
    ctx.restore();
    pendingChips.push({ x, y, width, height, fontSize, text, tone });
  }

  function flushChips(ctx) {
    let hidden = 0;
    for (const { rect, chip } of optionalChips) {
      if ([...placedChips, ...markerBoxes].some((o) => chipsOverlap(rect, o))) { hidden += 1; continue; }
      placedChips.push(rect);
      pendingChips.push(chip);
    }
    optionalChips = [];
    window.__mapChipsHidden = hidden;
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.lineWidth = 0.4;
    for (const { x, y, width, height, fontSize, text, tone } of pendingChips) {
      ctx.font = font("micro", fontSize / window.RosyPalette.canvasTextSize("micro"));
      ctx.globalAlpha = 0.92;
      ctx.fillStyle = css("--scrim");
      ctx.fillRect(x - width / 2, y - height / 2, width, height);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = css("--surface-line");
      ctx.strokeRect(x - width / 2, y - height / 2, width, height);
      ctx.fillStyle = tone === "crit" ? css("--status-crit") : tone === "warn" ? css("--status-warn") : css("--ink");
      ctx.fillText(text, x, y);
    }
    pendingChips = [];
    ctx.restore();
  }

  function poseOf(robotId) {
    const robot = view.robots.find((r) => r.robot_id === robotId);
    return robotMapPose(robot);  // map frame only; never odom
  }

  function cellOf(grid, x, y) {
    const cell = worldToCell(grid, x, y);
    return { cx: cell.col, cy: grid.height - cell.row };
  }

  function drawFormationOverlay(ctx, grid) {
    const formation = view.formation;
    if (!formation || !formation.active) {
      window.__swarmOverlay = { ...(window.__swarmOverlay || {}), slots: 0 };
      return;
    }
    const leaderPose = poseOf(formation.leader);
    if (!leaderPose) {
      window.__swarmOverlay = { ...(window.__swarmOverlay || {}), slots: 0 };
      return;      // 리더 좌표가 없으면 슬롯을 놓을 수 없다
    }
    const leaderCell = cellOf(grid, leaderPose.x, leaderPose.y);
    const size = Math.max(3, Math.min(grid.width, grid.height) * 0.045);
    const entries = Object.entries(formation.assignment || {});
    window.__swarmOverlay = { draws: (window.__swarmOverlay?.draws || 0) + 1, slots: entries.length };
    ctx.save();
    for (const [robotId, offset] of entries) {
      const world = slotWorld(offset, leaderPose);
      const { cx, cy } = cellOf(grid, world.x, world.y);
      // 슬롯 고스트 — 배정된 자리. 로봇 색을 쓴다(누구 자리인지가 축이다).
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.7, 0, Math.PI * 2);
      ctx.strokeStyle = colorOf(robotId);
      ctx.stroke();
      const pose = poseOf(robotId);
      if (pose) {
        // 로봇 → 슬롯 연결선 + 추적 오차. 오차가 임계를 넘을 때만 주의 색을 얻는다.
        const robotCell = cellOf(grid, pose.x, pose.y);
        const error = Math.hypot(pose.x - world.x, pose.y - world.y);
        ctx.beginPath();
        ctx.setLineDash([2, 2]);
        ctx.moveTo(robotCell.cx, robotCell.cy);
        ctx.lineTo(cx, cy);
        ctx.strokeStyle = error > TRACK_WARN_M ? css("--status-warn") : css("--line-quiet");
        ctx.stroke();
        ctx.setLineDash([]);
        drawChip(ctx, grid, (robotCell.cx + cx) / 2, (robotCell.cy + cy) / 2,
          `${error.toFixed(2)}m`, error > TRACK_WARN_M ? "warn" : undefined);
      } else {
        // 좌표를 못 받은 팔로워의 슬롯은 점선으로만 — 리더와의 연결이 끊긴 자리다.
        ctx.beginPath();
        ctx.setLineDash([1, 2]);
        ctx.moveTo(leaderCell.cx, leaderCell.cy);
        ctx.lineTo(cx, cy);
        ctx.strokeStyle = css("--line-quiet");
        ctx.stroke();
      }
    }
    // HOLD 중이면 왜 멈췄는지 맵 위에서 말한다 — 이유 없는 HOLD 는 고장으로 읽힌다.
    if (formation.state === "HOLDING" && formation.reason && formation.reason.length) {
      drawChip(ctx, grid, leaderCell.cx, leaderCell.cy - Math.min(grid.width, grid.height) * 0.08,
        `대형 유지 · ${formation.reason.join(" / ")}`, "warn");
    }
    ctx.restore();
  }

  const MEDIATION_SHORT = {
    ROUTE_CONFLICT: "경로 충돌",
    YIELDING: "비켜서는 중",
    YIELDED: "양보 대기",
    NO_YIELD_SPACE: "자리 없음",
  };

  function drawMediation(ctx, grid) {
    // 누가 누구 때문에 못 가는지는 관계다 — 목록에서 읽는 것과 맵에서 보는 것은 다르다(D-93).
    let lines = 0;
    for (const robot of view.robots) {
      const pose = poseOf(robot.robot_id);
      if (!pose) continue;
      const from = cellOf(grid, pose.x, pose.y);
      if (robot.queued && robot.queued.blocked_by) {
        const blockerPose = poseOf(robot.queued.blocked_by);
        if (blockerPose) {
          lines += 1;
          const to = cellOf(grid, blockerPose.x, blockerPose.y);
          ctx.save();
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(from.cx, from.cy);
          ctx.lineTo(to.cx, to.cy);
          ctx.strokeStyle = css("--status-warn");
          ctx.stroke();
          ctx.restore();
          const mid = cellOf(grid, (pose.x + blockerPose.x) / 2, (pose.y + blockerPose.y) / 2);
          drawChip(ctx, grid, mid.cx, mid.cy,
            MEDIATION_SHORT[robot.queued.reason] || robot.queued.reason || "대기", "warn");
        }
      }
      if (robot.yielding && robot.yielding.bay) {
        lines += 1;
        const to = cellOf(grid, robot.yielding.bay.x, robot.yielding.bay.y);
        ctx.save();
        ctx.setLineDash([2, 3]);
        ctx.beginPath();
        ctx.moveTo(from.cx, from.cy);
        ctx.lineTo(to.cx, to.cy);
        ctx.strokeStyle = css("--series-primary");
        ctx.stroke();
        ctx.restore();
        drawChip(ctx, grid, to.cx, to.cy, "비켜설 자리");
      }
    }
    window.__swarmOverlay = { ...(window.__swarmOverlay || {}), mediation: lines };
  }

  function colorOfSighting(robotId) {
    const index = view.robots.findIndex((r) => r.robot_id === robotId);
    return index >= 0 ? view.colors[index % view.colors.length] : css("--ink");
  }

  function sightingLabel(s) {
    const age = s.state === "delayed" ? ` · ${(s.age_ms / 1000).toFixed(1)}초 전` : "";
    const name = activeCall(s.robot_id) ? `호출 ${s.robot_id}` : s.robot_id;
    return `${name} · 카메라${age}`;
  }

  // 카메라 관측 1건: 점선 고리 + 방향 선. toPoint 는 map m → 현재 ctx 좌표, size 는 같은 단위.
  function drawSighting(ctx, s, toPoint, size, lineWidth) {
    const { x: cx, y: cy } = toPoint(s.x, s.y);
    ctx.save();
    ctx.globalAlpha = s.state === "delayed" ? 0.4 : 1;
    ctx.strokeStyle = colorOfSighting(s.robot_id);
    ctx.lineWidth = lineWidth;
    ctx.setLineDash([lineWidth * 2, lineWidth * 1.5]);
    ctx.beginPath();
    ctx.arc(cx, cy, size * 0.8, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    // 방향도 같은 toPoint 로 그린다 — 카메라 영상(호모그래피·D-513 7 회전)에서도 지도 방향이 맞다.
    const ahead = toPoint(s.x + 0.1 * Math.cos(s.yaw), s.y + 0.1 * Math.sin(s.yaw));
    const span = Math.hypot(ahead.x - cx, ahead.y - cy) || 1;
    ctx.lineTo(cx + (ahead.x - cx) / span * size * 1.4, cy + (ahead.y - cy) / span * size * 1.4);
    ctx.stroke();
    ctx.restore();
    drawChip(ctx, null, cx, cy + size * 1.9, sightingLabel(s), s.state === "delayed" ? "warn" : undefined,
      labelImportant(s.robot_id));
  }

  // D-457 관제 카메라 추적: 카메라 위치 고리 + 자가보고 위치까지 선 + 차이 칩. 0.15 m 초과는 주황,
  // 프레임 미확인(D-395 이전 로봇)은 점선. 이름 모를 검출은 회색 점. 표시 전용 — 목표·교통정리에 쓰지 않는다.
  function drawCameraTracking(ctx, toPoint, size, lineWidth) {
    if (!layerOn("tracking") || !view.cameraTracking) return;
    const tracking = preferMarkers(view.cameraTracking, layerOn("sightings") ? view.sightings : []);
    ctx.save();
    ctx.lineWidth = lineWidth;
    for (const row of tracking.robots) {
      const cam = toPoint(row.camera.x, row.camera.y);
      const pose = row.pose ? toPoint(row.pose.x, row.pose.y) : null;
      ctx.strokeStyle = css(row.warn ? "--status-warn" : "--series-primary");
      ctx.setLineDash(row.verified ? [] : [lineWidth * 2, lineWidth * 2]);
      ctx.beginPath();
      if (pose) {
        ctx.moveTo(cam.x, cam.y);
        ctx.lineTo(pose.x, pose.y);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(cam.x, cam.y, size * 0.9, 0, Math.PI * 2);
      ctx.stroke();
      const markers = new Set((view.siteMap?.maps || []).flatMap((map) => map.sources || [])
        .map((source) => source.robot_markers?.[row.robotId]).filter(Number.isInteger));
      const label = row.measured && !row.pose && markers.size === 1
        ? `ArUco ${[...markers][0]}` : offsetLabel(row);
      drawChip(ctx, null, cam.x, cam.y - size * 1.8, label, row.warn ? "warn" : undefined, labelImportant(row.robotId));
    }
    // D-600: 배경이 아직 못 본 바닥은 빗금 원 — 로봇이 비키면 Vision 이 채운다.
    ctx.strokeStyle = css("--ink-quiet");
    for (const area of tracking.unknownFloor || []) {
      const c = toPoint(area.x, area.y), edge = toPoint(area.x + area.radiusM, area.y);
      const r = Math.hypot(edge.x - c.x, edge.y - c.y);
      ctx.save();
      ctx.beginPath();
      ctx.arc(c.x, c.y, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.clip();
      ctx.beginPath();
      for (let d = -2 * r; d <= 2 * r; d += Math.max(4, lineWidth * 4)) {
        ctx.moveTo(c.x + d - r, c.y + r);
        ctx.lineTo(c.x + d + r, c.y - r);
      }
      ctx.stroke();
      ctx.restore();
    }
    ctx.fillStyle = css("--ink-quiet");
    for (const item of tracking.unknown) {
      const p = toPoint(item.x, item.y);
      ctx.beginPath();
      ctx.arc(p.x, p.y, size * 0.35, 0, Math.PI * 2);
      ctx.fill();
      if (item.markerId !== undefined) drawChip(ctx, null, p.x, p.y - size * 1.8, `ArUco ${item.markerId} · 미등록`);
    }
    ctx.restore();
  }

  function sitePolygons() {
    return (view.siteMap?.maps || []).filter((m) => (m.polygon_m || []).length >= 3);
  }

  function tracePolygon(ctx, points, toPoint) {
    ctx.beginPath();
    points.forEach(([x, y], i) => {
      const { x: px, y: py } = toPoint(x, y);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.closePath();
  }

  // D-573 1/7: 활성 현장 지도의 횡단보도 면(점선 윤곽)과 대기 띠. 읽기 전용이고, 상태색은 (f)에서 더한다.
  function drawCrosswalks(ctx, toPoint, lineWidth) {
    ctx.save();
    ctx.lineWidth = lineWidth;
    for (const crosswalk of layerOn("site") ? view.activeSiteMap?.map?.crosswalks || [] : []) {
      ctx.setLineDash([]);
      ctx.strokeStyle = css("--series-secondary");
      for (const band of crosswalk.approach || []) { tracePolygon(ctx, band, toPoint); ctx.stroke(); }
      ctx.setLineDash([lineWidth * 3, lineWidth * 2]);
      ctx.strokeStyle = css("--ink");
      tracePolygon(ctx, crosswalk.polygon, toPoint);
      ctx.stroke();
    }
    ctx.restore();
  }

  // 점유 격자 위에 사이트 사각형 윤곽과 카메라 관측을 겹친다(같은 map 프레임).
  function drawSiteOverlay(ctx, grid) {
    const toCell = (x, y) => { const c = cellOf(grid, x, y); return { x: c.cx, y: c.cy }; };
    const size = Math.max(3, Math.min(grid.width, grid.height) * 0.045);
    ctx.save();
    ctx.lineWidth = 0.5;
    ctx.setLineDash([2, 1.5]);
    ctx.strokeStyle = css("--series-primary");
    for (const entry of layerOn("site") ? sitePolygons() : []) {
      tracePolygon(ctx, entry.polygon_m, toCell);
      ctx.stroke();
    }
    ctx.restore();
    drawCrosswalks(ctx, toCell, 0.5);
    drawCameraTracking(ctx, toCell, size, 0.5);
    if (!layerOn("sightings")) return;
    for (const s of view.sightings) drawSighting(ctx, s, toCell, size, 0.5);
  }

  // Selected, pinning, called and 최우선 robots (view.attention, set by console.js) always keep their label.
  function labelImportant(robotId) {
    return view.selected === robotId || view.pinning === robotId || activeCall(robotId) || Boolean(view.attention?.has(robotId));
  }

  function activeCall(robotId) {
    return Boolean(view.call && view.call.robot_id === robotId && Date.now() < view.call.until);
  }

  // map-view.js draw()가 매 그리기 처음에 칩·표식 자리를 비우고, 로봇 표식 상자를 더한다.
  function resetChips() {
    placedChips = []; pendingChips = []; markerBoxes = []; optionalChips = [];
    window.__mapChips = placedChips;
    window.__mapMarkers = markerBoxes;
  }
  const addMarker = (box) => { markerBoxes.push(box); };

  return { CHIP_GAP, chipFontSize, drawChip, flushChips, resetChips, addMarker, cellOf, activeCall, labelImportant,
    drawFormationOverlay, drawMediation, drawSighting, drawCameraTracking, sitePolygons, tracePolygon, drawCrosswalks,
    drawSiteOverlay };
}
