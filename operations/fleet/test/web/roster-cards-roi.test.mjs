// The card's ceiling ROI asks Vision only for a target with a map position, and backs off on failure.
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { createRoiPoller, roiTargetId } = await import("../../../../applications/fleet/web/roster-cards.js");

function poller(view, responses = []) {
  const fetched = [], leases = [];
  globalThis.document = { hidden: false, getElementById: (id) => ({ id, hidden: true }) };
  globalThis.fetch = async (url) => { fetched.push(url); return responses.shift() ?? { ok: false, status: 503 }; };
  const call = async () => { leases.push(1); return { lease: "t", expires_in_s: 60 }; };
  const { refreshRoiPreview } = createRoiPoller({ scope: { onDispose() {}, interval() {}, listen() {} }, view, call });
  return { refreshRoiPreview, fetched, leases };
}

test("the ROI target is the focused arm or robot with a map position, else none", () => {
  const guide = { robots: [{ robot_id: "rosy_01", pose: { x: 0, y: 0 } }, { robot_id: "rosy_02", pose: null }] };
  assert.equal(roiTargetId({ focusRobot: "rosy_01", guide }), "rosy_01");
  assert.equal(roiTargetId({ focusRobot: "rosy_02", guide }), null);
  assert.equal(roiTargetId({ focusAnchorId: "arm_a", focusRobot: "rosy_02", guide, anchors: [{ target_id: "arm_a" }] }), "arm_a");
  assert.equal(roiTargetId({ guide }), null);
});

test("a robot without a map position is never polled", async () => {
  const p = poller({ focusRobot: "rosy_02", anchors: [{ target_id: "arm_a" }],
    guide: { robots: [{ robot_id: "rosy_02", pose: null }] } });
  await p.refreshRoiPreview();
  assert.deepEqual(p.fetched, []);
  assert.deepEqual(p.leases, []);
});

test("a failed ROI read waits before the next request", async () => {
  const p = poller({ focusRobot: "rosy_01", guide: { robots: [{ robot_id: "rosy_01", pose: { x: 0, y: 0 } }] } });
  await p.refreshRoiPreview();
  assert.equal(p.fetched.length, 1);
  assert.match(p.fetched[0], /\/roi\/rosy_01$/);
  await p.refreshRoiPreview();  // inside the back-off window
  assert.equal(p.fetched.length, 1);
});

test("no robot id is fixed into the station table, bay defaults or occupant fallbacks", async () => {
  for (const name of ["roster-cards.js", "roster.js", "console-goal.js", "charge-bays-view.js"]) {
    const text = await readFile(new URL(`../../../../applications/fleet/web/${name}`, import.meta.url), "utf8");
    assert.doesNotMatch(text, /rosy_4[256]/, name);
  }
});
