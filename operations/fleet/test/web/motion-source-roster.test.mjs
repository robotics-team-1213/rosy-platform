// The real attentionItems and the manual-control driver flag carry the motion source.
import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { createRoster } = await import("../../../../applications/fleet/web/roster.js");

const view = { robots: [], formation: null, stateUnavailable: false, receivedAtMs: Date.now(), trafficTrips: [] };
const { attentionItems } = createRoster({ scope: { onDispose() {}, interval() {} }, view, streamEvidence: () => null });
const robot = (state) => ({ robot_id: "a", online: true, state_age_s: 0.2,
  state: { mode: "IDLE", safety: { estop: false }, velocity: { linear: 0, angular: 0 },
           evidence: { velocity: { evidence: "fresh" } }, ...state } });

test("a robot moving with no known owner reaches the attention queue", () => {
  const items = attentionItems(robot({ velocity: { linear: 0.06, angular: 0 } }));
  assert.ok(items.some(i => i.severity === "crit" && i.text.includes("원인 불명 이동")), JSON.stringify(items));
});

test("an idle robot and a robot with a proven trip add no motion item", () => {
  assert.ok(!attentionItems(robot({})).some(i => i.text.includes("이동")));
  const trip = robot({ velocity: { linear: 0.06, angular: 0 }, trip_lease: { operator_name: "kim" } });
  assert.ok(!attentionItems(trip).some(i => i.text.includes("확인 불가") || i.text.includes("원인 불명")));
});
