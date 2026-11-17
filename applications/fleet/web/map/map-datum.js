// Shared bottom-left coordinate triad (x/y directions + 0.5 m scale) for occupancy grid & site views.
// `toPoint` maps map metres into caller user space; we sample basis vectors into device pixels
// so the arrows stay anchored at bottom-left while rotating faithfully with siteViewTurn.
// All ctx.stroke() calls run before ctx.fillText() so PAINT_LOG line-before-text invariants hold.

function unitVec(dx, dy, fallback) {
  const len = Math.hypot(dx, dy);
  return len > 1e-6 && Number.isFinite(len) ? {x: dx / len, y: dy / len} : fallback;
}

export function drawMapDatum(ctx, toPoint, bounds, {css, insetBottom = 16, insetLeft = 14, hoverWorld = null} = {}) {
  const inside = bounds.min_x <= 0 && bounds.max_x >= 0 && bounds.min_y <= 0 && bounds.max_y >= 0;
  const cx = (bounds.min_x + bounds.max_x) / 2;
  const cy = (bounds.min_y + bounds.max_y) / 2;
  const transform = ctx.getTransform?.();
  const toDevice = (x, y) => {
    const pt = toPoint(x, y);
    return transform?.transformPoint ? transform.transformPoint(pt) : pt;
  };
  const d0 = toDevice(cx, cy);
  const dx = toDevice(cx + 0.5, cy);
  const dy = toDevice(cx, cy + 0.5);
  const ux = unitVec(dx.x - d0.x, dx.y - d0.y, {x: 1, y: 0});
  const uy = unitVec(dy.x - d0.x, dy.y - d0.y, {x: 0, y: -1});
  const halfMetrePx = Math.hypot(dx.x - d0.x, dx.y - d0.y);

  const canvasW = ctx.canvas?.width || 800;
  const canvasH = ctx.canvas?.height || 600;
  const rect = typeof ctx.canvas?.getBoundingClientRect === "function" ? ctx.canvas.getBoundingClientRect() : null;
  const cssScale = rect?.width > 0 ? canvasW / rect.width : 1;
  const fontScale = Math.max(1, cssScale);

  const ink = css("--ink");
  const quietInk = css("--ink-quiet");
  const primary = css("--series-primary");
  const goal = css("--series-goal");
  const scrim = css("--scrim");
  const line = css("--surface-line");

  const arm = Math.round(24 * fontScale);
  const labelReach = arm + Math.round(9 * fontScale);
  const rx = {x: ux.x * labelReach, y: ux.y * labelReach};
  const ry = {x: uy.x * labelReach, y: uy.y * labelReach};
  const minDx = Math.min(0, rx.x, ry.x);
  const maxDx = Math.max(0, rx.x, ry.x);
  const minDy = Math.min(0, rx.y, ry.y);
  const maxDy = Math.max(0, rx.y, ry.y);

  const padX = Math.round(12 * fontScale);
  const padY = Math.round(10 * fontScale);
  const scaleLabel = Number.isFinite(halfMetrePx) && halfMetrePx >= 18 * fontScale && halfMetrePx <= 90 * fontScale
    ? {metres: "0.5 m", len: Math.round(halfMetrePx)}
    : null;
  const coordNote = hoverWorld && Number.isFinite(hoverWorld.x) && Number.isFinite(hoverWorld.y)
    ? `${hoverWorld.x.toFixed(2)}, ${hoverWorld.y.toFixed(2)} m`
    : (inside ? "0,0 기준 · m" : "map · m");
  const triadW = (maxDx - minDx) + padX * 2;
  const scaleW = scaleLabel ? scaleLabel.len + padX : 0;
  const boxW = Math.min(canvasW - 16, Math.max(triadW + scaleW, Math.round(138 * fontScale)));
  const footerH = Math.round(18 * fontScale);
  const triadH = (maxDy - minDy) + padY * 2;
  const boxH = triadH + footerH;

  const boxLeft = Math.max(8, Math.min(canvasW - boxW - 8, Math.round(insetLeft * cssScale)));
  const boxBottom = Math.max(boxH + 8, Math.min(canvasH - 8, Math.round(canvasH - insetBottom * cssScale)));
  const boxTop = boxBottom - boxH;
  const ox = boxLeft + padX - minDx;
  const oy = boxTop + padY - minDy;

  const xTip = {x: ox + ux.x * arm, y: oy + ux.y * arm};
  const yTip = {x: ox + uy.x * arm, y: oy + uy.y * arm};
  const labels = [
    {text: "x", x: ox + rx.x, y: oy + rx.y},
    {text: "y", x: ox + ry.x, y: oy + ry.y},
  ];
  const originCaptionPt = {x: boxLeft + padX, y: boxBottom - Math.round(9 * fontScale)};
  if (inside) labels.push({text: "0,0", x: originCaptionPt.x, y: originCaptionPt.y});

  // 1) Optional subtle center world-origin tick (no floating text over roads/zones)
  if (inside) {
    const oDev = toDevice(0, 0);
    if (Number.isFinite(oDev.x) && Number.isFinite(oDev.y)) {
      const tick = Math.round(4 * fontScale);
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalAlpha = 0.45;
      ctx.strokeStyle = quietInk;
      ctx.lineWidth = Math.max(1, fontScale);
      ctx.beginPath();
      ctx.moveTo(oDev.x - tick, oDev.y);
      ctx.lineTo(oDev.x + tick, oDev.y);
      ctx.moveTo(oDev.x, oDev.y - tick);
      ctx.lineTo(oDev.x, oDev.y + tick);
      ctx.stroke();
      ctx.restore();
    }
  }

  // 2) HUD scrim card (fillRect/strokeRect before all strokes & text)
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = scrim;
  ctx.fillRect?.(boxLeft, boxTop, boxW, boxH);
  ctx.strokeStyle = line;
  ctx.lineWidth = Math.max(1, fontScale * 0.8);
  ctx.strokeRect?.(boxLeft, boxTop, boxW, boxH);

  // 3) Axis arrows + arrowheads + scale tick — all stroke() before any fillText()
  const head = Math.round(5 * fontScale);
  const drawAxis = (tip, dir, colour) => {
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.lineTo(tip.x, tip.y);
    const backX = -dir.x, backY = -dir.y;
    const perpX = -dir.y, perpY = dir.x;
    ctx.moveTo(tip.x, tip.y);
    ctx.lineTo(tip.x + (backX * 0.85 + perpX * 0.5) * head, tip.y + (backY * 0.85 + perpY * 0.5) * head);
    ctx.moveTo(tip.x, tip.y);
    ctx.lineTo(tip.x + (backX * 0.85 - perpX * 0.5) * head, tip.y + (backY * 0.85 - perpY * 0.5) * head);
    ctx.strokeStyle = colour;
    ctx.lineWidth = Math.max(1.6, 1.8 * fontScale);
    ctx.stroke();
  };
  drawAxis(xTip, ux, primary);
  drawAxis(yTip, uy, goal);

  if (scaleLabel) {
    const sx = boxLeft + boxW - padX - scaleLabel.len;
    const sy = boxTop + padY + Math.round(6 * fontScale);
    const tickH = Math.round(4 * fontScale);
    ctx.beginPath();
    ctx.moveTo(sx, sy - tickH);
    ctx.lineTo(sx, sy);
    ctx.lineTo(sx + scaleLabel.len, sy);
    ctx.lineTo(sx + scaleLabel.len, sy - tickH);
    ctx.strokeStyle = quietInk;
    ctx.lineWidth = Math.max(1.2, 1.2 * fontScale);
    ctx.stroke();
  }

  // 4) Origin dot + all labels (fill/fillText strictly after all strokes)
  ctx.beginPath();
  ctx.arc(ox, oy, Math.max(2.5, 2.8 * fontScale), 0, Math.PI * 2);
  ctx.fillStyle = ink;
  ctx.fill();

  ctx.font = window.RosyPalette.canvasFont("micro", "mono", fontScale);
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";
  ctx.fillStyle = primary;
  ctx.fillText("x", labels[0].x, labels[0].y);
  ctx.fillStyle = goal;
  ctx.fillText("y", labels[1].x, labels[1].y);

  ctx.textAlign = "left";
  ctx.fillStyle = quietInk;
  ctx.fillText(coordNote, originCaptionPt.x, originCaptionPt.y);

  if (scaleLabel) {
    ctx.textAlign = "right";
    ctx.fillStyle = quietInk;
    ctx.fillText(scaleLabel.metres, boxLeft + boxW - padX, boxTop + padY + Math.round(16 * fontScale));
  }
  ctx.restore();
  return labels;
}
