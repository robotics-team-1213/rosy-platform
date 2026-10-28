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

const same = (a, b) => a[0] === b[0] && a[1] === b[1];
function line(points) {
  const next = points.map(point);
  if (next.length < 2 || next.some((p, i) => i && same(p, next[i - 1])))
    throw new Error('서로 다른 점으로 선을 구성하세요');
  return next;
}

export function splitPolyline(points, segmentIndex, value) {
  const next = line(points), at = point(value);
  if (!Number.isInteger(segmentIndex) || segmentIndex < 0 || segmentIndex >= next.length - 1)
    throw new Error('나눌 선분을 고르세요');
  const a = next[segmentIndex], b = next[segmentIndex + 1];
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const distance = Math.hypot(at[0] - a[0], at[1] - a[1]) + Math.hypot(at[0] - b[0], at[1] - b[1]);
  if (Math.abs(distance - length) > 1e-9 * Math.max(1, length) || same(at, next[0]) || same(at, next.at(-1)))
    throw new Error('선 내부의 분할점을 고르세요');
  const first = next.slice(0, segmentIndex + 1), second = next.slice(segmentIndex + 1);
  if (!same(first.at(-1), at)) first.push(at);
  if (!same(second[0], at)) second.unshift([...at]);
  return [line(first), line(second)];
}

export function joinPolylines(first, second, reverseFirst = false, reverseSecond = false) {
  const a = line(first), b = line(second);
  if (reverseFirst) a.reverse();
  if (reverseSecond) b.reverse();
  if (!same(a.at(-1), b[0])) throw new Error('명시적으로 같은 끝점만 연결할 수 있습니다');
  return line([...a, ...b.slice(1)]);
}

export function nearestVertex(value, candidates, radiusPx = 8) {
  const at = point(value), points = candidates.map(point);
  if (!Number.isFinite(radiusPx) || radiusPx < 0) throw new Error('붙이기 화면 거리를 확인하세요');
  let found = null, nearest = radiusPx, tied = false;
  points.forEach((p, i) => {
    const distance = Math.hypot(p[0] - at[0], p[1] - at[1]);
    if (distance < nearest || (found === null && distance <= nearest)) {
      found = i; nearest = distance; tied = false;
    } else if (found !== null && Math.abs(distance - nearest) < 1e-9) tied = true;
  });
  return tied ? null : found;
}
