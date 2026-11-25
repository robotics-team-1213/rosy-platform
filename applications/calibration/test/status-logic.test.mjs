import test from "node:test";
import assert from "node:assert/strict";

const {
  mergeIncident,
  classifyHold,
  classifyFrameBinding,
  classifyDrift,
  linkedArm,
  profileForArm,
} = await import("../web/status-logic.js");

test("arm links select the requested robot and survive profile ordering or missing profiles", () => {
  const profiles = [{id: "first", arm_id: "arm_s"}, {id: "ab-camera", arm_id: "arm_b"}];
  assert.equal(profileForArm(profiles, linkedArm("?arm=arm_b"), null).id, "ab-camera");
  assert.equal(profileForArm(profiles, linkedArm("?arm=arm_a"), "first"), null);
  assert.equal(profileForArm(profiles, null, "ab-camera").id, "ab-camera");
  assert.equal(linkedArm("?arm=arm_b&arm=arm_a"), null);
  assert.equal(linkedArm("?arm=other"), null);
});

test("classifyHold never reports HOLD CLEAR when hold evidence is missing, null, partial, or errored", () => {
  for (const blank of [undefined, null, {}, { local_held: null, fleet_held: null, incident_ids: [] }]) {
    const res = classifyHold(blank);
    assert.equal(res.state, "unknown");
    assert.equal(res.badge, "HOLD 미확인");
    assert.notEqual(res.badge, "HOLD CLEAR");
  }

  const partial = classifyHold({ local_held: false, fleet_held: null, fleet_reason: "unreachable" });
  assert.equal(partial.state, "partial");
  assert.equal(partial.status, "warn");
  assert.equal(partial.badge, "HOLD 미확인 (Fleet)");

  const err = classifyHold({ error: "exit 1" });
  assert.equal(err.state, "error");
  assert.equal(err.status, "warn");
  assert.equal(err.badge, "HOLD 조회 오류");
});

test("classifyHold prioritizes HELD on local_held, fleet_held, or unsent_outbox > 0", () => {
  const outbox = classifyHold({ local_held: false, fleet_held: false, unsent_outbox: 2 });
  assert.equal(outbox.state, "held");
  assert.equal(outbox.status, "crit");
  assert.equal(outbox.badge, "HELD (outbox:2)");

  const localHeld = classifyHold({ local_held: true, fleet_held: false, incident_ids: ["inc-9"] });
  assert.equal(localHeld.state, "held");
  assert.equal(localHeld.status, "crit");
  assert.equal(localHeld.badge, "HELD (inc-9)");

  const fleetHeld = classifyHold({ local_held: false, fleet_held: true, incident_ids: ["inc-2"] });
  assert.equal(fleetHeld.state, "held");
  assert.equal(fleetHeld.status, "crit");

  const clear = classifyHold({ local_held: false, fleet_held: false, unsent_outbox: 0 });
  assert.equal(clear.state, "clear");
  assert.equal(clear.badge, "HOLD CLEAR");
});

test("mergeIncident combines live status and fails closed if either source reports held", () => {
  const mergedClear = mergeIncident(
    { local_held: null, fleet_held: null, incident_ids: [] },
    { local_held: false, fleet_held: false, unsent_outbox: 0, incident_ids: [] },
  );
  assert.equal(classifyHold(mergedClear).state, "clear");

  const mergedHeld = mergeIncident(
    { local_held: true, fleet_held: false, incident_ids: ["inc-a"] },
    { local_held: false, fleet_held: false, unsent_outbox: 0, incident_ids: [] },
  );
  assert.equal(classifyHold(mergedHeld).state, "held");
  assert.equal(classifyHold(mergedHeld).badge, "HELD (inc-a)");
});

test("classifyFrameBinding surfaces CAMERA SHIFTED, MAP UNBOUND, and unconfirmed camera motion", () => {
  const unbound = classifyFrameBinding({
    hygiene: [{ code: "map_binding", message: "top camera map site geometry changed" }],
    camera_top: { shift: null },
  });
  assert.equal(unbound.status, "warn");
  assert.equal(unbound.badge, "MAP UNBOUND");
  assert.equal(unbound.shiftText, "카메라 이동 미확인");
  assert.match(unbound.title, /움직였는지는 아직 확인되지 않았습니다/);

  const shifted = classifyFrameBinding({
    hygiene: [{ code: "camera_shifted", message: "4.2px > 2.0px" }],
    camera_top: { shift: { ok: false, why: "no features" } },
  });
  assert.equal(shifted.status, "crit");
  assert.equal(shifted.badge, "CAMERA SHIFTED");
  assert.match(shifted.shiftText, /카메라 이동 미확인 \(no features\)/);
});

test("classifyDrift reads cross_verify.drift and fails closed to unknown or advisory", () => {
  assert.equal(
    classifyDrift({ cross_verify: { drift: { alarmed_sites: ["pallet"], pattern: "local", sites: {} } } }).verdict,
    "advisory",
  );
  assert.equal(
    classifyDrift({ cross_verify: { drift: { alarmed_sites: [], sites: { pallet: { status: "unknown" } } } } }).verdict,
    "unknown",
  );
  assert.equal(
    classifyDrift({ cross_verify: { drift: { alarmed_sites: [], sites: { pallet: { status: "pass" } } } } }).verdict,
    "pass",
  );
});
