// 현장 지도 뷰 (Fleet 분해 4). 격자 paint·좌표 변환·로봇/목표·대형·중재
// 오버레이·맵 폴링을 가진다. 셸은 클릭-목표 지정과 토큰·폴링 주기를 쥔다.
// 좌표계: 로봇 pose 는 CORE 가 TF `map → <ns>base_footprint` 로 읽어 주는 map 프레임
// 값이다(ros_bridge `_map_frame = "map"`). 그래서 N대를 한 격자 위에 그대로 겹쳐
// 그릴 수 있다. 격자는 행 0 이 아래쪽(y 최소)이고 캔버스는 위가 0 이라 y 를 뒤집는다.

export function createMapView({ el, view, css, auth, call }) {
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
    const free = hexToRgb(css("--paper"));
    const occupied = hexToRgb(css("--ground-deep"));
    const unknown = hexToRgb(css("--ground-soft"));
    for (let row = 0; row < height; row += 1) {
      for (let col = 0; col < width; col += 1) {
        const value = grid.data[row * width + col];
        const rgb = value === GRID.UNKNOWN || value < 0 ? unknown
          : value >= GRID.OCCUPIED_MIN ? occupied
            : value <= GRID.FREE_MAX ? free : unknown;
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

  function hexToRgb(value) {
    const hex = value.replace("#", "");
    const n = parseInt(hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
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

  function drawChip(ctx, grid, cx, cy, text, tone) {
    const point = ctx.getTransform().transformPoint({ x: cx, y: cy });
    const displayedWidth = ctx.canvas.getBoundingClientRect().width || ctx.canvas.width;
    const fontSize = Math.max(10, Math.round(12 * ctx.canvas.width / displayedWidth));
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.font = `${fontSize}px ${css("--mono") || "monospace"}`;
    const padding = fontSize * 0.4;
    const maxTextWidth = Math.max(fontSize, ctx.canvas.width - padding * 2 - 8);
    while (ctx.measureText(text).width > maxTextWidth && text.length > 1) {
      text = `${text.slice(0, -2)}…`;
    }
    const width = ctx.measureText(text).width + padding * 2;
    const height = fontSize + padding * 2;
    const x = Math.max(width / 2 + 4, Math.min(ctx.canvas.width - width / 2 - 4, point.x));
    const y = Math.max(height / 2 + 4, Math.min(ctx.canvas.height - height / 2 - 4, point.y));
    ctx.globalAlpha = 0.92;
    ctx.fillStyle = css("--scrim");
    ctx.fillRect(x - width / 2, y - height / 2, width, height);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = css("--surface-line");
    ctx.lineWidth = 0.4;
    ctx.strokeRect(x - width / 2, y - height / 2, width, height);
    ctx.fillStyle = tone === "crit" ? css("--status-crit")
      : tone === "warn" ? css("--status-warn") : css("--paper");
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
        ctx.strokeStyle = error > TRACK_WARN_M ? css("--status-warn") : css("--muted-line");
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
        ctx.strokeStyle = css("--muted-line");
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

  function draw() {
    const grid = view.map;
    if (!grid) return;
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

  async function refresh() {
    if (auth.locked) return;
    try {
      const grid = await call("/api/fleet/map");
      view.map = grid;
      draw();
    } catch (err) {
      el("map-tag").textContent = "맵 없음";
    }
  }

  return { draw, refresh, toWorld, streamEvidence };
}
