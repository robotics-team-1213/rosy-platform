// D-513 7 / D-515 카메라 그림 경로 (map-view.js 에서 분리). 실영상에 맞는 보정 고르기, 위에서 본
// 그림 펴기, 크게 보기·썸네일 회전, Vision 프레임 연결. 지도 그리기는 map-view.js 가 가지고
// draw hook 과 toPx 투영을 넘긴다.
import { setOffBy } from "/common/cause-line.js";
import { evidenceAgeText } from "/common/core_ui_logic.js";

import { siteBounds, fitTransform, project } from "./site-layer.js";
import { lensesMatch } from "/console/assets/map-fit.js";
import { affineFromTriangles, warpMesh } from "./camera-warp.js";
import { createPlaneFeed, planeCalibration, planeToMap } from "/console/assets/vision-view.js";

const FRESH_MS = 3000;
const PLANE_KEEP_MAX_MS = 30_000;

const fresh = (frame) => Number.isFinite(frame.ageMs) && frame.ageMs >= 0 && frame.ageMs <= FRESH_MS;

// 2026-11-14 요청 — 영상이 끊겨도 마지막 좋은 프레임을 지우지 않는다. 한 번이라도 live+신선했던
// 프레임만 유지할 수 있고, 나머지 입력(끊김·안 신선함·null)은 이전 그림을 가리키는 채로 둔다.
export const keepFrame = (kept, incoming) =>
  incoming && incoming.state === "live" && fresh(incoming) ? incoming : kept;

// 낡음 기록: 생중계는 `카메라 HH:MM:SS`, 끊기면 찍은 시각에서의 나이를 붙인다. 표시 전용이며
// 심각도 색과는 섞지 않는다.
export function staleStamp(capturedAtMs, nowMs, stale = false, label = "카메라") {
  if (!Number.isFinite(capturedAtMs)) return "";
  const clock = new Date(capturedAtMs);
  const time = [clock.getHours(), clock.getMinutes(), clock.getSeconds()]
    .map((part) => String(part).padStart(2, "0")).join(":");
  const ageS = Number.isFinite(nowMs) ? Math.max(0, Math.round((nowMs - capturedAtMs) / 1000)) : 0;
  return `${label} ${time}${stale ? evidenceAgeText(ageS) : ""}`;
}

export function cameraMapCalibration(frame, calibrations, siteMap) {
  if (!frame || frame.state !== "live" || frame.rectified || !siteMap || !fresh(frame)) return null;
  return (calibrations || []).find((row) => row.source_id === frame.source
    && (siteMap.maps || []).some((map) => map.map_id === row.map_id)
    && row.image?.width === frame.image?.naturalWidth
    && row.image?.height === frame.image?.naturalHeight
    // Vision's rule (D-457): a record without a lens only fits a frame without one; numbers to 1e-4.
    && lensesMatch(row.lens ?? null, frame.lens ?? null)
    && Array.isArray(row.map_to_image) && row.map_to_image.length === 9) || null;
}

// D-560 4: canvas affine [a, b, c, d, e, f] that lays plane pixels on the view through the map's toPx
// (x = min_x + u / ppm, y = max_y - v / ppm), so the view turn applies to the picture as to the lanes.
export function planeAffine(plane, width, height, toPx) {
  const at = (u, v) => { const m = planeToMap(plane, u, v); const p = toPx(m.x, m.y); return [p.x, p.y]; };
  return affineFromTriangles([[0, 0], [width, 0], [0, height]], [at(0, 0), at(width, 0), at(0, height)]);
}

// D-515: 원본 영상을 삼각형마다 아핀으로 옮겨 사이트 사각형 위에 위에서 본 그림으로 그린다.
// 이웃 삼각형 사이 머리카락 틈이 보이지 않게 잘라 내는 경로를 화면에서 0.5 px 넓힌다.
// 지도는 상태 폴링·관측·콜백으로 초당 여러 번 다시 그려진다. 펴는 일(576 번 그리기)은 새 프레임·
// 보정·크기에서만 하고, 그 사이에는 화면 밖 캔버스에 둔 결과를 한 번에 옮긴다.
function drawCameraTopDown(topDownCache, ctx, frame, calibration, bounds, toPx, width, height, dpr, rot = 0, alpha = 1) {
  const image = frame.image;
  const lp = calibration.lens_profile ?? null;
  const key = [calibration.source_id, calibration.map_id, calibration.calibration_revision,
    ...calibration.map_to_image, lp ? JSON.stringify(lp.D) : "", width, height, dpr, rot,
    bounds.min_x, bounds.max_x, bounds.min_y, bounds.max_y].join("|");
  let cached = topDownCache.get(key);
  const targetW = Math.round(width * dpr), targetH = Math.round(height * dpr);
  if (!cached) {
    const off = document.createElement("canvas");
    cached = { seq: null, image: null, canvas: off };
    topDownCache.set(key, cached);
    if (topDownCache.size > 2) topDownCache.delete(topDownCache.keys().next().value);
  }
  if (cached.image !== image || cached.seq !== frame.seq || cached.canvas.width !== targetW || cached.canvas.height !== targetH) {
    const off = cached.canvas;
    if (off.width !== targetW) off.width = targetW;
    if (off.height !== targetH) off.height = targetH;
    const octx = off.getContext("2d");
    if (octx.setTransform) octx.setTransform(dpr, 0, 0, dpr, 0, 0);
    else if (octx.scale) octx.scale(dpr, dpr);
    if (octx.clearRect) octx.clearRect(0, 0, width, height);
    warpOnto(octx, image, calibration.map_to_image, bounds, toPx, lp);
    cached.image = image;
    cached.seq = frame.seq;
  }
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = alpha;
  ctx.drawImage(cached.canvas, 0, 0);
  ctx.restore();
}
let lastWarp = null;
function warpOnto(ctx, image, mapToImage, bounds, toPx, lensProfile = null) {
  const lpSig = lensProfile ? JSON.stringify([lensProfile.model, lensProfile.K, lensProfile.D]) : "";
  const key = Array.isArray(mapToImage) && mapToImage.length === 9 && bounds
    ? [...mapToImage, bounds.min_x, bounds.max_x, bounds.min_y, bounds.max_y, lpSig] : null;
  if (!key || !lastWarp || key.length !== lastWarp.key.length || !lastWarp.key.every((v, i) => v === key[i])) {
    lastWarp = key ? { key, mesh: warpMesh(mapToImage, bounds, 24, 12, lensProfile) } : null;
  }
  const mesh = lastWarp ? lastWarp.mesh : warpMesh(mapToImage, bounds, 24, 12, lensProfile);
  for (const tri of mesh) {
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

export function createCameraBackdrop({ scope, el, view, draw }) {
  let cameraFrame = null;
  let capturedAt = 0;
  let stamp = null;
  let calibrations = [];
  // D-560: Vision's map plane is the picture; the D-515 raw warp is only the fallback.
  let planes = null;
  let keptPlane = null;
  let planeKey = null;
  let staleAt = 0; // 영상이 끊긴 시각(0 = 살아 있음). 그림을 지우는 대신 반투명+시각 글자로만 알린다.
  let lastCorrectedKey = null, lastCorrectedImage = null, lastCorrectedCleared = false;
  const topDownCache = new Map();
  const calibration = () => {
    const activeId = view.activeSiteMap?.map?.map_id;
    return cameraMapCalibration(cameraFrame,
      activeId ? calibrations.filter(row => row.map_id === activeId) : calibrations, view.siteMap);
  };
  const keyFor = (record) => view.displayMode === "overlay" && !view.map && record
    ? JSON.stringify([record.source_id, record.map_id, record.calibration_revision]) : null;
  const planeFrame = (record = calibration(), nowMs = Date.now()) => {
    const key = keyFor(record);
    if (keptPlane?.key !== key) keptPlane = null;
    if (keptPlane && !staleAt && planes?.current() !== keptPlane.frame
        && Number.isFinite(keptPlane.frame.capturedAtMs)
        && nowMs - keptPlane.frame.capturedAtMs > PLANE_KEEP_MAX_MS) keptPlane = null;
    return keptPlane?.frame ?? null;
  };
  const usesPlane = () => Boolean(planeFrame());
  function displayedPicture(record = calibration(), nowMs = Date.now()) {
    if (view.displayMode === "overlay" && !view.map) {
      const frame = planeFrame(record, nowMs);
      if (frame) return {
        kind: "plane", frame,
        capturedAtMs: Number.isFinite(frame.capturedAtMs) ? frame.capturedAtMs : capturedAt,
        stale: Boolean(staleAt) || planes?.current() !== frame,
      };
      if (!record) return { kind: "none" };
    }
    return cameraFrame
      ? { kind: "raw", frame: cameraFrame, capturedAtMs: capturedAt, stale: Boolean(staleAt) }
      : { kind: "none" };
  }
  function updateStamp() {
    const nowMs = Date.now();
    const hadKeptPlane = Boolean(keptPlane);
    const pic = displayedPicture(calibration(), nowMs);
    if (hadKeptPlane && !keptPlane) return redraw();
    if (!stamp) return;
    stamp.hidden = pic.kind === "none";
    const label = pic.kind === "plane" && pic.stale ? "평면 영상 지연" : "카메라";
    const next = staleStamp(pic.capturedAtMs, nowMs, pic.stale, label);
    if (stamp.textContent !== next) stamp.textContent = next;
  }
  function refreshPlane() {
    if (!planes) return;
    const key = keyFor(calibration());
    if (key !== planeKey) {
      planeKey = key;
      keptPlane = null;
      planes.refresh(false);
    }
    if (key && !staleAt) planes.refresh(true, cameraFrame.seq);
  }
  const setCalibrations = (rows) => { calibrations = rows; refreshPlane(); redraw(); };
  function drawTopDown(ctx, record, bounds, toPx, width, height, dpr, rot, pic = displayedPicture(record)) {
    const alpha = pic.stale ? 0.5 : 1;
    if (pic.kind === "raw") {
      drawCameraTopDown(topDownCache, ctx, pic.frame, record, bounds, toPx, width, height, dpr, rot, alpha);
      return;
    }
    if (pic.kind !== "plane") return;
    const { image, plane } = pic.frame;
    const affine = planeAffine(plane, image.naturalWidth ?? image.width, image.naturalHeight ?? image.height, toPx);
    if (!affine) return;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.beginPath();  // the plane never paints outside the site view the warp would cover
    [[bounds.min_x, bounds.min_y], [bounds.max_x, bounds.min_y], [bounds.max_x, bounds.max_y], [bounds.min_x, bounds.max_y]]
      .forEach(([x, y], k) => { const p = toPx(x, y); if (k) ctx.lineTo(p.x, p.y); else ctx.moveTo(p.x, p.y); });
    ctx.closePath();
    ctx.clip();
    ctx.transform(...affine);
    ctx.drawImage(image, 0, 0);
    ctx.restore();
  }
  function drawCorrected() {
    const canvas = el("camera-corrected"), status = el("camera-corrected-status");
    if (!canvas || !status) return;
    const record = calibration(), bounds = siteBounds(view.siteMap);
    const ready = Boolean(record && bounds);
    canvas.hidden = !ready;
    const nextStatus = ready ? `교정 후 · ${record.map_id} · ${record.calibration_revision || "승인 교정"}`
      : "같은 지도의 승인 교정과 신선한 영상이 필요합니다.";
    if (status.textContent !== nextStatus) status.textContent = nextStatus;
    if (ready) lastCorrectedCleared = false;
    if (!ready || !el("camera-comparison")?.open) {
      lastCorrectedKey = null;
      lastCorrectedImage = null;
      if (!ready && !lastCorrectedCleared) {
        canvas.width = canvas.width;
        lastCorrectedCleared = true;
      }
      return;
    }
    const pic = displayedPicture(record);
    const key = JSON.stringify([record.source_id, record.map_id, record.calibration_revision,
      bounds, pic.kind, pic.frame?.seq ?? null, pic.stale]);
    const image = pic.frame?.image ?? null;
    if (lastCorrectedKey === key && lastCorrectedImage === image) return;
    lastCorrectedKey = key;
    lastCorrectedImage = image;
    canvas.width = 480; canvas.height = 270;
    const ctx = canvas.getContext("2d");
    const transform = fitTransform(bounds, canvas.width, canvas.height, 8);
    const toPx = (x, y) => { const p = project(transform, x, y); return {x: p.px, y: p.py}; };
    drawTopDown(ctx, record, bounds, toPx, canvas.width, canvas.height, 1, 0, pic);
  }
  function redraw() {
    if (!view.map && view.siteMap) draw();
    drawCorrected();
    const status = el("map-display-status");
    const observed = planeFrame()?.observedFraction;
    const nextStatus = view.displayMode === "camera"
      ? cameraFrame ? "교정 전 · 카메라 원본" : "원본 영상 대기 · 신선한 프레임 없음"
      : view.displayMode === "overlay" && !calibration()
        ? "교정 영상 없음 · 2D 좌표 표시" : view.displayMode === "overlay"
          ? `공유 map 좌표 · m · 영상 유효 영역 ${Number.isFinite(observed)
            ? `${Math.round(observed * 100)}%` : "미확인"}` : "공유 map 좌표 · m";
    if (status && status.textContent !== nextStatus) status.textContent = nextStatus;
    updateStamp();
  }

  function setCameraFrame(frame) {
    cameraFrame = keepFrame(cameraFrame, frame);
    refreshPlane();
    redraw();
  }
  function bindCamera(visionView) {
    // The calibrated map draws the same authenticated Vision frame; Fleet does not relay image bytes.
    // D-493: the raw frame shows in one place at a time — the rail thumbnail, or the map stage
    // (#map-birdseye) when there is no map or the operator asks for the large view. CSS picks the place.
    const birdseye = el("map-birdseye"), toggle = el("birdseye-toggle"), stage = el("map-stage");
    const mode = el("map-display-mode");
    view.displayMode = mode.value || "overlay";
    const setLive = (url) => {
      birdseye.hidden = !url;
      if (url) birdseye.src = url;
      setOffBy(toggle, url ? "" : "영상 대기");
    };
    const showFrame = () => setLive(cameraFrame?.url);
    const setMode = (value) => {
      view.displayMode = value;
      mode.value = value;
      stage.dataset.view = value === "camera" ? "camera" : "map";
      toggle.setAttribute("aria-pressed", String(value === "camera"));
      showFrame();
      refreshPlane();
      redraw();
    };
    scope.listen(mode, "change", () => setMode(mode.value));
    scope.listen(el("camera-comparison"), "toggle", drawCorrected);
    planes = createPlaneFeed({ scope, visionView, onChange: (reason) => {
      const frame = planes.current(), record = calibration();
      if (reason === "plane-unavailable") {
        keptPlane = null;
      } else if (planeKey && planeKey === keyFor(record) && frame?.source === record.source_id
          && planeCalibration(frame, [record], view.siteMap)) {
        keptPlane = { key: planeKey, frame };
      }
      redraw();
    } });
    setLive(null);
    // 2026-11-14 요청: 끊긴 뒤에도 마지막 프레임을 지도·썸네일에 둔다. 낡음은 바닥 왼쪽 작은
    // 시각 글자(1초마다 갱신)와 반투명으로만 알린다 — 오류 색과는 섞지 않는다.
    stamp = el("map-camera-stamp");
    const goStale = () => {
      if (!cameraFrame) return;
      staleAt = Date.now();
      stage.dataset.cameraStale = "true";
      redraw();
    };
    scope.interval(updateStamp, 1000);
    scope.listen(toggle, "click", () => {
      setMode(view.displayMode === "camera" ? "overlay" : "camera");
      showFrame();
    });
    let cancelMapCameraExpiry = () => {};
    scope.subscribe(() => visionView.onFrame(scope.guard((frame) => {
      cancelMapCameraExpiry();
      if (frame.state !== "live" || !fresh(frame)) {
        goStale(); // 끊김 — 그림을 지우지 않고 마지막 좋은 프레임을 낡은 채로 둔다
        return;
      }
      const prevSeq = cameraFrame?.seq;
      const prevSource = cameraFrame?.source;
      capturedAt = Date.now() - frame.ageMs;
      const wasStale = Boolean(staleAt);
      staleAt = 0;
      delete stage.dataset.cameraStale;
      // D-631: the before-correction picture keeps the camera's original orientation.
      (frame.previewElement || frame.image)?.closest?.(".vision-frame")?.setAttribute("data-turn", "0");
      if (prevSeq == null || prevSeq !== frame.seq || prevSource !== frame.source || wasStale) {
        setCameraFrame(frame);
        showFrame();
      } else {
        cameraFrame = frame;
        refreshPlane();
        updateStamp();
      }
      cancelMapCameraExpiry = scope.timeout(goStale, Math.max(0, FRESH_MS - frame.ageMs));
    })));
  }
  return { calibration, usesPlane, setCalibrations, drawTopDown, setCameraFrame, bindCamera };
}
