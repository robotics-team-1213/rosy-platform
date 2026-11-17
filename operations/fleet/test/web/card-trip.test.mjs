// D-540 (d): the robot card's trip gate, what 운행 취소 stops, the card line and the ended-trip queue row.
import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { cancelScope, cardTripLine, cardTripSig, endedTripText, tripReason } = await import("../../../../applications/fleet/web/card-trip.js");
const { createSelection } = await import("../../../../shared/web/selection.js");
const { createRoster, selectRobot } = await import("../../../../applications/fleet/web/robot/roster.js");

const robot = (estop = false, extra = {}) => ({ robot_id: "a", online: true, state: { safety: { estop } }, ...extra });
const ACTIVE = { version: 4, map: { places: [] } };

test("workspace inspection never arms a goal and a different robot withdraws goal, pin and cursor", () => {
  const view = { robots: [robot(), { ...robot(), robot_id: "b" }], robotSelection: createSelection(null), selected: null, pinning: null, cursor: null };
  assert.equal(selectRobot(view, "a"), true);
  assert.equal(view.robotSelection.get(), "a");
  assert.equal(view.selected, null);
  Object.assign(view, { selected: "a", pinning: "a", cursor: { col: 4, row: 5 } });
  assert.equal(selectRobot(view, "a"), false);  // polling the same selection does not withdraw an explicit arm
  assert.equal(view.selected, "a");
  assert.equal(selectRobot(view, "missing"), false);
  assert.equal(view.robotSelection.get(), "a");
  assert.equal(selectRobot(view, "b"), true);
  assert.deepEqual([view.robotSelection.get(), view.selected, view.pinning, view.cursor], ["b", null, null, null]);
  assert.equal(selectRobot(view, null), true);
  assert.equal(view.robotSelection.get(), null);
});

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

test("trip gate explains formation conflicts without blocking unrelated robots", () => {
  const view = {activeSiteMap: ACTIVE, formation: {active: true, leader: 'a', assignment: {b: 0}}};
  const reason = id => tripReason(robot(false, {robot_id: id}), {view, operator: true, named: ''});
  assert.match(reason('a'), /대형.*해제/);
  assert.match(reason('b'), /대형.*해제/);
  assert.equal(reason('c'), '');
});

// 회귀(운행 폼이 다시 그려지지 않음): 서명은 그린 시점의 상태로 계산한다. 폼의 모든 표시 값이
// 서명을 움직여야 하고, 안 바뀐 상태는 같은 서명을 줘야 다시 그림 판정이 변하지 않는다.
test("cardTripSig reads the live form: every shown value moves it, unchanged state does not", () => {
  const now = 1000;
  const form = { robotId: "a", kind: "route", to: "A", start: "", lapStart: "", via: "",
    plan: null, lapPlan: null, busy: false, note: null, rule: null };
  assert.equal(cardTripSig(null, now), "");  // no form open: the panel drops the form
  const opened = cardTripSig(form, now);
  assert.notEqual(opened, "");
  form.plan = { plan_id: "p2", expires_at: now + 30 };  // '경로 보기' answer lands
  assert.notEqual(cardTripSig(form, now), opened);  // (a) 계획 도착 → 다시 그림
  const planned = cardTripSig(form, now);
  form.busy = true;
  assert.notEqual(cardTripSig(form, now), planned);  // (b) busy 토글
  form.busy = false;
  form.rule = { kind: "return", values: { percent: 20 }, answer: null, note: null, busy: false, draft: false };
  const ruled = cardTripSig(form, now);
  form.rule.kind = "departure";
  assert.notEqual(cardTripSig(form, now), ruled);  // (c) 규칙 종류 변경
  form.rule.kind = "return";
  form.rule.note = "판정을 받지 못했습니다. 다시 눌러 주세요.";
  assert.notEqual(cardTripSig(form, now), ruled);  // (d) 판정 실패
  form.rule.note = null;
  form.rule.answer = { verdict: "go", reason: "within_rules", rules_source: "active" };
  assert.notEqual(cardTripSig(form, now), ruled);  // 판정 answer
  form.rule.answer = null;
  assert.equal(cardTripSig(form, now), ruled);  // 같은 상태로 돌아오면 같은 서명 (순수 함수)
  const idle = cardTripSig(form, now);
  assert.equal(cardTripSig(form, now + 1), idle);  // (e) 아무 변화 없음 → 동일
  assert.notEqual(cardTripSig(form, now + 60), idle);  // 계획 만료(시작 직전 만료 재확인)도 화면에 닿는다
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
  const { attentionItems } = createRoster({ scope: {onDispose() {}, interval() {}}, view, streamEvidence: () => null });
  assert.deepEqual(attentionItems(robot()).map((item) => `${item.severity}${item.text}`),
    ["warn: 운행 멈춤 · 로봇 화면·Pilot에서 넘겨받음(kim-tablet)"]);
  view.trafficTrips = [{ robot_id: "a", trip_id: "t2" }];
  assert.deepEqual(attentionItems(robot()), []);
});

test("D-763 8: the card line shows Fleet's wait; past its bound a warn row, no 개입 (rev 2 Q7)", () => {
  const wait = (reason, waiting, over_bound = !waiting) => ({ robot_id: "a", trip_id: "t3", state: "running", wait: { reason, waiting, over_bound } });
  const traffic = { units: [], robots: [{ robot_id: "a", lap: 3 }] };
  assert.equal(cardTripLine({ traffic, trafficTrips: [wait("crosswalk_look", true)] }, "a"), "대기 · 횡단보도");
  assert.equal(cardTripLine({ traffic, trafficTrips: [wait("signal", true)] }, "a"), "대기 · 신호");
  assert.equal(cardTripLine({ traffic, trafficTrips: [wait("signal", false, false)] }, "a"), "반복 운행 3바퀴째");
  const view = { robots: [], stateUnavailable: false, receivedAtMs: null, trafficTrips: [wait("authority", true)], endedTrips: [] };
  const { attentionItems } = createRoster({ scope: {onDispose() {}, interval() {}}, view, streamEvidence: () => null });
  assert.deepEqual(attentionItems(robot()), []);  // a wait within its bound is no exception
  view.trafficTrips = [wait("crosswalk_wait", false)];
  assert.deepEqual(attentionItems(robot()).map((item) => `${item.severity}${item.text}`),
    ["warn: 대기 상한 넘음 · 횡단보도"]);
  assert.equal(cardTripLine({ traffic, trafficTrips: [wait("signal", false)] }, "a"), "대기 상한 넘음 · 신호");
});
