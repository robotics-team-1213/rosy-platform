// D-513 7 / D-515 카메라 그림 경로 (map-view.js 에서 분리). 실영상에 맞는 보정 고르기, 위에서 본
// 그림 펴기, 크게 보기·썸네일 회전, Vision 프레임 연결. 지도 그리기는 map-view.js 가 가지고
// draw hook 과 toPx 투영을 넘긴다.

import { mapUpTurn, quarterTurn } from "./site-layer.js";
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

export function createCameraBackdrop({ scope, el, view, draw }) {
  let cameraFrame = null;
  let calibrations = [];
  // D-560: Vision's map plane is the picture; the D-515 raw warp is only the fallback.
  let planes = null;
  const planeFrame = () => planes?.current() ?? null;
  const setCalibrations = (rows) => { calibrations = rows; };
  const usesPlane = () => Boolean(planeCalibration(planeFrame(), calibrations, view.siteMap));
  const calibration = () => planeCalibration(planeFrame(), calibrations, view.siteMap)
    || cameraMapCalibration(cameraFrame, calibrations, view.siteMap);
  function drawTopDown(ctx, record, bounds, toPx, width, height, dpr, rot) {
    if (!usesPlane()) {
      drawCameraTopDown(ctx, cameraFrame.image, record, bounds, toPx, width, height, dpr, rot);
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
  const redraw = () => { if (!view.map && view.siteMap) draw(); };

  function setCameraFrame(frame) {
    cameraFrame = frame?.state === "live" ? frame : null;
    redraw();
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
    planes = createPlaneFeed({ scope, visionView, onChange: redraw });
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
      if (frame.state !== "live" || !fresh(frame)) {
        lastFrame = null; setCameraFrame(null); setLive(null); return;
      }
      lastFrame = frame;
      // 레일 썸네일도 같은 회전 — 모서리 편집 중에는 CSS 가 원본으로 둔다(styles.css .vision-frame[data-turn]).
      frame.image?.closest?.(".vision-frame")?.setAttribute("data-turn", String(frameTurn(frame)));
      setCameraFrame(frame);
      showFrame();
      // Ask Vision only when the site view can draw it (no grid map, a site map, a calibration on it).
      planes.refresh(!view.map && planeCalibrationsFor(calibrations, view.siteMap, frame.source).length > 0);
      cancelMapCameraExpiry = scope.timeout(() => { lastFrame = null; setCameraFrame(null); setLive(null); }, Math.max(0, 3000 - frame.ageMs));
    })));
  }
  return { calibration, usesPlane, setCalibrations, drawTopDown, setCameraFrame, bindCamera };
}
