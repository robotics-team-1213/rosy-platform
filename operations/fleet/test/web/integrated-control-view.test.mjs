import test from "node:test";
import assert from "node:assert/strict";
const {register} = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const {stopControls} = await import("../../../../applications/fleet/web/work/integrated-control-view.js");

const unit = (unit_id, parent, changes = {}) => ({unit_id, parent, availability: "AVAILABLE", age_s: 0,
  dispatch: {authority_epoch: 3, generation: 7}, ...changes});

test("stop fences include only fresh descendants of the selected subtree", () => {
  const overview = {units: [unit("R", null), unit("A", "R"), unit("B", "R"),
    unit("A1", "A"), unit("old", "A", {age_s: 8}), unit("offline", "A", {availability: "UNAVAILABLE"})]};
  assert.deepEqual(stopControls(overview, "A"), {A: {authority_epoch: 3, generation: 7},
    A1: {authority_epoch: 3, generation: 7}});
  assert.deepEqual(stopControls(overview, "B"), {B: {authority_epoch: 3, generation: 7}});
  assert.deepEqual(stopControls(overview, "foreign"), {});
  assert.deepEqual(stopControls(overview, "A", 6), {});
});

test("missing observations and invalid dispatch fences cannot become fresh permits", () => {
  for (const changes of [{age_s: null}, {age_s: -1}, {age_s: Infinity}, {availability: "STALE"},
    {dispatch: null}, {dispatch: {authority_epoch: 1, generation: true}},
    {dispatch: {authority_epoch: -1, generation: 2}}, {dispatch: {authority_epoch: 1, generation: 1.5}}]) {
    assert.deepEqual(stopControls({units: [unit("constructor", null, changes)]}, "constructor"), {});
  }
});
