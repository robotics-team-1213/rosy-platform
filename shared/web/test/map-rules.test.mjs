import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

// The 2D map rules Fleet and World both import (/common/map-rules.js). Loaded as ESM the World way (no package "type").
const source = await readFile(new URL("../map-rules.js", import.meta.url), "utf8");
const { mapEvidence, placeText, scaleBar, stamp, viewTurnOf } =
  await import(`data:text/javascript,${encodeURIComponent(source)}`);

test("view turn follows D-513 7 values only", () => {
  assert.equal(viewTurnOf({ view_turn_deg: 90 }), 90);
  assert.equal(viewTurnOf({ view_turn_deg: 45 }), 0);
  assert.equal(viewTurnOf({ view_turn_deg: "90" }), 0);
  assert.equal(viewTurnOf(undefined), 0);
});

test("place text is the name then the ID, or the ID alone", () => {
  assert.equal(placeText({ id: "S3", name: "적재 3" }), "적재 3 (S3)");
  assert.equal(placeText({ id: "S3", name: "S3" }), "S3");
  assert.equal(placeText({ id: "S3", name: " " }), "S3");
  assert.equal(placeText({ id: "S3" }), "S3");
});

test("scale bar: the Fleet map range keeps 0.5/1/2 m inside its bar room", () => {
  // Fleet drawNdOverlay: canvas px per metre 20–200 with 100–600 px of room keeps the Fleet steps.
  for (const [pxPerM, room, stepM] of [[20, 600, 2], [27.9, 100, 2], [28, 100, 1], [79.9, 100, 1], [80, 600, 0.5], [200, 120, 0.5]]) {
    assert.equal(scaleBar(pxPerM, room)?.stepM, stepM, `${pxPerM} px/m in ${room} px`);
  }
  assert.equal(scaleBar(30, 20), null);  // room for no bar of 24 px or more
});

test("scale bar uses the Fleet 0.5/1/2 m steps, smaller only when zoomed in (World)", () => {
  assert.deepEqual(scaleBar(100), { stepM: 0.5, barPx: 50 });
  assert.deepEqual(scaleBar(40), { stepM: 1, barPx: 40 });
  assert.deepEqual(scaleBar(20), { stepM: 2, barPx: 40 });
  assert.equal(scaleBar(10), null);
  assert.equal(scaleBar(0), null);
  assert.deepEqual(scaleBar(250, 126), { stepM: 0.5, barPx: 125 });
  assert.equal(scaleBar(400, 126).stepM, 0.2);
  assert.deepEqual(scaleBar(1000, 126), { stepM: 0.1, barPx: 100 });
  assert.equal(scaleBar(2000, 126).stepM, 0.05);
  assert.equal(scaleBar(5000, 126), null);  // no 0.02 m step: the table stops at 0.05 m
  assert.equal(scaleBar(100_000, 126), null);
});

test("stamps are KST on screen with the UTC original in the title", () => {
  const now = Date.parse("2026-11-26T03:00:00Z");
  assert.deepEqual(stamp(Date.parse("2026-11-26T01:02:03Z") / 1000, now),
    { text: "10:02:03", title: "2026-11-26T01:02:03.000Z (UTC)" });
  assert.deepEqual(stamp("2026-11-24T00:00:00Z", now), { text: "11-24 09:00:00", title: "2026-11-24T00:00:00.000Z (UTC)" });
  assert.deepEqual(stamp(undefined, now), { text: "확인되지 않음", title: "" });
  assert.deepEqual(mapEvidence({ version: 8, timeLabel: "수신", time: Date.parse("2026-11-26T01:02:03Z") / 1000,
    source: "Fleet 활성 지도" }, now), { text: "지도 v8 · 수신 10:02:03 · Fleet 활성 지도",
    title: "수신 2026-11-26T01:02:03.000Z (UTC)" });
});
