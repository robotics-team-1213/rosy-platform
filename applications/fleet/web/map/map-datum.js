import {GRID_STEP_M, gridLines} from "./site-layer.js";

export function gridCellOf(x, y, step = GRID_STEP_M) {
  const col = Math.floor(x / step), row = Math.floor(y / step);
  return {col, row, x0: col * step, x1: (col + 1) * step, y0: row * step, y1: (row + 1) * step,
    label: `X${col}·Y${row}`};
}

export function axisOrientation(rot) {
  return ({90: "+X ↓ · +Y →", 180: "+X ← · +Y ↓", 270: "+X ↑ · +Y ←"})[rot] || "+X → · +Y ↑";
}

export function drawMapDatum(ctx, toPoint, bounds, {css, step = GRID_STEP_M, dpr = 1}) {
  const {min_x, max_x, min_y, max_y} = bounds;
  const transform = ctx.getTransform?.();
  const project = (x, y) => {
    const point = toPoint(x, y);
    return transform?.transformPoint?.(point) ?? point;
  };
  const start = project(min_x, min_y), end = project(max_x, max_y);
  const left = Math.min(start.x, end.x), bottom = Math.max(start.y, end.y);
  const width = ctx.canvas?.width ?? Math.max(start.x, end.x) + 32 * dpr;
  const height = ctx.canvas?.height ?? bottom + 32 * dpr;
  const labels = [];
  const pendingLabels = [];
  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.lineWidth = 1;
  ctx.strokeStyle = css("--line-quiet");
  ctx.fillStyle = css("--ink");
  ctx.font = window.RosyPalette.canvasFont("micro", "mono");
  ctx.textBaseline = "middle";
  ctx.beginPath();

  for (const [axis, lo, hi, position] of [
    ["X", min_x, max_x, (m) => project(m, min_y)],
    ["Y", min_y, max_y, (m) => project(min_x, m)],
  ]) {
    if (hi <= lo) continue;
    const first = position(lo), last = position(hi);
    const horizontal = Math.abs(last.x - first.x) > Math.abs(last.y - first.y);
    const along = (m) => position(m)[horizontal ? "x" : "y"] / dpr;
    const edge = horizontal ? Math.min(bottom / dpr, height / dpr - 1) : Math.max(left / dpr, 1);
    const outside = horizontal ? height - bottom >= 30 * dpr : left >= 30 * dpr;
    const sign = (horizontal === outside) ? 1 : -1;
    const point = (m, offset) => horizontal
      ? {x: along(m), y: edge + sign * offset}
      : {x: edge + sign * offset, y: along(m)};
    const line = (a, b) => { ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); };
    const label = (text, m, offset) => {
      const p = point(m, offset);
      labels.push({text, x: p.x, y: p.y});
      const half = horizontal ? (ctx.measureText?.(text)?.width ?? 0) / 2 : 0;
      const x = Math.max(half, Math.min(width / dpr - half, p.x));
      const y = Math.max(6, Math.min(height / dpr - 6, p.y));
      pendingLabels.push([text, x, y, ctx.textAlign]);
    };
    line(point(lo, 0), point(hi, 0));
    ctx.textAlign = horizontal ? "center" : outside ? "right" : "left";
    const pxPerMetre = Math.abs(along(hi) - along(lo)) / (hi - lo);
    const metreStride = Math.max(1, Math.ceil(22 / pxPerMetre));
    for (const m of gridLines(lo, hi, step)) {
      line(point(m, 0), point(m, Number.isInteger(m) ? 5 : 3));
    }
    for (const m of gridLines(lo, hi, metreStride)) label(String(m), m, 12);
    if (pxPerMetre * step >= (horizontal ? 22 : 24)) {
      for (let index = Math.floor(lo / step); index < Math.ceil(hi / step); index += 1) {
        const start = Math.max(lo, index * step), end = Math.min(hi, (index + 1) * step);
        if ((end - start) * pxPerMetre >= 16) label(`${axis}${index}`, (start + end) / 2, horizontal ? 24 : 12);
      }
    }
  }
  ctx.stroke();
  for (const [text, x, y, align] of pendingLabels) {
    ctx.textAlign = align;
    ctx.fillText(text, x, y);
  }
  ctx.restore();
  return labels;
}
