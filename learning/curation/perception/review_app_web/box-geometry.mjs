// Pointer positions and labels always use original image coordinates.
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const rounded = value => Math.round(value * 10) / 10;

export function drawnBox(a, b, width, height) {
  return [clamp(Math.min(a[0], b[0]), 0, width), clamp(Math.min(a[1], b[1]), 0, height),
          clamp(Math.max(a[0], b[0]), 0, width), clamp(Math.max(a[1], b[1]), 0, height)].map(rounded);
}

export function boxHandles([x0, y0, x1, y1]) {
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  return {nw:[x0,y0], n:[cx,y0], ne:[x1,y0], e:[x1,cy],
          se:[x1,y1], s:[cx,y1], sw:[x0,y1], w:[x0,cy]};
}

export function hitBox(boxes, point, tolerance, selected) {
  if (selected !== null && boxes[selected]) {
    const handles = Object.entries(boxHandles(boxes[selected].bbox_xyxy))
      .map(([mode, p]) => ({mode, distance:Math.hypot(p[0]-point[0],p[1]-point[1])}))
      .sort((a,b) => a.distance-b.distance);
    if (handles[0].distance <= tolerance) return {index:selected, mode:handles[0].mode};
  }
  for (let index=boxes.length-1; index>=0; index--) {
    const [x0,y0,x1,y1]=boxes[index].bbox_xyxy;
    if (x0<=point[0] && point[0]<=x1 && y0<=point[1] && point[1]<=y1) return {index,mode:'move'};
  }
  return null;
}

export function dragBox(original, mode, start, current, width, height) {
  let [x0,y0,x1,y1] = original;
  const dx=current[0]-start[0], dy=current[1]-start[1];
  if (mode==='move') {
    const mx=clamp(dx,-x0,width-x1), my=clamp(dy,-y0,height-y1);
    return [x0+mx,y0+my,x1+mx,y1+my].map(rounded);
  }
  if (mode.includes('w')) x0=clamp(x0+dx,0,x1-2);
  if (mode.includes('e')) x1=clamp(x1+dx,x0+2,width);
  if (mode.includes('n')) y0=clamp(y0+dy,0,y1-2);
  if (mode.includes('s')) y1=clamp(y1+dy,y0+2,height);
  return [x0,y0,x1,y1].map(rounded);
}
