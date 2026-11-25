import test from "node:test";
import assert from "node:assert/strict";

import { distortImagePoint, warpMesh } from "../../../../applications/fleet/web/map/camera-warp.js";
import { colorForErrorM, formatRecalStatus, seedPointsFromFit, snapMapPoint } from "../../../../applications/fleet/web/calibration/manual-fit-math.js";

test("warpMesh applies forward radial distortion when lensProfile is provided", () => {
  const lp = {
    model: "pinhole",
    K: [[500, 0, 320], [0, 500, 180], [0, 0, 1]],
    D: [-0.25, 0.05, 0, 0, 0],
    image_size: [640, 360],
  };
  const h = [100, 0, 320, 0, -100, 180, 0, 0, 1];
  const bounds = { min_x: -1, max_x: 1, min_y: -0.5, max_y: 0.5 };
  const meshRaw = warpMesh(h, bounds, 4, 2, null);
  const meshDist = warpMesh(h, bounds, 4, 2, lp);
  assert.equal(meshRaw.length, meshDist.length);
  const [xu, yu] = meshRaw[0].image[0];
  const [xd, yd] = meshDist[0].image[0];
  assert.ok(Math.hypot(xd - xu, yd - yu) > 1.0);
  const [rx, ry] = distortImagePoint(320, 180, lp);
  assert.deepEqual([rx, ry], [320, 180]);
});

test("snapMapPoint snaps to nearest polyline vertex within threshold and colors error tiers", () => {
  const ls = {
    bounds: { min_x: -1, max_x: 1, min_y: -0.5, max_y: 0.5 },
    polylines: [{ points: [[0.5, -0.2], [0.9, 0.3]] }],
  };
  assert.deepEqual(snapMapPoint(0.52, -0.19, ls, 0.05), { x: 0.5, y: -0.2, snapped: true });
  assert.deepEqual(snapMapPoint(0.0, 0.0, ls, 0.05), { x: 0.0, y: 0.0, snapped: false });
  assert.equal(colorForErrorM(0.01), "#2ea043");
  assert.equal(colorForErrorM(0.03), "#d29922");
  assert.equal(colorForErrorM(0.08), "#f85149");
  const seeded = seedPointsFromFit({
    mapToImage: [100, 0, 320, 0, -100, 180, 0, 0, 1],
    image: { width: 640, height: 360 },
  }, ls, 640, 360);
  assert.equal(seeded.length, 6);
});

test("formatRecalStatus summarizes pending candidate and rollback states", () => {
  assert.equal(formatRecalStatus(null), null);
  assert.equal(formatRecalStatus({ state: "IDLE", pending_candidate: null }), null);
  const msg = formatRecalStatus({
    state: "NEEDS_OPERATOR",
    pending_candidate: { reason: "drift_exceeds_auto_cap", metrics: { move_m: 0.31, rotation_deg: 2.4, rms_m: 0.004 } },
  });
  assert.match(msg, /31\.0 cm/);
  assert.match(msg, /2\.4°/);
  assert.match(formatRecalStatus({ state: "ROLLED_BACK", reason: "shadow_health_regression" }), /롤백됨/);
});
