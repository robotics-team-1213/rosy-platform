// Markerless start reference geometry. Never used for goals, identity or localization.

// D-540 5: a click on the install top-down picture (canvas, object-fit: contain) becomes a map
// pose only inside the drawn picture and inside the track bounds; the letterbox, the layout's
// margin and a degenerate transform give no pose.
export function picturePose(rect, size, canvasToMap, bounds, clientX, clientY) {
  if (!canvasToMap || !bounds || !(size.width > 0 && size.height > 0)) return null;
  const scale = Math.min(rect.width / size.width, rect.height / size.height);
  if (!(scale > 0)) return null;
  const px = (clientX - rect.left - (rect.width - size.width * scale) / 2) / scale;
  const py = (clientY - rect.top - (rect.height - size.height * scale) / 2) / scale;
  if (!(px >= 0 && py >= 0 && px < size.width && py < size.height)) return null;
  const h = canvasToMap, w = h[6] * px + h[7] * py + h[8];
  const x = (h[0] * px + h[1] * py + h[2]) / w, y = (h[3] * px + h[4] * py + h[5]) / w;
  if (!(w > 1e-9) || !Number.isFinite(x) || !Number.isFinite(y)) return null;
  return x >= bounds.min_x && x <= bounds.max_x && y >= bounds.min_y && y <= bounds.max_y ? { x, y } : null;
}

export function drawStartPointMarks(ctx, toPx, rows, maps, color, lineWidth) {
  for (const row of rows || []) {
    if (!row.valid || !maps.includes(row.map_id)) continue;
    const p=toPx(row.x,row.y), q=toPx(row.x+.15*Math.cos(row.yaw),row.y+.15*Math.sin(row.yaw));
    const left=toPx(row.x+.11*Math.cos(row.yaw+.25),row.y+.11*Math.sin(row.yaw+.25));
    const right=toPx(row.x+.11*Math.cos(row.yaw-.25),row.y+.11*Math.sin(row.yaw-.25));
    ctx.save(); ctx.strokeStyle=color; ctx.lineWidth=lineWidth;
    ctx.beginPath(); ctx.arc(p.x,p.y,lineWidth*4,0,2*Math.PI); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(p.x,p.y); ctx.lineTo(q.x,q.y);
    ctx.moveTo(left.x,left.y); ctx.lineTo(q.x,q.y); ctx.lineTo(right.x,right.y); ctx.stroke(); ctx.restore();
  }
}
