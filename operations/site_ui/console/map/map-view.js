// 현장 지도 뷰 (Fleet 분해 4). 격자 paint·좌표 변환·로봇/목표 그리기를 가진다. 대형·중재·관측
// 오버레이는 map-overlays.js, 맵 폴링은 map-polling.js가 가진다(D-798 3.2). 셸은 클릭-목표 지정과 토큰·폴링 주기를 쥔다.
// 좌표계: 로봇 pose 는 CORE 가 TF `map → <ns>base_footprint` 로 읽어 주는 map 프레임
// 값이다(ros_bridge `_map_frame = "map"`). 그래서 N대를 한 격자 위에 그대로 겹쳐
// 그릴 수 있다. 격자는 행 0 이 아래쪽(y 최소)이고 캔버스는 위가 0 이라 y 를 뒤집는다.
// D-257 사이트 층: 천장 카메라가 덮는 사각형과 카메라 관측(sighting)을 같은 map 프레임에
// 그린다. 관측은 속이 빈 점선 고리로, CORE TF pose(채운 삼각형)와 섞지 않는다.

import {
  siteBounds, canvasSizeFor, fitTransform, project, gridLines, GRID_STEP_M,
  streamEvidence, quarterTurn,
} from "./site-layer.js";
import { createCameraBackdrop } from "./camera-backdrop.js";
import { createMapOverlays } from "./map-overlays.js";
import { createMapPolling } from "./map-polling.js";
import { drawTrails } from "./trail-view.js";
import { drawSignalLamps, drawTraffic } from "./traffic-view.js";
import { drawGuide } from "/console/assets/guide-layer.js";
import { robotMapPose } from "./localization-badge.js";
import { drawMapDatum } from "./map-datum.js";

// Map label: the short id ("rosy_012" -> "012").
const shortId = (robotId) => String(robotId).replace(/^rosy_/, "");

export function createMapView({ scope, el, view, auth, call, onMapChanged, onMapUnavailable, onTrafficChanged = () => {} }) {
  const camera = createCameraBackdrop({ scope, el, view, draw });
  // D-359 §4 — 색·글꼴은 ui.js(window.RosyPalette)가 어떤 CSS 색이든 풀어 캐시한다.
  const css = (name) => window.RosyPalette.cssColor(name);
  const font = (role, displayScale = 1) => window.RosyPalette.canvasFont(role, "mono", displayScale);
  const GRID = { UNKNOWN: -1, FREE_MAX: 25, OCCUPIED_MIN: 65 };
  // D-360 레이어 토글(field-view.js 가 view.layers 를 채운다). 값이 없으면 모두 켠다.
  const layerOn = (key) => view.layers?.[key] !== false;
  const {
    CHIP_GAP, chipFontSize, drawChip, flushChips, resetChips, addMarker, cellOf, activeCall, labelImportant,
    drawFormationOverlay, drawMediation, drawSighting, drawCameraTracking, sitePolygons, tracePolygon, drawCrosswalks,
    drawSiteOverlay,
  } = createMapOverlays({ view, css, font, layerOn, worldToCell, colorOf });

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

  // 점유 격자가 없을 때: 사이트 사각형에 맞춘 미터 축척 뷰. 목표 지정은 받지 않는다.
  function drawSiteView() {
    const bounds = siteBounds(view.siteMap);
    if (!bounds) return;
    const canvas = el("map-canvas");
    const calibration = camera.calibration();
    // 교정 낡음(카메라 재조준): 정지 로봇의 관측 차이가 계속 클 때(tracking-view). D-595: 이것은
    // 진단 경고일 뿐이다 — 그림은 수락된 보정으로 그대로 두고(폴링마다 바뀌지 않게) 경고만 얹는다.
    // 보정을 바꾸는 것은 설치·보정의 맵 고정(맞춤 → 추적 보정 적용)뿐이다.
    const cameraOn = view.displayMode === "overlay" && Boolean(calibration);
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
    // 돌리므로 글자는 똑바로 선다.
    const rot = view.siteViewTurn || 0;
    const side = rot === 90 || rot === 270;
    const fw = side ? height : width, fh = side ? width : height;
    const t = fitTransform(bounds, fw, fh, 32);
    const turn = quarterTurn(rot, fw, fh);
    const toPx = (x, y) => { const p = project(t, x, y); return turn.point(p.px, p.py); };
    // D-593 pin on the site view (a motor-mode robot has no grid): canvas CSS px → map m.
    view.siteToWorld = (x, y) => { const p = turn.unpoint(x, y); return { x: (p.x - t.ox) / t.scale, y: (t.oy - p.y) / t.scale }; };
    ctx.fillStyle = css("--ground-deep");
    ctx.fillRect(0, 0, width, height);
    if (cameraOn) camera.drawTopDown(ctx, calibration, bounds, toPx, width, height, dpr, rot);
    const labelFont = font("micro");

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
    }
    ctx.restore();

    drawMapDatum(ctx, toPx, bounds, {css});

    const activeMap = view.activeSiteMap?.map;
    if (layerOn("lanes") && view.siteMap.maps.some(row => row.map_id === activeMap?.map_id)) {
      ctx.save();
      ctx.strokeStyle = css("--series-primary");
      ctx.fillStyle = css("--ink");
      ctx.lineWidth = 2;
      ctx.font = labelFont;
      for (const edge of activeMap.edges || []) {
        ctx.setLineDash(edge.drive_mode === "free" ? [6, 4] : []);
        ctx.beginPath();
        edge.polyline.forEach(([x, y], index) => {
          const p = toPx(x, y);
          if (index) ctx.lineTo(p.x, p.y); else ctx.moveTo(p.x, p.y);
        });
        ctx.stroke();
      }
      for (const [index, place] of (activeMap.places || []).entries()) {
        const p = toPx(place.x, place.y);
        ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill();
        ctx.fillText(String(index + 1), p.x + 8, p.y - 8);
      }
      ctx.restore();
    }
    drawCrosswalks(ctx, toPx, 1.5);
    drawTrails(ctx, view, toPx, 1.5, call);
    traffic(ctx, toPx, t.scale);
    drawCameraTracking(ctx, toPx, Math.max(14, t.scale * 0.09), 2);
    guide(ctx, toPx);
    if (layerOn("sightings")) {
      for (const s of view.sightings) drawSighting(ctx, s, toPx, Math.max(14, t.scale * 0.09), 2);
    }
    flushChips(ctx);
  }

  const traffic = (ctx, toPoint, pxPerM) =>
    drawTraffic(ctx, toPoint, pxPerM, { view, el, css, colorOf, drawChip, on: layerOn("traffic") });
  // D-536: 로봇 몸체 원·방향·불확실성 고리와 안내 목표. "로봇" 층을 따른다.
  const guide = (ctx, toPoint) => {
    // Guide chips start with the robot id ("rosy_01 · ±0.05 m"): exceptions and the selected robot always show.
    const chip = (c, g, x, y, text, tone) => drawChip(c, g, x, y, text, tone, labelImportant(String(text).split(" · ")[0]));
    drawGuide(ctx, toPoint, { guide: view.guide, css, colorOf, drawChip: chip, on: layerOn("poses") });
    drawSignalLamps(ctx, toPoint, { view, css, on: layerOn("traffic") });  // D-525 rev 3: above the robots
  };

  function describeSightings() {
    const observed = new Set(view.sightings.filter((s) => s.state === "fresh").map((s) => s.robot_id));
    for (const row of view.cameraTracking?.robots || []) observed.add(row.robotId);
    return `카메라 관측 ${observed.size}/${Math.max(view.robots.length, observed.size)}대`;
  }


  function draw() {
    const activeMap = view.activeSiteMap?.map;
    const places = layerOn("lanes") && view.siteMap?.maps.some(row => row.map_id === activeMap?.map_id) ? activeMap.places || [] : [];
    const placeList = el("map-places");
    if (placeList) {
      placeList.hidden = !places.length;
      placeList.replaceChildren(...places.map(place => {
        const row = document.createElement("li");
        row.textContent = `${place.name} · ${place.x.toFixed(2)}, ${place.y.toFixed(2)} m`;
        return row;
      }));
    }
    const calibrationStatus = el("map-calibration-status");
    if (calibrationStatus) {
      const drift = camera.calibration() && view.trackingDrift;
      calibrationStatus.hidden = !drift;
      calibrationStatus.textContent = !drift ? "" : drift.origin === "server"
        ? `카메라 교정 어긋남(자동 검사) — 승인 교정과 새 맞춤 제안이 최대 ${Math.round(drift.distanceM * 100)} cm 어긋남(${drift.sourceId}). 맵 고정을 다시 하세요(맞춤 → 추적 보정 적용).`
        : `카메라 교정 어긋남 — 정지 로봇 관측 차이 최대 ${Math.round(drift.distanceM * 100)} cm(${drift.robotId}). 맵 고정을 다시 하세요(맞춤 → 추적 보정 적용).`;
    }
    if (view.call && Date.now() >= view.call.until) view.call = null;
    const callLabel = view.call ? ` · 호출 ${view.call.robot_id}` : "";
    const grid = view.map;
    if (!grid && !view.siteMap) drawTraffic(null, null, 0, {view: {}, el, on: true});
    resetChips();
    if (!grid) {
      if (view.siteMap) {
        drawSiteView();
        const b = siteBounds(view.siteMap, 0);
        el("map-tag").textContent =
          `사이트 ${(b.max_x - b.min_x).toFixed(1)}×${(b.max_y - b.min_y).toFixed(1)} m · ${describeSightings()}`
          + (camera.calibration()
            ? ` · ${camera.usesPlane() ? "Rosy Cam 평면 영상" : "브라우저 보정(대체)"} · ${camera.calibration().calibration_revision}`
              + (view.trackingDrift ? " · 카메라 교정 어긋남 — 맵 고정 다시 필요" : "") : "")
          + callLabel;
        el("map-canvas").setAttribute("aria-label",
          `천장 카메라 사이트 지도 — ${describeSightings()}${callLabel}. 이 지도에서는 목표를 지정할 수 없습니다.`
          + (view.trackingDrift ? " 카메라 교정이 어긋난 것 같습니다. 그림은 수락된 보정 그대로이며 맵 고정을 다시 하세요." : ""));
      }
      return;
    }
    const canvas = el("map-canvas");
    const ctx = canvas.getContext("2d");
    paintGrid(grid);
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
    drawTrails(ctx, view, (x, y) => { const c = cellOf(grid, x, y); return { x: c.cx, y: c.cy }; }, 0.4, call);
    ctx.lineWidth = 0.6;
    const labels = [];  // id labels go after every marker box exists, so a label never covers a marker
    view.robots.forEach((robot, index) => {
      // Only the robot's LOCALIZED map pose draws the triangle; otherwise Fleet's map pose (guide circle)
      // and Rosy Cam tracking (ring) show where it is, each in its own layer.
      const pose = robotMapPose(robot);
      if (!pose || !layerOn("poses")) return;
      const color = view.colors[index % view.colors.length];
      const cell = worldToCell(grid, pose.x, pose.y);
      const cx = cell.col;
      const cy = grid.height - cell.row;
      const pxPerCell = Math.max(canvas.clientWidth / grid.width, canvas.clientHeight / grid.height) || 1;
      const size = Math.min(3, 18 / pxPerCell);
      // Chips use screen-sized type; keep their half-height clear of the marker at every grid scale.
      const labelOffset = Math.max(size * 2.2, size + (chipFontSize(ctx) * 0.9 + CHIP_GAP) / ctx.getTransform().d);
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
        drawChip(ctx, grid, cx, cy - labelOffset, `호출 ${robot.robot_id}`, "warn");
      }
      const [a, b] = [-size, size].map((d) => ctx.getTransform().transformPoint({ x: cx + d, y: cy + d }));
      addMarker({ x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y, robot: robot.robot_id });
      labels.push([cx, cy + labelOffset, robot.robot_id]);

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
    for (const [x, y, robotId] of labels) drawChip(ctx, grid, x, y, shortId(robotId), undefined, labelImportant(robotId));
    traffic(ctx, (x, y) => { const c = cellOf(grid, x, y); return { x: c.cx, y: c.cy }; }, 1 / grid.resolution);
    guide(ctx, (x, y) => { const c = cellOf(grid, x, y); return { x: c.cx, y: c.cy }; });
    drawFormationOverlay(ctx, grid);
    drawMediation(ctx, grid);
    drawSiteOverlay(ctx, grid);
    // US-009 — 원점 글자(x·y·0,0)도 글자다. 선을 다 그린 뒤, 칩 바로 앞에 칠해 선이 글자를 지나지 않는다.
    drawMapDatum(ctx, (x, y) => {
      const cell = cellOf(grid, x, y);
      return {x: cell.cx, y: cell.cy};
    }, {
      min_x: grid.origin.x, min_y: grid.origin.y,
      max_x: grid.origin.x + grid.width * grid.resolution,
      max_y: grid.origin.y + grid.height * grid.resolution,
    }, {css});
    flushChips(ctx);
    if (view.selected && view.cursor) {
      const { col, row } = view.cursor;
      const cx = col + 0.5;
      const cy = grid.height - row - 0.5;
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, 1.8, 0, Math.PI * 2);
      ctx.lineWidth = 0.5;
      ctx.strokeStyle = css("--series-goal");
      ctx.stroke();
      ctx.restore();
      const world = toWorld(grid, col, row);
      const metres = `${world.x.toFixed(2)}, ${world.y.toFixed(2)} m`;
      drawChip(ctx, null, cx + 2, cy, metres);
      canvas.setAttribute("aria-label", `${canvas.getAttribute("aria-label")}. ${metres}`);
      flushChips(ctx);
    }
  }

  // 사이트 사각형·격자·교통·상황·관측 폴링은 map-polling.js가 가진다. 이 뷰를 다시 그리게 draw를 건넨다.
  const { refresh, refreshSightings, refreshTraffic, refreshGuide, resetPolling } = createMapPolling({ scope, el, view,
    auth, call, camera, draw, layerOn, onMapChanged, onMapUnavailable, onTrafficChanged });

  return { draw, refresh, refreshSightings, refreshTraffic, refreshGuide, resetPolling, toWorld, streamEvidence,
    setCameraFrame: camera.setCameraFrame, bindCamera: camera.bindCamera };
}
