// D-515 — 천장 카메라 원본을 지도 미터 좌표의 위에서 본 직사각형으로 편다(표시 전용).
// 2D 캔버스는 원근 변환을 못 하므로 사이트 사각형을 작은 삼각형으로 나누고, 삼각형마다
// 원본 영상의 같은 삼각형을 아핀 변환으로 옮긴다. 순수 함수만 둔다(DOM 없음, node 시험).
import { project } from "./map-fit.js";

// 사이트 사각형(지도 m)을 nx×ny 칸으로 나눈 삼각형 목록. 각 삼각형은 지도 꼭짓점(map)과
// 원본 영상 픽셀 꼭짓점(image)을 같이 갖는다. 지평선 뒤 꼭짓점이 있는 삼각형은 뺀다.
// 영상 밖으로 나가는 꼭짓점은 남긴다 — 그 부분은 그릴 픽셀이 없어 비어 보인다.
export function warpMesh(mapToImage, bounds, nx = 24, ny = 12) {
  if (!Array.isArray(mapToImage) || mapToImage.length !== 9 || !bounds) return [];
  const { min_x: x0, max_x: x1, min_y: y0, max_y: y1 } = bounds;
  if (![x0, x1, y0, y1].every(Number.isFinite) || !(x1 > x0) || !(y1 > y0)) return [];
  const node = (i, j) => {
    const x = x0 + ((x1 - x0) * i) / nx, y = y0 + ((y1 - y0) * j) / ny;
    const p = project(mapToImage, x, y);
    return { map: [x, y], image: p };
  };
  const grid = [];
  for (let j = 0; j <= ny; j++) {
    const row = [];
    for (let i = 0; i <= nx; i++) row.push(node(i, j));
    grid.push(row);
  }
  const triangles = [];
  const push = (a, b, c) => {
    if (a.image && b.image && c.image) {
      triangles.push({ map: [a.map, b.map, c.map], image: [a.image, b.image, c.image] });
    }
  };
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const a = grid[j][i], b = grid[j][i + 1], c = grid[j + 1][i + 1], d = grid[j + 1][i];
      push(a, b, c);
      push(a, c, d);
    }
  }
  return triangles;
}

// 세 점 src → 세 점 dst 로 보내는 캔버스 아핀 [a, b, c, d, e, f]
// (ctx.setTransform(a, b, c, d, e, f): x' = a·x + c·y + e, y' = b·x + d·y + f). 퇴화면 null.
export function affineFromTriangles(src, dst) {
  const [[x0, y0], [x1, y1], [x2, y2]] = src;
  const [[u0, v0], [u1, v1], [u2, v2]] = dst;
  const det = x0 * (y1 - y2) + x1 * (y2 - y0) + x2 * (y0 - y1);
  if (!Number.isFinite(det) || Math.abs(det) < 1e-12) return null;
  const solve = (p0, p1, p2) => [
    (p0 * (y1 - y2) + p1 * (y2 - y0) + p2 * (y0 - y1)) / det,
    (p0 * (x2 - x1) + p1 * (x0 - x2) + p2 * (x1 - x0)) / det,
    (p0 * (x1 * y2 - x2 * y1) + p1 * (x2 * y0 - x0 * y2) + p2 * (x0 * y1 - x1 * y0)) / det,
  ];
  const [a, c, e] = solve(u0, u1, u2);
  const [b, d, f] = solve(v0, v1, v2);
  return [a, b, c, d, e, f];
}
