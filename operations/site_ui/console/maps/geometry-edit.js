// Geometry only: units, domain meaning and editing permissions belong to callers.
function point(value) {
  if (!Array.isArray(value) || value.length !== 2 || !value.every(Number.isFinite))
    throw new Error('유한한 2차원 좌표가 필요합니다');
  return [...value];
}

function vertex(points, index) {
  if (!Number.isInteger(index) || index < 0 || index >= points.length)
    throw new Error('수정할 꼭짓점을 고르세요');
  return points.map(point);
}

export function replaceVertex(points, index, value) {
  const next = vertex(points, index);
  next[index] = point(value);
  return next;
}

export function removeVertex(points, index, minimum = 2) {
  const next = vertex(points, index);
  if (!Number.isInteger(minimum) || minimum < 1 || next.length <= minimum)
    throw new Error('도형에 필요한 최소 꼭짓점 수를 유지하세요');
  return next.filter((_, position) => position !== index);
}

export function mapPoint(svg, view, screenPoint) {
  const at = screenPoint.matrixTransform(svg.getScreenCTM().inverse());
  return point(view.toMap(at.x, at.y));
}
