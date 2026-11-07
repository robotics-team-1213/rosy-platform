// Motion source: a source is named only by a fact that proves it; everything else is 확인 불가.
import test from "node:test";
import assert from "node:assert/strict";

import { motionSource, movingNow } from "../../../../applications/fleet/web/motion-source.js";

const T0 = 1_000_000;
const FRESH = { velocity: { evidence: "fresh" } };
const robot = (state = {}, extra = {}) => ({
  robot_id: "a", online: true, state_age_s: 0.3, goal: null, yielding: null,
  state: { mode: "IDLE", navigation: "IDLE", velocity: { linear: 0, angular: 0 }, evidence: FRESH, ...state }, ...extra });
const view = (extra = {}) => ({ receivedAtMs: T0, trafficTrips: [], ...extra });
const src = (r, v = view()) => motionSource(r, v, T0 + 500);

test("fresh zero velocity with nothing issued is idle, not unknown", () => {
  assert.equal(src(robot()).key, "idle");
  assert.equal(src(robot()).attention, false);
});

test("each proving fact names its own source", () => {
  assert.equal(src(robot({ trip_lease: { lease_id: "l", trip_id: "t", operator_name: "kim" } })).text, "배차 운행 · kim");
  assert.equal(src(robot(), view({ trafficTrips: [{ robot_id: "a" }] })).key, "trip");
  assert.equal(src(robot(), view({ manualDriveRobot: "a" })).key, "console_manual");
  assert.equal(src(robot({ docking: { state: "DOCKING" } })).key, "dock");
  assert.equal(src(robot({ docking: { state: "UNDOCKING" } })).key, "dock");
  assert.equal(src(robot({ swarm: { active: true } })).key, "formation");
  assert.equal(src(robot({}, { yielding: { by: "b" } })).key, "recovery");
  assert.equal(src(robot({}, { goal: { x: 1, y: 2 } })).key, "fleet_goal");
  assert.equal(src(robot({}, { calibration: { label: "x" } })).key, "calibration");
});

test("another robot's console drive does not name this robot", () => {
  assert.equal(src(robot(), view({ manualDriveRobot: "b" })).key, "idle");
});

test("MANUAL mode alone never says who drives; moving makes it an attention item", () => {
  const still = src(robot({ mode: "MANUAL" }));
  assert.equal(still.key, "manual_unknown");
  assert.match(still.text, /조종 주체 확인 불가/);
  assert.equal(still.attention, false);
  const moving = src(robot({ mode: "MANUAL", velocity: { linear: 0.03, angular: 0 } }));
  assert.equal(moving.attention, true);
  assert.equal(moving.cls, "crit");
});

test("moving with no known owner is an attention item, never idle", () => {
  const mystery = src(robot({ velocity: { linear: 0.05, angular: 0 } }));
  assert.equal(mystery.key, "unowned");
  assert.equal(mystery.text, "원인 불명 이동");
  assert.equal(mystery.attention, true);
  const nav = src(robot({ mode: "NAVIGATION", navigation: "NAVIGATING", velocity: { linear: 0, angular: 0.2 } }));
  assert.equal(nav.text, "목표 주행 · 지시자 확인 불가");
  assert.equal(nav.attention, true);
});

test("stale state is not shown as live", () => {
  const r = robot({ mode: "MANUAL", velocity: { linear: 0.05, angular: 0 } }, { state_age_s: 9 });
  const out = src(r);
  assert.equal(out.key, "unknown");
  assert.match(out.text, /상태 \d+초 전 값/);
  assert.equal(out.attention, false);
  // the browser's own wait since the poll counts too
  assert.equal(motionSource(robot({}, { state_age_s: 2 }), view(), T0 + 4000).key, "unknown");
});

test("velocity evidence that is not fresh gives no verdict on motion", () => {
  const out = src(robot({ evidence: { velocity: { evidence: "delayed" } }, velocity: { linear: 0.1, angular: 0 } }));
  assert.equal(out.key, "unknown");
  assert.equal(out.text, "출처 확인 불가");
  assert.match(out.title, /속도 근거/);
  assert.equal(movingNow({ velocity: { linear: 0.1, angular: 0 } }, null), null);
});

test("offline, missing state and Fleet state loss are 확인 불가", () => {
  assert.equal(src(robot({}, { online: false })).key, "unknown");
  assert.equal(src({ robot_id: "a", online: true, state: null }).key, "unknown");
  assert.equal(src(robot(), view({ stateUnavailable: true })).text, "출처 확인 불가");
});

test("a proving source wins over a missing velocity, and stale still beats every source", () => {
  assert.equal(src(robot({ evidence: {}, trip_lease: { operator_name: "" } })).key, "trip");
  assert.equal(src(robot({ trip_lease: { operator_name: "" } }, { state_age_s: 30 })).key, "unknown");
});
