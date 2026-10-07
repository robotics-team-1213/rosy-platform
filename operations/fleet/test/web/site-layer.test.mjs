import test from "node:test";
import assert from "node:assert/strict";

import {
  classifySightings, siteBounds, canvasSizeFor, fitTransform, project, gridLines,
  SIGHTING_STALE_MS, SIGHTING_HIDE_MS, streamEvidence, displayRotation, quarterTurn, cameraScreenToMap, mapQuarterTurn,
} from "../../fleet/server/web/site-layer.js";

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

test("D-513 7: a 90° turn puts the picture's right edge at the bottom", () => {
  const turn = quarterTurn(90, 1280, 720);
  assert.deepEqual([turn.width, turn.height], [720, 1280]);
  assert.deepEqual(turn.point(1280, 360), { x: 360, y: 1280 }); // right middle -> bottom middle
  assert.deepEqual(turn.point(0, 0), { x: 720, y: 0 });          // top left -> top right
  assert.deepEqual(quarterTurn(180, 10, 4).point(0, 0), { x: 10, y: 4 });
  assert.deepEqual(quarterTurn(270, 10, 4).point(0, 0), { x: 0, y: 10 });
  assert.deepEqual(quarterTurn(0, 10, 4).point(3, 2), { x: 3, y: 2 });
});

test("D-513 7: the rotation comes from the source row, anything else is 0", () => {
  const siteMap = { maps: [{ sources: [{ source_id: "cam", display_rotation_deg: 90 },
    { source_id: "odd", display_rotation_deg: 45 }] }] };
  assert.equal(displayRotation(siteMap, "cam"), 90);
  assert.equal(displayRotation(siteMap, "odd"), 0);
  assert.equal(displayRotation(siteMap, "missing"), 0);
  assert.equal(displayRotation(null, "cam"), 0);
});

test("D-513 7: a click on the turned picture maps back through the turn and calibration", () => {
  const h = [100, 0, 200, 0, -100, 100, 0, 0, 1]; // map (x, y) -> image (100x+200, -100y+100)
  for (const rot of [0, 90, 180, 270]) {
    const turn = quarterTurn(rot, 400, 200);
    const back = turn.unpoint(...Object.values(turn.point(30, 40)));
    assert.deepEqual(back, { x: 30, y: 40 });
    const shown = turn.point(100 * 0.5 + 200, -100 * -0.25 + 100);
    const map = cameraScreenToMap(h, turn, shown.x, shown.y);
    assert.ok(Math.abs(map.x - 0.5) < 1e-9 && Math.abs(map.y + 0.25) < 1e-9, `rot ${rot}`);
  }
  assert.equal(cameraScreenToMap([0, 0, 0, 0, 0, 0, 0, 0, 0], quarterTurn(0, 1, 1), 0, 0), null);
});

test("D-513 7: the map view turn follows where map +x points on the turned picture", () => {
  const record = { map_to_image: [100, 0, 200, 0, -100, 100, 0, 0, 1],
    image: { width: 400, height: 200 }, track_bounds_m: { min_x: -1, max_x: 1, min_y: -0.5, max_y: 0.5 } };
  assert.equal(mapQuarterTurn(record, 0), 0);    // map +x is image right
  assert.equal(mapQuarterTurn(record, 90), 90);  // image right is now screen down
  assert.equal(mapQuarterTurn(record, 270), 270);
  assert.equal(mapQuarterTurn({}, 90), 0);
});
