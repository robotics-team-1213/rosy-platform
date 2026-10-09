// D-540 (d): the robot card's trip gate, what 운행 취소 stops, the card line and the ended-trip queue row.
import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { cancelScope, cardTripLine, endedTripText, tripReason } = await import("../../fleet/server/web/card-trip.js");
const { createRoster } = await import("../../fleet/server/web/roster.js");

const robot = (estop = false, extra = {}) => ({ robot_id: "a", online: true, state: { safety: { estop } }, ...extra });
const ACTIVE = { version: 4, map: { places: [] } };

test("trip gate: Fleet state, role, named operator, link, E-stop, safety, active map — first reason wins", () => {
  const view = { stateUnavailable: false, activeSiteMap: ACTIVE };
  const named = "이름 있는 운영자 로그인이 필요합니다";
  assert.equal(tripReason(robot(), { view: { ...view, stateUnavailable: true }, operator: true, named: "" }), "Fleet 상태 확인 불가");
  assert.equal(tripReason(robot(), { view, operator: false, named }), "운영자 권한이 필요합니다");
  assert.equal(tripReason(robot(), { view, operator: true, named }), named);
  assert.equal(tripReason({ ...robot(), online: false }, { view, operator: true, named: "" }), "로봇 오프라인");
  assert.equal(tripReason(robot(true), { view, operator: true, named: "" }), "비상정지 중");
  assert.equal(tripReason(robot(null), { view, operator: true, named: "" }), "안전 상태 확인 불가");
  assert.equal(tripReason(robot(), { view: { ...view, activeSiteMap: null }, operator: true, named: "" }), "활성 현장 지도 없음");
  assert.equal(tripReason(robot(), { view, operator: true, named: "" }), "");
});

test("운행 취소 stops the open trip, else the goal and the lane driving that is on", () => {
  assert.deepEqual(cancelScope({ trip_id: "t1" }, "CAMERA_LINE"), { trip: "t1", lane: true, text: "진행 중인 운행을 취소합니다" });
  assert.equal(cancelScope({ trip_id: "t1" }, "OFF").lane, false);
  assert.equal(cancelScope(null, "CAMERA_LINE").lane, true);
  assert.equal(cancelScope(null, "IR_LINE").lane, true);
  assert.deepEqual(cancelScope(null, "OFF"), { trip: null, lane: false, text: "목표를 취소합니다" });
});

const LOST = { trip_id: "t0", robot_id: "a", state: "stopped", reason: "lease_lost",
  detail: { lease_reason: "taken_over", lease_by: "kim-tablet" } };

test("card line: lap for an open trip, the lease end reason after it stopped, nothing after arrive", () => {
  const traffic = { units: [], robots: [{ robot_id: "a", lap: 3, trip_state: "running" }] };
  assert.equal(cardTripLine({ traffic, trafficTrips: [{ robot_id: "a", trip_id: "t1" }], endedTrips: [LOST] }, "a"), "반복 운행 3바퀴째");
  const ended = { traffic: { units: [], robots: [] }, trafficTrips: [], endedTrips: [LOST] };
  assert.equal(cardTripLine(ended, "a"), "운행 멈춤 · 로봇 화면·Pilot에서 넘겨받음(kim-tablet)");
  assert.equal(endedTripText({ ...ended, endedTrips: [{ ...LOST, state: "arrived" }, LOST] }, "a"), "");
  assert.equal(endedTripText({ ...ended, endedTrips: [{ ...LOST, state: "canceled" }] }, "a"), "");
});

test("a stopped trip is a warn row (the card opens); a new open trip clears it", () => {
  const view = { robots: [], stateUnavailable: false, receivedAtMs: null, trafficTrips: [], endedTrips: [LOST] };
  const { attentionItems } = createRoster({ view, streamEvidence: () => null });
  assert.deepEqual(attentionItems(robot()).map((item) => `${item.severity}${item.text}`),
    ["warn: 운행 멈춤 · 로봇 화면·Pilot에서 넘겨받음(kim-tablet)"]);
  view.trafficTrips = [{ robot_id: "a", trip_id: "t2" }];
  assert.deepEqual(attentionItems(robot()), []);
});
