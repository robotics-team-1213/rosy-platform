import test from "node:test";
import assert from "node:assert/strict";

const {cellHoldActive, pauseSummary, resumeLockReason, decisionLockReason, RESUME_REFUSALS} =
  await import("../../../../applications/fleet/web/work/cell-resume-view.js");

test("cellHoldActive detects cell hold from human_safety or gate phase", () => {
  const heldFlag = {human_safety: {human_detected: {cell_s: true, cell_ab: false}, active_estop: false}, cells: {}};
  assert.equal(cellHoldActive(heldFlag, "cell_s"), true);
  assert.equal(cellHoldActive(heldFlag, "cell_ab"), false);

  const heldGate = {human_safety: {human_detected: {cell_s: false}}, cells: {cell_ab: {gate: {phase: "HUMAN_HOLD"}}}};
  assert.equal(cellHoldActive(heldGate, "cell_ab"), true);

  const cleared = {
    human_safety: {human_detected: {cell_s: false, cell_ab: false, all: false}, active_estop: false},
    cells: {cell_s: {gate: {phase: "RELEASED", reason: "HUMAN_CLEARED_AWAITING_RESUME"}}},
  };
  assert.equal(cellHoldActive(cleared, "cell_s"), false);
  assert.equal(cellHoldActive(cleared), false);
});

test("pauseSummary shows who paused, why, and prior task status", () => {
  const summary = pauseSummary(
    {task_id: "t1", cell_id: "cell_s", paused_by: "alice", paused_reason: "HUMAN_DETECTED_ESTOP", paused_from_status: "RUNNING"},
    {},
  );
  assert.match(summary, /일시중지: alice/);
  assert.match(summary, /사람 감지 비상정지/);
  assert.match(summary, /이전 RUNNING/);

  const clearedSummary = pauseSummary(
    {task_id: "t2", cell_id: "cell_s"},
    {cells: {cell_s: {gate: {reason: "HUMAN_CLEARED_AWAITING_RESUME"}}}},
  );
  assert.match(clearedSummary, /홀드 해제됨 · 작업별 재개 대기/);
});

test("resumeLockReason blocks resume while cell hold is active, busy, unauthorized, or refused", () => {
  const task = {task_id: "t1", cell_id: "cell_s", status: "PAUSED_HUMAN"};
  const held = {human_safety: {human_detected: {cell_s: true}}};
  const cleared = {human_safety: {human_detected: {cell_s: false}}, cells: {cell_s: {gate: {phase: "RELEASED"}}}};

  assert.match(resumeLockReason(task, held, {}), /셀 홀드 활성 중/);
  assert.equal(resumeLockReason(task, cleared, {busy: true}), "요청 처리 중입니다");
  assert.equal(resumeLockReason(task, cleared, {approveReason: "기명 운영자 로그인 필요"}), "기명 운영자 로그인 필요");
  assert.equal(resumeLockReason(task, cleared, {refusal: RESUME_REFUSALS.HUMAN_HOLD_ACTIVE}), RESUME_REFUSALS.HUMAN_HOLD_ACTIVE);
  assert.equal(resumeLockReason(task, cleared, {}), "");
});

test("decisionLockReason enforces proposer != approver self-approval lock", () => {
  const proposal = {decision_id: "dec-1", proposed_by: "bob"};
  assert.equal(decisionLockReason(proposal, {principal: "bob"}), RESUME_REFUSALS.PROPOSER_IS_APPROVER);
  assert.equal(decisionLockReason(proposal, {principal: "alice"}), "");
  assert.equal(decisionLockReason(proposal, {principal: "alice", approveReason: "운영자 로그인 필요"}), "운영자 로그인 필요");
});

test("clear/resume bodies carry the note; restart flag only after the confirm", async () => {
  const m = await import("../../../../applications/fleet/web/work/cell-resume-view.js");
  assert.deepEqual(m.clearBody("cell_s", "사람 나감"), {cell_id: "cell_s", note: "사람 나감"});
  assert.deepEqual(m.resumeBody("확인"), {note: "확인"});
  assert.deepEqual(m.resumeBody("확인", true), {note: "확인", restart_from_start: true});
  assert.equal(m.needsRestartConfirm({code: "RESUME_NEEDS_RESTART_CONFIRM"}), true);
  assert.equal(m.needsRestartConfirm({code: "NOTE_REQUIRED"}), false);
  assert.equal(m.NOTE_MAX, 200);
  for (const code of ["CELL_ABORTED_HOLD", "ARM_HOLD_ACTIVE", "HUMAN_HOLD_ACTIVE", "NOTE_REQUIRED", "PROPOSER_IS_APPROVER"]) {
    assert.match(m.RESUME_REFUSALS[code], /[가-힣]/, code);
  }
});

test("decision proposals are keyed by the server's decision_id", () => {
  const prop = {decision_id: "d1", proposed_by: "ai", cell: "cell_s"};
  assert.equal(decisionLockReason(prop, {principal: "ai"}), RESUME_REFUSALS.PROPOSER_IS_APPROVER);
  assert.equal(decisionLockReason(prop, {principal: "kim"}), "");
});
