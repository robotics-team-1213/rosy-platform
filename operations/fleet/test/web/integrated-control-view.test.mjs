import test from "node:test";
import assert from "node:assert/strict";
const {register} = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const {stopControls, childLinks} = await import("../../../../applications/fleet/web/work/integrated-control-view.js");

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

test("child links follow verified https origins and never carry credentials", () => {
  const summary = {child_origins: {A: "https://cell-a.example.test:8443", B: "http://plain.invalid:8080"},
    child_arm_units: ["A"]};
  assert.deepEqual(childLinks(summary, "A"), [
    {href: "https://cell-a.example.test:8443/console", label: "관제 화면 열기"},
    {href: "https://cell-a.example.test:8443/console/cell", label: "셀 화면 열기"},
  ]);
  // http origins, unknown targets and missing summaries produce no links.
  assert.deepEqual(childLinks(summary, "B"), []);
  assert.deepEqual(childLinks(summary, "R"), []);
  assert.deepEqual(childLinks(null, "A"), []);
  assert.deepEqual(childLinks({child_origins: {A: "https://a.test"}, child_arm_units: []}, "A"),
    [{href: "https://a.test/console", label: "관제 화면 열기"}]);
});
