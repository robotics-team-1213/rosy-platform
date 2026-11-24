import test from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";

register("./resolve-console-assets.mjs", import.meta.url);

const { canonicalArmId, normalizeWorkcellObservations, isArmAttentionOrLive } = await import(
  "/console/assets/cell-cockpit-stage.js"
);
const { activeCellWorkRows } = await import(
  "/console/assets/cell-context-panel.js"
);

test("canonicalArmId normalizes omx_ and _follower affixes", () => {
  assert.equal(canonicalArmId("omx_arm_a"), "arm_a");
  assert.equal(canonicalArmId("arm_s_follower"), "arm_s");
  assert.equal(canonicalArmId(" OMX_Arm_B_Follower "), "arm_b");
});

test("normalizeWorkcellObservations keeps fresh metrics and redacts stale positions", () => {
  const obs = normalizeWorkcellObservations(
    {
      workcells: [
        {
          arms: [
            {
              arm_id: "omx_arm_a",
              source_id: "arm_a_follower",
              label: "Arm A",
              fresh: true,
              source_age_s: 0.4,
              positions: { joint1: 0, joint2: -Math.PI / 6, gripper_joint_1: 0.02 },
              motor_health: {
                schema_version: "rosy.motor-health.v1",
                status: "warn",
                motors: [
                  { temperature_c: 48, pwm_utilization: 0.62, current_ma: -450, warnings: ["warm"] },
                ],
              },
              incidents: [
                { state: "open", decision: { hold: true } },
                { state: "cleared", decision: { hold: true } },
              ],
            },
            {
              arm_id: "arm_s",
              label: "Arm S",
              fresh: false,
              positions: { joint1: 0, joint2: 0 },
              motor_health: {
                schema_version: "rosy.motor-health.v1",
                status: "fault",
                motors: [{ hardware_error: 2, temperature_c: 55, pwm: 400, pwm_limit: 500 }],
              },
            },
          ],
          cameras: [
            { source_id: "omx_wrist_a", role: "wrist", stream: "color", arm_id: "omx_arm_a", fresh: true },
            { source_id: "omx_side_depth", role: "side", stream: "depth", fresh: false },
            { source_id: "omx_overhead", role: "overhead", stream: "color", fresh: true },
            { source_id: "omx_side", role: "side", stream: "color", fresh: true },
          ],
        },
      ],
    },
    12345,
  );

  assert.equal(obs.receivedAtMs, 12345);
  assert.equal(obs.arms.length, 2);

  const armA = obs.arms[0];
  assert.equal(armA.id, "arm_a");
  assert.equal(armA.fresh, true);
  assert.match(armA.jointsText, /J1:0\.0°/);
  assert.match(armA.jointsText, /J2:-30\.0°/);
  assert.equal(armA.maxTempC, 48);
  assert.equal(armA.maxPwmPct, 62);
  assert.equal(armA.maxCurrentMa, 450);
  assert.equal(armA.held, true);
  assert.equal(armA.openIncidents.length, 1);

  const armS = obs.arms[1];
  assert.equal(armS.fresh, false);
  assert.equal(armS.positions, null);
  assert.equal(armS.jointsDeg, null);
  assert.equal(armS.jointsText, null);
  assert.equal(armS.maxPwmPct, 80);
  assert.equal(armS.hwFaultMotors, 1);

  assert.deepEqual(
    obs.cameras.map((c) => c.source_id),
    ["omx_overhead", "omx_side", "omx_side_depth", "omx_wrist_a"],
  );
  assert.equal(obs.cameras[3].arm_id, "arm_a");

  assert.deepEqual(obs.summary, {
    armsTotal: 2,
    armsFresh: 1,
    camsTotal: 4,
    camsLive: 3,
    heldCount: 1,
    openIncidentCount: 1,
    faultArmCount: 1,
    warnArmCount: 1,
    receivedAtMs: 12345,
  });
});

test("isArmAttentionOrLive and activeCellWorkRows isolate active work and attention-needing arms", () => {
  assert.equal(isArmAttentionOrLive({ id: "arm_a", fresh: false, held: false, openIncidents: [], hwFaultMotors: 0, warnMotors: 0 }), false);
  assert.equal(isArmAttentionOrLive({ id: "arm_a", fresh: false, held: false, openIncidents: [], hwFaultMotors: 0, warnMotors: 0 }, "arm_a"), true);
  assert.equal(isArmAttentionOrLive({ id: "arm_b", fresh: true, held: false, openIncidents: [], hwFaultMotors: 0, warnMotors: 0 }), true);
  assert.equal(isArmAttentionOrLive({ id: "arm_s", fresh: false, held: true, openIncidents: [{}], hwFaultMotors: 0, warnMotors: 0 }), true);

  const filtered = activeCellWorkRows([
    { source: "cell_job", source_id: "j1", status: "PROPOSED", visible_state: "approval_pending" },
    { source: "mission", source_id: "m1", status: "RUNNING", visible_state: "in_progress" },
    { source: "cell_job", source_id: "j2", status: "COMPLETED", visible_state: "ended" },
    { source: "trip", source_id: "t1", status: "RUNNING", visible_state: "in_progress" },
  ]);
  assert.deepEqual(filtered.map((r) => r.source_id), ["j1", "m1"]);
});
