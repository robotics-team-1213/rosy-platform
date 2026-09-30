// 현장 지도 뷰 (Fleet 분해 4). 격자 paint·좌표 변환·로봇/목표·대형·중재
// 오버레이·맵 폴링을 가진다. 셸은 클릭-목표 지정과 토큰·폴링 주기를 쥔다.
// 좌표계: 로봇 pose 는 CORE 가 TF `map → <ns>base_footprint` 로 읽어 주는 map 프레임
// 값이다(ros_bridge `_map_frame = "map"`). 그래서 N대를 한 격자 위에 그대로 겹쳐
// 그릴 수 있다. 격자는 행 0 이 아래쪽(y 최소)이고 캔버스는 위가 0 이라 y 를 뒤집는다.
// D-257 사이트 층: 천장 카메라가 덮는 사각형과 카메라 관측(sighting)을 같은 map 프레임에
// 그린다. 관측은 속이 빈 점선 고리로, CORE TF pose(채운 삼각형)와 섞지 않는다.

import {
  classifySightings, siteBounds, canvasSizeFor, fitTransform, project, gridLines, GRID_STEP_M,
} from "./site-layer.js";

export function createMapView({ el, view, auth, call, onMapChanged, onMapUnavailable }) {
  // D-359 §4 — 색·글꼴은 ui.js(window.RosyPalette)가 어떤 CSS 색이든 풀어 캐시한다.
  const css = (name) => window.RosyPalette.cssColor(name);
  const font = (size) => window.RosyPalette.canvasFont(size, "mono");
  const GRID = { UNKNOWN: -1, FREE_MAX: 25, OCCUPIED_MIN: 65 };
  // Map tracking visualization only; relay evidence comes from the Fleet server.
  const TRACK_WARN_M = 0.3;     // 기본 간격(0.6 m)의 절반을 넘으면 주의 색을 쓴다.

  function paintGrid(grid) {
    const canvas = el("map-canvas");
    const { width, height } = grid;
    // Occupancy cells stay pixelated, while map labels need enough backing pixels
    // to remain legible when a small grid is stretched across the console.
    const scale = Math.min(10, Math.max(1, Math.floor(1600 / Math.max(width, height))));
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

  // 릴레이 건강을 D-72 증거로 옮긴다. fresh 는 아무것도 붙이지 않는다(§7.3 정상은 안 보임).
  function streamEvidence(formation, robotId) {
    if (!formation?.active) return null;
    const evidence = formation.stream_evidence?.[robotId];
    if (!evidence) return { text: "\uC99D\uAC70 \uD310\uB2E8 \uC5C6\uC74C", cls: "warn" };
    if (evidence.state === "fresh") return null;
    if (evidence.state === "disconnected") return { text: "\uB04A\uAE40", cls: "crit" };
    if (evidence.state === "delayed") {
      const age = typeof evidence.age_s === "number" ? ` \u00B7 ${evidence.age_s.toFixed(1)}\uCD08` : "";
      const reason = evidence.reason === "rate_below_floor" ? " \u00B7 \uC1A1\uC2E0 \uBE48\uB3C4 \uB0AE\uC74C" : "";
      return { text: `\uC9C0\uC5F0${reason}${age}`, cls: "warn" };
    }
    return { text: "\uC1A1\uC2E0 \uC2DC\uAC01 \uC5C6\uC74C", cls: "warn" };
  }

  // D-359 US-008 — 이번 그리기에 놓인 칩(캔버스 픽셀, 시험은 window.__mapChips). 추적 오차와
  // 중재 칩이 겹쳐 못 읽었다: 새 칩은 빈 자리가 날 때까지 아래·위로 한 칸씩 번갈아 비킨다.
  let placedChips = [];
  const CHIP_GAP = 2, CHIP_TRIES = 12;
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
    for (let step = 1; step <= CHIP_TRIES && placedChips.some((r) => chipsOverlap(rectAt(y), r)); step += 1) {
      const rows = Math.ceil(step / 2);
      y = clampY(anchorY + (step % 2 ? 1 : -1) * rows * (height + CHIP_GAP));
    }
    placedChips.push(rectAt(y));
    ctx.globalAlpha = 0.92;
    ctx.fillStyle = css("--scrim");
    ctx.fillRect(x - width / 2, y - height / 2, width, height);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = css("--surface-line");
    ctx.lineWidth = 0.4;
    ctx.strokeRect(x - width / 2, y - height / 2, width, height);
    ctx.fillStyle = tone === "crit" ? css("--status-crit")
      : tone === "warn" ? css("--status-warn") : css("--ink");
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x, y);
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
        `HOLD · ${formation.reason.join(" / ")}`, "warn");
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
    const age = s.state === "stale" ? ` · ${(s.age_ms / 1000).toFixed(1)}초 전` : "";
    return `${s.robot_id} · 카메라${age}`;
  }

  // 카메라 관측 1건: 점선 고리 + 방향 선. toPoint 는 map m → 현재 ctx 좌표, size 는 같은 단위.
  function drawSighting(ctx, s, toPoint, size, lineWidth) {
    const { x: cx, y: cy } = toPoint(s.x, s.y);
    ctx.save();
    ctx.globalAlpha = s.state === "stale" ? 0.4 : 1;
    ctx.strokeStyle = colorOfSighting(s.robot_id);
    ctx.lineWidth = lineWidth;
    ctx.setLineDash([lineWidth * 2, lineWidth * 1.5]);
    ctx.beginPath();
    ctx.arc(cx, cy, size * 0.8, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    // 캔버스 y 가 아래로 자라므로 sin 은 뒤집는다.
    ctx.lineTo(cx + Math.cos(s.yaw) * size * 1.4, cy - Math.sin(s.yaw) * size * 1.4);
    ctx.stroke();
    ctx.restore();
    drawChip(ctx, null, cx, cy + size * 1.9, sightingLabel(s), s.state === "stale" ? "warn" : undefined);
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
    for (const entry of sitePolygons()) {
      tracePolygon(ctx, entry.polygon_m, toCell);
      ctx.stroke();
    }
    ctx.restore();
    for (const s of view.sightings) drawSighting(ctx, s, toCell, size, 0.5);
  }

  // 점유 격자가 없을 때: 사이트 사각형에 맞춘 미터 축척 뷰. 목표 지정은 받지 않는다.
  function drawSiteView() {
    const bounds = siteBounds(view.siteMap);
    if (!bounds) return;
    const canvas = el("map-canvas");
    // 비트맵을 화면에 보이는 박스 크기(× DPR)에 맞춘다 — 글자와 선이 CSS px 로 읽히게.
    // 박스를 아직 모르면(숨김 등) 사각형 종횡비로 대신한다.
    const rect = canvas.getBoundingClientRect();
    const fallback = canvasSizeFor(bounds, 800);
    const width = rect.width > 0 ? rect.width : fallback.width;
    const height = rect.height > 0 ? rect.height : fallback.height;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    const t = fitTransform(bounds, width, height, 32);
    const toPx = (x, y) => { const p = project(t, x, y); return { x: p.px, y: p.py }; };
    ctx.fillStyle = css("--ground-deep");
    ctx.fillRect(0, 0, width, height);
    const labelFont = font(12);

    // 0.5 m 격자
    ctx.save();
    ctx.lineWidth = 1;
    ctx.strokeStyle = css("--line-quiet");
    ctx.globalAlpha = 0.5;
    for (const gx of gridLines(bounds.min_x, bounds.max_x, GRID_STEP_M)) {
      const a = toPx(gx, bounds.min_y);
      const b = toPx(gx, bounds.max_y);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    for (const gy of gridLines(bounds.min_y, bounds.max_y, GRID_STEP_M)) {
      const a = toPx(bounds.min_x, gy);
      const b = toPx(bounds.max_x, gy);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    ctx.restore();

    // 사각형 + 치수 + 출처(source_id)
    ctx.save();
    ctx.font = labelFont;
    for (const entry of sitePolygons()) {
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
    const axisAt = originVisible ? toPx(0, 0) : toPx(bounds.min_x + 0.1, bounds.min_y + 0.1);
    const axisLen = Math.min(t.scale * 0.4, width / 8);
    ctx.save();
    ctx.lineWidth = 2;
    ctx.font = labelFont;
    ctx.textBaseline = "middle";
    ctx.strokeStyle = css("--ink");
    ctx.fillStyle = css("--ink");
    ctx.beginPath();
    ctx.moveTo(axisAt.x, axisAt.y);
    ctx.lineTo(axisAt.x + axisLen, axisAt.y);
    ctx.moveTo(axisAt.x, axisAt.y);
    ctx.lineTo(axisAt.x, axisAt.y - axisLen);
    ctx.stroke();
    ctx.fillText("x", axisAt.x + axisLen + 4, axisAt.y);
    ctx.textAlign = "center";
    ctx.fillText("y", axisAt.x, axisAt.y - axisLen - 10);
    if (originVisible) {
      ctx.beginPath();
      ctx.arc(axisAt.x, axisAt.y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.textAlign = "right";
      ctx.fillText("0,0", axisAt.x - 6, axisAt.y + 12);
    }
    ctx.restore();

    for (const s of view.sightings) drawSighting(ctx, s, toPx, Math.max(7, t.scale * 0.09), 1.5);
  }

  function describeSightings() {
    const fresh = view.sightings.filter((s) => s.state === "fresh").length;
    return `카메라 관측 ${fresh}/${view.sightings.length}대`;
  }

  function draw() {
    const grid = view.map;
    placedChips = [];
    window.__mapChips = placedChips;
    if (!grid) {
      if (view.siteMap) {
        drawSiteView();
        const b = siteBounds(view.siteMap, 0);
        el("map-tag").textContent =
          `사이트 ${(b.max_x - b.min_x).toFixed(1)}×${(b.max_y - b.min_y).toFixed(1)} m · ${describeSightings()}`;
        el("map-canvas").setAttribute("aria-label",
          `천장 카메라 사이트 지도 — ${describeSightings()}. 이 지도에서는 목표를 지정할 수 없습니다.`);
      }
      return;
    }
    const canvas = el("map-canvas");
    const ctx = canvas.getContext("2d");
    paintGrid(grid);
    if (view.stateUnavailable) {
      el("map-tag").textContent = "로봇 위치 확인 불가";
      canvas.setAttribute("aria-label", "로봇 위치 확인 불가 — Fleet 상태 연결을 확인하세요");
      return;
    }
    el("map-tag").textContent = `${grid.width}×${grid.height} · ${grid.map_id || "map"}`;
    canvas.setAttribute("aria-label", "지도에서 로봇 목표 위치 선택");
    // 격자 픽셀 위에 그리므로 선 굵기도 격자 칸 단위다. 0.6칸이면 3 cm 남짓이다.
    ctx.lineWidth = 0.6;
    view.robots.forEach((robot, index) => {
      const pose = robot.state && robot.state.pose;
      if (!pose) return;
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
      ctx.restore();

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
    drawFormationOverlay(ctx, grid);
    drawMediation(ctx, grid);
    drawSiteOverlay(ctx, grid);
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
    try {
      view.siteMap = await call("/api/fleet/site-map");
    } catch (err) {
      // NO_SITE_MAP — 카메라 사각형이 설정되지 않은 현장이다. 일시 실패면 직전 사각형을 둔다.
      if (err.status === 404 && err.code === "NO_SITE_MAP") view.siteMap = null;
    }
  }

  async function refresh() {
    if (auth.locked) return;
    sightingsUnavailable = false;
    await refreshSiteMap();
    if (auth.locked) return;
    try {
      const grid = await call("/api/fleet/map");
      view.map = grid;
      el("map-stage").dataset.mapState = "ready";
      el("map-empty").hidden = true;
      el("map-canvas").removeAttribute("aria-hidden");
      el("map-canvas").setAttribute("role", "button");
      syncLegend("grid");
      draw();
      onMapChanged();
    } catch (err) {
      view.map = null;
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
      el("map-empty-title").textContent = "지도를 확인할 수 없습니다";
      el("map-empty-detail").textContent = "Fleet 지도 연결과 등록 로봇 상태를 확인하세요.";
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
  async function refreshSightings() {
    if (auth.locked || sightingsInFlight || sightingsUnavailable || !view.siteMap) return;
    sightingsInFlight = true;
    let next = [];
    try {
      next = classifySightings(await call("/api/fleet/sightings"));
    } catch (err) {
      // 일시 실패도 옛 관측을 남기지 않는다.
      if (err.status === 404) sightingsUnavailable = true;
    } finally {
      sightingsInFlight = false;
    }
    const unchanged = JSON.stringify(next) === JSON.stringify(view.sightings);
    view.sightings = next;
    if (unchanged && !next.length) return; // 빈 채로 그대로면 격자를 다시 칠하지 않는다
    el("legend-sighting").hidden = !view.siteMap && !view.sightings.length;
    draw();
  }

  return { draw, refresh, refreshSightings, toWorld, streamEvidence };
}
