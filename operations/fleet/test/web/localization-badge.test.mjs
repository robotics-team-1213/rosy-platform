import test from "node:test";
import assert from "node:assert/strict";

import {
  localizationTag, localizationUrgent, positionTag, robotMapPose, robotPoseText, sitePoseText, untrustedQueuedReason,
} from "../../fleet/server/web/localization-badge.js";

const row = (over) => ({ state: "LOCALIZED", pose_frame: "map", trusted: true, legacy: false,
  needs_human: false, label: "위치 확정", ...over });

test("an offline robot has no localization tag", () => {
  assert.equal(localizationTag(null), null);
  assert.equal(localizationTag(undefined), null);
});

test("a localized robot is a neutral tag with the server's label", () => {
  assert.deepEqual(localizationTag(row()), { text: "위치 확정", cls: "", title: "LOCALIZED · map" });
});

test("an unlocalized robot warns and needs_human is critical", () => {
  assert.equal(localizationTag(row({ state: "CANDIDATES", pose_frame: "odom", trusted: false,
    label: "위치 후보 중재 중" })).cls, "warn");
  const human = localizationTag(row({ state: "CANDIDATES", trusted: false, needs_human: true,
    label: "위치 확인 필요" }));
  assert.equal(human.text, "위치 확인 필요");
  assert.equal(human.cls, "crit");
  assert.equal(localizationUrgent(row({ needs_human: true })), true);
  assert.equal(localizationUrgent(row()), false);
});

test("a robot without D-395 warns 위치 상태 미보고", () => {
  const legacy = localizationTag(row({ state: "UNKNOWN", pose_frame: null, trusted: false, legacy: false,
    label: "위치 상태 미보고" }));
  assert.equal(legacy.text, "위치 상태 미보고");
  assert.equal(legacy.cls, "warn");
});

test("a robot without D-395 that Fleet's MapPose places shows the MapPose state, not 미보고", () => {
  // Field 2026-10-10: rosy_40 (motor mode) was LOCALIZED by camera and the badge said 위치 상태 미보고.
  const legacy = row({ state: "UNKNOWN", pose_frame: null, trusted: false, legacy: false, label: "위치 상태 미보고" });
  assert.deepEqual(localizationTag(legacy, { pose: { x: 1, y: 2, state: "LOCALIZED" } }),
    { text: "위치 확정", cls: "", title: "Fleet MapPose · LOCALIZED" });
  assert.equal(localizationTag(legacy, { pose: { x: 1, y: 2, state: "DEGRADED" } }).cls, "warn");
  assert.equal(localizationTag(legacy, { pose: null }).text, "위치 상태 미보고");
  assert.equal(localizationTag(row(), { pose: { state: "DEGRADED" } }).text, "위치 확정");  // D-395 robot: its own
});

test("a mission held behind an untrusted robot says why", () => {
  assert.match(untrustedQueuedReason("rosy_02"), /^rosy_02 위치를 확인할 수 없어 대기 중/);
});

test("the card names the robot pose frame and shows Fleet's site map pose apart", () => {
  // Field check 2026-10-10: "위치 0.90, 0.05" was odom and read as a map coordinate.
  const state = { pose: { x: 0.9, y: 0.05, yaw: -0.12 }, map_id: null };
  assert.equal(robotPoseText(state, { state: "UNKNOWN", pose_frame: null, trusted: false, legacy: false }), "odom 0.90, 0.05");
  assert.equal(robotPoseText({ ...state, map_id: "m" }, null), "map 0.90, 0.05");
  assert.equal(robotPoseText(state, { pose_frame: "odom" }), "odom 0.90, 0.05");
  assert.equal(robotPoseText({}, null), "—");
  assert.equal(sitePoseText(null), null);
  assert.equal(sitePoseText({ robot_id: "a", pose: null }), "지도 위치 모름");
  assert.equal(sitePoseText({ robot_id: "a", pose: { x: 0.69, y: -0.44, state: "DEGRADED", source: "bridged" } }),
    "지도 0.69, -0.44 · 추정·odom 이음");
  assert.equal(sitePoseText({ robot_id: "a", pose: { x: 1, y: 2, state: "LOCALIZED", source: "sighting" } }),
    "지도 1.00, 2.00 · 확정·카메라");
  // Field 2026-10-10: odom newer than a 0.4 s camera anchor read "확정·odom 이음".
  const bridged = { x: 1, y: 2, state: "LOCALIZED", source: "bridged", anchor_source: "sighting" };
  assert.equal(sitePoseText({ pose: { ...bridged, anchor_age_s: 0.4 } }), "지도 1.00, 2.00 · 확정·카메라");
  assert.equal(sitePoseText({ pose: { ...bridged, anchor_age_s: 3 } }), "지도 1.00, 2.00 · 확정·odom 이음");
  assert.equal(sitePoseText({ pose: { ...bridged, anchor_age_s: 0.2, anchor_source: "operator_pin" } }),
    "지도 1.00, 2.00 · 확정·운영자 핀");
});

test("the map draws the robot's own pose only when it is a LOCALIZED map pose, never odom", () => {
  const pose = { x: 0.9, y: 0.05, yaw: -0.12 };
  // Field check 2026-10-10: a manual-only robot (localization null, no map) was drawn at odom coordinates.
  assert.equal(robotMapPose({ localization: { pose_frame: null, legacy: true }, state: { pose, map_id: null, localization: null } }), null);
  assert.equal(robotMapPose({ state: { pose, map_id: "m", localization: { state: "LOCALIZED", pose_frame: "odom" } } }), null);
  assert.equal(robotMapPose({ state: { pose, map_id: "m", localization: { state: "DEGRADED", pose_frame: "map" } } }), null);
  assert.equal(robotMapPose({ state: { pose, map_id: "m", localization: { state: "LOCALIZED", pose_frame: "map" } } }), pose);
  assert.equal(robotMapPose({ state: { pose, map_id: "m", localization: null } }), null);  // map_id alone cannot establish trust
  assert.equal(robotMapPose({ state: null }), null);
});

test("the card's position chip speaks what places the robot, and a missing CORE block is not a fault", () => {
  const legacy = row({ state: "UNKNOWN", pose_frame: null, trusted: false, legacy: false, trusted: false, label: "위치 상태 미보고" });
  const guide = (pose) => ({ robot_id: "rosy_01", pose });
  // Fleet's site map pose first, even when CORE reports nothing (lane following without Nav2).
  assert.deepEqual(positionTag(legacy, guide({ x: 0.69, y: -0.44, state: "LOCALIZED", source: "sighting" })),
    { text: "지도 위치 확정 · 카메라", cls: "", title: "Fleet map pose: LOCALIZED · sighting" });
  assert.equal(positionTag(row(), guide({ x: 1, y: 2, state: "DEGRADED", source: "bridged" })).text, "지도 위치 추정 · odom 이음");
  // No Fleet pose: CORE's own state when CORE reports one.
  assert.deepEqual(positionTag(row(), guide(null)), localizationTag(row()));
  // Missing CORE localization remains explicitly unknown without a Fleet pose.
  assert.deepEqual(positionTag(legacy, guide(null)), localizationTag(legacy));
  assert.equal(positionTag(legacy, undefined).cls, "warn");
  assert.equal(positionTag(null, undefined), null);
  // A person must decide: still critical.
  assert.equal(positionTag(row({ needs_human: true, trusted: false, label: "위치 확인 필요" }),
    guide({ x: 1, y: 1, state: "LOCALIZED", source: "sighting" })).cls, "crit");
});

test("an LED-confirmed blob is the pin place only while the map pose is not LOCALIZED", async () => {
  const { pinPrefill } = await import("../../fleet/server/web/localization-badge.js");
  const identity = { robots: [{ robot_id: "rosy_41", state: "CONFIRMED", x: 0.398, y: -0.499 },
    { robot_id: "rosy_40", state: "UNKNOWN", x: null, y: null }] };
  const degraded = { pose: { x: 0.962, y: -0.011, state: "DEGRADED" } };
  assert.deepEqual(pinPrefill(identity, degraded, "rosy_41"), { x: 0.398, y: -0.499 });
  assert.deepEqual(pinPrefill(identity, { pose: null }, "rosy_41"), { x: 0.398, y: -0.499 });
  assert.equal(pinPrefill(identity, { pose: { x: 0.4, y: -0.5, state: "LOCALIZED" } }, "rosy_41"), null);
  assert.equal(pinPrefill(identity, degraded, "rosy_40"), null);
  assert.equal(pinPrefill(null, degraded, "rosy_41"), null);
});
