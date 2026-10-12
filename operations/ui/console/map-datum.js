// Shared map origin for the occupancy grid and the metre site view.
// `toPoint` maps map metres into the caller's current user space. Axis direction
// comes from that delta. Strokes stay in user space; labels are device pixels.

export function drawMapDatum(ctx, toPoint, bounds, {css}) {
  const inside = bounds.min_x <= 0 && bounds.max_x >= 0 && bounds.min_y <= 0 && bounds.max_y >= 0;
  const ox = inside ? 0 : bounds.min_x + 0.1;
  const oy = inside ? 0 : bounds.min_y + 0.1;
  const at = toPoint(ox, oy);
  const xStep = toPoint(ox + 0.1, oy);
  const yStep = toPoint(ox, oy + 0.1);
  const transform = ctx.getTransform?.();
  const scale = Math.hypot(transform?.a ?? 1, transform?.b ?? 0) || 1;
  const axisLen = Math.min(40 / scale, ((ctx.canvas?.width || 400) / scale) / 8);
  const tip = (point) => {
    const span = Math.hypot(point.x - at.x, point.y - at.y) || 1;
    return {
      x: at.x + (point.x - at.x) / span * axisLen,
      y: at.y + (point.y - at.y) / span * axisLen,
    };
  };
  const xTip = tip(xStep);
  const yTip = tip(yStep);
  const ink = css("--ink");
  const labels = [{text: "x", x: xTip.x, y: xTip.y}, {text: "y", x: yTip.x, y: yTip.y}];
  if (inside) labels.push({text: "0,0", x: at.x, y: at.y});
  ctx.save();
  ctx.lineWidth = 2 / scale;
  ctx.strokeStyle = ink;
  ctx.fillStyle = ink;
  ctx.beginPath();
  ctx.moveTo(at.x, at.y);
  ctx.lineTo(xTip.x, xTip.y);
  ctx.moveTo(at.x, at.y);
  ctx.lineTo(yTip.x, yTip.y);
  ctx.stroke();
  if (inside) {
    ctx.beginPath();
    ctx.arc(at.x, at.y, 4 / scale, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
  for (const item of labels) {
    const point = transform?.transformPoint ? transform.transformPoint({x: item.x, y: item.y}) : item;
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = ink;
    ctx.font = window.RosyPalette.canvasFont("micro", "mono");
    ctx.textAlign = item.text === "0,0" ? "right" : "center";
    ctx.textBaseline = "middle";
    ctx.fillText(item.text, point.x, point.y);
    ctx.restore();
  }
  return labels;
}
