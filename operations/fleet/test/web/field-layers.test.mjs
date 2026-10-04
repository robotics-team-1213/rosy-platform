import test from "node:test";
import assert from "node:assert/strict";

import {
  LAYER_DEFAULTS, parseLayers, normalizeProposal, quadAspect, configuredSize, aspectMismatch,
  parseFieldSize, homography, applyHomography, rectifiedLayout,
} from "../../fleet/server/web/field-layers.js";

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} vs ${b}`);

test("layer prefs fall back to defaults on missing, broken or foreign storage", () => {
  assert.deepEqual(parseLayers(null), LAYER_DEFAULTS);
  assert.deepEqual(parseLayers("{not json"), LAYER_DEFAULTS);
  assert.deepEqual(parseLayers("[1,2]"), LAYER_DEFAULTS);
  const parsed = parseLayers(JSON.stringify({ grid: false, poses: "no", extra: true }));
  assert.equal(parsed.grid, false);
  assert.equal(parsed.poses, true);
  assert.equal("extra" in parsed, false);
});

test("a proposal is accepted only with four finite corners, confidence and aspect", () => {
  const body = { proposal: {
    corners_normalized: [[0.1, 0.2], [0.9, 0.2], [0.95, 0.9], [-0.1, 0.9]],
    confidence: 0.93, aspect_ratio: 1.8, shape: "rectangle",
  } };
  const p = normalizeProposal(body);
  assert.deepEqual(p.corners[3], [0, 0.9]); // clamped into the image
  assert.equal(p.shape, "rectangle");
  assert.equal(normalizeProposal({ proposal: null }), null);
  assert.equal(normalizeProposal({ proposal: { ...body.proposal, corners_normalized: [[0, 0]] } }), null);
  assert.equal(normalizeProposal({ proposal: { ...body.proposal, confidence: "high" } }), null);
  assert.equal(normalizeProposal({ proposal: { ...body.proposal, aspect_ratio: 0 } }), null);
});

test("quad aspect averages opposite sides", () => {
  close(quadAspect([[0, 0], [200, 0], [200, 100], [0, 100]]), 2);
  close(quadAspect([[10, 0], [90, 0], [100, 50], [0, 50]]), 180 / (2 * Math.hypot(10, 50)));
});

test("configured size comes from the site-map entry that lists the source", () => {
  const siteMap = { maps: [
    { map_id: "a", bounds_m: { min_x: 0, min_y: 0, max_x: 1, max_y: 1 }, sources: [{ source_id: "x" }] },
    { map_id: "b", bounds_m: { min_x: 0, min_y: 0, max_x: 0.182, max_y: 0.0974 }, sources: [{ source_id: "s21" }] },
  ] };
  const size = configuredSize(siteMap, "s21");
  assert.equal(size.mapId, "b");
  close(size.width, 0.182);
  assert.equal(configuredSize({ maps: [] }, "s21"), null);
  assert.equal(configuredSize(null, "s21"), null);
});

test("aspect mismatch ignores orientation and flags a relative gap over tolerance", () => {
  const cfg = { width: 4, height: 2 };
  assert.equal(aspectMismatch(cfg, 2.05).state, "match");
  assert.equal(aspectMismatch(cfg, 0.5).state, "match"); // rotated camera
  const off = aspectMismatch(cfg, 1.2);
  assert.equal(off.state, "mismatch");
  close(off.expected, 2);
  assert.equal(aspectMismatch(null, 1.5).state, "unconfigured");
  assert.equal(aspectMismatch(cfg, Number.NaN).state, "unknown");
});

test("operator W×H accepts only a bounded positive size", () => {
  assert.deepEqual(parseFieldSize("3.6", "1.8"), { width: 3.6, height: 1.8 });
  assert.equal(parseFieldSize("0", "1"), null);
  assert.equal(parseFieldSize("abc", "1"), null);
  assert.equal(parseFieldSize("1", "1000"), null);
});

test("homography maps the four corners exactly and rejects a degenerate quad", () => {
  const src = [[0, 0], [1, 0], [1, 1], [0, 1]];
  const dst = [[10, 20], [300, 40], [340, 260], [0, 240]];
  const h = homography(src, dst);
  src.forEach(([x, y], i) => {
    const [u, v] = applyHomography(h, x, y);
    close(u, dst[i][0], 1e-6);
    close(v, dst[i][1], 1e-6);
  });
  assert.equal(homography(src, [[0, 0], [0, 0], [0, 0], [0, 0]]), null);
});

test("rectified layout keeps the aspect and leaves a masked margin", () => {
  const layout = rectifiedLayout(2, 640, 400, 0.1);
  close(layout.field.width / layout.field.height, 2, 0.02);
  assert.ok(layout.width <= 640 && layout.height <= 400);
  assert.ok(layout.field.x > 0 && layout.field.y > 0);
  assert.equal(layout.width, layout.field.width + 2 * layout.field.x);
  const tall = rectifiedLayout(0.25, 640, 400);
  assert.ok(tall.height <= 400 && tall.field.width < tall.field.height);
});

test("the overhead tracking layer is on by default and can be switched off", () => {
  assert.equal(LAYER_DEFAULTS.tracking, true);
  assert.equal(parseLayers(JSON.stringify({ tracking: false })).tracking, false);
});
