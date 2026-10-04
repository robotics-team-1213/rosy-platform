// Union viewport control rectangles into disjoint holes: evenodd must not refill intersections.
export function disjointRectangles(rectangles, width = Infinity, height = Infinity) {
  const rects = rectangles.filter(r => [r.left, r.top, r.right, r.bottom].every(Number.isFinite))
    .map(r => ({left: Math.max(0, r.left), top: Math.max(0, r.top), right: Math.min(width, r.right), bottom: Math.min(height, r.bottom)}))
    .filter(r => r.right > r.left && r.bottom > r.top);
  const edges = [...new Set(rects.flatMap(r => [r.top, r.bottom]))].sort((a, b) => a - b);
  const pieces = [];
  for (let i = 1; i < edges.length; i++) {
    const top = edges[i - 1], bottom = edges[i];
    const spans = rects.filter(r => r.top < bottom && r.bottom > top)
      .map(r => [r.left, r.right]).sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const [left, right] of spans) {
      const previous = merged.at(-1);
      if (previous && left <= previous[1]) previous[1] = Math.max(previous[1], right);
      else merged.push([left, right]);
    }
    for (const [left, right] of merged) pieces.push({left, top, right, bottom});
  }
  return pieces;
}
