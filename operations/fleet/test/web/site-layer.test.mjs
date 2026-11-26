import test from "node:test";
import assert from "node:assert/strict";

import {
  classifySightings, siteBounds, canvasSizeFor, gridLines,
  SIGHTING_STALE_MS, SIGHTING_HIDE_MS, streamEvidence, mapUpTurn,
  roadOverlayPoints, surveyedRoadPoints, surveyText, unmeasuredRoadPoints,
} from "../../../../applications/fleet/web/map/site-layer.js";
import { fitBox, viewTurnOf } from "../../../../applications/fleet/web/shared/site-map-model.js";
import { project as projectHomography } from "../../../../shared/web/plane-math.js";

test("world_261026 charging bay overlays draw straight, leaving source geometry intact", () => {
  const polyline = [[-0.43002, 0.04266], [-0.4354, 0.3294], [-0.41816, 0.47]];
  for (const bay of [1, 2, 3]) {
    const edge = {id: `bay_${bay}`, from: `P${bay}`, to: `C${bay}`, polyline};
    assert.deepEqual(roadOverlayPoints("world_261026", edge), [polyline[0], polyline[2]]);
    assert.equal(roadOverlayPoints("other_site", edge), polyline);
    assert.equal(roadOverlayPoints("world_261026", {...edge, id: "ring"}), polyline);
    assert.equal(polyline.length, 3);
  }
});

// What GET /api/fleet/site-map/active serves for world_261026 (fleet.site_map.with_floor_surveys, test_site_map_survey.py).
const surveyed = (edge, line, anchors, extra = {}) => ({...edge, display_polyline: line,
  display_source: {kind: "survey", surveyed_at: "2026-11-26", plane: "ceiling_north", anchors, stored_until: null, ...extra}});

test("C1 floor stripe ends on observed paint independently of the charging pose", () => {
  const polyline = [[-0.43002, 0.04266], [-0.4354, 0.3294], [-0.41816, 0.47]];
  const plain = {id: "bay_1", from: "P1", to: "C1", polyline};
  const edge = surveyed(plain, [[-0.4222, 0.0433], [-0.4386, 0.44]], [polyline[0], polyline[2]], {note: "영상의 분홍 충전선 중심"});
  assert.deepEqual(surveyedRoadPoints(edge), [[-0.4222, 0.0433], [-0.4386, 0.44]]);
  assert.equal(surveyedRoadPoints(plain), null); // no server field: no survey line
  assert.equal(surveyedRoadPoints({...edge, display_source: {...edge.display_source, kind: "guess"}}), null);
  assert.equal(surveyedRoadPoints({...edge, polyline: [polyline[0], [-0.42, 0.48]]}), null); // moved 10 mm
  assert.equal(unmeasuredRoadPoints(edge), null);
  assert.equal(surveyText(edge.display_source), "측량 2026-11-26 · ceiling_north · 영상의 분홍 충전선 중심");
});

test("upper floor midpoint meets the turn approach on one straight line; stored S3 maneuver stays available", () => {
  const s3 = [0.745, -0.207], tangent = [0.9238, -0.207], s5 = [0.89822, -0.48152];
  const upper = surveyed({id: "upper_east", from: "S3", to: "J_in", polyline: [s3, [0.31418, -0.25008]]},
    [[0.745, -0.25008], [0.31418, -0.25008]], [s3, [0.31418, -0.25008]]);
  const turn = surveyed({id: "loop_right", from: "S5", to: "S3", polyline: [s5, [1.0593, -0.3424], tangent, s3]},
    [[0.9238, -0.25008], [0.745, -0.25008]], [s5, s3], {stored_until: tangent});
  const approach = surveyedRoadPoints(turn), lane = surveyedRoadPoints(upper);
  assert.deepEqual(approach.at(-1), lane[0]);
  assert.ok([...approach, ...lane].every(([, y]) => y === -0.25008));
  assert.deepEqual(unmeasuredRoadPoints(turn), turn.polyline.slice(0, 3));
  assert.deepEqual(turn.polyline.at(-1), s3);
});

const row = (changes) => ({
  robot_id: "rosy-pinky-8kcn", x: 1, y: 0.5, yaw: 0, captured_at: 10, age_ms: 200,
  stale: false, source_id: "ceiling_north", ...changes,
});

test("fresh, delayed and expired sightings are classified by age", () => {
  const out = classifySightings({ sightings: [
    row({ robot_id: "a", age_ms: 100 }),
    row({ robot_id: "b", age_ms: SIGHTING_STALE_MS + 1 }),
    row({ robot_id: "c", age_ms: SIGHTING_HIDE_MS + 1 }),
    row({ robot_id: "d", age_ms: 1500, stale: true }),
  ] });
  // 증거 어휘는 닫힌 네 상태다 — 서버의 stale 플래그는 화면에서 delayed다.
  assert.deepEqual(out.map((s) => [s.robot_id, s.state]),
    [["a", "fresh"], ["b", "delayed"], ["d", "delayed"]]);
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
  const t = fitBox(bounds, width, height, 50);
  assert.equal(t.scale, 200);
  assert.deepEqual(t.toPx(0, 0), [100, 450]);
  assert.deepEqual(t.toPx(4, 2), [900, 50]);
});

test("grid lines land on 0.5 m multiples inside the range", () => {
  assert.deepEqual(gridLines(-0.25, 1.25), [0, 0.5, 1]);
  assert.deepEqual(gridLines(0, 1), [0, 0.5, 1]);
});

// D-359 US-009 — the relay pill sits alone on a robot card, so it names the relay.
test("relay evidence pills say what is late, lost or unknown", () => {
  const formation = (evidence) => ({ active: true, stream_evidence: evidence });
  assert.equal(streamEvidence({ active: false }, "a"), null);
  assert.equal(streamEvidence(formation({ a: { state: "fresh" } }), "a"), null);
  assert.deepEqual(streamEvidence(formation({}), "a"),
    { text: "릴레이 증거 없음", cls: "warn", evidence: "unavailable" });
  assert.deepEqual(streamEvidence(formation({ a: { state: "disconnected" } }), "a"),
    { text: "릴레이 끊김", cls: "crit", evidence: "disconnected" });
  assert.deepEqual(streamEvidence(formation({ a: { state: "delayed", age_s: 1.26 } }), "a"),
    { text: "릴레이 지연 · 1.3초 전", cls: "warn", evidence: "delayed" });
  assert.equal(streamEvidence(formation({ a: { state: "delayed", reason: "rate_below_floor" } }), "a").text,
    "릴레이 지연 · 송신 빈도 낮음");
  assert.deepEqual(streamEvidence(formation({ a: { state: "unavailable" } }), "a"),
    { text: "릴레이 증거 없음", cls: "warn", evidence: "unavailable" });
});

test("D-513 7: a view turn rotates the fitted map clockwise, and toMap and the matrix agree with toPx", () => {
  const bounds = { min_x: 0, min_y: 0, max_x: 4, max_y: 2 };
  const down = (rot) => { const t = fitBox(bounds, 1000, 1000, 50, rot), a = t.toPx(0, 0), b = t.toPx(1, 0); return [Math.sign(b[0] - a[0]), Math.sign(b[1] - a[1])]; };
  assert.deepEqual([0, 90, 180, 270].map(down), [[1, 0], [0, 1], [-1, 0], [0, -1]]); // map +x: right, down, left, up
  for (const rot of [0, 90, 180, 270]) {
    const t = fitBox(bounds, 720, 1280, 32, rot);
    for (const [x, y] of [[0, 0], [4, 2], [1.25, 0.5]]) {
      const [px, py] = t.toPx(x, y);
      assert.ok(px >= 31.99 && px <= 688.01 && py >= 31.99 && py <= 1248.01, `rot ${rot} keeps (${x}, ${y}) inside`);
      const back = t.toMap(px, py), viaMatrix = projectHomography(t.matrix, x, y);
      assert.ok(Math.abs(back[0] - x) < 1e-9 && Math.abs(back[1] - y) < 1e-9, `rot ${rot}`);
      assert.ok(Math.abs(viaMatrix[0] - px) < 1e-9 && Math.abs(viaMatrix[1] - py) < 1e-9, `matrix rot ${rot}`);
    }
  }
});

test("D-513 7: the picture turns so map +y points up — no installation key", () => {
  const bounds = { min_x: -1, max_x: 1, min_y: -0.5, max_y: 0.5 };
  // map (x, y) -> image (100x+200, -100y+100): map +y is already image up
  assert.equal(mapUpTurn({ map_to_image: [100, 0, 200, 0, -100, 100, 0, 0, 1], track_bounds_m: bounds }), 0);
  // map +y is image left (wall-side right = map -y): turn 90° clockwise so +y points up
  assert.equal(mapUpTurn({ map_to_image: [0, -100, 200, 100, 0, 100, 0, 0, 1], track_bounds_m: bounds }), 90);
  // map +y is image down: half turn
  assert.equal(mapUpTurn({ map_to_image: [100, 0, 200, 0, 100, 100, 0, 0, 1], track_bounds_m: bounds }), 180);
  assert.equal(mapUpTurn(undefined), 0);
})

test("D-513 7: the site map's view turn comes from the active map, else 0 (one check, site-map-model viewTurnOf)", () => {
  const turnOf = (active) => viewTurnOf(active?.map);
  assert.equal(turnOf({ map: { view_turn_deg: 90 } }), 90);
  assert.equal(turnOf({ map: { view_turn_deg: 45 } }), 0);
  assert.equal(turnOf({ map: {} }), 0);
  assert.equal(turnOf(null), 0);
});
