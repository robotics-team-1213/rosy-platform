// 색은 tokens.css가 소유한다(concept 16 §6, D-72 L1). 캔버스는 CSS 변수를
// 직접 못 쓰므로 한 번만 읽어 캐시한다 — 픽셀마다 읽으면 안 된다.
const PALETTE_TOKENS = {
  rasterUnknown: "--raster-unknown",
  rasterFree: "--raster-free",
  rasterUncertain: "--raster-uncertain",
  rasterOccupied: "--raster-occupied",
  costLethal: "--status-warn",
  route: "--series-primary",
  // 로봇 자신은 계열 중 하나가 아니라 보는 사람의 현재 위치다. 계열 색
  // 예산을 쓰지 않고 가장 밝은 중립으로 둔다.
  pose: "--paper",
  ground: "--ground-deep",
};

let paletteCache = null;

function readToken(name) {
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  const hex = raw.replace("#", "");
  if (hex.length !== 6) return [0, 0, 0];
  return [
    parseInt(hex.slice(0, 2), 16),
    parseInt(hex.slice(2, 4), 16),
    parseInt(hex.slice(4, 6), 16),
  ];
}

function palette() {
  if (paletteCache) return paletteCache;
  paletteCache = {};
  for (const [key, token] of Object.entries(PALETTE_TOKENS)) {
    paletteCache[key] = readToken(token);
  }
  return paletteCache;
}

function cssColor(key) {
  const [r, g, b] = palette()[key];
  return `rgb(${r}, ${g}, ${b})`;
}

function GridFrame(grid) {
  this.width = Number(grid?.width) || 0;
  this.height = Number(grid?.height) || 0;
  this.resolution = Number(grid?.resolution) || 0;
  this.originX = Number(grid?.origin?.x) || 0;
  this.originY = Number(grid?.origin?.y) || 0;
  this.data = grid?.data || [];
}

GridFrame.prototype.worldToCell = function worldToCell(x, y) {
  if (this.resolution <= 0 || this.width <= 0 || this.height <= 0) return null;
  const column = Math.floor((Number(x) - this.originX) / this.resolution);
  const row = Math.floor((Number(y) - this.originY) / this.resolution);
  if (column < 0 || row < 0 || column >= this.width || row >= this.height) return null;
  return { column, row };
};

GridFrame.prototype.sampleWorld = function sampleWorld(x, y) {
  const cell = this.worldToCell(x, y);
  if (!cell) return null;
  const value = Number(this.data[cell.row * this.width + cell.column]);
  return Number.isFinite(value) ? value : null;
};

GridFrame.prototype.canvasToWorld = function canvasToWorld(px, py, canvasWidth, canvasHeight) {
  const cellX = (px / canvasWidth) * this.width;
  const cellY = (1 - py / canvasHeight) * this.height;
  return {
    x: this.originX + cellX * this.resolution,
    y: this.originY + cellY * this.resolution,
  };
};

GridFrame.prototype.worldToCanvas = function worldToCanvas(x, y, canvasWidth, canvasHeight) {
  const cellX = (Number(x) - this.originX) / this.resolution;
  const cellY = (Number(y) - this.originY) / this.resolution;
  return {
    x: (cellX / this.width) * canvasWidth,
    y: (1 - cellY / this.height) * canvasHeight,
  };
};

function occupancyColor(cell) {
  const tone = palette();
  if (cell < 0) return tone.rasterUnknown;
  if (cell < 20) return tone.rasterFree;
  if (cell < 60) return tone.rasterUncertain;
  return tone.rasterOccupied;
}

function paintLayers(occupancy, costmap, layers, width, height) {
  const image = new ImageData(width, height);
  const costFrame = layers.costmap && costmap ? new GridFrame(costmap) : null;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const world = occupancy.canvasToWorld(x + 0.5, y + 0.5, width, height);
      const cell = layers.occupancy ? occupancy.sampleWorld(world.x, world.y) : -1;
      const color = occupancyColor(cell == null ? -1 : cell);
      const index = (y * width + x) * 4;
      image.data[index] = color[0];
      image.data[index + 1] = color[1];
      image.data[index + 2] = color[2];
      image.data[index + 3] = 255;
      if (!costFrame) continue;
      const lethal = costFrame.sampleWorld(world.x, world.y);
      if (lethal == null || lethal < 50) continue;
      const mix = Math.min(1, lethal / 254);
      const hazard = palette().costLethal;
      image.data[index] = Math.round(image.data[index] * (1 - mix) + hazard[0] * mix);
      image.data[index + 1] = Math.round(image.data[index + 1] * (1 - mix) + hazard[1] * mix);
      image.data[index + 2] = Math.round(image.data[index + 2] * (1 - mix) + hazard[2] * mix);
    }
  }
  return image;
}

export function createFieldMap(options) {
  const canvas = options.canvas;
  const empty = options.empty;
  const status = options.status;
  const api = options.api;
  const apiMaybe = options.apiMaybe;
  const emptyRecoveryLink = options.emptyRecoveryLink;
  const mayOpenSetup = options.mayOpenSetup === true;
  const getPose = options.getPose;
  const getNavigation = options.getNavigation;
  const canGoal = options.canGoal;
  const setAction = options.setAction;
  const listenerController = new AbortController();
  let resizeObserver = null;
  const layerButtons = [...(options.layerRoot?.querySelectorAll("[data-map-layer]") || [])];
  const clickButtons = [...(options.layerRoot?.querySelectorAll("[data-map-click]") || [])];

  const layers = { occupancy: true, costmap: true, path: true };
  let clickMode = "pose";
  // D-259: 키보드 십자선(캔버스 px). 색은 새로 열지 않고 paper를 쓰고 모양으로
  // 구분한다(로봇 삼각 vs 십자+원) — Law 1. 확정은 클릭과 같은 confirm·API를 탄다.
  let cross = null;
  const CROSS_STEP = 12;
  if (canvas && !canvas.hasAttribute("tabindex")) canvas.tabIndex = 0;
  const state = { occupancy: null, path: [], costmap: null, raster: null, lastNav: null, mapState: "loading" };
  const ctx = canvas?.getContext("2d") || null;

  function setStatus(text, statusState = "ready") {
    if (status) {
      status.textContent = text;
      status.setAttribute("state", statusState);
    }
  }

  function syncClickButtons() {
    const allowed = canGoal?.() === true;
    clickButtons.forEach((button) => {
      button.disabled = !allowed;
      if (allowed) button.setAttribute("aria-pressed", button.dataset.mapClick === clickMode ? "true" : "false");
      else button.removeAttribute("aria-pressed");
    });
  }

  function syncEmpty() {
    if (!empty) return;
    const knownEmpty = state.mapState === "empty";
    empty.hidden = !knownEmpty;
    if (knownEmpty) empty.textContent = "지도 데이터가 아직 없습니다. 운용자가 작업 준비에서 지도를 설정해야 합니다.";
    if (emptyRecoveryLink) emptyRecoveryLink.hidden = !(knownEmpty && mayOpenSetup);
  }

  function fitCanvas() {
    if (!canvas) return false;
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round((canvas.clientWidth || canvas.width || 1) * ratio));
    const height = Math.max(1, Math.round((canvas.clientHeight || canvas.height || 1) * ratio));
    if (canvas.width === width && canvas.height === height) return false;
    canvas.width = width;
    canvas.height = height;
    return true;
  }

  function syncCursor() {
    if (!canvas) return;
    canvas.style.cursor = canGoal?.() ? "crosshair" : "default";
  }

  function rebuildRaster() {
    if (!ctx || !canvas) return;
    fitCanvas();
    if (!state.occupancy) {
      state.raster = null;
      ctx.fillStyle = cssColor("ground");
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      return;
    }
    const frame = new GridFrame(state.occupancy);
    state.raster = paintLayers(frame, state.costmap, layers, canvas.width, canvas.height);
  }

  function paint() {
    if (!ctx || !canvas) return;
    if (!state.occupancy || !state.raster) {
      ctx.fillStyle = cssColor("ground");
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      return;
    }
    ctx.putImageData(state.raster, 0, 0);
    const frame = new GridFrame(state.occupancy);
    if (layers.path && state.path.length >= 2) {
      ctx.beginPath();
      state.path.forEach((pose, index) => {
        const point = frame.worldToCanvas(pose.x, pose.y, canvas.width, canvas.height);
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.strokeStyle = cssColor("route");
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    if (cross) {
      ctx.save();
      ctx.strokeStyle = cssColor("pose");
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(cross.x, cross.y, 9, 0, Math.PI * 2);
      ctx.moveTo(cross.x - 14, cross.y);
      ctx.lineTo(cross.x - 5, cross.y);
      ctx.moveTo(cross.x + 5, cross.y);
      ctx.lineTo(cross.x + 14, cross.y);
      ctx.moveTo(cross.x, cross.y - 14);
      ctx.lineTo(cross.x, cross.y - 5);
      ctx.moveTo(cross.x, cross.y + 5);
      ctx.lineTo(cross.x, cross.y + 14);
      ctx.stroke();
      ctx.restore();
    }
    const pose = getPose?.();
    if (!pose || !Number.isFinite(Number(pose.x))) return;
    const point = frame.worldToCanvas(pose.x, pose.y, canvas.width, canvas.height);
    ctx.save();
    ctx.translate(point.x, point.y);
    ctx.rotate(-Number(pose.yaw) || 0);
    ctx.beginPath();
    ctx.moveTo(10, 0);
    ctx.lineTo(-7, 7);
    ctx.lineTo(-7, -7);
    ctx.closePath();
    ctx.fillStyle = cssColor("pose");
    ctx.fill();
    ctx.restore();
  }

  function setPose() {
    syncClickButtons();
    const nav = getNavigation?.();
    if (nav && nav !== state.lastNav) {
      state.lastNav = nav;
      refreshPath();
    }
    syncCursor();
    paint();
  }

  async function refreshPath() {
    const path = await apiMaybe("/api/v1/navigation/path");
    state.path = path?.poses || [];
    paint();
  }

  async function refresh() {
    try {
      const [grid, path, costmap] = await Promise.all([
        apiMaybe("/api/v1/map"),
        apiMaybe("/api/v1/navigation/path"),
        apiMaybe("/api/v1/map/costmap?scope=global"),
      ]);
      state.occupancy = grid;
      state.path = path?.poses || [];
      state.costmap = costmap;
      state.mapState = grid ? "ready" : "empty";
      syncEmpty();
      syncCursor();
      if (!grid) setStatus("지도가 아직 없습니다.", "empty");
      else if (!Number.isFinite(Number(grid.width)) || !Number.isFinite(Number(grid.height)))
        setStatus(grid.map_id || "크기 미상");
      else setStatus(`${grid.width}×${grid.height}${grid.map_id ? ` · ${grid.map_id}` : ""}`);
    } catch (error) {
      // Without a server freshness field, do not leave a previous snapshot looking current.
      state.occupancy = null;
      state.path = [];
      state.costmap = null;
      state.mapState = error.status === 403 ? "forbidden" : "error";
      syncEmpty();
      syncCursor();
      setStatus(error.status === 403
        ? "지도 데이터를 볼 권한이 없습니다."
        : "최신 지도 데이터를 읽지 못했습니다. 연결 상태를 확인하고 다시 시도하십시오.", error.status === 403 ? "forbidden" : "error");
    }
    rebuildRaster();
    paint();
  }

  layerButtons.forEach((button) => {
    const layer = button.dataset.mapLayer;
    button.setAttribute("aria-pressed", layers[layer] ? "true" : "false");
    button.addEventListener("click", () => {
      layers[layer] = !layers[layer];
      button.setAttribute("aria-pressed", layers[layer] ? "true" : "false");
      rebuildRaster();
      paint();
    }, {signal: listenerController.signal});
  });

  clickButtons.forEach((button) => {
    const mode = button.dataset.mapClick;
    button.addEventListener("click", () => {
      if (button.disabled || canGoal?.() !== true) return;
      clickMode = mode;
      syncClickButtons();
    }, {signal: listenerController.signal});
  });
  syncClickButtons();

  if (typeof ResizeObserver === "function" && canvas) {
    resizeObserver = new ResizeObserver(() => {
      if (fitCanvas()) {
        rebuildRaster();
        paint();
      }
    });
    resizeObserver.observe(canvas);
  }

  // D-259: 클릭과 키보드 확정은 같은 길이다. 좌표→confirm→POST 전부가 여기 있다.
  async function commitPoint(px, py) {
    if (!state.occupancy || !canvas) return;
    if (!canGoal?.()) {
      setStatus("이 프로필에서는 목표 전송이 꺼져 있습니다.");
      return;
    }
    const world = new GridFrame(state.occupancy).canvasToWorld(px, py, canvas.width, canvas.height);
    const yaw = Number(getPose?.()?.yaw) || 0;
    const locating = clickMode === "pose";
    const label = locating ? "초기 자세" : "목표";
    const path = locating
      ? "/api/v1/localization/initialpose"
      : "/api/v1/navigation/goal";
    if (!window.confirm(`${label} ${world.x.toFixed(2)}, ${world.y.toFixed(2)} 로 보낼까요?`)) return;
    try {
      await api(path, {
        method: "POST",
        body: JSON.stringify({ x: world.x, y: world.y, yaw }),
      });
      setAction?.(`${label} ${world.x.toFixed(2)}, ${world.y.toFixed(2)} 전송`);
      setStatus(`${locating ? "pose" : "goal"} ${world.x.toFixed(2)}, ${world.y.toFixed(2)}`);
    } catch (error) {
      setStatus(`${label} 전송 실패: ${error.message}`, error.status === 403 ? "forbidden" : "error");
    }
  }

  canvas?.addEventListener("click", async (event) => {
    const rect = canvas.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * canvas.width;
    const py = ((event.clientY - rect.top) / rect.height) * canvas.height;
    cross = {
      x: Math.min(Math.max(px, 0), canvas.width),
      y: Math.min(Math.max(py, 0), canvas.height),
    };
    paint();
    await commitPoint(cross.x, cross.y);
  }, {signal: listenerController.signal});

  canvas?.addEventListener("keydown", async (event) => {
    if (!state.occupancy || !canvas) return;
    const step = event.shiftKey ? 2 : CROSS_STEP;
    if (!cross) {
      // 첫 진입은 로봇 자리, 모르면 한가운데 — 어디서 시작했는지 보이게 한다.
      // 격자가 비정상이면 worldToCanvas 가 NaN 을 내므로 유한성까지 본다.
      const pose = getPose?.();
      let start = null;
      if (pose && Number.isFinite(Number(pose.x))) {
        const frame = new GridFrame(state.occupancy);
        const point = frame.worldToCanvas(pose.x, pose.y, canvas.width, canvas.height);
        if (Number.isFinite(point.x) && Number.isFinite(point.y)) start = point;
      }
      cross = start || { x: canvas.width / 2, y: canvas.height / 2 };
      cross.x = Math.min(Math.max(cross.x, 0), canvas.width);
      cross.y = Math.min(Math.max(cross.y, 0), canvas.height);
    }
    let moved = true;
    if (event.key === "ArrowLeft") cross.x -= step;
    else if (event.key === "ArrowRight") cross.x += step;
    else if (event.key === "ArrowUp") cross.y -= step;
    else if (event.key === "ArrowDown") cross.y += step;
    else if (event.key === "Escape") { cross = null; paint(); return; }
    else if (event.key === "Enter") { await commitPoint(cross.x, cross.y); return; }
    else moved = false;
    if (!moved) return;
    event.preventDefault();
    cross.x = Math.min(Math.max(cross.x, 0), canvas.width);
    cross.y = Math.min(Math.max(cross.y, 0), canvas.height);
    paint();
  }, {signal: listenerController.signal});

  syncEmpty();
  return {
    refresh,
    setPose,
    destroy() {
      listenerController.abort();
      resizeObserver?.disconnect();
    },
  };
}
