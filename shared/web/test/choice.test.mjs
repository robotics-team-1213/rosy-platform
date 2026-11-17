import {test} from "node:test";
import assert from "node:assert/strict";
import {createSelection} from "../selection.js";
import {moveIndex, findByPrefix, toggleValue, masterState, masterValues} from "../choice-logic.js";
import {robotOptions} from "../robot-options.js";
import {robotProfile} from "../robot-profile.js";

test("selection: notifies in subscribe order, once per change, never for the same value", () => {
  const selection = createSelection("a");
  const seen = [];
  selection.subscribe((id, {source}) => seen.push(["first", id, source]));
  selection.subscribe(id => seen.push(["second", id]));
  assert.equal(selection.get(), "a");
  assert.equal(selection.set("a"), false);
  assert.deepEqual(seen, []);
  assert.equal(selection.set("b", {source: "map"}), true);
  assert.deepEqual(seen, [["first", "b", "map"], ["second", "b"]]);
  assert.equal(selection.set(null), true);
  assert.equal(selection.get(), null);
});

test("selection: off stops notices, also when called during a round", () => {
  const selection = createSelection();
  const seen = [];
  const offB = selection.subscribe(() => seen.push("b"));
  selection.subscribe(() => { seen.push("a"); offB(); });
  const offC = selection.subscribe(() => seen.push("c"));
  selection.set("x");
  assert.deepEqual(seen, ["b", "a", "c"]);
  offC();
  selection.set("y");
  assert.deepEqual(seen, ["b", "a", "c", "a"]);
});

test("selection: a set inside a subscriber is notified first and ends the outer round", () => {
  const selection = createSelection();
  const seen = [];
  selection.subscribe(id => { seen.push(`1:${id}`); if (id === "x") selection.set("y"); });
  selection.subscribe(id => seen.push(`2:${id}`));
  selection.set("x");
  assert.deepEqual(seen, ["1:x", "1:y", "2:y"]);
  assert.equal(selection.get(), "y");
});

test("moveIndex: arrows stop at the ends, Home and End jump, other keys are not motion", () => {
  assert.equal(moveIndex("ArrowDown", 0, 3), 1);
  assert.equal(moveIndex("ArrowDown", 2, 3), 2);
  assert.equal(moveIndex("ArrowUp", 0, 3), 0);
  assert.equal(moveIndex("ArrowUp", 2, 3), 1);
  assert.equal(moveIndex("Home", 2, 3), 0);
  assert.equal(moveIndex("End", 0, 3), 2);
  assert.equal(moveIndex("Enter", 0, 3), null);
  assert.equal(moveIndex("ArrowDown", 0, 0), null);
});

test("findByPrefix: next match after the focus, wraps, repeated letter cycles, none = -1", () => {
  const labels = ["Alpha", "Beta", "Bravo", "alpine"];
  assert.equal(findByPrefix(labels, "b", 0), 1);
  assert.equal(findByPrefix(labels, "b", 1), 2);
  assert.equal(findByPrefix(labels, "b", 2), 1);
  assert.equal(findByPrefix(labels, "bbb", 1), 2);
  assert.equal(findByPrefix(labels, "br", 0), 2);
  assert.equal(findByPrefix(labels, "al", 0), 0);
  assert.equal(findByPrefix(labels, "z", 0), -1);
  assert.equal(findByPrefix([], "a", 0), -1);
});

test("toggleValue keeps item order and refuses to pass max; masterState and masterValues", () => {
  const order = ["a", "b", "c", "d"];
  assert.deepEqual(toggleValue(["c"], "a", order, 0), ["a", "c"]);
  assert.deepEqual(toggleValue(["a", "c"], "a", order, 0), ["c"]);
  const full = ["a", "b"];
  assert.equal(toggleValue(full, "c", order, 2), full);
  assert.deepEqual(toggleValue(full, "a", order, 2), ["b"]);
  assert.equal(masterState(0, 3), "false");
  assert.equal(masterState(2, 3), "mixed");
  assert.equal(masterState(3, 3), "true");
  assert.deepEqual(masterValues(["a"], ["a", "b", "c"], 0), ["a", "b", "c"]);
  assert.deepEqual(masterValues(["a", "b", "c"], ["a", "b", "c"], 0), []);
  assert.deepEqual(masterValues([], ["a", "b", "c"], 2), ["a", "b"]);
  assert.deepEqual(masterValues([], [], 0), []);
  assert.deepEqual(masterValues(["c", "d"], ["a", "b", "c", "d"], 2), []);  // max reached: master turns off, never sticks
});

test("robotOptions: arms first, then mobile, kind in the label, no robot -> no options, unnamed robot shows its id", () => {
  const profiles = [
    robotProfile({id: "rosy_40", kind: "mobile"}),
    robotProfile({id: "arm_a", name: "OMX-AI A", kind: "arm"}),
    robotProfile({id: "rosy_41", name: "Pinky 41", kind: "mobile"}),
  ];
  assert.deepEqual(robotOptions(profiles), [
    {value: "arm_a", label: "OMX-AI A · 로봇암"},
    {value: "rosy_40", label: "rosy_40 · 이동로봇"},
    {value: "rosy_41", label: "Pinky 41 · 이동로봇"},
  ]);
  assert.deepEqual(robotOptions([]), []);
});
