import test from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";

register("./resolve-console-assets.mjs", import.meta.url);

// ARM-CELL 팔 A/B 실행·복구 패널: 실제 실행은 같은 조건의 시험 실행이 성공한 다음에만, 복구 버튼은 준비 상태가 말할 때만.
const { DEFAULT_FORM, runParamsKey, runReason, armRecoveryActions, armReadinessText, jobErrorText, jobStateText, createCellJobPanel } =
  await import("/console/assets/cell-job-panel.js");

const FORM = { ...DEFAULT_FORM, model: "m1", proposer: "proposer-b" };

test("dry run is the default and needs a proposer and a model", () => {
  assert.equal(DEFAULT_FORM.dryRun, true);
  assert.match(runReason({ ...FORM, proposer: " " }), /제안자/);
  assert.match(runReason({ ...FORM, model: "" }), /모델/);
  assert.equal(runReason({ ...FORM, mode: "taught", model: "" }), "");
  assert.match(runReason({ ...FORM, maxChunks: 61 }), /1~60/);
  assert.equal(runReason(FORM), "");
});

test("a real run opens only after a passed dry run of the same params", () => {
  const real = { ...FORM, dryRun: false };
  assert.match(runReason(real), /시험 실행이 먼저/);
  const key = runParamsKey(FORM);
  assert.equal(runReason(real, { passedDryRunKey: key }), "");
  assert.match(runReason({ ...real, maxChunks: 2 }, { passedDryRunKey: key }), /시험 실행이 먼저/);
  assert.match(runReason({ ...real, paced: true }, { passedDryRunKey: key }), /시험 실행이 먼저/);
  assert.equal(runReason({ ...real, proposer: "someone-else" }, { passedDryRunKey: key }), "");
});

test("viewer, busy and running states lock the run", () => {
  assert.equal(runReason(FORM, { lockReason: "운영자 권한이 필요합니다" }), "운영자 권한이 필요합니다");
  assert.match(runReason(FORM, { busy: true }), /보내는 중/);
  assert.match(runReason(FORM, { running: true }), /실행 중/);
});

test("recovery buttons follow readiness", () => {
  assert.deepEqual(armRecoveryActions({ folded: true }), { recoverHold: false, safeHome: false });
  assert.deepEqual(armRecoveryActions({ folded: true, human_hold_latched: true }), { recoverHold: true, safeHome: false });
  assert.deepEqual(armRecoveryActions({ folded: false }), { recoverHold: false, safeHome: true });
  assert.deepEqual(armRecoveryActions({ incident_held: true, folded: true }), { recoverHold: false, safeHome: true });
  assert.deepEqual(armRecoveryActions({ folded: false, human_hold_latched: true, active_job_id: "j" }), { recoverHold: false, safeHome: false });
  assert.deepEqual(armRecoveryActions(undefined), { recoverHold: false, safeHome: false });
  assert.deepEqual(armRecoveryActions({ folded: null, state_unknown: { reason: "stale" } }), { recoverHold: false, safeHome: true });
  assert.deepEqual(armRecoveryActions({ folded: null, state_unknown: { reason: "board_missing" } }), { recoverHold: false, safeHome: false });
});

test("readiness and job lines are plain Korean", () => {
  const text = armReadinessText({ folded: true, human_hold_latched: false, incident_held: true, incident_reason: "torque off",
    session_lock_held: true, live_state_age_s: 1.25 }).join(" · ");
  assert.equal(text, "접힘 · 보류 없음 · 사건 보류: torque off · 세션 잠금 있음 · 관측 1.3초 전");
  assert.equal(jobStateText({ id: "j1", job: "safe_home", running: false, exit: 0 }), "safe_home 완료 (j1)");
  assert.equal(jobStateText({ id: "j1", job: "safe_home", running: false, exit: 2 }), "safe_home 실패: 종료 코드 2 (j1)");
});

test("an unknown arm state says why and when it was last seen, never folded", () => {
  const text = armReadinessText({ folded: null, state_unknown: { reason: "board_missing", last_observed_at: Date.now() / 1000 - 7200 } })[0];
  assert.match(text, /^알 수 없음 \(보드 없음 · 마지막 관측 2시간/);
  assert.equal(armReadinessText({ folded: null, state_unknown: { reason: "never_observed", last_observed_at: null } })[0],
    "알 수 없음 (관측 기록 없음)");
});

test("a refusal is shown as the cell said it", () => {
  assert.equal(jobErrorText({ status: 409, code: "PEER_ARM_NOT_FOLDED", message: "arm_b is not folded" }),
    "거절됨 (PEER_ARM_NOT_FOLDED): arm_b is not folded");
  assert.equal(jobErrorText({ status: 502, message: "HTTP 502" }), "거절됨: HTTP 502");
  assert.match(jobErrorText({ status: 403 }), /이름 있는 운영자/);
});

test("the panel polls a started dry run and then unlocks the same real run", async () => {
  const calls = [];
  let job = { id: "j1", job: "cell_policy_drive", running: true, exit: null };
  const call = async (path, opts = {}) => {
    calls.push([opts.method || "GET", path, opts.body ? JSON.parse(opts.body) : undefined]);
    if (path.endsWith("/options")) return { arms: ["arm_a", "arm_b"], models: [{ id: "m1", label: "m1" }] };
    if (path.endsWith("/readiness")) return { arms: { arm_a: { folded: true } } };
    if (opts.method === "POST") return { id: "j1" };
    return job;
  };
  const panel = createCellJobPanel({ call });
  await panel.refresh();
  const view = panel.view();
  assert.ok(view);
  assert.deepEqual(calls.map(([m, p]) => [m, p]), [["GET", "/api/fleet/cells/cell_ab/jobs/options"], ["GET", "/api/fleet/cells/cell_ab/jobs/readiness"]]);
  assert.equal(panel.sig() > 0, true);
  panel.set({ model: "m1", proposer: "proposer-b", maxChunks: 2 });
  await panel.runDry();
  assert.deepEqual(calls.at(-1), ["POST", "/api/fleet/cells/cell_ab/jobs/cell_policy_drive",
    { arm: "arm_a", proposer: "proposer-b", mode: "act", paced_chunks: false, max_chunks: 2, dry_run: true, model: "m1" }]);
  const real = { ...panel.state().form, dryRun: false };
  await panel.refresh();
  assert.match(runReason(real, { passedDryRunKey: panel.state().passedDryRunKey }), /시험 실행이 먼저/);
  job = { ...job, running: false, exit: 0 };
  await panel.refresh();
  assert.equal(panel.state().passedDryRunKey, runParamsKey(real));
  assert.equal(runReason(real, { passedDryRunKey: panel.state().passedDryRunKey }), "");
});
