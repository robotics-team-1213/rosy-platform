// B1/B2 (arm-proposal-view.js): 예외 큐 선별, 작업 큐 행 글자, 제안자 자기 승인 잠금 — 순수 부분만.
import test from "node:test";
import assert from "node:assert/strict";
const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { armAttention, armProposalLine, selfApprovalReason, skillOf, WAITING_SKILLS } =
  await import("../../../../applications/fleet/web/work/arm-proposal-view.js");

const case_ = (id, lifecycle, extra = {}) => ({id, sample: true, title: `제안 ${id}`, lifecycle,
  requested_by: "operator-b", proposed_by: "decision-ai", evidence: [], candidates: [], ...extra});
const ALL = ["proposed", "waiting_approval", "approved", "running", "measured_success", "measured_failure",
  "stopped", "timed_out", "fallback_proposed"].map((lifecycle, index) =>
  case_(`arm-ai-${index + 1}`, lifecycle, lifecycle === "proposed" ? {blocking: false} : {}));
ALL[4].measured = "verify_placed";  // 측정 성공은 출처가 있어야 성공이다(D-293 4)

test("the exception queue takes only blocking waits and skill exceptions; normal and waiting rows stay out", () => {
  const rows = armAttention({sample: true, cases: [
    ...ALL,
    case_("arm-ai-block", "waiting_approval", {blocking: true, title: "적재 2단 · 로봇 대기"}),
    case_("arm-ai-lock", "measured_failure", {guard: "lock", title: "부하 든 채 실패"}),
  ]});
  assert.deepEqual(rows.map(row => [row.key, row.severity]), [
    ["arm-skill|arm-ai-6", "warn"],            // measured_failure
    ["arm-skill|arm-ai-7", "crit"],            // stopped = danger
    ["arm-skill|arm-ai-8", "warn"],            // timed_out
    ["arm-proposal|arm-ai-block", "warn"],     // blocking wait only
    ["arm-skill|arm-ai-lock", "crit"],         // a failure under lock is danger
  ]);
  assert.equal(rows[3].decision, "arm_proposal");
  assert.ok(rows[3].text.includes("승인 대기") && rows[3].text.includes("적재 2단"));
  assert.ok(rows[1].text.includes("정지 · HOLD"));
});

test("no feed, a null feed, or a feed without cases reads as no rows at all", () => {
  assert.deepEqual(armAttention(undefined), []);
  assert.deepEqual(armAttention(null), []);
  assert.deepEqual(armAttention({sample: true}), []);
  assert.deepEqual(armAttention({sample: true, cases: ALL.slice(2, 5)}), []);  // approved·running·측정 성공은 정상
});

test("work queue rows read the C20 state table words for all nine lifecycles", () => {
  assert.deepEqual(ALL.map(item => armProposalLine(item).replace(`팔 제안 · ${item.id} · `, "")), [
    "승인 대기", "승인 대기", "승인됨 · 시작 대기", "실행 중", "측정 성공", "측정 실패", "정지 · HOLD",
    "시간 초과 · HOLD", "대체 제안됨 · 승인 필요"]);
  assert.equal(armProposalLine(case_("r", "running", {step: {n: 3, of: 5}})), "팔 제안 · r · 실행 중 3/5");
  assert.equal(skillOf(case_("r", "running", {executor: "smolvla", policyId: "ACT v3", version: "a".repeat(64)}))
    .readout.find(row => row.label === "정책").value, "ACT v3@aaaaaaaa");
});

test("the proposer never approves their own proposal; a stranger may", () => {
  const item = case_("arm-ai-1", "waiting_approval", {requested_by: "bob", proposed_by: "decision-ai"});
  assert.equal(selfApprovalReason(item, "bob"), "제안자는 자기 제안을 승인할 수 없습니다");
  assert.equal(selfApprovalReason(item, "decision-ai"), "제안자는 자기 제안을 승인할 수 없습니다");
  assert.equal(selfApprovalReason(item, "carol"), "");
  assert.equal(selfApprovalReason(item, undefined), "");
});

test("waiting lifecycles are the approval seat; running and terminal states are not", () => {
  assert.deepEqual([...WAITING_SKILLS], ["proposed", "waiting_approval", "fallback_proposed"]);
});
