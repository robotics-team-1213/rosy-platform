import test from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";

register("./resolve-console-assets.mjs", import.meta.url);

// 알림 창의 팔 사건 행: 열린 사건마다 한 행, 행은 그 사건의 해제 단계로 열린다.
const { armIncidentAlertRows, armIncidentClearPlan, armIncidentKey, armIncidentRowFor, clearArmIncident, clearPipelineArmHold } =
  await import("/console/assets/arm-incident-clear.js");
const { normalizeWorkcellObservations } = await import("/console/assets/cell-obs-model.js");

const HUMAN_HOLD = "runner: human hold; a person checks the arm (jaws, contacts, wedged objects) before torque ON";

test("a person-check hold becomes a checklist of its own items and a prefilled note", () => {
  const plan = armIncidentClearPlan({ incident_id: "a", decision: { hold: true, reason: HUMAN_HOLD } });
  assert.equal(plan.mode, "clear");
  assert.deepEqual(plan.checks, ["집게", "닿은 곳", "끼인 물체"]);
  assert.equal(plan.note, "현장 확인: 집게, 닿은 곳, 끼인 물체 이상 없음");
});

test("a reason without a check list still asks for the arm and the path", () => {
  const plan = armIncidentClearPlan({ decision: { hold: true, reason: "arm incident not cleared" } });
  assert.equal(plan.mode, "clear");
  assert.deepEqual(plan.checks, ["팔과 집게", "이동 경로에 걸린 물체"]);
});

test("an extended arm with torque off and a USB home recovery show one next step, never a clear", () => {
  const extended = armIncidentClearPlan({ decision: { hold: true, reason: "torque off with arm extended; guarded fold required" } });
  assert.equal(extended.mode, "next_step");
  assert.match(extended.step, /가드 홈 복귀/);
  assert.equal(extended.checks, undefined);
  const home = armIncidentClearPlan({ event_kind: "home_recovery", decision: { hold: true, reason: "USB connection lost; guarded home recovery required" } });
  assert.equal(home.mode, "next_step");
  assert.match(home.step, /자동 폴드/);
});

test("open incidents become drawer decision rows keyed by arm and incident; cleared ones do not", () => {
  const obs = normalizeWorkcellObservations({ workcells: [{ arms: [
    { arm_id: "arm_a", source_id: "arm_a_follower", label: "Arm A", incidents: [
      { incident_id: "i1", state: "open", decision: { hold: true, reason: HUMAN_HOLD } },
      { incident_id: "i2", state: "open", decision: { hold: false, reason: "guard stop handled" } },
      { incident_id: "i0", state: "cleared", decision: { hold: true } },
    ] },
    { arm_id: "arm_s", label: "Arm S", incidents: [
      { incident_id: "h1", state: "open", event_kind: "home_recovery", decision: { hold: true } },
    ] },
  ] }] });
  const { crit, warn } = armIncidentAlertRows(obs);
  const rows = [...crit, ...warn];
  assert.deepEqual(rows.map((r) => [r.key, r.severity, r.decision, r.robotId]), [
    [armIncidentKey("arm_a_follower", "i1"), "crit", "arm-incident", "Arm A"],
    [armIncidentKey("arm_a_follower", "i2"), "warn", "arm-incident", "Arm A"],
    ["arm_s|arm-incident-h1", "warn", "arm-incident", "Arm S"],
  ]);
  assert.match(rows[0].text, /^: 팔 보류/);
  assert.deepEqual(armIncidentAlertRows(null), { crit: [], warn: [] });
});

function fakeCall(holds, refuse = null) {
  const calls = [];
  const call = async (path, opts = {}) => {
    calls.push([opts.method || "GET", path, opts.body ? JSON.parse(opts.body) : null]);
    if (path === "/api/fleet/pipeline/status") {
      if (holds === 404) throw Object.assign(new Error("HTTP 404"), { status: 404 });
      return { arm_holds: holds };
    }
    if (path.endsWith("/arm-holds/clear") && refuse) throw Object.assign(new Error(refuse), { status: 409, code: refuse });
    return {};
  };
  return { call, calls };
}
const ARM = { id: "arm_a", sourceId: "arm_a_follower" };
const PAYLOAD = { note: "현장 확인: 집게 이상 없음", cause: "unknown", basis: "unknown" };

test("one confirm clears the held Fleet arm hold, then the incident, with the same note, cause and basis", async () => {
  const { call, calls } = fakeCall({ arm_a: { held: true } });
  assert.deepEqual(await clearArmIncident(call, ARM, { incident_id: "i/1" }, PAYLOAD), { holdCleared: true });
  assert.deepEqual(calls, [
    ["GET", "/api/fleet/pipeline/status", null],
    ["POST", "/api/fleet/pipeline/arm-holds/clear", { arm_id: "arm_a", ...PAYLOAD }],
    ["POST", "/api/fleet/workcell-observations/arms/arm_a_follower/incidents/i%2F1/clear", PAYLOAD],
  ]);
});

test("a refused hold clears nothing, so the incident row stays with its next step", async () => {
  const { call, calls } = fakeCall({ arm_a: { held: true } }, "NAMED_OPERATOR_REQUIRED");
  assert.match((await clearArmIncident(call, ARM, { incident_id: "i1" }, PAYLOAD)).nextStep, /이름 있는 운영자/);
  assert.ok(!calls.some(([, path]) => path.includes("/incidents/")));
});

test("no Fleet hold on that arm (or no pipeline) sends no hold clear", async () => {
  for (const holds of [{ arm_a: { held: false }, arm_b: { held: true } }, 404]) {
    const { call, calls } = fakeCall(holds);
    assert.deepEqual(await clearPipelineArmHold(call, "arm_a", PAYLOAD), {});
    assert.ok(!calls.some(([, path]) => path.endsWith("/arm-holds/clear")));
  }
});

test("a hold the server keeps becomes its single next step", async () => {
  const { call } = fakeCall({ arm_a: { held: true } }, "STAGED_HOMING_VISUAL_VERIFY_REQUIRED");
  assert.match((await clearPipelineArmHold(call, "arm_a", PAYLOAD)).nextStep, /카메라 접힘 확인/);
});

test("a cell's button finds the open incident row of any of its arms", () => {
  const obs = normalizeWorkcellObservations({ workcells: [{ arms: [
    { arm_id: "arm_b", source_id: "omx_arm_b", incidents: [{ incident_id: "b1", state: "open", decision: { hold: true, reason: "x" } }] },
  ] }] });
  assert.equal(armIncidentRowFor("cell_ab", obs).key, "omx_arm_b|arm-incident-b1");
  assert.equal(armIncidentRowFor("cell_s", obs), null);
});

test("a second incident on the same arm that needs a guarded fold blocks the clear: nothing is posted", async () => {
  const { call, calls } = fakeCall({ arm_a: { held: true } });
  const arm = { ...ARM, openIncidents: [
    { incident_id: "i1", decision: { hold: true, reason: "arm incident not cleared" } },
    { incident_id: "i2", decision: { hold: true, reason: "torque off with arm extended; guarded fold required" } },
  ], homeRecoveries: [] };
  const result = await clearArmIncident(call, arm, arm.openIncidents[0], PAYLOAD);
  assert.match(result.nextStep, /가드 홈 복귀/);
  assert.deepEqual(calls, []);
});
