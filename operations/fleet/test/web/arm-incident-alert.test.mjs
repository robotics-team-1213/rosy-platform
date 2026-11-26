import test from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";

register("./resolve-console-assets.mjs", import.meta.url);

// 알림 창의 팔 사건 행: 열린 사건마다 한 행, 행은 그 사건의 해제 단계로 열린다.
const { armIncidentAlertRows, armIncidentClearPlan, armIncidentKey } = await import("/console/assets/arm-incident-clear.js");
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
