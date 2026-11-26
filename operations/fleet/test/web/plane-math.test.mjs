import test from "node:test";
import assert from "node:assert/strict";

import { invert3, project } from "../../../../shared/web/plane-math.js";
import * as mapFit from "../../../../applications/fleet/web/shared/map-fit.js";

// 2026-11-26 패널 C-1: the four former copies, kept here verbatim as the reference the shared one replaced.
const legacy = {
  // applications/fleet/web/shared/map-fit.js (invert3, project) and measured-calibration-view.js (invert3x3, same body)
  mapFitInvert(m) {
    const [a, b, c, d, e, f, g, h, i] = m;
    const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
    const det = a * A + b * B + c * C;
    if (!Number.isFinite(det) || Math.abs(det) < 1e-15) return null;
    return [A, -(b * i - c * h), b * f - c * e, B, a * i - c * g, -(a * f - c * d), C, -(a * h - b * g), a * e - b * d].map((v) => v / det);
  },
  mapFitProject(h, x, y) {
    const w = h[6] * x + h[7] * y + h[8];
    if (!(w > 1e-9)) return null;
    return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w];
  },
  // applications/fleet/web/calibration/field-layers.js applyHomography: no horizon check
  fieldApply(h, x, y) {
    const w = h[6] * x + h[7] * y + h[8];
    return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w];
  },
  // applications/calibration/web/grid-projection.js invert3x3 / applyH: nested rows, 1e-18, |w| only
  gridInvert(rows) {
    const [[a, b, c], [d, e, f], [g, i, j]] = rows;
    const c00 = e * j - f * i, c01 = c * i - b * j, c02 = b * f - c * e;
    const det = a * c00 + d * c01 + g * c02;
    if (Math.abs(det) < 1e-18) return null;
    const inv = 1 / det;
    return [[c00 * inv, c01 * inv, c02 * inv], [(f * g - d * j) * inv, (a * j - c * g) * inv, (c * d - a * f) * inv],
      [(d * i - e * g) * inv, (b * g - a * i) * inv, (a * e - b * d) * inv]];
  },
  gridApply(m, x, y) {
    const w = m[2][0] * x + m[2][1] * y + m[2][2];
    if (!Number.isFinite(w) || Math.abs(w) < 1e-12) return null;
    return [(m[0][0] * x + m[0][1] * y + m[0][2]) / w, (m[1][0] * x + m[1][1] * y + m[1][2]) / w];
  },
};
const rows = (m) => [m.slice(0, 3), m.slice(3, 6), m.slice(6, 9)];
const close = (a, b, tol = 1e-9) => a.forEach((v, k) => assert.ok(Math.abs(v - b[k]) <= tol * Math.max(1, Math.abs(b[k])), `${a} vs ${b}`));

// A floor-camera homography (map m -> image px), a cell arm homography (h33 = 1) and a plain affine.
const CASES = [
  [612.4, -48.1, 640.2, 31.7, -598.3, 362.9, 0.0123, -0.0411, 1.0],
  [-1.21e-3, 2.4e-5, 0.43, 1.8e-5, 1.19e-3, -0.38, 2.1e-6, -4.0e-6, 1.0],
  [400, 0, 600, 0, -400, 300, 0, 0, 1],
];
const POINTS = [[0, 0], [0.5, -0.25], [-1.2, 0.7], [320, 240], [12, -3]];

test("the shared invert3 and project equal every former copy on ordinary homographies", () => {
  assert.equal(mapFit.invert3, invert3);
  assert.equal(mapFit.project, project);
  for (const h of CASES) {
    const inv = invert3(h);
    close(inv, legacy.mapFitInvert(h));
    close(inv, legacy.gridInvert(rows(h)).flat());
    for (const [x, y] of POINTS) {
      for (const m of [h, inv]) {
        const shared = project(m, x, y);
        assert.deepEqual(shared, legacy.mapFitProject(m, x, y));
        if (!shared) continue;
        close(shared, legacy.fieldApply(m, x, y));
        close(shared, legacy.gridApply(rows(m), x, y));
      }
    }
    const [u, v] = project(h, 0.3, 0.2);
    close(project(inv, u, v), [0.3, 0.2]);
  }
});

test("differences the copies had are settled by the strictest rule", () => {
  // Horizon: a point behind the camera (w <= 1e-9) is not on screen. field-layers drew it mirrored, grid-projection too.
  const behind = [1, 0, 0, 0, 1, 0, 0, 0, -1];
  assert.equal(project(behind, 2, 3), null);
  assert.deepEqual(legacy.fieldApply(behind, 2, 3), [-2, -3]);
  assert.deepEqual(legacy.gridApply(rows(behind), 2, 3), [-2, -3]);
  // w = 0: field-layers gave Infinity, the shared one gives no point.
  const horizon = [1, 0, 0, 0, 1, 0, 1, 0, 0];
  assert.equal(project(horizon, 0, 5), null);
  assert.ok(!Number.isFinite(legacy.fieldApply(horizon, 0, 5)[1]));
  // Singular threshold: |det| between 1e-18 and 1e-15 is singular now; grid-projection inverted it.
  const tiny = [1e-6, 0, 0, 0, 1e-6, 0, 0, 0, 1e-4];
  assert.equal(invert3(tiny), null);
  assert.ok(legacy.gridInvert(rows(tiny)));
  // Shape and values: grid-projection read any rows, measured-calibration-view refused strings; the shared one refuses both.
  assert.equal(invert3([1, 0, 0, 0, 1, 0, 0, 0]), null);
  assert.equal(invert3(["1", 0, 0, 0, 1, 0, 0, 0, 1]), null);
  assert.equal(invert3([1, 0, 0, 0, 1, 0, 0, 0, Number.NaN]), null);
  assert.equal(invert3(null), null);
  assert.equal(invert3(mapFit.flatMatrix([[1, 2], [3, 4], [5, 6]])), null);
  assert.deepEqual(invert3(mapFit.flatMatrix(rows(CASES[2]))), invert3(CASES[2]));
});
