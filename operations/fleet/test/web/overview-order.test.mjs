import test from "node:test";
import assert from "node:assert/strict";
import { overviewProblem, sortProblemsFirst } from "../../../../applications/fleet/web/robot/overview-order.js";

const mobile = (id, bad) => ({ profile: { id }, robot: { id, bad } });
const arm = (id, extra) => ({ profile: { id, link: { state: "connected" }, ...extra }, robot: null });
const attention = (r) => r.bad;

test("problem robots come first and keep API order inside each grade", () => {
  const list = [mobile("a", false), mobile("b", true), mobile("c", false), mobile("d", true)];
  assert.deepEqual(sortProblemsFirst(list, attention).map((e) => e.profile.id), ["b", "d", "a", "c"]);
});

test("arms count as problems on alarm or lost link", () => {
  assert.equal(overviewProblem(arm("s", {}), attention), false);
  assert.equal(overviewProblem(arm("s", { alarm: { tag: "x" } }), attention), true);
  assert.equal(overviewProblem(arm("s", { link: { state: "delayed" } }), attention), true);
});

test("sorting is stable across calls and does not mutate input", () => {
  const list = [mobile("a", true), mobile("b", true), mobile("c", false)];
  const once = sortProblemsFirst(list, attention);
  assert.deepEqual(sortProblemsFirst(once, attention).map((e) => e.profile.id), ["a", "b", "c"]);
  assert.deepEqual(list.map((e) => e.profile.id), ["a", "b", "c"]);
});
