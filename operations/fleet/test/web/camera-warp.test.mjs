import assert from "node:assert/strict";
import test from "node:test";
import { affineFromTriangles, warpMesh } from "../../fleet/server/web/camera-warp.js";
import { project } from "../../fleet/server/web/map-fit.js";

// 2026-10-07 site refit (paint-f81a872f5cd8): map_v2_fleet ±1.405 × ±0.63 m on a 1280×720 frame.
const H = [198.7684013, 60.88816412, 358.4076331, -26.40441669, -261.6040215, 248.6616531,
  -0.1057708784, 0.07516692745, 0.6835707836];
const BOUNDS = { min_x: -1.405, max_x: 1.405, min_y: -0.63, max_y: 0.63 };

test("the mesh covers the site rectangle with paired map and image corners", () => {
  const mesh = warpMesh(H, BOUNDS, 24, 12);
  assert.equal(mesh.length, 24 * 12 * 2);
  for (const tri of mesh.slice(0, 20)) {
    tri.map.forEach(([x, y], k) => {
      const p = project(H, x, y);
      assert.ok(Math.abs(p[0] - tri.image[k][0]) < 1e-9 && Math.abs(p[1] - tri.image[k][1]) < 1e-9);
    });
  }
  // The measured frame cuts the far corner off: (1.405, -0.63) lands below the 720 px frame.
  const corner = project(H, 1.405, -0.63);
  assert.ok(corner[1] > 720, corner);
});

test("triangles behind the horizon are dropped, bad input gives no mesh", () => {
  const horizon = [1, 0, 0, 0, 1, 0, 0, 1, 0]; // w = y: the y ≤ 0 half is behind the camera
  // Rows at y = -1, 0, 1, 2, 3: only the cells between y = 1 and y = 3 have every corner in front.
  const mesh = warpMesh(horizon, { min_x: 0, max_x: 1, min_y: -1, max_y: 3 }, 2, 4);
  assert.equal(mesh.length, 2 * 2 * 2);
  assert.ok(mesh.every((tri) => tri.map.every(([, y]) => y > 0)));
  assert.deepEqual(warpMesh(null, BOUNDS), []);
  assert.deepEqual(warpMesh(H, { min_x: 1, max_x: 0, min_y: 0, max_y: 1 }), []);
});

test("the canvas affine sends each image triangle exactly onto its screen triangle", () => {
  const src = [[10, 20], [300, 40], [120, 260]];
  const dst = [[0, 0], [200, 0], [0, 100]];
  const [a, b, c, d, e, f] = affineFromTriangles(src, dst);
  src.forEach(([x, y], k) => {
    assert.ok(Math.abs(a * x + c * y + e - dst[k][0]) < 1e-9);
    assert.ok(Math.abs(b * x + d * y + f - dst[k][1]) < 1e-9);
  });
  assert.equal(affineFromTriangles([[0, 0], [1, 1], [2, 2]], dst), null);
});
