// Markerless start reference geometry. Never used for goals, identity or localization.
import {siteBounds, fitTransform} from './site-layer.js';

export function pointerPose(view, rect, canvas, clientX, clientY) {
  if (!(rect.width > 0 && rect.height > 0 && canvas.width > 0 && canvas.height > 0)) return null;
  const aspect = view.map || canvas;
  const scale = Math.min(rect.width / aspect.width, rect.height / aspect.height);
  const w = aspect.width * scale, h = aspect.height * scale;
  const px = clientX - rect.left - (rect.width-w)/2;
  const py = clientY - rect.top - (rect.height-h)/2;
  if (px<0 || py<0 || px>=w || py>=h) return null;
  if (view.map) {
    const g=view.map;
    return {x:g.origin.x+px/w*g.width*g.resolution, y:g.origin.y+(1-py/h)*g.height*g.resolution};
  }
  const b=siteBounds(view.siteMap);
  if (!b) return null;
  // Live camera picture (D-513 7): undo the drawn turn and calibration, in bitmap pixels.
  const t=fitTransform(b, rect.width, rect.height, 32);
  const point=view.cameraPick ? view.cameraPick(px/w*canvas.width, py/h*canvas.height)
    : {x:(clientX-rect.left-t.ox)/t.scale, y:(t.oy-clientY+rect.top)/t.scale};
  if (!point) return null;
  const track=siteBounds(view.siteMap,0);
  return point.x>=track.min_x && point.x<=track.max_x && point.y>=track.min_y && point.y<=track.max_y ? point : null;
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
