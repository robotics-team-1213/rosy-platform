import test from "node:test";
import assert from "node:assert/strict";

import {
  flatMatrix, multiply3, invert3, project, scale3, projectPolyline, projectTriangles,
  normalizeMapProposal, reasonText, cutGuidance, fitSummary, pickLanes, topDownLayout,
  parseMapDraft, draftFrom, fieldToMap, retryDelay, MAP_FIT_MAX_TRIES, canAccept, fitUsable,
  orientHomography, calibrationRequest, lensesMatch, fitFromCalibration,
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
  assert.equal(retryDelay({ busy: true, retryAfterMs: 8000 }, 0), 8000); // a long Retry-After is honoured
  assert.equal(retryDelay({ busy: true, retryAfterMs: 60000 }, 0), 15000);
  assert.equal(MAP_FIT_MAX_TRIES, 15);
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

test("the specific map entry wins over an every-map entry listed first", () => {
  const b = { min_x: -1.4, min_y: -0.63, max_x: 1.4, max_y: 0.63 };
  const lanes = { maps: [
    { map_id: null, source_ids: ["ceiling-north", "south"], bounds_m: b, lane_graph_sha256: "all" },
    { map_id: "site-v1", source_ids: ["ceiling-north"], bounds_m: b, lane_graph_sha256: "v1" },
  ] };
  assert.equal(pickLanes(lanes, "ceiling-north").mapId, "site-v1");
  assert.equal(pickLanes(lanes, "ceiling-north").laneSha, "v1");
  assert.equal(pickLanes(lanes, "south").mapId, null);
});

test("only a current, passed, drawable proposal for this camera can be accepted", () => {
  const norm = normalizeMapProposal(body());
  assert.equal(canAccept({ source: "cam", norm }, "cam"), true);
  assert.equal(canAccept({ source: "cam", norm }, "other"), false);
  assert.equal(canAccept(null, "cam"), false);
  const rejected = normalizeMapProposal(body({ accepted: false, proposal: null, rejected_fit: body().proposal }));
  assert.equal(canAccept({ source: "cam", norm: rejected }, "cam"), false); // the accepted check
  const previous = normalizeMapProposal(body(), { proposalState: "previous" });
  assert.equal(previous.previous, true);
  assert.equal(previous.ageMs, 40);
  assert.equal(canAccept({ source: "cam", norm: previous }, "cam"), false);
  const summary = fitSummary(normalizeMapProposal(body({ frame_age_ms: 4200 }), { proposalState: "previous" }));
  assert.match(summary.headline, /^이전 결과 · 4 s 전/);
  assert.doesNotMatch(summary.headline, /보고 수락하세요/);
});

test("a fit is not stretched onto another frame shape or another map", () => {
  const fit = { image: { width: 1280, height: 720 },
    stamp: { mapId: "site-v1", laneSha: "a", paintSha: "b" } };
  const lanesNow = { mapId: "site-v1", laneSha: "a", paintSha: "b" };
  assert.equal(fitUsable(fit, 640, 360, lanesNow).ok, true); // same shape, half size
  assert.equal(fitUsable(fit, 1280, 725, lanesNow).ok, true); // < 1 %
  assert.equal(fitUsable(fit, 720, 1280, lanesNow).reason, "shape"); // rotated phone
  assert.equal(fitUsable(fit, 1600, 1200, lanesNow).reason, "shape"); // 4:3 mode
  assert.equal(fitUsable(fit, 1280, 720, { ...lanesNow, mapId: "other" }).reason, "map");
  assert.equal(fitUsable(fit, 1280, 720, { ...lanesNow, paintSha: "c" }).reason, "map");
  assert.equal(fitUsable({ image: fit.image }, 1280, 720, lanesNow).ok, true); // pending without a stamp
});

test("the homography sign is normalised so the image centre is in front (w > 0)", () => {
  const flipped = IMAGE_TO_MAP.map((v) => -v); // same projective map, opposite sign
  const norm = normalizeMapProposal(body({ proposal: { ...body().proposal, image_to_map: rows(flipped),
    map_to_image: rows(MAP_TO_IMAGE.map((v) => -v)) } }));
  const centreMap = project(norm.fit.imageToMap, 640, 360);
  assert.ok(centreMap, "image centre must not be behind the horizon");
  const back = project(norm.fit.mapToImage, ...centreMap);
  close(back[0], 640, 1e-6);
  close(back[1], 360, 1e-6);
  assert.equal(orientHomography([0, 0, 0, 0, 0, 0, 0, 0, 0], 10, 10), null);
});

test("an accepted draft round-trips through storage and rejects foreign values", () => {
  const norm = normalizeMapProposal(body());
  const draft = parseMapDraft(draftFrom(norm, { mapId: "site-v1", laneSha: "a", paintSha: "b" },
    Date.UTC(2026, 8, 30)));
  draft.mapToImage.forEach((v, i) => close(v / draft.mapToImage[8], MAP_TO_IMAGE[i], 1e-9));
  assert.equal(draft.mapId, "site-v1");
  assert.deepEqual(draft.stamp, { mapId: "site-v1", laneSha: "a", paintSha: "b" });
  assert.equal(draft.acceptedAt, "2026-09-30T00:00:00.000Z");
  assert.ok(JSON.parse(draftFrom(norm, null)).use === "display-only");
  assert.equal(parseMapDraft("{not json"), null);
  assert.equal(parseMapDraft(null), null);
  assert.equal(parseMapDraft(JSON.stringify({ map_to_image: [1, 2, 3], image: { width: 1, height: 1 } })), null);
  assert.equal(flatMatrix([[1, 2, 3], [4, 5, 6], [7, 8, "x"]]), null);
});

test("an applied fit becomes a Fleet calibration request; previous or other-source fits never do", () => {
  const body = {
    accepted: true, image: { width: 1280, height: 720 }, frame_seq: 12,
    proposal: { image_to_map: [[0.005, 0, 0], [0, -0.005, 3.6], [0, 0, 1]], score: 0.9, precision: 0.95,
      coverage: 0.8, cut_directions: [] },
  };
  const pending = { source: "ceiling_north", norm: normalizeMapProposal(body, {}) };
  const laneSet = { mapId: "map_v2_fleet", bounds: { min_x: 0, min_y: 0, max_x: 6.4, max_y: 3.6 } };
  const lens = { kind: "standard", focal_mm: 5.4, hfov_deg: 66.9 };
  const request = calibrationRequest(pending, "ceiling_north", laneSet, lens);
  assert.equal(request.source_id, "ceiling_north");
  assert.equal(request.map_id, "map_v2_fleet");
  assert.equal(request.map_to_image.length, 9);
  close(request.map_to_image[0], 200);
  close(request.map_to_image[4], -200);
  close(request.map_to_image[5], 720);
  assert.deepEqual(request.image, { width: 1280, height: 720 });
  assert.deepEqual(request.track_bounds_m, { min_x: 0, min_y: 0, max_x: 6.4, max_y: 3.6 });
  assert.equal(request.fit_score, 0.855);
  assert.deepEqual(request.lens, lens);
  assert.equal(request.frame_seq, 12);
  const previous = { ...pending, norm: { ...pending.norm, previous: true } };
  assert.equal(calibrationRequest(previous, "ceiling_north", laneSet, lens), null);
  assert.equal(calibrationRequest(pending, "ceiling_south", laneSet, lens), null);
  assert.equal(calibrationRequest(pending, "ceiling_north", null, lens), null);
  const noMap = calibrationRequest(pending, "ceiling_north", { mapId: null, bounds: laneSet.bounds }, null);
  assert.equal("map_id" in noMap, false);
  assert.equal(noMap.lens, null);
  // A proposal made against another map (its lane stamp) is never filed under the current map.
  const stamped = { ...pending, stamp: { mapId: "map_old", laneSha: null, paintSha: null } };
  assert.equal(calibrationRequest(stamped, "ceiling_north", laneSet, lens), null);
  const sameMap = { ...pending, stamp: { mapId: "map_v2_fleet", laneSha: null, paintSha: null } };
  assert.equal(calibrationRequest(sameMap, "ceiling_north", laneSet, lens).map_id, "map_v2_fleet");
});

test("an approved tracking calibration is a display fit only when the lens matches", () => {
  const lens = { kind: "standard", focal_mm: 5.4, hfov_deg: 67.8 };
  const record = {
    source_id: "ceiling_north", map_id: "map_v2_fleet", calibration_revision: "paint-daccc3e53522",
    map_to_image: MAP_TO_IMAGE, image: { width: 1280, height: 720 }, frame_seq: 14992,
    use: "display-only", lens,
  };
  assert.equal(lensesMatch(null, null), true);
  assert.equal(lensesMatch(lens, null), false);
  assert.equal(lensesMatch(null, lens), false);
  assert.equal(lensesMatch(lens, { kind: "standard", focal_mm: 5.41, hfov_deg: 67.8 }), false);
  assert.equal(lensesMatch(lens, { kind: "wide", focal_mm: 5.4, hfov_deg: 67.8 }), false);
  assert.equal(lensesMatch(lens, { kind: "standard", focal_mm: 5.4001, hfov_deg: 67.803 }), true);
  const fit = fitFromCalibration(record, lens);
  assert.equal(fit.revision, "paint-daccc3e53522");
  assert.equal(fit.mapId, "map_v2_fleet");
  const shown = project(fit.mapToImage, -0.3357, 0.0011);
  const expected = project(MAP_TO_IMAGE, -0.3357, 0.0011);
  close(shown[0], expected[0], 1e-4);
  close(shown[1], expected[1], 1e-4);
  assert.equal(fitFromCalibration(record, null), null);
  assert.equal(fitFromCalibration({ ...record, lens: null }, lens), null);
  const bare = fitFromCalibration({ ...record, lens: null }, null);
  assert.equal(bare.revision, "paint-daccc3e53522");
  assert.equal(fitFromCalibration({ ...record, calibration_revision: 3 }, lens).revision, null);
  assert.equal(fitFromCalibration({ ...record, map_to_image: [1, 2, 3] }, lens), null);
  assert.equal(fitFromCalibration(null, lens), null);
});
