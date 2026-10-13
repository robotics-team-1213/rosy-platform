// D-513 7 / D-515 카메라 그림 경로 (map-view.js 에서 분리). 실영상에 맞는 보정 고르기, 위에서 본
// 그림 펴기, 크게 보기·썸네일 회전, Vision 프레임 연결. 지도 그리기는 map-view.js 가 가지고
// draw hook 과 toPx 투영을 넘긴다.

import { siteBounds, fitTransform, project } from "./site-layer.js";
import { lensesMatch } from "/console/assets/map-fit.js";
import { affineFromTriangles, warpMesh } from "./camera-warp.js";
import { createPlaneFeed, planeCalibration, planeCalibrationsFor, planeToMap } from "/console/assets/vision-view.js";

const FRESH_MS = 3000;

const fresh = (frame) => Number.isFinite(frame.ageMs) && frame.ageMs >= 0 && frame.ageMs <= FRESH_MS;

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
const topDownCache = new Map();
function drawCameraTopDown(ctx, frame, calibration, bounds, toPx, width, height, dpr, rot = 0) {
  const image = frame.image;
  const key = [calibration.source_id, calibration.map_id, calibration.calibration_revision,
    ...calibration.map_to_image, width, height, dpr, rot,
    bounds.min_x, bounds.max_x, bounds.min_y, bounds.max_y].join("|");
  let cached = topDownCache.get(key);
  if (!cached || cached.frame !== frame) {
    const off = document.createElement("canvas");
    off.width = Math.round(width * dpr);
    off.height = Math.round(height * dpr);
    const octx = off.getContext("2d");
    octx.scale(dpr, dpr);
    warpOnto(octx, image, calibration.map_to_image, bounds, toPx);
    cached = { frame, canvas: off };
    topDownCache.set(key, cached);
    if (topDownCache.size > 2) topDownCache.delete(topDownCache.keys().next().value);
  }
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.drawImage(cached.canvas, 0, 0);
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

export function createCameraBackdrop({ scope, el, view, draw }) {
  let cameraFrame = null;
  let calibrations = [];
  // D-560: Vision's map plane is the picture; the D-515 raw warp is only the fallback.
  let planes = null;
  const planeFrame = () => {
    const frame = planes?.current();
    return cameraFrame && fresh(cameraFrame) && frame?.source === cameraFrame.source ? frame : null;
  };
  const setCalibrations = (rows) => { calibrations = rows; redraw(); };
  const calibration = () => cameraMapCalibration(cameraFrame, calibrations, view.siteMap);
  const usesPlane = () => {
    const plane = planeCalibration(planeFrame(), calibrations, view.siteMap);
    return Boolean(plane && plane.calibration_revision === calibration()?.calibration_revision);
  };
  function drawTopDown(ctx, record, bounds, toPx, width, height, dpr, rot) {
    if (!usesPlane()) {
      drawCameraTopDown(ctx, cameraFrame, record, bounds, toPx, width, height, dpr, rot);
      return;
    }
    const { image, plane } = planeFrame();
    const affine = planeAffine(plane, image.naturalWidth, image.naturalHeight, toPx);
    if (!affine) return;
    ctx.save();
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
    status.textContent = ready ? `교정 후 · ${record.map_id} · ${record.calibration_revision || "승인 교정"}`
      : "같은 지도의 승인 교정과 신선한 영상이 필요합니다.";
    if (!ready) { canvas.width = canvas.width; return; }
    if (!el("camera-comparison")?.open) return;
    canvas.width = 480; canvas.height = 270;
    const ctx = canvas.getContext("2d");
    const transform = fitTransform(bounds, canvas.width, canvas.height, 8);
    const toPx = (x, y) => { const p = project(transform, x, y); return {x: p.px, y: p.py}; };
    drawTopDown(ctx, record, bounds, toPx, canvas.width, canvas.height, 1, 0);
  }
  function redraw() {
    if (!view.map && view.siteMap) draw();
    drawCorrected();
    const status = el("map-display-status");
    if (status) status.textContent = view.displayMode === "camera"
      ? cameraFrame ? "교정 전 · 카메라 원본" : "원본 영상 대기 · 신선한 프레임 없음"
      : view.displayMode === "overlay" && !calibration()
        ? "교정 영상 없음 · 2D 좌표 표시" : view.displayMode === "overlay"
          ? `공유 map 좌표 · m · 영상 유효 영역 ${usesPlane() && Number.isFinite(planeFrame()?.observedFraction)
            ? `${Math.round(planeFrame().observedFraction * 100)}%` : "미확인"}` : "공유 map 좌표 · m";
  }

  function setCameraFrame(frame) {
    cameraFrame = frame?.state === "live" ? frame : null;
    redraw();
  }
  function bindCamera(visionView) {
    // The calibrated map draws the same authenticated Vision frame; Fleet does not relay image bytes.
    // D-493: the raw frame shows in one place at a time — the rail thumbnail, or the map stage
    // (#map-birdseye) when there is no map or the operator asks for the large view. CSS picks the place.
    const birdseye = el("map-birdseye"), toggle = el("birdseye-toggle"), stage = el("map-stage");
    const mode = el("map-display-mode");
    view.displayMode = mode.value || "coordinates";
    const setMode = (value) => {
      view.displayMode = value;
      mode.value = value;
      stage.dataset.view = value === "camera" ? "camera" : "map";
      toggle.setAttribute("aria-pressed", String(value === "camera"));
      redraw();
    };
    scope.listen(mode, "change", () => setMode(mode.value));
    scope.listen(el("camera-comparison"), "toggle", drawCorrected);
    planes = createPlaneFeed({ scope, visionView, onChange: redraw });
    const setLive = (url) => {
      birdseye.hidden = !url;
      if (url) birdseye.src = url;
      toggle.disabled = !url;
      if (url) toggle.removeAttribute("reason"); else toggle.setAttribute("reason", "영상 대기");
    };
    setLive(null);
    let lastFrame = null;
    const showFrame = () => setLive(lastFrame?.url);
    scope.listen(toggle, "click", () => {
      setMode(view.displayMode === "camera" ? "coordinates" : "camera");
      showFrame();
    });
    let cancelMapCameraExpiry = () => {};
    scope.subscribe(() => visionView.onFrame(scope.guard((frame) => {
      cancelMapCameraExpiry();
      if (frame.state !== "live" || !fresh(frame)) {
        lastFrame = null; setCameraFrame(null); setLive(null); planes.refresh(false); return;
      }
      lastFrame = frame;
      // D-631: the before-correction picture keeps the camera's original orientation.
      (frame.previewElement || frame.image)?.closest?.(".vision-frame")?.setAttribute("data-turn", "0");
      setCameraFrame(frame);
      showFrame();
      // Ask Vision only when the site view can draw it (no grid map, a site map, a calibration on it).
      planes.refresh(!view.map && planeCalibrationsFor(calibrations, view.siteMap, frame.source).length > 0);
      cancelMapCameraExpiry = scope.timeout(() => {
        lastFrame = null; setCameraFrame(null); setLive(null); planes.refresh(false);
      }, Math.max(0, 3000 - frame.ageMs));
    })));
  }
  return { calibration, usesPlane, setCalibrations, drawTopDown, setCameraFrame, bindCamera };
}
