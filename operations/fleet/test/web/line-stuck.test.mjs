import test from "node:test";
import assert from "node:assert/strict";

import {
  CAUSE_LABEL, DECISIONS, PHASE_LABEL, confirmText, decisionButtons, needsConfirm, outcomeText,
  pendingStucks, rearText, refusalText, resolverText, stuckFacts,
} from "../../fleet/server/web/line-stuck.js";

const STUCK = {
  stuck_id: "stuck-abc", cause: "obstacle_ahead", phase: "ASKING", held_s: 12.4,
  attempts: 0, max_attempts: 2, local_enabled: true, robot_online: true,
  front_clearance_m: 0.123, rear_clearance_m: 0.31, turn_clearance_m: null, preview_seq: 812,
};
const byDecision = (buttons) => Object.fromEntries(buttons.map((b) => [b.decision, b]));

test("only robots with an open stuck are pending", () => {
  const robots = [{ robot_id: "a", line_stuck: STUCK }, { robot_id: "b", line_stuck: null },
    { robot_id: "c" }, { robot_id: "d", line_stuck: { stuck_id: "" } }];
  assert.deepEqual(pendingStucks(robots).map((r) => r.robot_id), ["a"]);
  assert.deepEqual(pendingStucks(undefined), []);
});

test("five answers in CORE order with Korean labels; RESUME and BACK_AND_RETRY confirm", () => {
  assert.deepEqual(DECISIONS, ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]);
  const buttons = decisionButtons(STUCK, { operator: true });
  assert.deepEqual(buttons.map((b) => b.label), ["대기", "재개", "후진 후 재시도", "수동", "중단"]);
  assert.deepEqual(buttons.filter((b) => b.confirm).map((b) => b.decision), ["RESUME", "BACK_AND_RETRY"]);
  assert.ok(buttons.every((b) => b.reason === ""));
  assert.equal(needsConfirm("WAIT"), false);
  assert.equal(needsConfirm("ABORT"), false);
});

test("BACK_AND_RETRY is disabled when local recovery is off or attempts are spent", () => {
  const off = byDecision(decisionButtons({ ...STUCK, local_enabled: false }, { operator: true }));
  assert.match(off.BACK_AND_RETRY.reason, /로컬 복구가 꺼져/);
  assert.equal(off.RESUME.reason, "");
  const spent = byDecision(decisionButtons({ ...STUCK, attempts: 2 }, { operator: true }));
  assert.match(spent.BACK_AND_RETRY.reason, /모두 썼습니다/);
});

test("a viewer, an unreachable robot or an answer in flight blocks every button", () => {
  for (const [stuck, options, pattern] of [
    [STUCK, { operator: false }, /운영자 권한/],
    [{ ...STUCK, robot_online: false }, { operator: true }, /연결이 끊겼습니다/],
    [STUCK, { operator: true, busy: true }, /보내는 중/],
  ]) {
    for (const button of decisionButtons(stuck, options)) assert.match(button.reason, pattern);
  }
});

test("facts show clearances in metres, unknowns as a dash, and the preview seq", () => {
  const facts = Object.fromEntries(stuckFacts(STUCK).map(([key, , value]) => [key, value]));
  assert.equal(facts.front, "0.12 m");
  assert.equal(facts.turn, "—");
  assert.equal(facts.held, "12 s");
  assert.equal(facts.attempts, "0/2");
  assert.equal(facts.preview, "#812");
  assert.ok(!stuckFacts({ ...STUCK, preview_seq: null }).some(([key]) => key === "preview"));
});

test("an empty rear band reads 비어 있음, an unknown one 알 수 없음 (D-407 re-run C)", () => {
  assert.equal(rearText({ rear_clearance_m: 0.31, rear_state: "clear" }), "0.31 m");
  assert.equal(rearText({ rear_clearance_m: null, rear_state: "clear" }), "비어 있음");
  assert.equal(rearText({ rear_clearance_m: null, rear_state: "unknown" }), "알 수 없음");
  assert.equal(rearText({ rear_clearance_m: null }), "알 수 없음");
  const rear = stuckFacts({ ...STUCK, rear_clearance_m: null, rear_state: "unknown" })
    .find(([key]) => key === "rear");
  assert.equal(rear[2], "알 수 없음");
  assert.equal(rear[3], "stuck-fact-unknown");
  const empty = stuckFacts({ ...STUCK, rear_clearance_m: null, rear_state: "clear" })
    .find(([key]) => key === "rear");
  assert.equal(empty[2], "비어 있음");
  assert.equal(empty[3], undefined);
});

test("causes and phases read as operator Korean", () => {
  assert.equal(CAUSE_LABEL.obstacle_ahead, "앞 물체로 멈춤");
  assert.equal(CAUSE_LABEL.lane_lost, "차선을 잃고 멈춤");
  for (const phase of ["ASKING", "WAITING_CONSOLE", "BACKING", "SETTLING"]) assert.ok(PHASE_LABEL[phase]);
});

test("the confirm step names the robot and the risk", () => {
  assert.match(confirmText("rosy_01", "RESUME"), /^rosy_01 재개 — 앞이 비었는지/);
  assert.match(confirmText("rosy_01", "BACK_AND_RETRY"), /뒤가 비었습니까/);
  assert.equal(confirmText("rosy_01", "WAIT"), "");
});

test("CORE refusals keep their code and message verbatim", () => {
  const late = refusalText("rosy_01", "RESUME", {
    code: "STUCK_ID_MISMATCH", status: 409, message: "no open stuck with this id (late or wrong answer)" });
  assert.match(late, /이미 닫혔거나 바뀐 막힘/);
  assert.ok(late.endsWith("(STUCK_ID_MISMATCH: no open stuck with this id (late or wrong answer))"));
  const resume = refusalText("rosy_01", "RESUME", {
    code: "STUCK_DECISION_REFUSED", status: 409, message: "RESUME refused: object_within_stop_distance" });
  assert.match(resume, /정지 거리 안에 아직 물체가 있습니다/);
  assert.match(resume, /RESUME refused: object_within_stop_distance/);
  const unknown = refusalText("rosy_01", "BACK_AND_RETRY", {
    code: "STUCK_DECISION_REFUSED", status: 409, message: "BACK_AND_RETRY refused: new_reason" });
  assert.match(unknown, /CORE가 거부했습니다 \(STUCK_DECISION_REFUSED: BACK_AND_RETRY refused: new_reason\)/);
  assert.match(refusalText("rosy_01", "ABORT", { status: 403, code: "FORBIDDEN", message: "operator role required" }),
    /운영자 권한/);
});

test("transport failures say not delivered or outcome unknown, never refused", () => {
  const unreachable = refusalText("rosy_01", "ABORT", { status: 502, code: "ROBOT_UNREACHABLE",
    message: "answer not delivered: the robot could not be reached" });
  assert.match(unreachable, /^rosy_01 중단 전달 실패 — 로봇에 닿지 않아/);
  const unknown = refusalText("rosy_01", "RESUME", { status: 502, code: "STUCK_DECISION_OUTCOME_UNKNOWN",
    message: "the robot did not reply; CORE may have applied the answer. Re-read the stuck before answering again" });
  assert.match(unknown, /^rosy_01 재개 결과 불명 — /);
  assert.match(unknown, /이미 적용했을 수 있으니 막힘 상태를 다시 확인/);
  assert.match(unknown, /\(STUCK_DECISION_OUTCOME_UNKNOWN: the robot did not reply/);
});

test("accepted answers say what the robot will do", () => {
  assert.match(outcomeText("rosy_01", "WAIT", { outcome: "hold" }), /^rosy_01 대기: 대기로 답했습니다/);
  // D-398: 보이는 글에서 맨 열거값을 뺐다 — 중단 문장 자체가 뜻을 말한다.
  assert.match(outcomeText("rosy_01", "ABORT", { outcome: "idle" }), /차선 추종을 중단했습니다/);
  assert.doesNotMatch(outcomeText("rosy_01", "ABORT", { outcome: "idle" }), /IDLE/);
  assert.match(outcomeText("rosy_01", "MANUAL", {}), /CORE가 받았습니다/);
});

test("resolverText says what the Fleet resolver did, or why a human is needed", () => {
  assert.equal(resolverText(null), "");
  assert.equal(resolverText({ tier: "rule", rule: "R2", decision: "BACK_AND_RETRY", escalated: null }),
    "자동 판단 R2: 후진 후 재시도");
  assert.equal(resolverText({ tier: "human", escalated: "no_rule" }),
    "자동 판단 불가 — 사람 확인 필요 (맞는 규칙 없음)");
  assert.equal(resolverText({ tier: "human", escalated: "calibration" }),
    "자동 판단 불가 — 사람 확인 필요 (보정 중)");
  assert.equal(resolverText({ tier: "human", escalated: "core:ROBOT_UNREACHABLE" }),
    "자동 판단 불가 — 사람 확인 필요 (CORE 응답 ROBOT_UNREACHABLE)");
  assert.equal(resolverText({ tier: "human", escalated: "human_claimed" }), "운영자가 맡음");
});

test("D-540 9: an unnamed operator may WAIT or ABORT but not answer with motion", () => {
  const named = "이름 있는 운영자 로그인이 필요합니다";
  const buttons = byDecision(decisionButtons(STUCK, { operator: true, namedReason: named }));
  assert.equal(buttons.WAIT.reason, "");
  assert.equal(buttons.ABORT.reason, "");
  for (const decision of ["RESUME", "BACK_AND_RETRY", "MANUAL"]) assert.equal(buttons[decision].reason, named);
  assert.match(refusalText("rosy_01", "RESUME", { status: 403, code: "OPERATOR_IDENTITY_REQUIRED", message: "" }),
    /이름 있는 운영자 로그인이 필요합니다/);
});
