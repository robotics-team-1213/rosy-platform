// D-560 S2: Vision map-plane header, pixel↔map formula, and the two screens' placement of the plane.
import assert from "node:assert/strict";
import test from "node:test";
import { mapToPlane, parsePlaneHeader, planeToMap } from "../../fleet/server/web/shared/vision-view.js";
import { planeAffine, planeCalibration } from "../../fleet/server/web/camera-backdrop.js";
import { fitTransform, project, quarterTurn } from "../../fleet/server/web/site-layer.js";
import { planePixelAt, planeView } from "../../fleet/server/web/shared/site-map-model.js";

const PLANE = { min_x: -0.15, min_y: -0.15, max_x: 6.55, max_y: 3.75, ppm: 400 };
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`);

test("X-Frame-Plane parses five finite numbers with min < max and px_per_m > 0, nothing else", () => {
  assert.deepEqual(parsePlaneHeader("-0.15,-0.15,6.55,3.75,400"), PLANE);
  assert.deepEqual(parsePlaneHeader(" -0.15, -0.15 ,6.55,3.75, 400 "), PLANE);
  for (const bad of [null, undefined, "", "1,2,3,4", "0,0,1,1,400,5", "0,,1,1,400", "0,0,1,1,abc",
    "0,0,1,1,Infinity", "NaN,0,1,1,400", "1,0,1,1,400", "0,1,1,1,400", "2,0,1,1,400",
    "0,0,1,1,0", "0,0,1,1,-400"]) {
    assert.equal(parsePlaneHeader(bad), null, String(bad));
  }
});

test("plane pixel ↔ map follows x = min_x + u/ppm, y = max_y − v/ppm both ways", () => {
  assert.deepEqual(planeToMap(PLANE, 0, 0), { x: -0.15, y: 3.75 });
  const corner = planeToMap(PLANE, 2680, 1560);
  close(corner.x, 6.55); close(corner.y, -0.15);
  for (const [x, y] of [[0, 0], [3.2, 1.8], [6.4, 3.6], [-0.1, 3.7]]) {
    const { u, v } = mapToPlane(PLANE, x, y);
    const back = planeToMap(PLANE, u, v);
    close(back.x, x); close(back.y, y);
  }
});

test("the console lays plane pixels where toPx puts the same map point, with and without a view turn", () => {
  const bounds = { min_x: -0.4, min_y: -0.4, max_x: 6.8, max_y: 4.0 };
  for (const rot of [0, 90, 180, 270]) {
    const side = rot === 90 || rot === 270;
    const fw = side ? 700 : 1200, fh = side ? 1200 : 700;
    const t = fitTransform(bounds, fw, fh, 32);
    const turn = quarterTurn(rot, fw, fh);
    const toPx = (x, y) => { const p = project(t, x, y); return turn.point(p.px, p.py); };
    const [a, b, c, d, e, f] = planeAffine(PLANE, 2680, 1560, toPx);
    for (const [x, y] of [[0, 0], [6.4, 3.6], [1.25, 2.5]]) {
      const { u, v } = mapToPlane(PLANE, x, y);
      const want = toPx(x, y);
      close(a * u + c * v + e, want.x, 1e-6); close(b * u + d * v + f, want.y, 1e-6);
    }
  }
});

test("the site-map tab picks the map point under the click through the plane pixel, with any view turn", () => {
  const size = { width: 2680, height: 1560 };
  const bounds = { min_x: PLANE.min_x, max_x: PLANE.min_x + size.width / PLANE.ppm,
    min_y: PLANE.max_y - size.height / PLANE.ppm, max_y: PLANE.max_y };
  for (const rot of [0, 90, 180, 270]) {
    const { view, field } = planeView(bounds, 800, 480, rot);
    for (const [x, y] of [[0, 0], [6.4, 3.6], [1.25, 2.5]]) {
      const [px, py] = view.toPx(x, y);
      const { u, v } = planePixelAt(field, rot, size, px, py);
      const at = mapToPlane(PLANE, x, y);
      close(u, at.u, 1e-6); close(v, at.v, 1e-6);
      const back = planeToMap(PLANE, u, v);
      close(back.x, x); close(back.y, y);
    }
  }
});

test("the console uses a plane only while fresh and of an approved calibration on this site map", () => {
  const cal = { source_id: "ceiling_north", map_id: "map_v2_fleet", calibration_revision: "paint-7b2" };
  const siteMap = { maps: [{ map_id: "map_v2_fleet" }] };
  const frame = { source: "ceiling_north", calibrationRevision: "paint-7b2", ageMs: 100, plane: PLANE };
  assert.equal(planeCalibration(frame, [cal], siteMap), cal);
  for (const changed of [{ ageMs: 3001 }, { ageMs: NaN }, { ageMs: -1 }, { source: "other" },
    { calibrationRevision: "paint-old" }, { calibrationRevision: null }]) {
    assert.equal(planeCalibration({ ...frame, ...changed }, [cal], siteMap), null);
  }
  assert.equal(planeCalibration(frame, [cal], { maps: [{ map_id: "other" }] }), null);
  assert.equal(planeCalibration(null, [cal], siteMap), null);
});
