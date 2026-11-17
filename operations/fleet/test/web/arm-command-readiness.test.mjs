import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);

const { armCommandReadiness, armCameraSpecs, armRobotProfile, buildDockEntries, summarizeFleetProfiles } = await import(
  "../../../../applications/fleet/web/robot/robot-panel-adapters.js"
);

test("armCommandReadiness checks every gate in priority order and returns 명령 가능 only when all pass", () => {
  const base = {
    operator: true,
    named: true,
    live: { available: true, stale: false, age_s: 0.4 },
    hold: { held: false },
    humanSafety: false,
    gatePhase: "IDLE",
    ownerConnected: true,
  };
  assert.deepEqual(armCommandReadiness(base), { ok: true, reason: "명령 가능" });
  assert.equal(armCommandReadiness({ ...base, operator: false }).reason, "기명 운영자만 가능");
  assert.equal(armCommandReadiness({ ...base, named: false }).reason, "기명 운영자만 가능");
  assert.match(armCommandReadiness({ ...base, live: null }).reason, /^연결 끊김/);
  assert.match(armCommandReadiness({ ...base, live: { available: false, age_s: 12 } }).reason, /연결 끊김 · 12초 전 값/);
  assert.match(armCommandReadiness({ ...base, live: { available: true, stale: true, age_s: 8 } }).reason, /상태 지연 · 8초 전/);
  assert.equal(armCommandReadiness({ ...base, humanSafety: true }).reason, "사람 감지 정지 중 · 현장 확인 필요");
  assert.match(armCommandReadiness({ ...base, hold: { held: true, reason: "충돌 감지" } }).reason, /홀드 중 · 충돌 감지/);
  assert.equal(armCommandReadiness({ ...base, gatePhase: "RUNNING" }).reason, "셀 RUNNING · 명령 불가");
  assert.equal(armCommandReadiness({ ...base, ownerConnected: false }).reason, "실물 실행 경로 미연결");

  // Priority: unnamed operator beats disconnect & human safety
  assert.equal(armCommandReadiness({ operator: false, live: null, humanSafety: true, hold: { held: true } }).reason, "기명 운영자만 가능");
  // Disconnect beats human safety
  assert.match(armCommandReadiness({ operator: true, named: true, live: null, humanSafety: true }).reason, /^연결 끊김/);
  // Human safety beats hold and gate phase
  assert.equal(armCommandReadiness({ ...base, humanSafety: true, hold: { held: true }, gatePhase: "RUNNING" }).reason, "사람 감지 정지 중 · 현장 확인 필요");
});

test("armCameraSpecs excludes side camera on arm_s (cell_s) and includes it on arm_a/arm_b", () => {
  assert.deepEqual(armCameraSpecs("arm_s").map((c) => c.source), ["arm_s_top", "arm_s_wrist"]);
  assert.deepEqual(armCameraSpecs("arm_a").map((c) => c.source), ["top", "side", "arm_a_wrist"]);
  assert.deepEqual(armCameraSpecs("arm_b").map((c) => c.source), ["top", "side", "arm_b_wrist"]);
});

test("buildDockEntries combines Pinky and OMX arm profiles and summarizes health", () => {
  const view = {
    robots: [
      { robot_id: "rosy_42", online: true, state_age_s: 0.3, state: { safety: { estop: false } }, power_health: { battery: { percent: 80 } } },
      { robot_id: "rosy_45", online: false, state_age_s: 12, state: null },
    ],
    trafficTrips: [],
    receivedAtMs: Date.now(),
  };
  const plan = {
    omx_cells: { cell_s: { gate: { phase: "IDLE" } }, cell_ab: { gate: { phase: "IDLE" } } },
    arm_live_states: { arm_s: { available: true, stale: false, age_s: 0.2 }, arm_a: { available: true, stale: false, age_s: 0.2 } },
    arm_holds: { arm_s: { held: true, reason: "점검" } },
    human_safety: {},
  };
  const entries = buildDockEntries(view, plan);
  assert.deepEqual(entries.map((e) => e.profile.id), ["rosy_42", "rosy_45", "arm_s", "arm_a", "arm_b"]);
  assert.equal(armRobotProfile("arm_b", plan, view).link.state, "unavailable");
  assert.equal(summarizeFleetProfiles(entries), "로봇 5대 · 정상 2 · 주의 1 · 끊김 2");
});

test("armRobotProfile reads active omx_cell_tasks from charge-bays and ignores terminal GOAL_CONFIRMED", () => {
  const plan = {
    omx_cells: { cell_s: { gate: { phase: "BUSY" } }, cell_ab: { gate: { phase: "IDLE" } } },
    arm_live_states: { arm_s: { available: true, online: true, age_s: 0.2 }, arm_a: { available: true, online: true, age_s: 0.2 } },
    omx_cell_tasks: [
      { task_id: "cell-task-1", cell_id: "cell_s", arm_id: "arm_s", status: "RUNNING" },
      { task_id: "cell-task-old", cell_id: "cell_ab", arm_id: "arm_a", status: "GOAL_CONFIRMED" },
      { task_id: "cell-task-a-live", cell_id: "cell_ab", arm_id: "arm_a", status: "RUNNING" },
    ],
  };
  const armS = armRobotProfile("arm_s", plan, {});
  const armA = armRobotProfile("arm_a", plan, {});
  const armB = armRobotProfile("arm_b", plan, {});
  assert.equal(armS.detail.activeTask?.task_id, "cell-task-1");
  assert.equal(armS.task.text, "cell-task-1 · RUNNING");
  assert.equal(armA.detail.activeTask?.task_id, "cell-task-a-live");
  assert.equal(armB.detail.activeTask, null);
});

test("armRobotProfile shows the Korean cell phase, never the raw gate.phase (D-540)", () => {
  const plan = (phase) => ({ omx_cells: { cell_s: { gate: { phase } } }, arm_live_states: { arm_s: { available: true, online: true, age_s: 0.2 } } });
  assert.equal(armRobotProfile("arm_s", plan("IDLE"), {}).task.text, "대기 중");
  assert.equal(armRobotProfile("arm_s", plan("ARM_IN_BED_ZONE"), {}).task.text, "OMX 작업 중 · AMR 잠금");
  assert.equal(armRobotProfile("arm_s", plan("UNKNOWN_PHASE"), {}).task.text, "대기");
  assert.equal(armRobotProfile("arm_s", plan(undefined), {}).task.text, "대기");
});
