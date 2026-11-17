import test from "node:test";
import assert from "node:assert/strict";
const { lockedItems, MAP_TOOLS_LOCK } = await import("../../../../applications/fleet/web/map/map-tool-lock.js");

test("F8: with no map every display tool is locked with a reason; with a map the items are unchanged", () => {
  const items = [{value: "a", label: "A"}, {value: "b", label: "B"}];
  assert.equal(lockedItems(items, false), items);
  const locked = lockedItems(items, true);
  assert.ok(locked.every(item => item.disabled === true && item.reason === MAP_TOOLS_LOCK));
  assert.match(MAP_TOOLS_LOCK, /지도 설정/);
});
