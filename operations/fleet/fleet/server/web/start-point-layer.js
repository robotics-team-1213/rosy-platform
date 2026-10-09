// Markerless start reference marks. Never used for goals, identity or localization.

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
