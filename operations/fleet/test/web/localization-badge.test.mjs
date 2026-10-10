import test from "node:test";
import assert from "node:assert/strict";

import {
  localizationTag, localizationUrgent, robotMapPose, robotPoseText, sitePoseText, untrustedQueuedReason,
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
  const legacy = localizationTag(row({ state: null, pose_frame: null, legacy: true,
    label: "위치 상태 미보고" }));
  assert.equal(legacy.text, "위치 상태 미보고");
  assert.equal(legacy.cls, "warn");
});

test("a mission held behind an untrusted robot says why", () => {
  assert.match(untrustedQueuedReason("rosy_02"), /^rosy_02 위치를 확인할 수 없어 대기 중/);
});

test("the card names the robot pose frame and shows Fleet's site map pose apart", () => {
  // Field check 2026-10-10: "위치 0.90, 0.05" was odom and read as a map coordinate.
  const state = { pose: { x: 0.9, y: 0.05, yaw: -0.12 }, map_id: null };
  assert.equal(robotPoseText(state, { state: null, pose_frame: null, legacy: true }), "odom 0.90, 0.05");
  assert.equal(robotPoseText({ ...state, map_id: "m" }, null), "map 0.90, 0.05");
  assert.equal(robotPoseText(state, { pose_frame: "odom" }), "odom 0.90, 0.05");
  assert.equal(robotPoseText({}, null), "—");
  assert.equal(sitePoseText(null), null);
  assert.equal(sitePoseText({ robot_id: "a", pose: null }), "지도 위치 모름");
  assert.equal(sitePoseText({ robot_id: "a", pose: { x: 0.69, y: -0.44, state: "DEGRADED", source: "bridged" } }),
    "지도 0.69, -0.44 · 추정·odom 이음");
  assert.equal(sitePoseText({ robot_id: "a", pose: { x: 1, y: 2, state: "LOCALIZED", source: "sighting" } }),
    "지도 1.00, 2.00 · 확정·카메라");
});

test("the map draws the robot's own pose only when it is a LOCALIZED map pose, never odom", () => {
  const pose = { x: 0.9, y: 0.05, yaw: -0.12 };
  // Field check 2026-10-10: a manual-only robot (localization null, no map) was drawn at odom coordinates.
  assert.equal(robotMapPose({ localization: { pose_frame: null, legacy: true }, state: { pose, map_id: null, localization: null } }), null);
  assert.equal(robotMapPose({ state: { pose, map_id: "m", localization: { state: "LOCALIZED", pose_frame: "odom" } } }), null);
  assert.equal(robotMapPose({ state: { pose, map_id: "m", localization: { state: "DEGRADED", pose_frame: "map" } } }), null);
  assert.equal(robotMapPose({ state: { pose, map_id: "m", localization: { state: "LOCALIZED", pose_frame: "map" } } }), pose);
  assert.equal(robotMapPose({ state: { pose, map_id: "m", localization: null } }), pose);  // pre-D-395 Nav2 robot
  assert.equal(robotMapPose({ state: null }), null);
});
