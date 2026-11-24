import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);

const { createCalmPowerHealth } = await import("../../../../applications/fleet/web/shared/calm-power.js");
const { batteryMeterState } = await import("../../../../applications/fleet/web/shared/cockpit-telemetry.js");

function robot(extra = {}, battery = {}) {
  return {
    robot_id: "rosy_01",
    online: true,
    power_health_age_s: 0.2,
    power_health: {
      battery: {
        evidence: "fresh",
        sample_age_s: 0.2,
        stale_after_s: 5,
        level: "ok",
        percent: 80,
        filtered_voltage: 8.1,
        charging_state: "confirmed",
        charging_evidence_age_s: 0.2,
        ...battery,
      },
      recommendation: "normal_idle_policy",
    },
    state: { safety: { estop: false } },
    ...extra,
  };
}

test("calm power holds transient online unknown for 3s then clears cleanly", () => {
  const calm = createCalmPowerHealth({ graceMs: 3000 });
  const fresh = calm.read(robot(), { receivedAtMs: 1000, nowMs: 1000 });
  assert.equal(fresh.percent, 80);
  assert.equal(fresh.battery, "80%");
  assert.equal(fresh.chargingConfirmed, true);

  // Brief online miss holds percent/% text while D-509 charging drops immediately to 확인 불가.
  const blip1 = calm.read(robot({ power_health_age_s: 7.0 }), { receivedAtMs: 1000, nowMs: 2000 });
  assert.equal(blip1.percent, 80);
  assert.equal(blip1.battery, "80%");
  assert.equal(blip1.charging, "확인 불가");
  assert.equal(blip1.chargingConfirmed, false);

  const blip2 = calm.read(robot({ power_health_age_s: 8.0 }), { receivedAtMs: 1000, nowMs: 4500 });
  assert.equal(blip2.percent, 80);
  assert.equal(blip2.battery, "80%");

  // Once >= 3000ms elapses, transitions to 확인 불가.
  const expired = calm.read(robot({ power_health_age_s: 9.0 }), { receivedAtMs: 1000, nowMs: 5000 });
  assert.equal(expired.percent, null);
  assert.equal(expired.battery, "확인 불가");
});

test("calm power clears immediately on offline, stateUnavailable, or explicit sensor fault", () => {
  const calm = createCalmPowerHealth({ graceMs: 3000 });
  assert.equal(calm.read(robot(), { receivedAtMs: 1000, nowMs: 1000 }).percent, 80);

  const offline = calm.read(robot({ online: false }), { receivedAtMs: 1000, nowMs: 1500 });
  assert.equal(offline.percent, null);
  assert.equal(offline.battery, "확인 불가");

  assert.equal(calm.read(robot(), { receivedAtMs: 2000, nowMs: 2000 }).percent, 80);
  const unavail = calm.read(robot({ power_health_age_s: 7.0 }), { receivedAtMs: 2000, nowMs: 2500, stateUnavailable: true });
  assert.equal(unavail.percent, null);

  assert.equal(calm.read(robot(), { receivedAtMs: 3000, nowMs: 3000 }).percent, 80);
  const missing = calm.read(robot({}, { evidence: "missing" }), { receivedAtMs: 3000, nowMs: 3500 });
  assert.equal(missing.percent, null);
  assert.match(missing.problem, /배터리 값 없음/);
});

test("batteryMeterState maps tones, clamping, charging, and offline/unknown", () => {
  assert.deepEqual(batteryMeterState({ percent: 80, charging: false, online: true }), { tone: "good", charging: false, meter: "80%" });
  assert.deepEqual(batteryMeterState({ percent: 30, charging: true, online: true }), { tone: "warn", charging: true, meter: "30%" });
  assert.deepEqual(batteryMeterState({ percent: 15, charging: false, online: true }), { tone: "crit", charging: false, meter: "15%" });
  assert.deepEqual(batteryMeterState({ percent: 80, charging: true, online: false }), { tone: "unknown", charging: false, meter: "0%" });
  assert.deepEqual(batteryMeterState({ percent: null, charging: true, online: true }), { tone: "unknown", charging: false, meter: "0%" });
});
