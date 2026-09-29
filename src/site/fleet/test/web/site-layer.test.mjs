import test from "node:test";
import assert from "node:assert/strict";

import {
  classifySightings, siteBounds, canvasSizeFor, fitTransform, project, gridLines,
  SIGHTING_STALE_MS, SIGHTING_HIDE_MS,
} from "../../fleet/server/web/site-layer.js";

const row = (changes) => ({
  robot_id: "rosy-pinky-8kcn", x: 1, y: 0.5, yaw: 0, captured_at: 10, age_ms: 200,
  stale: false, source_id: "ceiling_north", ...changes,
});

test("fresh, stale and expired sightings are classified by age", () => {
  const out = classifySightings({ sightings: [
    row({ robot_id: "a", age_ms: 100 }),
    row({ robot_id: "b", age_ms: SIGHTING_STALE_MS + 1 }),
    row({ robot_id: "c", age_ms: SIGHTING_HIDE_MS + 1 }),
    row({ robot_id: "d", age_ms: 1500, stale: true }),
  ] });
  assert.deepEqual(out.map((s) => [s.robot_id, s.state]),
    [["a", "fresh"], ["b", "stale"], ["d", "stale"]]);
});

test("only the latest sighting per robot is kept and malformed rows are dropped", () => {
  const out = classifySightings({ sightings: [
    row({ captured_at: 5, x: 0 }),
    row({ captured_at: 9, x: 2 }),
    row({ robot_id: "bad", x: "1" }),
    null,
  ] });
  assert.equal(out.length, 1);
  assert.equal(out[0].x, 2);
  assert.deepEqual(classifySightings(null), []);
});

test("site bounds cover every rectangle with a margin", () => {
  const b = siteBounds({ maps: [
    { polygon_m: [[0, 0], [4, 0], [4, 2], [0, 2]] },
    { polygon_m: [[4, 0], [6, 0], [6, 1], [4, 1]] },
  ] }, 0.5);
  assert.deepEqual(b, { min_x: -0.5, min_y: -0.5, max_x: 6.5, max_y: 2.5 });
  assert.equal(siteBounds({ maps: [] }), null);
  assert.equal(siteBounds(null), null);
});

test("fit keeps metres square and flips y so +y points up the canvas", () => {
  const bounds = { min_x: 0, min_y: 0, max_x: 4, max_y: 2 };
  const { width, height } = canvasSizeFor(bounds, 1000);
  assert.deepEqual([width, height], [1000, 500]);
  const t = fitTransform(bounds, width, height, 50);
  const origin = project(t, 0, 0);
  const corner = project(t, 4, 2);
  assert.equal(t.scale, 200);
  assert.deepEqual(origin, { px: 100, py: 450 });
  assert.deepEqual(corner, { px: 900, py: 50 });
});

test("grid lines land on 0.5 m multiples inside the range", () => {
  assert.deepEqual(gridLines(-0.25, 1.25), [0, 0.5, 1]);
  assert.deepEqual(gridLines(0, 1), [0, 0.5, 1]);
});
