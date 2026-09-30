import test from "node:test";
import assert from "node:assert/strict";

import {
  flatMatrix, multiply3, invert3, project, scale3, projectPolyline, projectTriangles,
  normalizeMapProposal, reasonText, cutGuidance, fitSummary, pickLanes, topDownLayout,
  parseMapDraft, draftFrom, fieldToMap, retryDelay, MAP_FIT_MAX_TRIES,
} from "../../fleet/server/web/map-fit.js";

test("the field fallback maps the field rectangle onto the map rectangle, y up", () => {
  const bounds = { min_x: -1.405, max_x: 1.405, min_y: -0.63, max_y: 0.63 };
  const field = { x: 20, y: 10, width: 562, height: 252 };
  const h = fieldToMap(bounds, field);
  const tl = project(h, 20, 10);
  const br = project(h, 582, 262);
  close(tl[0], -1.405); close(tl[1], 0.63);
  close(br[0], 1.405); close(br[1], -0.63);
  // Through a homography whose map corners fall outside the image, nothing is clamped.
  const shown = multiply3([400, 0, 400, 0, -400, 300, 0, 0, 1], h);
  assert.ok(project(shown, 20, 10)[0] < 0);
});

test("a busy map-fit read retries after Retry-After, a real error does not", () => {
  assert.equal(retryDelay({ busy: true, retryAfterMs: 1000 }, 0), 1000);
  assert.equal(retryDelay({ busy: true, retryAfterMs: 60000 }, 0), 5000);
  assert.equal(retryDelay({ busy: true }, 0), 1000);
  assert.equal(retryDelay({ busy: true, retryAfterMs: 1000 }, MAP_FIT_MAX_TRIES - 1), null);
  assert.equal(retryDelay(new Error("Vision 응답 500"), 0), null);
});

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} vs ${b}`);

// Map metres -> 1280x720 image: 400 px/m, rotated 180 degrees, centred at (640, 360), mild tilt.
const MAP_TO_IMAGE = [-400, 0, 640, 0, 400, 360, 0.02, 0.01, 1];
const IMAGE_TO_MAP = invert3(MAP_TO_IMAGE);
const rows = (m) => [m.slice(0, 3), m.slice(3, 6), m.slice(6, 9)];

function body(overrides = {}) {
  const fit = {
    image_to_map: rows(IMAGE_TO_MAP), map_to_image: rows(MAP_TO_IMAGE), score: 0.91, precision: 0.96,
    coverage: 0.76, cut_sides: ["-x"], cut_directions: ["west"], side_outside: { "-x": 0.4 },
    rotation_deg: 180, mirrored: false, orientation_margin: 0.3,
  };
  return {
    source: "ceiling-north", frame_seq: 9, frame_age_ms: 40, image: { width: 1280, height: 720 },
    map_frame: "map", accepted: true, proposal: fit, rejected_fit: null, reason: "ok",
    registrar: { version: "paint-register/1", elapsed_ms: 812.4 }, ...overrides,
  };
}

test("3x3 inverse round-trips a map point through the image and back", () => {
  const p = project(MAP_TO_IMAGE, 0.5, -0.25);
  const back = project(IMAGE_TO_MAP, p[0], p[1]);
  close(back[0], 0.5);
  close(back[1], -0.25);
  const identity = multiply3(MAP_TO_IMAGE, IMAGE_TO_MAP);
  identity.forEach((v, i) => close(v / identity[8], [1, 0, 0, 0, 1, 0, 0, 0, 1][i], 1e-9));
  assert.equal(invert3([1, 2, 3, 2, 4, 6, 0, 0, 1]), null); // singular
});

test("points behind the horizon split a polyline instead of wrapping across the image", () => {
  const h = [1, 0, 0, 0, 1, 0, -1, 0, 1]; // w = 1 - x: x >= 1 is behind the camera
  const runs = projectPolyline([[0, 0], [0.5, 0], [2, 0], [3, 0], [0.2, 0.1], [0.1, 0.1]], h);
  assert.equal(runs.length, 2);
  assert.equal(runs[0].length, 2);
  assert.equal(project(h, 1, 0), null);
  const closed = projectPolyline([[0, 0], [0.1, 0], [0.1, 0.1]], [1, 0, 0, 0, 1, 0, 0, 0, 1], true);
  assert.deepEqual(closed[0].at(-1), [0, 0]);
  assert.equal(projectTriangles([[0, 0, 0.5, 0, 2, 0], [0, 0, 0.5, 0, 0.5, 0.5]], h).length, 1);
});

test("an accepted proposal carries both matrices; the display scale follows the decoded image", () => {
  const norm = normalizeMapProposal(body());
  assert.equal(norm.accepted, true);
  assert.deepEqual(norm.fit.cutDirections, ["west"]);
  assert.equal(norm.seq, 9);
  // A 640x360 decoded frame is half the Vision frame: map (0,0) lands at the half-size centre.
  const shown = multiply3(scale3(640 / 1280, 360 / 720), norm.fit.mapToImage);
  const centre = project(shown, 0, 0);
  close(centre[0], 320);
  close(centre[1], 180);
});

test("a rejected fit is reference-only; a malformed or matrix-less accept is not trusted", () => {
  const rejected = normalizeMapProposal(body({
    accepted: false, proposal: null, rejected_fit: body().proposal, reason: "weak paint match (0.62)",
  }));
  assert.equal(rejected.accepted, false);
  assert.ok(rejected.fit);
  assert.equal(normalizeMapProposal(body({ proposal: null })), null);
  assert.equal(normalizeMapProposal(body({ proposal: { ...body().proposal, image_to_map: [[1, 2]] } })), null);
  assert.equal(normalizeMapProposal(body({ image: { width: 0, height: 720 } })), null);
  assert.equal(normalizeMapProposal({}), null);
  const blank = normalizeMapProposal(body({ accepted: false, proposal: null, reason: "no white paint" }));
  assert.equal(blank.fit, null);
  // A rejected fit that carries only coverage and cut sides: guidance yes, nothing to draw.
  const metricsOnly = normalizeMapProposal(body({ accepted: false, proposal: null, reason: "weak paint match (0.5)",
    rejected_fit: { coverage: 0.4, cut_sides: ["-x"], cut_directions: ["west"] } }));
  assert.equal(metricsOnly.fit.mapToImage, null);
  assert.equal(metricsOnly.fit.coverage, 0.4);
  const summary = fitSummary(metricsOnly);
  assert.match(summary.headline, /지도 40% 보임/);
  assert.doesNotMatch(summary.headline, /주황 선/);
  assert.match(summary.guidance, /서쪽으로/);
});

test("reasons and cut sides become Korean operator guidance", () => {
  assert.equal(reasonText("ok"), "맞춤 통과");
  assert.equal(reasonText("no white paint"), "흰 차선 페인트가 보이지 않습니다");
  assert.equal(reasonText("weak paint match (0.62)"), "페인트 일치가 약합니다 (weak paint match (0.62))");
  assert.match(reasonText("image is mirrored; check the camera app"), /거울상/);
  assert.equal(reasonText("something new"), "Vision: something new");
  assert.equal(cutGuidance(["west"]), "지도 서쪽 끝이 화면 밖입니다 — 카메라를 서쪽으로 옮기거나 더 넓게 잡으세요.");
  assert.match(cutGuidance(["north", "east"]), /북쪽·동쪽/);
  assert.equal(cutGuidance([]), null);
});

test("the summary says accept-to-apply for a pass and never offers accept on a rejection", () => {
  const pass = fitSummary(normalizeMapProposal(body()));
  assert.equal(pass.tone, "good");
  assert.match(pass.headline, /일치 0\.91 · 정밀 0\.96 · 지도 76% 보임/);
  assert.match(pass.headline, /자동 적용하지 않습니다/);
  assert.match(pass.guidance, /서쪽으로/);
  const fail = fitSummary(normalizeMapProposal(body({
    accepted: false, proposal: null, rejected_fit: body().proposal, reason: "orientation ambiguous (margin 0.04)",
  })));
  assert.equal(fail.tone, "warn");
  assert.match(fail.headline, /^맞춤 거부 — 방향을/);
  assert.match(fail.headline, /수락할 수 없습니다/);
  assert.equal(fitSummary(null).tone, "warn");
});

test("lanes pick the entry naming the source, then the every-map entry", () => {
  const b = { min_x: -1.4, min_y: -0.63, max_x: 1.4, max_y: 0.63 };
  const lanes = { maps: [
    { map_id: "other", source_ids: ["south"], bounds_m: b, polylines: [], paint_triangles: [] },
    { map_id: null, source_ids: ["ceiling-north"], bounds_m: b,
      polylines: [{ id: "east", points: [[0, 0], [1, 0]] }, { id: "bad", points: [[0, 0]] }],
      paint_triangles: [[0, 0, 1, 0, 1, 1], [0, 0]] },
  ] };
  const picked = pickLanes(lanes, "ceiling-north");
  assert.equal(picked.mapId, null);
  assert.equal(picked.polylines.length, 1);
  assert.equal(picked.triangles.length, 1);
  assert.equal(pickLanes(lanes, "south").mapId, "other");
  assert.equal(pickLanes({ maps: [] }, "x"), null);
  assert.equal(pickLanes({ maps: [{ bounds_m: { min_x: 1, max_x: 0, min_y: 0, max_y: 1 } }] }, "x"), null);
});

test("top-down layout fits the map with y up and inverts back to metres", () => {
  const layout = topDownLayout({ min_x: -1.405, min_y: -0.63, max_x: 1.405, max_y: 0.63 }, 640, 400, 0.1);
  assert.ok(layout.width <= 640 && layout.height <= 400);
  const topLeft = project(layout.mapToCanvas, -1.505, 0.73);
  close(topLeft[0], 0);
  close(topLeft[1], 0);
  const below = project(layout.mapToCanvas, 0, -0.5);
  const above = project(layout.mapToCanvas, 0, 0.5);
  assert.ok(below[1] > above[1]); // map +y is up on the canvas
  const back = project(layout.canvasToMap, ...project(layout.mapToCanvas, 0.3, 0.2));
  close(back[0], 0.3);
  close(back[1], 0.2);
});

test("an accepted draft round-trips through storage and rejects foreign values", () => {
  const norm = normalizeMapProposal(body());
  const draft = parseMapDraft(draftFrom(norm, "site-v1", Date.UTC(2026, 8, 30)));
  assert.deepEqual(draft.mapToImage, MAP_TO_IMAGE);
  assert.equal(draft.mapId, "site-v1");
  assert.equal(draft.acceptedAt, "2026-09-30T00:00:00.000Z");
  assert.ok(JSON.parse(draftFrom(norm, null)).use === "display-only");
  assert.equal(parseMapDraft("{not json"), null);
  assert.equal(parseMapDraft(null), null);
  assert.equal(parseMapDraft(JSON.stringify({ map_to_image: [1, 2, 3], image: { width: 1, height: 1 } })), null);
  assert.equal(flatMatrix([[1, 2, 3], [4, 5, 6], [7, 8, "x"]]), null);
});
