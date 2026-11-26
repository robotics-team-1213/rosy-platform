// DOM-free planar geometry for the zone map, in metres. Polygons are arrays of [x, y]. Cutting one polygon
// out of another (Sutherland-Hodgman) measures the shared area exactly for a convex clip and only
// under-measures for a concave one (a stop zone from the site map); it never over-measures.

function pointInPolygon([x, y], polygon) {
  let hit = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    if ((yi > y) !== (yj > y) && x < xi + ((y - yi) * (xj - xi)) / (yj - yi)) hit = !hit;
  }
  return hit;
}

function segmentsCross(a, b, c, d) {
  const side = (p, q, r) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  return side(a, b, c) * side(a, b, d) < 0 && side(c, d, a) * side(c, d, b) < 0;
}

function pointSegmentDistance(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const span = dx * dx + dy * dy;
  const t = span === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

/** Open polyline -> its segments; a closed ring when the first point is repeated at the end. */
function segments(points) {
  return points.slice(1).map((point, index) => [points[index], point]);
}

const ringOf = (polygon) => segments([...polygon, polygon[0]]);

const edgeDistance = (point, polygon) => Math.min(...ringOf(polygon).map(([a, b]) => pointSegmentDistance(point, a, b)));

const signedArea = (polygon) => ringOf(polygon).reduce((sum, [a, b]) => sum + (a[0] * b[1] - b[0] * a[1]) / 2, 0);

/** ``subject`` cut by the convex ``clip`` polygon (Sutherland-Hodgman); empty when they share no area. */
function clipped(subject, clip) {
  const fence = signedArea(clip) < 0 ? [...clip].reverse() : clip;
  let output = subject;
  for (let index = 0; index < fence.length && output.length; index += 1) {
    const [a, b] = [fence[index], fence[(index + 1) % fence.length]];
    const input = output;
    output = [];
    const inside = (p) => (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0;
    let previous = input[input.length - 1];
    for (const current of input) {
      if (inside(current)) {
        if (!inside(previous)) output.push(lineCrossing(previous, current, a, b));
        output.push(current);
      } else if (inside(previous)) {
        output.push(lineCrossing(previous, current, a, b));
      }
      previous = current;
    }
  }
  return output;
}

/** Where the segment p->q meets the infinite line a->b. */
function lineCrossing([px, py], [qx, qy], [ax, ay], [bx, by]) {
  const denominator = (ax - bx) * (py - qy) - (ay - by) * (px - qx);
  const t = denominator === 0 ? 0 : ((ax - px) * (py - qy) - (ay - py) * (px - qx)) / denominator;
  return [ax + t * (bx - ax), ay + t * (by - ay)];
}

const OVERLAP_M2 = 1e-6;

/** The interiors share more than a sliver of area. Each cut-out lies inside both shapes, so a measured
 * area is always a real overlap: a concave clip (a stop zone from the site map) only under-measures, it
 * never invents area, and the other direction and the vertex and edge tests make up for it. Those tests
 * alone miss two rectangles that overlap in a third rectangle (no vertex inside, edges meeting in
 * T-junctions). Two areas that only touch along an edge do not overlap. */
export function interiorsOverlap(a, b) {
  return Math.abs(signedArea(clipped(a, b))) > OVERLAP_M2
    || Math.abs(signedArea(clipped(b, a))) > OVERLAP_M2
    || a.some((point) => pointInPolygon(point, b) && edgeDistance(point, b) > 1e-6)
    || b.some((point) => pointInPolygon(point, a) && edgeDistance(point, a) > 1e-6)
    || ringOf(a).some(([p, q]) => ringOf(b).some(([r, s]) => segmentsCross(p, q, r, s)));
}

/** ``inner`` lies wholly in ``outer``: cut out, it keeps its whole area. Vertex tests wobble on a shared edge. */
export function contains(outer, inner) {
  return Math.abs(Math.abs(signedArea(clipped(inner, outer))) - Math.abs(signedArea(inner))) <= OVERLAP_M2;
}

/** 0 when the polyline enters the polygon, else the gap between them. */
export function polylinePolygonGap(polyline, polygon) {
  if (polyline.some((point) => pointInPolygon(point, polygon))) return 0;
  let gap = Infinity;
  const ring = ringOf(polygon);
  for (const [a, b] of segments(polyline)) {
    for (const [c, d] of ring) {
      if (segmentsCross(a, b, c, d)) return 0;
      gap = Math.min(gap, pointSegmentDistance(a, c, d), pointSegmentDistance(b, c, d),
        pointSegmentDistance(c, a, b), pointSegmentDistance(d, a, b));
    }
  }
  return gap;
}

export function centroid(polygon) {
  const n = polygon.length;
  return polygon.reduce((sum, [x, y]) => [sum[0] + x / n, sum[1] + y / n], [0, 0]);
}

/** The robot body and cargo tray at a place pose (profile geometry: x forward, y left). */
export function bodyPolygon(place, vehicle) {
  const c = Math.cos(place.yaw);
  const s = Math.sin(place.yaw);
  return [[vehicle.frontM, vehicle.halfWidthM], [vehicle.frontM, -vehicle.halfWidthM],
    [vehicle.rearM, -vehicle.halfWidthM], [vehicle.rearM, vehicle.halfWidthM]]
    .map(([dx, dy]) => [place.x + dx * c - dy * s, place.y + dx * s + dy * c]);
}
