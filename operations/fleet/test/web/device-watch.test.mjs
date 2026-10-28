import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { shownRobot } = await import("../../../../applications/fleet/web/device-watch.js");

test("the watch follows the open card, then the armed robot, then a sole robot", () => {
  const one = { robot_id: "rosy_26" };
  const two = { robot_id: "rosy_60" };
  assert.equal(shownRobot({ robots: [one, two], focusRobot: "rosy_60", selected: "rosy_26" }).robot_id, "rosy_60");
  assert.equal(shownRobot({ robots: [one, two], focusRobot: null, selected: "rosy_26" }).robot_id, "rosy_26");
  assert.equal(shownRobot({ robots: [one], focusRobot: null, selected: null }).robot_id, "rosy_26");
  assert.equal(shownRobot({ robots: [one, two], focusRobot: "missing", selected: null }), null);
  assert.equal(shownRobot({ robots: [] }), null);
});
