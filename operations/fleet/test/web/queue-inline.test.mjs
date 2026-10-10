// D-540 3 — queue rows open into their decision; robot cards fold to one line unless they must not.
import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { cardExpanded, createRoster, mustExpand } = await import("../../fleet/server/web/roster.js");
const { openDecisionKey, queueRowText } = await import("../../fleet/server/web/queues.js");
const { replanView } = await import("../../fleet/server/web/trip-replan.js");

const nominal = (extra = {}) => ({ robot_id: "a", online: true, state: { safety: { estop: false } }, ...extra });

test("the four must-expand states: offline, E-stop latched, safety not nominal, calibration", () => {
  assert.equal(mustExpand(nominal()), false);
  assert.equal(mustExpand(nominal({ online: false })), true);
  assert.equal(mustExpand(nominal({ state: null })), true);                          // no state = offline
  assert.equal(mustExpand(nominal({ state: { safety: { estop: true } } })), true);    // latched
  assert.equal(mustExpand(nominal({ state: { safety: {} } })), true);                 // safety unknown
  assert.equal(mustExpand(nominal({ state: {} })), true);
  assert.equal(mustExpand(nominal({ calibration: { label: "카메라 보정", holder: "kim" } })), true);
});

test("a must-expand card stays open even after the operator folds it", () => {
  const folded = { open: false, attention: ": 비상 정지 걸림" };
  assert.equal(cardExpanded({ must: true, selected: false, attention: ": 비상 정지 걸림", choice: folded }), true);
});

test("nominal folds, exception opens, the operator's fold holds until the exceptions change", () => {
  assert.equal(cardExpanded({ must: false, selected: false, attention: "", choice: undefined }), false);
  assert.equal(cardExpanded({ must: false, selected: true, attention: "", choice: { open: false, attention: "" } }), true);
  assert.equal(cardExpanded({ must: false, selected: false, attention: ": 교통 대기", choice: undefined }), true);
  const folded = { open: false, attention: ": 교통 대기" };
  assert.equal(cardExpanded({ must: false, selected: false, attention: ": 교통 대기", choice: folded }), false);
  assert.equal(cardExpanded({ must: false, selected: false, attention: ": 교통 대기|: 목표 실패", choice: folded }), true);
  assert.equal(cardExpanded({ must: false, selected: false, attention: "", choice: { open: true, attention: "" } }), true);
});

test("one queue row is open: the operator's pick while it lives, else the most urgent decision", () => {
  const keys = ["a|stuck", "b|replan"];
  assert.equal(openDecisionKey(keys, null), "a|stuck");
  assert.equal(openDecisionKey(keys, { key: "b|replan", open: true }), "b|replan");
  assert.equal(openDecisionKey(keys, { key: "a|stuck", open: false }), null);
  assert.equal(openDecisionKey(keys, { key: "gone|stuck", open: true }), "a|stuck");
  assert.equal(openDecisionKey([], null), null);
});

const view = { robots: [], formation: null, stateUnavailable: false, receivedAtMs: Date.now(), trafficTrips: [] };
const { attentionItems } = createRoster({ view, streamEvidence: () => null });

test("an offline stuck robot keeps its decision row after the disconnect row", () => {
  const items = attentionItems({ robot_id: "a", online: false, state: null, line_stuck: { stuck_id: "s" } });
  assert.deepEqual(items.map((item) => [item.severity, item.decision]), [["warn", undefined], ["crit", "stuck"]]);
});

test("a trip held for a changed route is a critical replan row; a running trip is not", () => {
  view.trafficTrips = [{ trip_id: "t1", robot_id: "a", hold: { reason: "replan", plan: { places: [] } } },
    { trip_id: "t2", robot_id: "b", hold: null }];
  assert.deepEqual(attentionItems(nominal()).filter((item) => item.decision).map((item) => item.decision), ["replan"]);
  assert.equal(attentionItems(nominal({ robot_id: "b" })).length, 0);
  view.trafficTrips = [];
});

test("replan slot: confirm needs an operator and a plan; cancel (a stop) needs only an operator", () => {
  const held = { trip_id: "t1", robot_id: "a",
    hold: { reason: "replan", plan: { places: ["p1", "p2"] }, length_m: 3.14, eta_s: 41.6 } };
  assert.deepEqual(replanView(held, { operator: true }),
    { facts: "바뀐 경로 3.1 m · 약 42초 · 장소 2곳", confirmReason: "", cancelReason: "" });
  assert.equal(replanView(held, { operator: false }).confirmReason, "운영자 권한이 필요합니다");
  assert.equal(replanView(held, { operator: true, busy: true }).cancelReason, "답을 보내는 중");
  const named = replanView(held, { operator: true, named: "이름 있는 운영자 로그인이 필요합니다" });
  assert.equal(named.confirmReason, "이름 있는 운영자 로그인이 필요합니다");  // a move (D-540 9)
  assert.equal(named.cancelReason, "");                                   // a stop stays open
  const failed = { ...held, hold: { reason: "lap", plan: null, code: "PLAN_NO_ROUTE" } };
  const spec = replanView(failed, { operator: true });
  assert.equal(spec.confirmReason, "다시 계산한 경로가 없습니다");
  assert.equal(spec.cancelReason, "");
  assert.match(spec.facts, /PLAN_NO_ROUTE/);
});

test("a later row of the same robot hides the name and its colon", () => {
  // Field check 2026-10-10: ": Rosy Cam이 rosy_41를 찾지 못합니다" started with a bare colon.
  assert.equal(queueRowText(": 교통 대기", true), ": 교통 대기");
  assert.equal(queueRowText(": Rosy Cam이 rosy_41을 찾지 못합니다", false), "Rosy Cam이 rosy_41을 찾지 못합니다");
});
