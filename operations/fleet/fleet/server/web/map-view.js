// 현장 지도 뷰 (Fleet 분해 4). 격자 paint·좌표 변환·로봇/목표·대형·중재
// 오버레이·맵 폴링을 가진다. 셸은 클릭-목표 지정과 토큰·폴링 주기를 쥔다.
// 좌표계: 로봇 pose 는 CORE 가 TF `map → <ns>base_footprint` 로 읽어 주는 map 프레임
// 값이다(ros_bridge `_map_frame = "map"`). 그래서 N대를 한 격자 위에 그대로 겹쳐
// 그릴 수 있다. 격자는 행 0 이 아래쪽(y 최소)이고 캔버스는 위가 0 이라 y 를 뒤집는다.
// D-257 사이트 층: 천장 카메라가 덮는 사각형과 카메라 관측(sighting)을 같은 map 프레임에
// 그린다. 관측은 속이 빈 점선 고리로, CORE TF pose(채운 삼각형)와 섞지 않는다.

import {
  classifySightings, siteBounds, canvasSizeFor, fitTransform, project, gridLines, GRID_STEP_M,
  streamEvidence, mapUpTurn, quarterTurn, siteViewTurn,
} from "./site-layer.js";
import { offsetLabel, preferMarkers } from "./tracking-layer.js";
import { NO_MAP_RETRY_MS, createPollGate } from "./poll-gate.js";
import {drawStartPointMarks} from './start-point-layer.js';
import { affineFromTriangles, warpMesh } from "./camera-warp.js";
import { trafficClock, trafficDrawing } from "./site-map-model.js";

export function cameraMapCalibration(frame, calibrations, siteMap) {
  if (!frame || frame.state !== "live" || frame.rectified || !siteMap
    || !Number.isFinite(frame.ageMs) || frame.ageMs < 0 || frame.ageMs > 3000) return null;
  return (calibrations || []).find((row) => row.source_id === frame.source
    && (siteMap.maps || []).some((map) => map.map_id === row.map_id)
    && row.image?.width === frame.image?.naturalWidth
    && row.image?.height === frame.image?.naturalHeight
    && (!row.lens || (row.lens.kind === frame.lens?.kind
      && row.lens.focal_mm === frame.lens?.focal_mm
      && row.lens.hfov_deg === frame.lens?.hfov_deg))
    && Array.isArray(row.map_to_image) && row.map_to_image.length === 9) || null;
}

// D-515: 원본 영상을 삼각형마다 아핀으로 옮겨 사이트 사각형 위에 위에서 본 그림으로 그린다.
// 이웃 삼각형 사이 머리카락 틈이 보이지 않게 잘라 내는 경로를 화면에서 0.5 px 넓힌다.
// 지도는 상태 폴링·관측·콜백으로 초당 여러 번 다시 그려진다. 펴는 일(576 번 그리기)은 새 프레임·
// 보정·크기에서만 하고, 그 사이에는 화면 밖 캔버스에 둔 결과를 한 번에 옮긴다.
let topDownCache = null;
function drawCameraTopDown(ctx, image, calibration, bounds, toPx, width, height, dpr, rot = 0) {
  const key = [calibration.calibration_revision, width, height, dpr, rot,
    bounds.min_x, bounds.max_x, bounds.min_y, bounds.max_y].join("|");
  if (!topDownCache || topDownCache.image !== image || topDownCache.key !== key) {
    const off = document.createElement("canvas");
    off.width = Math.round(width * dpr);
    off.height = Math.round(height * dpr);
    const octx = off.getContext("2d");
    octx.scale(dpr, dpr);
    warpOnto(octx, image, calibration.map_to_image, bounds, toPx);
    topDownCache = { image, key, canvas: off };
  }
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.drawImage(topDownCache.canvas, 0, 0);
  ctx.restore();
}
function warpOnto(ctx, image, mapToImage, bounds, toPx) {
  for (const tri of warpMesh(mapToImage, bounds)) {
    const dst = tri.map.map(([x, y]) => { const p = toPx(x, y); return [p.x, p.y]; });
    const affine = affineFromTriangles(tri.image, dst);
    if (!affine) continue;
    const cx = (dst[0][0] + dst[1][0] + dst[2][0]) / 3, cy = (dst[0][1] + dst[1][1] + dst[2][1]) / 3;
    ctx.save();
    ctx.beginPath();
    dst.forEach(([x, y], k) => {
      const len = Math.hypot(x - cx, y - cy) || 1;
      const ex = x + ((x - cx) / len) * 0.5, ey = y + ((y - cy) / len) * 0.5;
      if (k === 0) ctx.moveTo(ex, ey); else ctx.lineTo(ex, ey);
    });
    ctx.closePath();
    ctx.clip();
    ctx.transform(...affine);
    ctx.drawImage(image, 0, 0);
    ctx.restore();
  }
}

export function createMapView({ scope, el, view, auth, call, onMapChanged, onMapUnavailable, onTrafficChanged = () => {} }) {
  let cameraFrame = null;
  let calibrations = [];
  let calibrationsAt = 0;
  // D-359 §4 — 색·글꼴은 ui.js(window.RosyPalette)가 어떤 CSS 색이든 풀어 캐시한다.
  const css = (name) => window.RosyPalette.cssColor(name);
  const font = (size) => window.RosyPalette.canvasFont(size, "mono");
  const GRID = { UNKNOWN: -1, FREE_MAX: 25, OCCUPIED_MIN: 65 };
  // Map tracking visualization only; relay evidence comes from the Fleet server.
  const TRACK_WARN_M = 0.3;     // 기본 간격(0.6 m)의 절반을 넘으면 주의 색을 쓴다.
  // D-360 레이어 토글(field-view.js 가 view.layers 를 채운다). 값이 없으면 모두 켠다.
  const layerOn = (key) => view.layers?.[key] !== false;

  function paintGrid(grid) {
    const canvas = el("map-canvas");
    const { width, height } = grid;
    // Occupancy cells stay pixelated, while map labels need enough backing pixels
    // to remain legible when a small grid is stretched across the console.
    const displaySize = Math.min(canvas.clientWidth || 1600, canvas.clientHeight || 1600) * (window.devicePixelRatio || 1);
    const scale = Math.min(10, Math.max(1, Math.round(displaySize / Math.max(width, height))));
    canvas.width = width * scale;
    canvas.height = height * scale;
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    const image = ctx.createImageData(width, height);
    // 로봇 지도(dashboard map.js)와 같은 raster 토큰이다 — 두 화면의 지형 색이 같다.
    const tone = window.RosyPalette.readPalette({
      unknown: "--raster-unknown", free: "--raster-free",
      uncertain: "--raster-uncertain", occupied: "--raster-occupied",
    });
    for (let row = 0; row < height; row += 1) {
      for (let col = 0; col < width; col += 1) {
        const value = grid.data[row * width + col];
        const rgb = value === GRID.UNKNOWN || value < 0 ? tone.unknown
          : value >= GRID.OCCUPIED_MIN ? tone.occupied
            : value <= GRID.FREE_MAX ? tone.free : tone.uncertain;
        const pixel = ((height - 1 - row) * width + col) * 4;
        image.data[pixel] = rgb[0];
        image.data[pixel + 1] = rgb[1];
        image.data[pixel + 2] = rgb[2];
        image.data[pixel + 3] = 255;
      }
    }
    const cells = document.createElement("canvas");
    cells.width = width;
    cells.height = height;
    cells.getContext("2d").putImageData(image, 0, 0);
    ctx.drawImage(cells, 0, 0, canvas.width, canvas.height);
    ctx.scale(scale, scale); // following geometry keeps using map-cell coordinates
  }

  function worldToCell(grid, x, y) {
    return {
      col: (x - grid.origin.x) / grid.resolution,
      row: (y - grid.origin.y) / grid.resolution,
    };
  }

  function toWorld(grid, col, row) {
    return {
      x: grid.origin.x + (col + 0.5) * grid.resolution,
      y: grid.origin.y + (row + 0.5) * grid.resolution,
    };
  }

  function colorOf(robotId) {
    const index = view.robots.findIndex((r) => r.robot_id === robotId);
    return view.colors[(index >= 0 ? index : 0) % view.colors.length];
  }

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
  let placedChips = [], pendingChips = [], markerBoxes = []; const CHIP_GAP = 2, CHIP_TRIES = 12;
  const chipsOverlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

  function drawChip(ctx, grid, cx, cy, text, tone) {
    const point = ctx.getTransform().transformPoint({ x: cx, y: cy });
    const displayedWidth = ctx.canvas.getBoundingClientRect().width || ctx.canvas.width;
    const fontSize = Math.max(12, Math.round(12 * ctx.canvas.width / displayedWidth));
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.font = font(fontSize);
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
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.lineWidth = 0.4;
    for (const { x, y, width, height, fontSize, text, tone } of pendingChips) {
      ctx.font = font(fontSize);
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
    return robot && robot.state ? robot.state.pose : null;
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
    drawChip(ctx, null, cx, cy + size * 1.9, sightingLabel(s), s.state === "delayed" ? "warn" : undefined);
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
      drawChip(ctx, null, cam.x, cam.y - size * 1.8, offsetLabel(row), row.warn ? "warn" : undefined);
    }
    ctx.fillStyle = css("--ink-quiet");
    for (const item of tracking.unknown) {
      const p = toPoint(item.x, item.y);
      ctx.beginPath();
      ctx.arc(p.x, p.y, size * 0.35, 0, Math.PI * 2);
      ctx.fill();
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
    drawCameraTracking(ctx, toCell, size, 0.5);
    if (!layerOn("sightings")) return;
    for (const s of view.sightings) drawSighting(ctx, s, toCell, size, 0.5);
  }

  // 점유 격자가 없을 때: 사이트 사각형에 맞춘 미터 축척 뷰. 목표 지정은 받지 않는다.
  function drawSiteView() {
    const bounds = siteBounds(view.siteMap);
    if (!bounds) return;
    const canvas = el("map-canvas");
    const calibration = cameraMapCalibration(cameraFrame, calibrations, view.siteMap);
    // 교정 낡음(카메라 재조준): 정지 로봇의 관측 차이가 계속 클 때(tracking-view). 낡은 교정으로
    // 실영상 위에 지도를 얹으면 잘려 돌아간 지도를 정확해 보이게 그린다 — 영상과 지도를 함께
    // 내리고 미터 뷰로 돌아간다. 맞춤 패널에서 다시 검토·수락하면 돌아온다.
    const drift = calibration && view.trackingDrift ? view.trackingDrift : null;
    const cameraOn = calibration && !drift;
    // 비트맵을 화면에 보이는 박스 크기(× DPR)에 맞춘다 — 글자와 선이 CSS px 로 읽히게.
    // 박스를 아직 모르면(숨김 등) 사각형 종횡비로 대신한다.
    const rect = canvas.getBoundingClientRect();
    const fallback = canvasSizeFor(bounds, 800);
    // D-515: 실영상도 지도 미터 뷰(+y 위) 위에 위에서 본 직사각형으로 편다. 지도 방향이 화면
    // 방향이라 따로 돌리지 않고(D-513 7의 mapUpTurn 불필요), 클릭도 미터 뷰를 그대로 거꾸로 푼다.
    const width = rect.width > 0 ? rect.width : fallback.width;
    const height = rect.height > 0 ? rect.height : fallback.height;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    // D-515 + D-513 7: 사이트 지도의 화면 방향(view_turn_deg, 시계 방향 quarter turn)만큼 미터 뷰를
    // 돌린다. 돌린 상자 크기에 맞춰 넣고, 모든 점(영상 삼각형·차로·로봇·글자 자리)을 toPx 하나로
    // 돌리므로 글자는 똑바로 선다. 클릭은 돌림을 먼저 풀고 미터 뷰를 거꾸로 푼다.
    const rot = view.siteViewTurn || 0;
    const side = rot === 90 || rot === 270;
    const fw = side ? height : width, fh = side ? width : height;
    const t = fitTransform(bounds, fw, fh, 32);
    const turn = quarterTurn(rot, fw, fh);
    const toPx = (x, y) => { const p = project(t, x, y); return turn.point(p.px, p.py); };
    view.cameraPick = rot ? (bx, by) => {
      const q = turn.unpoint(bx / dpr, by / dpr);
      return { x: (q.x - t.ox) / t.scale, y: (t.oy - q.y) / t.scale };
    } : null;
    ctx.fillStyle = css("--ground-deep");
    ctx.fillRect(0, 0, width, height);
    if (cameraOn) drawCameraTopDown(ctx, cameraFrame.image, calibration, bounds, toPx, width, height, dpr, rot);
    else {
      if (drift) {
        const text = `카메라 교정 어긋남 — 정지 로봇 관측 차이 최대 ${Math.round(drift.distanceM * 100)} cm(${drift.robotId}).`
          + " 카메라 맞춤을 다시 검토·수락하세요.";
        ctx.save();
        ctx.font = font(13);
        const boxWidth = ctx.measureText(text).width + 24;
        ctx.fillStyle = css("--scrim");
        ctx.fillRect(Math.max(4, (width - boxWidth) / 2), 8, boxWidth, 28);
        ctx.fillStyle = css("--status-warn");
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(text, width / 2, 14);
        ctx.restore();
      }
    }
    const labelFont = font(12);

    // 0.5 m 격자
    ctx.save();
    ctx.lineWidth = 1;
    ctx.strokeStyle = css("--line-quiet");
    ctx.globalAlpha = 0.5;
    for (const gx of layerOn("grid") ? gridLines(bounds.min_x, bounds.max_x, GRID_STEP_M) : []) {
      const a = toPx(gx, bounds.min_y);
      const b = toPx(gx, bounds.max_y);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    for (const gy of layerOn("grid") ? gridLines(bounds.min_y, bounds.max_y, GRID_STEP_M) : []) {
      const a = toPx(bounds.min_x, gy);
      const b = toPx(bounds.max_x, gy);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    ctx.restore();

    // 사각형 + 치수 + 출처(source_id)
    ctx.save();
    ctx.font = labelFont;
    for (const entry of layerOn("site") ? sitePolygons() : []) {
      tracePolygon(ctx, entry.polygon_m, toPx);
      ctx.globalAlpha = 0.08;
      ctx.fillStyle = css("--series-primary");
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = 2;
      ctx.strokeStyle = css("--series-primary");
      ctx.stroke();
      const b = entry.bounds_m;
      const bottom = toPx((b.min_x + b.max_x) / 2, b.min_y);
      const right = toPx(b.max_x, (b.min_y + b.max_y) / 2);
      const top = toPx(b.min_x, b.max_y);
      ctx.fillStyle = css("--ink-quiet");
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(`${(b.max_x - b.min_x).toFixed(2)} m`, bottom.x, bottom.y + 6);
      ctx.save();
      ctx.translate(right.x + 6, right.y);
      ctx.rotate(Math.PI / 2);
      ctx.textBaseline = "bottom"; // 회전 뒤 "bottom" 이 사각형 바깥쪽이다
      ctx.fillText(`${(b.max_y - b.min_y).toFixed(2)} m`, 0, 0);
      ctx.restore();
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      const sources = (entry.sources || []).map((src) => src.source_id).join(", ");
      ctx.fillText(`${entry.map_id} · 카메라 ${sources}`, top.x, top.y - 6);
    }
    ctx.restore();

    // 축과 원점: 원점이 보이면 그 자리에, 아니면 범위 왼쪽 아래에 x/y 방향만 그린다.
    const originVisible = bounds.min_x <= 0 && bounds.max_x >= 0
      && bounds.min_y <= 0 && bounds.max_y >= 0;
    const axisOrigin = originVisible ? [0, 0] : [bounds.min_x + 0.1, bounds.min_y + 0.1];
    const axisAt = toPx(...axisOrigin);
    const axisLen = Math.min(t.scale * 0.4, width / 8);
    // 축은 지도 방향으로 그린다 — 실영상(호모그래피·회전)에서도 x/y 가 실제 지도 축을 가리킨다.
    const axisTip = (dx, dy) => {
      const p = toPx(axisOrigin[0] + dx, axisOrigin[1] + dy);
      const span = Math.hypot(p.x - axisAt.x, p.y - axisAt.y) || 1;
      return { x: axisAt.x + (p.x - axisAt.x) / span * axisLen, y: axisAt.y + (p.y - axisAt.y) / span * axisLen };
    };
    const xTip = axisTip(0.1, 0), yTip = axisTip(0, 0.1);
    ctx.save();
    ctx.lineWidth = 2;
    ctx.font = labelFont;
    ctx.textBaseline = "middle";
    ctx.strokeStyle = css("--ink");
    ctx.fillStyle = css("--ink");
    ctx.beginPath();
    ctx.moveTo(axisAt.x, axisAt.y);
    ctx.lineTo(xTip.x, xTip.y);
    ctx.moveTo(axisAt.x, axisAt.y);
    ctx.lineTo(yTip.x, yTip.y);
    ctx.stroke();
    ctx.textAlign = "center";
    ctx.fillText("x", xTip.x + (xTip.x - axisAt.x) / axisLen * 10, xTip.y + (xTip.y - axisAt.y) / axisLen * 10);
    ctx.fillText("y", yTip.x + (yTip.x - axisAt.x) / axisLen * 10, yTip.y + (yTip.y - axisAt.y) / axisLen * 10);
    if (originVisible) {
      ctx.beginPath();
      ctx.arc(axisAt.x, axisAt.y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.textAlign = "right";
      ctx.fillText("0,0", axisAt.x - 6, axisAt.y + 12);
    }
    ctx.restore();

    drawTraffic(ctx, toPx, t.scale);
    drawCameraTracking(ctx, toPx, Math.max(7, t.scale * 0.09), 1.5);
    drawStartPointMarks(ctx, toPx, view.startPoints, view.siteMap.maps.map(row=>row.map_id), css('--series-secondary'), 2);
    if (layerOn("sightings")) {
      for (const s of view.sightings) drawSighting(ctx, s, toPx, Math.max(7, t.scale * 0.09), 1.5);
    }
    flushChips(ctx);
  }

  // D-517 10 교통 층 — 블록 띠(점유 채움·허가 테두리·불명 빗금), 구역 윤곽과 "점유 a/b · 대기 n",
  // 로봇마다 통행권 끝 가로 표시. 미터 좌표를 toPoint 하나로 그려 화면 방향·위에서 본 보기를 그대로 따른다.
  // 테두리는 굵은 선에서 가는 선을 지운 따로 그린 판이라 밑의 실영상을 덮지 않는다.
  function drawTraffic(ctx, toPoint, pxPerM) {
    const drawing = layerOn("traffic") ? trafficDrawing(view.traffic, view.activeSiteMap, view.trafficTrips) : null;
    el("legend-traffic").hidden = !drawing || !(drawing.bands.length || drawing.zones.length);
    if (!drawing) return;
    const band = Math.max(6, Math.min(16, 0.09 * pxPerM));
    const trace = (target, points) => {
      target.beginPath();
      points.forEach(([x, y], i) => { const p = toPoint(x, y); if (i) target.lineTo(p.x, p.y); else target.moveTo(p.x, p.y); });
    };
    const outline = (lines, colour, width, edge, dash = []) => {
      const sheet = document.createElement("canvas");
      sheet.width = ctx.canvas.width; sheet.height = ctx.canvas.height;
      const o = sheet.getContext("2d");
      o.setTransform(ctx.getTransform());
      o.lineJoin = "round";
      o.strokeStyle = colour;
      o.lineWidth = width;
      o.setLineDash(dash);
      for (const line of lines) { trace(o, line); o.stroke(); }
      o.setLineDash([]);
      o.globalCompositeOperation = "destination-out";
      o.lineWidth = width - 2 * edge;
      o.lineCap = "round";
      for (const line of lines) { trace(o, line); o.stroke(); }
      ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(sheet, 0, 0); ctx.restore();
    };
    for (const zone of drawing.zones) outline(zone.lines, css("--ink-quiet"), band + 10, 2);
    const hatch = document.createElement("canvas");
    hatch.width = hatch.height = 8;
    const h = hatch.getContext("2d");
    h.strokeStyle = css("--status-warn"); h.lineWidth = 2;
    h.beginPath(); h.moveTo(0, 8); h.lineTo(8, 0); h.moveTo(-2, 2); h.lineTo(2, -2); h.moveTo(6, 10); h.lineTo(10, 6); h.stroke();
    ctx.save();
    ctx.lineCap = "butt"; ctx.lineJoin = "round"; ctx.lineWidth = band;
    for (const item of drawing.bands) {
      if (item.state === "GRANTED") continue;
      trace(ctx, item.points);
      ctx.strokeStyle = item.state === "OCCUPIED" ? colorOf(item.robot) : ctx.createPattern(hatch, "repeat");
      ctx.globalAlpha = item.state === "OCCUPIED" ? 0.9 : 1;
      ctx.stroke();
    }
    ctx.restore();
    for (const item of drawing.bands.filter((b) => b.state === "GRANTED")) outline([item.points], colorOf(item.robot), band, 2);
    for (const item of drawing.bands.filter((b) => b.state === "UNKNOWN")) outline([item.points], css("--status-warn"), band, 1.5, [4, 3]);
    ctx.save();
    ctx.lineCap = "round";
    for (const tick of drawing.ticks) {
      const p = toPoint(tick.x, tick.y);
      const q = toPoint(tick.x + Math.cos(tick.angle) * 0.05, tick.y + Math.sin(tick.angle) * 0.05);
      const span = Math.hypot(q.x - p.x, q.y - p.y) || 1;
      const nx = -(q.y - p.y) / span * band * 0.9, ny = (q.x - p.x) / span * band * 0.9;
      for (const [colour, width] of [[css("--ground-deep"), 6], [colorOf(tick.robot), 3]]) {
        ctx.beginPath(); ctx.moveTo(p.x - nx, p.y - ny); ctx.lineTo(p.x + nx, p.y + ny);
        ctx.strokeStyle = colour; ctx.lineWidth = width; ctx.stroke();
      }
    }
    ctx.restore();
    // 통행권 끝에 로봇 이름 — 띠 색만으로는 어느 로봇의 블록인지 읽히지 않는다(같은 계열 색).
    for (const tick of drawing.ticks) {
      const p = toPoint(tick.x, tick.y);
      drawChip(ctx, null, p.x, p.y - band - 14, tick.robot, "");
    }
    // 구역 글은 차로망 안쪽(가운데 쪽)에 둔다 — 띠·통행권 표시와 바깥 사각형 치수 글을 덮지 않는다.
    const centre = toPoint(...drawing.centre);
    for (const zone of drawing.zones) {
      const p = toPoint(zone.anchor.x, zone.anchor.y);
      const q = toPoint(zone.anchor.x + Math.cos(zone.anchor.angle) * 0.05, zone.anchor.y + Math.sin(zone.anchor.angle) * 0.05);
      const span = Math.hypot(q.x - p.x, q.y - p.y) || 1;
      let nx = -(q.y - p.y) / span, ny = (q.x - p.x) / span;
      if (nx * (centre.x - p.x) + ny * (centre.y - p.y) < 0) { nx = -nx; ny = -ny; }
      const reach = band + 18 + Math.abs(nx) * 52;  // a sideways label needs room for its width
      drawChip(ctx, null, p.x + nx * reach, p.y + ny * reach, zone.label, "");
    }
    window.__trafficLayer = { bands: drawing.bands.length, zones: drawing.zones.length, ticks: drawing.ticks.length };
  }

  function describeSightings() {
    const fresh = view.sightings.filter((s) => s.state === "fresh").length;
    return `카메라 관측 ${fresh}/${view.sightings.length}대`;
  }

  function activeCall(robotId) {
    return Boolean(view.call && view.call.robot_id === robotId && Date.now() < view.call.until);
  }

  function draw() {
    if (view.call && Date.now() >= view.call.until) view.call = null;
    const callLabel = view.call ? ` · 호출 ${view.call.robot_id}` : "";
    const grid = view.map;
    placedChips = []; pendingChips = []; markerBoxes = [];
    window.__mapChips = placedChips;
    window.__mapMarkers = markerBoxes;
    if (!grid) {
      if (view.siteMap) {
        drawSiteView();
        const b = siteBounds(view.siteMap, 0);
        el("map-tag").textContent =
          `사이트 ${(b.max_x - b.min_x).toFixed(1)}×${(b.max_y - b.min_y).toFixed(1)} m · ${describeSightings()}`
          + (cameraMapCalibration(cameraFrame, calibrations, view.siteMap)
            ? (view.trackingDrift
              ? " · 카메라 교정 어긋남 — 맞춤 재수락 필요"
              : ` · Rosy Cam 실영상 · ${cameraMapCalibration(cameraFrame, calibrations, view.siteMap).calibration_revision}`) : "")
          + callLabel;
        el("map-canvas").setAttribute("aria-label",
          `천장 카메라 사이트 지도 — ${describeSightings()}${callLabel}. 이 지도에서는 목표를 지정할 수 없습니다.`
          + (view.trackingDrift ? " 카메라 교정이 어긋나 실영상 대신 미터 눈금으로 보여 줍니다." : ""));
      }
      return;
    }
    const canvas = el("map-canvas");
    const ctx = canvas.getContext("2d");
    paintGrid(grid);
    drawStartPointMarks(ctx, (x,y)=>{const p=cellOf(grid,x,y);return {x:p.cx,y:p.cy};}, view.startPoints, [grid.map_id], css('--series-secondary'), .6);
    if (view.stateUnavailable) {
      el("map-tag").textContent = `로봇 위치 확인 불가${callLabel}`;
      canvas.setAttribute("aria-label", `로봇 위치 확인 불가${callLabel} — Fleet 상태 연결을 확인하세요`);
      return;
    }
    el("map-tag").textContent = `${grid.width}×${grid.height} · ${grid.map_id || "map"}${callLabel}`;
    canvas.setAttribute("aria-label", view.call
      ? `지도에서 로봇 목표 위치 선택. 호출 ${view.call.robot_id}`
      : "지도에서 로봇 목표 위치 선택");
    // 격자 픽셀 위에 그리므로 선 굵기도 격자 칸 단위다. 0.6칸이면 3 cm 남짓이다.
    ctx.lineWidth = 0.6;
    view.robots.forEach((robot, index) => {
      const pose = robot.state && robot.state.pose;
      if (!pose || !layerOn("poses")) return;
      const color = view.colors[index % view.colors.length];
      const cell = worldToCell(grid, pose.x, pose.y);
      const cx = cell.col;
      const cy = grid.height - cell.row;
      const size = Math.max(3, Math.min(grid.width, grid.height) * 0.045);
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(-pose.yaw); // 캔버스 y 가 아래로 자라므로 회전도 뒤집는다
      ctx.beginPath();
      ctx.moveTo(size, 0);
      ctx.lineTo(-size * 0.6, size * 0.62);
      ctx.lineTo(-size * 0.6, -size * 0.62);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = robot.online ? 1 : 0.35;
      ctx.fill();
      if (activeCall(robot.robot_id)) {
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.arc(0, 0, size * 1.7, 0, Math.PI * 2);
        ctx.lineWidth = 0.35;
        ctx.strokeStyle = css("--status-warn");
        ctx.stroke();
      }
      ctx.restore();
      if (activeCall(robot.robot_id)) {
        drawChip(ctx, grid, cx, cy - size * 2.2, `호출 ${robot.robot_id}`, "warn");
      }
      const [a, b] = [-size, size].map((d) => ctx.getTransform().transformPoint({ x: cx + d, y: cy + d }));
      markerBoxes.push({ x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y, robot: robot.robot_id });

      // 목표는 Fleet 이 기억하는 값이다(로봇 상태에는 없다) — "내가 무엇을 시켰는가".
      // 대기 중인 미션도 그린다 — 어디로 갈 예정인지가 보여야 순서를 판단한다.
      const goal = robot.goal || robot.queued;
      if (goal && typeof goal.x === "number") {
        const gcell = worldToCell(grid, goal.x, goal.y);
        ctx.beginPath();
        ctx.arc(gcell.col, grid.height - gcell.row, size * 0.5, 0, Math.PI * 2);
        ctx.strokeStyle = css("--series-goal");
        ctx.globalAlpha = 1;
        ctx.stroke();
      }
    });
    drawTraffic(ctx, (x, y) => { const c = cellOf(grid, x, y); return { x: c.cx, y: c.cy }; }, 1 / grid.resolution);
    drawFormationOverlay(ctx, grid);
    drawMediation(ctx, grid);
    drawSiteOverlay(ctx, grid);
    flushChips(ctx);
    if (view.selected && view.cursor) {
      const { col, row } = view.cursor;
      ctx.save();
      ctx.beginPath();
      ctx.arc(col + 0.5, grid.height - row - 0.5, 1.8, 0, Math.PI * 2);
      ctx.lineWidth = 0.5;
      ctx.strokeStyle = css("--series-goal");
      ctx.stroke();
      ctx.restore();
    }
  }

  function syncLegend(mode) {
    el("map-legend").hidden = mode === "none";
    for (const item of el("map-legend").querySelectorAll("[data-legend=grid]")) {
      item.hidden = mode !== "grid";
    }
    el("legend-sighting").hidden = !view.siteMap && !view.sightings.length;
  }

  async function refreshSiteMap() {
    const life = scope.capture();
    life.check();
    try {
      const siteMap = await call("/api/fleet/site-map");
      life.check();
      view.siteMap = siteMap;
      el("map-stage").dataset.siteMap = "configured";
      if (Date.now() - calibrationsAt > 30000) {
        try {
          const result = await call("/api/fleet/calibrations", { signals: [life.signal] });
          life.check();
          calibrations = result.calibrations || [];
          calibrationsAt = Date.now();
        } catch (error) { if (error.name === "AbortError") return; calibrations = []; }
        // D-513 7: 활성 현장 지도의 화면 방향. 지도가 없거나(404/409) 읽지 못하면 기본 방향.
        try {
          view.activeSiteMap = await call("/api/fleet/site-map/active", { signals: [life.signal] });
          view.siteViewTurn = siteViewTurn(view.activeSiteMap);
          life.check();
        } catch (error) {
          if (error.name === "AbortError") return;
          if (error.status === 404 || error.status === 409) { view.siteViewTurn = 0; view.activeSiteMap = null; } // no active map; else keep the last turn
        }
      }
    } catch (err) {
      if (err.name === "AbortError") return;
      // NO_SITE_MAP — 카메라 사각형이 설정되지 않은 현장이다. 일시 실패면 직전 사각형을 둔다.
      if (err.status === 404 && err.code === "NO_SITE_MAP") {
        view.siteMap = null;
        el("map-stage").dataset.siteMap = "none";
      }
    }
  }

  // NO_MAP(지도를 내는 로봇 없음)은 기능 미설정이 아니라 "아직 없음"이다. 로봇이 나중에
  // 지도를 낼 수 있으니 멈추지 않고 30 s 간격으로만 다시 묻는다. 라우트 없음 404 는
  // resetPolling()(로그인) 전까지 멈춘다. 일시 실패는 다음 5 s 주기에 다시 묻는다.
  const mapGate = createPollGate({ slowCodes: { NO_MAP: NO_MAP_RETRY_MS } });

  // D-517 10: 교통 표(1 s). Fleet 이 그 라우트를 모르면(404) 다음 로그인까지 묻지 않는다.
  // 진행 중 trip 이 있을 때만 /trips 로 계획을 읽는다 — 통행권 끝을 계획 위에 놓는다.
  const trafficGate = createPollGate();
  let trafficInFlight = false;
  scope.onDispose(() => { trafficInFlight = false; });
  async function refreshTraffic() {
    const life = scope.capture();
    life.check();
    if (auth.locked || trafficInFlight || !trafficGate.due()) return;
    trafficInFlight = true;
    try {
      const traffic = await call("/api/fleet/traffic", { signals: [life.signal] });
      life.check();
      trafficGate.ok();
      view.trafficTrips = traffic.robots.length
        ? ((await call("/api/fleet/trips", { signals: [life.signal] })).open || []) : [];
      life.check();
      if (traffic.map_version !== null && traffic.map_version !== view.activeSiteMap?.version) {
        view.activeSiteMap = await call("/api/fleet/site-map/active", { signals: [life.signal] });
        life.check();
      }
      view.traffic = traffic;
    } catch (err) {
      if (err.name === "AbortError") return;
      if (trafficGate.fail(err.status, err.code) === "absent") view.traffic = null;
    } finally {
      if (life.current()) trafficInFlight = false;
    }
    view.trafficClock = trafficClock(view.trafficClock, view.traffic, Date.now());
    el("traffic-toggle").hidden = !view.traffic?.units?.length;
    onTrafficChanged();
  }
  scope.listen(el("traffic-toggle"), "click", () => {
    const on = !layerOn("traffic");
    view.layers = { ...view.layers, traffic: on };
    el("traffic-toggle").setAttribute("aria-pressed", String(on));
    el("traffic-toggle").textContent = on ? "교통 켬" : "교통 끔";  // the quiet button has no pressed look
    draw();
  });

  function resetPolling() {
    trafficGate.reset();
    mapGate.reset();
    sightingsUnavailable = false;
  }

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (auth.locked) return;
    sightingsUnavailable = false;
    await refreshSiteMap();
    life.check();
    if (auth.locked || !mapGate.due()) return;
    let mapFailure = "retry";
    try {
      const grid = await call("/api/fleet/map");
      life.check();
      mapGate.ok();
      view.map = grid;
      el("map-stage").dataset.mapState = "ready";
      el("map-empty").hidden = true;
      el("map-canvas").removeAttribute("aria-hidden");
      el("map-canvas").setAttribute("role", "button");
      syncLegend("grid");
      draw();
      onMapChanged();
    } catch (err) {
      if (err.name === "AbortError") return;
      view.map = null;
      if (auth.locked) return;
      if (!auth.locked) mapFailure = mapGate.fail(err.status, err.code);
      if (view.siteMap && !auth.locked) {
        // 점유 격자 없이 카메라 사각형만 있다 — 관측 전용 뷰. 목표 지정은 계속 막힌다.
        const canvas = el("map-canvas");
        canvas.removeAttribute("aria-hidden");
        canvas.setAttribute("role", "img"); // 관측 전용 — 누를 수 있는 버튼이 아니다
        canvas.tabIndex = -1;
        canvas.classList.add("idle");
        el("map-stage").dataset.mapState = "site";
        el("map-empty").hidden = true;
        syncLegend("site");
        draw();
        onMapUnavailable();
        return;
      }
      const canvas = el("map-canvas");
      canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
      canvas.setAttribute("aria-hidden", "true");
      canvas.tabIndex = -1;
      canvas.classList.add("idle");
      el("map-stage").dataset.mapState = "unavailable";
      if (mapFailure === "slow") {
        el("map-empty-title").textContent = "지도를 보내는 로봇이 없습니다";
        el("map-empty-detail").textContent = "로봇이 지도를 내면 30초 안에 표시합니다.";
      } else if (mapFailure === "absent") {
        el("map-empty-title").textContent = "지도 미설정";
        el("map-empty-detail").textContent = "이 Fleet에는 현장 지도 기능이 없습니다.";
      } else {
        el("map-empty-title").textContent = "지도를 확인할 수 없습니다";
        el("map-empty-detail").textContent = "Fleet 지도 연결과 등록 로봇 상태를 확인하세요.";
      }
      el("map-empty").hidden = false;
      syncLegend("none");
      el("map-tag").textContent = "맵 없음";
      onMapUnavailable();
    }
  }

  // 카메라 관측 폴링(≈1 s). 관측은 표시 전용이다 — 목표·판단 입력으로 넘기지 않는다.
  // 사이트 사각형이 있을 때만 두드린다. 관측 설정이 없으면 라우트가 없어 404 이므로,
  // 404 를 받으면 다음 refresh() 까지 멈춘다.
  let sightingsInFlight = false;
  let sightingsUnavailable = false;
  scope.onDispose(() => { sightingsInFlight = false; });
  async function refreshSightings() {
    const life = scope.capture();
    life.check();
    if (auth.locked || sightingsInFlight || sightingsUnavailable || !view.siteMap) return;
    sightingsInFlight = true;
    let next = [];
    try {
      next = classifySightings(await call("/api/fleet/sightings"));
      life.check();
    } catch (err) {
      if (err.name === "AbortError") return;
      // 일시 실패도 옛 관측을 남기지 않는다.
      if (err.status === 404) sightingsUnavailable = true;
    } finally {
      if (life.current()) sightingsInFlight = false;
    }
    const unchanged = JSON.stringify(next) === JSON.stringify(view.sightings);
    view.sightings = next;
    if (unchanged && !next.length) return; // 빈 채로 그대로면 격자를 다시 칠하지 않는다
    el("legend-sighting").hidden = !view.siteMap && !view.sightings.length;
    draw();
  }

  function setCameraFrame(frame) {
    cameraFrame = frame?.state === "live" ? frame : null;
    if (!view.map && view.siteMap) draw();
  }
  // D-513 7: 크게 보기·썸네일도 이 카메라 보정의 지도 방향으로 돌린다. 펴 놓은 미리보기도
  // 모서리 순서를 지켜 펴므로 같은 회전이다. 보정이 없으면 0 — 받은 URL 그대로다.
  // 실영상과 같은 조건으로 고른다: 지금 지도의 보정이고, 원본 프레임이면 크기도 같아야 한다.
  function frameTurn(frame) {
    const maps = (view.siteMap?.maps || []).map((map) => map.map_id);
    const record = calibrations.find((row) => row.source_id === frame.source && maps.includes(row.map_id)
      && (frame.rectified || (row.image?.width === frame.image?.naturalWidth
        && row.image?.height === frame.image?.naturalHeight)));
    return record ? (mapUpTurn(record) + (view.siteViewTurn || 0)) % 360 : 0;
  }
  function turnedUrl(frame) {
    const image = frame.image;
    const rot = frameTurn(frame);
    if (!rot || !image?.naturalWidth) return frame.url;
    const turn = quarterTurn(rot, image.naturalWidth, image.naturalHeight);
    const canvas = document.createElement("canvas");
    canvas.width = turn.width; canvas.height = turn.height;
    const ctx = canvas.getContext("2d");
    ctx.transform(...turn.matrix);
    ctx.drawImage(image, 0, 0);
    return canvas.toDataURL("image/jpeg", 0.9);
  }
  function bindCamera(visionView) {
    // The calibrated map draws the same authenticated Vision frame; Fleet does not relay image bytes.
    // D-493: the raw frame shows in one place at a time — the rail thumbnail, or the map stage
    // (#map-birdseye) when there is no map or the operator asks for the large view. CSS picks the place.
    const birdseye = el("map-birdseye"), toggle = el("birdseye-toggle"), stage = el("map-stage");
    const setLive = (url) => {
      birdseye.hidden = !url;
      if (url) birdseye.src = url;
      toggle.disabled = !url;
      if (url) toggle.removeAttribute("reason"); else toggle.setAttribute("reason", "영상 대기");
    };
    setLive(null);
    // 돌린 조감도는 보일 때만 다시 그린다 — 숨은 동안 프레임마다 JPEG 을 만들지 않는다.
    let lastFrame = null;
    const shown = () => stage.dataset.view === "camera" || ["auth", "unavailable", "loading"].includes(stage.dataset.mapState);
    const showFrame = () => setLive(lastFrame && (shown() ? turnedUrl(lastFrame) : lastFrame.url));
    // 지도 상태가 바뀌어 조감도가 드러나면 다음 프레임을 기다리지 않고 돌린 그림으로 바꾼다.
    scope.subscribe(() => {
      const observer = new MutationObserver(showFrame);
      observer.observe(stage, { attributes: true, attributeFilter: ["data-map-state"] });
      return () => observer.disconnect();
    });
    scope.listen(toggle, "click", () => {
      const large = stage.dataset.view !== "camera";
      stage.dataset.view = large ? "camera" : "map";
      toggle.setAttribute("aria-pressed", String(large));
      showFrame();
    });
    let cancelMapCameraExpiry = () => {};
    scope.subscribe(() => visionView.onFrame(scope.guard((frame) => {
      cancelMapCameraExpiry();
      if (frame.state !== "live" || !Number.isFinite(frame.ageMs) || frame.ageMs < 0 || frame.ageMs > 3000) {
        lastFrame = null; setCameraFrame(null); setLive(null); return;
      }
      lastFrame = frame;
      // 레일 썸네일도 같은 회전 — 모서리 편집 중에는 CSS 가 원본으로 둔다(styles.css .vision-frame[data-turn]).
      frame.image?.closest?.(".vision-frame")?.setAttribute("data-turn", String(frameTurn(frame)));
      setCameraFrame(frame);
      showFrame();
      cancelMapCameraExpiry = scope.timeout(() => { lastFrame = null; setCameraFrame(null); setLive(null); }, Math.max(0, 3000 - frame.ageMs));
    })));
  }
  return { draw, refresh, refreshSightings, refreshTraffic, resetPolling, toWorld, streamEvidence, setCameraFrame, bindCamera };
}
