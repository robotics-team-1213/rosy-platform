import test from "node:test";
import assert from "node:assert/strict";

const flags = () => { const set = new Set(); return {set, toggleAttribute: (name, on) => (on ? set.add(name) : set.delete(name))}; };
const {applyUnitScope, owns, relays, scopeSummary, unitScope} = await import(new URL("../../../../applications/fleet/web/shared/unit-scope.js", import.meta.url));

test("a cell hides drive and the children list, keeps arms (D-960 §4)", () => {
  const root = flags();
  applyUnitScope({role: "cell", drive: false, arms: true, children: false, enrollment: false}, root);
  assert.deepEqual([...root.set].sort(), ["data-unit-arms", "data-unit-scope-ready"]);  // no data-unit-root
  assert.equal(owns("drive"), false);
  assert.equal(scopeSummary(unitScope()), "셀 관제 · 맡은 일: 팔 셀");
});

test("a root with no arm cell below it drives its Pinky and sees its children but not the arms", () => {
  const root = flags();
  applyUnitScope({role: "root", drive: true, arms: false, children: true, enrollment: false}, root);
  assert.deepEqual([...root.set].sort(), ["data-unit-children", "data-unit-drive", "data-unit-root", "data-unit-scope-ready"]);
  assert.equal(scopeSummary(unitScope()), "통합관제 · 맡은 일: 주행 로봇, 하위 관제");
});

test("no scope from an older server keeps every block", () => {
  const root = flags();
  applyUnitScope(undefined, root);
  assert.equal(root.set.has("data-unit-scope-ready"), false);
  assert.equal(root.set.has("data-unit-root"), true);
  assert.equal(owns("arms"), true);
  assert.equal(scopeSummary(undefined), "");
});

test("a cell with child units keeps the root-only stop controls and only relays arm jobs", () => {
  const root = flags();
  applyUnitScope({role: "cell", drive: false, arms: true, children: true, enrollment: false}, root);
  assert.equal(root.set.has("data-unit-root"), true);
  assert.equal(relays(), true);
  applyUnitScope({role: "standalone", drive: true, arms: true, children: false, enrollment: true}, root);
  assert.equal(relays(), false);
  assert.equal(owns("arms"), true);
});
