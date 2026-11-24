// Pure geometry, top-down lens-aware pixel warp, and loupe helpers for manual calibration workbench.
import { project } from "/console/assets/map-fit.js";
import { distortImagePoint } from "/console/assets/camera-warp.js";

export function colorForErrorM(errM) {
  if (!Number.isFinite(errM)) return "#888888";
  if (errM <= 0.02) return "#2ea043";
  if (errM <= 0.05) return "#d29922";
  return "#f85149";
}

export function snapMapPoint(mapX, mapY, laneSet, thresholdM = 0.06) {
  if (!laneSet) return { x: mapX, y: mapY, snapped: false };
  let best = null, bestD = thresholdM;
  for (const line of laneSet.polylines || []) {
    for (const [px, py] of line.points || []) {
      const d = Math.hypot(px - mapX, py - mapY);
      if (d < bestD) { bestD = d; best = { x: px, y: py, snapped: true }; }
    }
  }
  return best || { x: mapX, y: mapY, snapped: false };
}

export function seedPointsFromFit(fit, laneSet, width, height) {
  if (!fit?.mapToImage || !laneSet?.bounds) return [];
  const b = laneSet.bounds;
  const xs = [b.min_x + 0.15 * (b.max_x - b.min_x), 0.5 * (b.min_x + b.max_x), b.max_x - 0.15 * (b.max_x - b.min_x)];
  const ys = [b.min_y + 0.2 * (b.max_y - b.min_y), b.max_y - 0.2 * (b.max_y - b.min_y)];
  const sx = width / fit.image.width, sy = height / fit.image.height;
  const pairs = [];
  for (const my of ys) {
    for (const mx of xs) {
      const u = project(fit.mapToImage, mx, my);
      if (!u) continue;
      const p = fit.lensProfile ? distortImagePoint(u[0], u[1], fit.lensProfile) : u;
      const px = p[0] * sx, py = p[1] * sy;
      if (px >= 4 && px <= width - 4 && py >= 4 && py <= height - 4) {
        pairs.push({ imagePx: [Number(px.toFixed(1)), Number(py.toFixed(1))], mapM: [Number(mx.toFixed(4)), Number(my.toFixed(4))] });
      }
    }
  }
  return pairs;
}

export function warpTopDownCanvas(ctx, image, mapToImage, layout, scratch, lensProfile = null) {
  const iw = image?.naturalWidth || image?.width || 0;
  const ih = image?.naturalHeight || image?.height || 0;
  if (!iw || !ih || !Array.isArray(mapToImage) || mapToImage.length !== 9) return null;
  scratch.width = iw;
  scratch.height = ih;
  const sctx = scratch.getContext("2d", { willReadFrequently: true });
  sctx.drawImage(image, 0, 0);
  const srcData = sctx.getImageData(0, 0, iw, ih).data;
  const { width: w, height: h, canvasToMap } = layout;
  const dstImg = ctx.createImageData(w, h);
  const dst = dstImg.data;
  const c2m = canvasToMap;
  const [m0, m1, m2, m3, m4, m5, m6, m7, m8] = mapToImage;
  const cxM = (layout.bounds ? 0.5 * (layout.bounds.min_x + layout.bounds.max_x) : 0);
  const cyM = (layout.bounds ? 0.5 * (layout.bounds.min_y + layout.bounds.max_y) : 0);
  const refW = m6 * cxM + m7 * cyM + m8 || 1;
  for (let v = 0; v < h; v += 1) {
    const my = c2m[3] * 0 + c2m[4] * v + c2m[5];
    for (let u = 0; u < w; u += 1) {
      const mx = c2m[0] * u + c2m[1] * v + c2m[2];
      const hw = m6 * mx + m7 * my + m8;
      if (hw * refW <= 1e-9) continue;
      const xu = (m0 * mx + m1 * my + m2) / hw;
      const yu = (m3 * mx + m4 * my + m5) / hw;
      const [rx, ry] = lensProfile ? distortImagePoint(xu, yu, lensProfile) : [xu, yu];
      const ix = Math.round(rx), iy = Math.round(ry);
      if (ix < 0 || iy < 0 || ix >= iw || iy >= ih) continue;
      const si = (iy * iw + ix) * 4, di = (v * w + u) * 4;
      dst[di] = srcData[si]; dst[di + 1] = srcData[si + 1]; dst[di + 2] = srcData[si + 2]; dst[di + 3] = 255;
    }
  }
  return dstImg;
}

export function drawLoupe(ctx, image, imgX, imgY, canvasW, zoom = 4, size = 112) {
  const iw = image?.naturalWidth || image?.width || 0;
  const ih = image?.naturalHeight || image?.height || 0;
  if (!iw || !ih || !Number.isFinite(imgX) || !Number.isFinite(imgY)) return;
  const pad = 10, x0 = canvasW - size - pad, y0 = pad;
  const srcSpan = size / zoom;
  ctx.save();
  ctx.fillStyle = "#111113";
  ctx.fillRect(x0 - 2, y0 - 2, size + 4, size + 4);
  ctx.beginPath();
  ctx.rect(x0, y0, size, size);
  ctx.clip();
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(image, imgX - srcSpan / 2, imgY - srcSpan / 2, srcSpan, srcSpan, x0, y0, size, size);
  ctx.strokeStyle = "#58a6ff";
  ctx.lineWidth = 1;
  const cx = x0 + size / 2, cy = y0 + size / 2;
  ctx.beginPath();
  ctx.moveTo(cx - 14, cy); ctx.lineTo(cx + 14, cy);
  ctx.moveTo(cx, cy - 14); ctx.lineTo(cx, cy + 14);
  ctx.stroke();
  ctx.restore();
  ctx.save();
  ctx.strokeStyle = "#f0f6fc";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(x0, y0, size, size);
  ctx.restore();
}
