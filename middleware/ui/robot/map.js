// 색은 tokens.css가 소유한다(concept 16 §6, D-72 L1). 캔버스는 CSS 변수를
// 직접 못 쓰므로 한 번 풀어 둔 표를 쓴다 — 픽셀마다 읽으면 안 된다.
import { confirmIrreversible } from "/common/ui.js";
const PALETTE_TOKENS = {
  rasterUnknown: "--raster-unknown",
  rasterFree: "--raster-free",
  rasterUncertain: "--raster-uncertain",
  rasterOccupied: "--raster-occupied",
  costLethal: "--status-warn",
  route: "--series-primary",
  // 로봇 자신은 계열 중 하나가 아니라 보는 사람의 현재 위치다. 계열 색
  // 예산을 쓰지 않고 가장 밝은 중립으로 둔다.
  pose: "--ink",
  ground: "--ground-deep",
};

// ui.js(window.RosyPalette)가 어떤 CSS 색이든 풀어 캐시하고 테마가 바뀌면 비운다.
function palette() {
  return window.RosyPalette.readPalette(PALETTE_TOKENS);
}

function cssColor(key) {
  return window.RosyPalette.cssColor(PALETTE_TOKENS[key]);
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

function occupancyColor(cell, tone) {
  if (cell < 0) return tone.rasterUnknown;
  if (cell < 20) return tone.rasterFree;
  if (cell < 60) return tone.rasterUncertain;
  return tone.rasterOccupied;
}

function paintLayers(occupancy, costmap, layers, width, height) {
  const image = new ImageData(width, height);
  const costFrame = layers.costmap && costmap ? new GridFrame(costmap) : null;
  const tone = palette();
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const world = occupancy.canvasToWorld(x + 0.5, y + 0.5, width, height);
      const cell = layers.occupancy ? occupancy.sampleWorld(world.x, world.y) : -1;
      const color = occupancyColor(cell == null ? -1 : cell, tone);
      const index = (y * width + x) * 4;
      image.data[index] = color[0];
      image.data[index + 1] = color[1];
      image.data[index + 2] = color[2];
      image.data[index + 3] = 255;
      if (!costFrame) continue;
      const lethal = costFrame.sampleWorld(world.x, world.y);
      if (lethal == null || lethal < 50) continue;
      const mix = Math.min(1, lethal / 254);
      const hazard = tone.costLethal;
      image.data[index] = Math.round(image.data[index] * (1 - mix) + hazard[0] * mix);
      image.data[index + 1] = Math.round(image.data[index + 1] * (1 - mix) + hazard[1] * mix);
      image.data[index + 2] = Math.round(image.data[index + 2] * (1 - mix) + hazard[2] * mix);
    }
  }
  return image;
}

export function createFieldMap(options) {
  const {
    canvas, empty, status, api, apiMaybe, emptyRecoveryLink,
    getPose, getNavigation, getMapSources, canGoal, setAction,
  } = options;
  const mayOpenSetup = options.mayOpenSetup === true;
  const listenerController = new AbortController();
  let committing = false;
  let resizeObserver = null;
  const layerButtons = [...(options.layerRoot?.querySelectorAll("[data-map-layer]") || [])];
  const clickButtons = [...(options.layerRoot?.querySelectorAll("[data-map-click]") || [])];

  const layers = { occupancy: true, costmap: true, path: true };
  let clickMode = "pose";
  // D-259: 키보드 십자선(캔버스 px). 색은 새로 열지 않고 paper를 쓰고 모양으로
  // 구분한다(로봇 삼각 vs 십자+원) — Law 1. 확정은 클릭과 같은 confirm·API를 탄다.
  let cross = null;
  let targetReadoutTimer = null;
  let goal = null;  // D-396: 마지막으로 보낸 내비게이션 목표 (world 좌표)
  window.addEventListener("rosy:goal-clear", () => { goal = null; paint(); });
  const CROSS_STEP = 12;
  if (canvas && !canvas.hasAttribute("tabindex")) canvas.tabIndex = 0;
  const state = { occupancy: null, path: null, pathLoaded: false, costmap: null, raster: null, lastNav: null, mapState: "loading" };
  let pathRequest = 0;
  const ctx = canvas?.getContext("2d") || null;

  function notifyTargetReadout() {
    if (targetReadoutTimer) clearTimeout(targetReadoutTimer);
    targetReadoutTimer = setTimeout(() => {
      targetReadoutTimer = null;
      if (!cross || !state.occupancy || !canvas) {
        options.onTargetReadout?.({inside: false, unavailable: !state.occupancy});
        return;
      }
      const frame = new GridFrame(state.occupancy);
      const world = frame.canvasToWorld(cross.x, cross.y, canvas.width, canvas.height);
      const inside = frame.worldToCell(world.x, world.y) !== null;
      options.onTargetReadout?.({...world, inside, unavailable: false});
    }, 140);
  }

  function setStatus(text, statusState = "ready") {
    if (status) {
      status.textContent = text;
      status.setAttribute("state", statusState);
    }
  }

  const mapIdMismatch = () => Boolean(state.occupancy?.map_id && options.getCurrentMapId?.()
    && state.occupancy.map_id !== options.getCurrentMapId());
  const canMapClick = (mode) => Boolean(state.occupancy) && !mapIdMismatch() && canGoal?.(mode) === true;
  function pathEvidence() {
    const path = state.path;
    if (!state.pathLoaded) return {visible: false, label: "확인 중"};
    if (!path) return {visible: false, label: "수신 실패"};
    if (!Array.isArray(path.poses) || path.poses.length < 2) return {visible: false, label: "없음"};
    if (path.poses.some((pose) => !Number.isFinite(pose?.x) || !Number.isFinite(pose?.y)))
      return {visible: false, label: "좌표 확인 불가"};
    if (mapIdMismatch() || (path.map_id && state.occupancy?.map_id && path.map_id !== state.occupancy.map_id))
      return {visible: false, label: "지도 ID 불일치"};
    if (!path.map_id || !state.occupancy?.map_id) return {visible: false, label: "지도 ID 미확인"};
    if (path.frame_id !== "map") return {visible: false, label: "지도 좌표 미확인"};
    if (!Number.isFinite(path.age_s) || path.age_s < 0) return {visible: false, label: "수신 나이 미확인"};
    if (options.onlyActivePath && !["PLANNING", "NAVIGATING"].includes(getNavigation?.()))
      return {visible: false, label: "주행 상태 확인 필요"};
    const age = Math.floor(path.age_s + (performance.now() - path.readAt) / 1000);
    return {visible: true, label: `마지막 수신 ${age}초 전`};
  }
  function setPath(path) {
    state.path = path ? {...path, readAt: performance.now()} : null;
    state.pathLoaded = true;
    options.onPathReadout?.(pathEvidence());
  }
  function syncMapStatus() {
    const mismatch = mapIdMismatch();
    options.onMapIdMismatch?.(mismatch);
    if (state.mapState !== "ready") return;
    const grid = state.occupancy;
    const message = mismatch ? "로봇과 지도 ID가 다릅니다. 지도 갱신을 기다리세요."
      : !Number.isFinite(Number(grid.width)) || !Number.isFinite(Number(grid.height))
        ? grid.map_id || "크기 미상" : `${grid.width}×${grid.height}${grid.map_id ? ` · ${grid.map_id}` : ""}`;
    const statusState = mismatch ? "pending" : "ready";
    if (status?.textContent !== message || status?.getAttribute("state") !== statusState) setStatus(message, statusState);
  }

  function syncClickButtons() {
    // D-359 §5.3 — 역할 화면은 공용 안내문을 쓰고, 목표만 막힐 때는 해당 버튼에도 이유를 단다.
    clickButtons.forEach((button) => {
      const allowed = canMapClick(button.dataset.mapClick);
      const reason = allowed ? "" : mapIdMismatch() ? "로봇과 지도 ID 불일치" : (options.goalReason?.(button.dataset.mapClick) || "");
      button.disabled = !allowed;
      if (reason) button.setAttribute("reason", reason);
      else button.removeAttribute("reason");
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
    canvas.toggleAttribute("data-goal-cursor", canMapClick(clickMode));
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
    if (layers.path && pathEvidence().visible) {
      const scale = window.devicePixelRatio || 1;
      const points = state.path.poses.map((pose) => frame.worldToCanvas(pose.x, pose.y, canvas.width, canvas.height));
      ctx.beginPath();
      points.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = cssColor("route");
      ctx.lineWidth = 4 * scale;
      ctx.stroke();
      // 마지막 수신 계획의 끝 방향만 표시한다. 현재 목표나 실제 주행 궤적 표시는 아니다.
      const end = points[points.length - 1];
      const previous = points.slice(0, -1).reverse().find((point) => Math.hypot(end.x - point.x, end.y - point.y) > scale);
      if (previous) {
        ctx.save();
        ctx.translate(end.x, end.y);
        ctx.rotate(Math.atan2(end.y - previous.y, end.x - previous.x));
        ctx.fillStyle = cssColor("route");
        ctx.beginPath();
        ctx.moveTo(5 * scale, 0);
        ctx.lineTo(-9 * scale, -6 * scale);
        ctx.lineTo(-9 * scale, 6 * scale);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      }
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
    // D-396: 목표 마커 — 경로 색 다이아몬드. 로봇 삼각형(pose)과 구분된다.
    if (goal && state.occupancy && !mapIdMismatch()) {
      const goalPoint = frame.worldToCanvas(goal.x, goal.y, canvas.width, canvas.height);
      ctx.save();
      ctx.translate(goalPoint.x, goalPoint.y);
      ctx.rotate(Math.PI / 4);
      ctx.strokeStyle = cssColor("route");
      ctx.lineWidth = 2;
      ctx.strokeRect(-5, -5, 10, 10);
      ctx.restore();
    }
    const pose = mapIdMismatch() ? null : options.getDisplayPose ? options.getDisplayPose() : getPose?.();
    if (!pose || !Number.isFinite(Number(pose.x))) return;
    const point = frame.worldToCanvas(pose.x, pose.y, canvas.width, canvas.height);
    const scale = window.devicePixelRatio || 1;
    ctx.save();
    ctx.translate(point.x, point.y);
    ctx.rotate(-Number(pose.yaw) || 0);
    ctx.strokeStyle = cssColor("pose");
    ctx.lineWidth = 1.5 * scale;
    ctx.beginPath();
    ctx.arc(0, 0, 16 * scale, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(12 * scale, 0);
    ctx.lineTo(-8 * scale, 8 * scale);
    ctx.lineTo(-8 * scale, -8 * scale);
    ctx.closePath();
    ctx.fillStyle = cssColor("pose");
    ctx.fill();
    ctx.restore();
  }

  function setPose() {
    syncClickButtons();
    syncMapStatus();
    const nav = getNavigation?.();
    if (nav !== state.lastNav) {
      pathRequest++;
      state.lastNav = nav;
      state.pathLoaded = false;
      state.path = null;
      if (nav) refreshPath();
      else setPath({poses: []});
    }
    options.onPathReadout?.(pathEvidence());
    syncCursor();
    paint();
  }

  async function refreshPath() {
    const request = ++pathRequest;
    const isCurrent = options.captureLifetime?.().current || (() => true);
    const path = await apiMaybe("/api/v1/navigation/path").catch(() => null);
    if (listenerController.signal.aborted || !isCurrent() || request !== pathRequest) return;
    setPath(path);
    paint();
  }

  function wanted(key) {
    const sources = getMapSources?.();
    return !sources || sources[key] !== false;
  }

  async function refresh(isCurrent = options.captureLifetime?.().current || (() => true)) {
    const request = ++pathRequest;
    try {
      const [grid, path, costmap] = await Promise.all([
        wanted("occupancy") ? apiMaybe("/api/v1/map") : null,
        apiMaybe("/api/v1/navigation/path").catch(() => null),
        wanted("global_costmap") ? apiMaybe("/api/v1/map/costmap?scope=global") : null,
      ]);
      if (listenerController.signal.aborted || !isCurrent()) return;
      state.occupancy = grid;
      if (request === pathRequest) setPath(path);
      state.costmap = costmap;
      state.mapState = grid ? "ready" : "empty";
      syncEmpty();
      syncCursor();
      if (!grid) setStatus("지도가 아직 없습니다.", "empty");
    } catch (error) {
      if (listenerController.signal.aborted || !isCurrent()) return;
      // Without a server freshness field, do not leave a previous snapshot looking current.
      state.occupancy = null;
      if (request === pathRequest) setPath(null);
      state.costmap = null;
      state.mapState = error.status === 403 ? "forbidden" : "error";
      syncEmpty();
      syncCursor();
      setStatus(error.status === 403
        ? "지도 데이터를 볼 권한이 없습니다."
        : "최신 지도 데이터를 읽지 못했습니다. 연결 상태를 확인하고 다시 시도하십시오.", error.status === 403 ? "forbidden" : "error");
    }
    rebuildRaster();
    syncMapStatus();
    syncClickButtons();
    options.onPathReadout?.(pathEvidence());
    paint();
    if (cross) notifyTargetReadout();
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
      if (button.disabled || !canMapClick(mode)) return;
      clickMode = mode;
      syncClickButtons();
    }, {signal: listenerController.signal});
  });
  syncClickButtons();

  // D-359 §4 — 테마가 바뀌면 새로 고침 없이 다시 칠한다. 색 캐시는 ui.js가 먼저 비운다.
  document.addEventListener("rosy:theme", () => {
    rebuildRaster();
    paint();
  }, {signal: listenerController.signal});

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
    if (committing || listenerController.signal.aborted) return;
    if (!state.occupancy || !canvas) {
      setAction?.("최신 지도 데이터를 확인할 수 없어 위치·목표를 보내지 않았습니다.");
      return;
    }
    if (mapIdMismatch()) {
      setAction?.("로봇과 지도 ID가 달라 위치·목표를 보내지 않았습니다. 지도 갱신을 기다리세요.");
      return;
    }
    if (!canGoal?.(clickMode)) {
      setAction?.(options.goalReason?.(clickMode) || "현재 실행 모드나 로봇 기능으로는 위치·목표 조작을 쓸 수 없습니다.");
      return;
    }
    const world = new GridFrame(state.occupancy).canvasToWorld(px, py, canvas.width, canvas.height);
    const yaw = Number(getPose?.()?.yaw) || 0;
    const locating = clickMode === "pose";
    const label = locating ? "초기 자세" : "목표";
    const path = locating
      ? "/api/v1/localization/initialpose"
      : "/api/v1/navigation/goal";
    const mapSnapshot = JSON.stringify(state.occupancy);
    const modeSnapshot = clickMode;
    const owner = options.captureLifetime?.() || {current: () => true, signal: listenerController.signal};
    committing = true;
    try {
      const confirmed = await (options.confirm || confirmIrreversible)({message: `${label} ${world.x.toFixed(2)}, ${world.y.toFixed(2)} 로 보낼까요?`, action: locating ? "위치 설정" : "목표 전송", opener: canvas, signal: AbortSignal.any([owner.signal, listenerController.signal])});
      if (!confirmed || !owner.current() || listenerController.signal.aborted || !canMapClick(modeSnapshot) || modeSnapshot !== clickMode || mapSnapshot !== JSON.stringify(state.occupancy) || yaw !== (Number(getPose?.()?.yaw) || 0)) return;
      await api(path, {
        method: "POST",
        body: JSON.stringify({ x: world.x, y: world.y, yaw }),
      });
      if (listenerController.signal.aborted || !owner.current()) return;
      setAction?.(`${label} ${world.x.toFixed(2)}, ${world.y.toFixed(2)} 요청을 CORE가 받았습니다. 실제 적용 상태는 로봇 readback으로 확인하세요.`);
      if (!locating) {
        window.dispatchEvent(new CustomEvent("rosy:goal", { detail: { x: world.x, y: world.y } }));
        // D-396: 목표를 지도에도 기억한다 — paint() 에서 마커로 그린다.
        goal = { x: world.x, y: world.y };
        paint();
      }
    } catch (error) {
      if (!listenerController.signal.aborted && owner.current()) setAction?.(`${label} 전송 실패: ${error.message}`);
    } finally { committing = false; }
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
    notifyTargetReadout();
    await commitPoint(cross.x, cross.y);
  }, {signal: listenerController.signal});

  canvas?.addEventListener("keydown", async (event) => {
    if (!state.occupancy || !canvas) return;
    const step = event.shiftKey ? 2 : CROSS_STEP;
    if (!cross) {
      // 첫 진입은 로봇 자리, 모르면 한가운데 — 어디서 시작했는지 보이게 한다.
      // 격자가 비정상이면 worldToCanvas 가 NaN 을 내므로 유한성까지 본다.
      const pose = options.getDisplayPose ? options.getDisplayPose() : getPose?.();
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
    else if (event.key === "Escape") { cross = null; paint(); notifyTargetReadout(); return; }
    else if (event.key === "Enter") { await commitPoint(cross.x, cross.y); return; }
    else moved = false;
    if (!moved) return;
    event.preventDefault();
    cross.x = Math.min(Math.max(cross.x, 0), canvas.width);
    cross.y = Math.min(Math.max(cross.y, 0), canvas.height);
    paint();
    notifyTargetReadout();
  }, {signal: listenerController.signal});

  syncEmpty();
  return {
    refresh,
    setPose,
    get mapState() { return state.mapState; },
    destroy() {
      listenerController.abort();
      resizeObserver?.disconnect();
      if (targetReadoutTimer) clearTimeout(targetReadoutTimer);
    },
  };
}
