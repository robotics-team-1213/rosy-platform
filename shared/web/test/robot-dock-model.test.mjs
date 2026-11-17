import {test} from "node:test";
import assert from "node:assert/strict";
import {robotProfile} from "../robot-profile.js";
import {dockEntries} from "../robot-dock-model.js";

test("short ids extract mobile trailing digits, arm last segment uppercased, and fall back to whole id", () => {
  const profiles = [
    robotProfile({id: "rosy_42", kind: "mobile", online: true, estop: false}),
    robotProfile({id: "pinky", kind: "mobile", online: true, estop: false}),
    robotProfile({id: "arm_s", kind: "arm", online: true}),
    robotProfile({id: "omx_left_a", kind: "arm", online: true}),
    robotProfile({id: "omx", kind: "arm", online: true}),
    robotProfile({id: "arm_", kind: "arm", online: true}),
  ];
  assert.deepEqual(
    dockEntries(profiles).map((e) => [e.id, e.short]),
    [["rosy_42", "42"], ["pinky", "pinky"], ["arm_s", "S"], ["omx_left_a", "A"], ["omx", "omx"], ["arm_", "arm_"]],
  );
});

test("orders mobile robots first then arms while keeping given order within each kind", () => {
  const profiles = [
    robotProfile({id: "arm_s", kind: "arm", online: true}),
    robotProfile({id: "rosy_45", kind: "mobile", online: true, estop: false}),
    robotProfile({id: "arm_a", kind: "arm", online: true}),
    robotProfile({id: "rosy_42", kind: "mobile", online: true, estop: false}),
  ];
  assert.deepEqual(dockEntries(profiles).map((e) => e.id), ["rosy_45", "rosy_42", "arm_s", "arm_a"]);
});

test("marks appear only when abnormal, map unavailable link to unknown, and support both marks", () => {
  const calm = robotProfile({id: "rosy_46", kind: "mobile", online: true, ageS: 1, estop: false});
  const delayed = robotProfile({id: "rosy_45", kind: "mobile", online: true, ageS: 3, estop: false}, {staleAfterS: 2});
  const lost = robotProfile({id: "arm_b", kind: "arm", online: false, ageS: 95});
  const unknown = robotProfile({id: "arm_u", kind: "arm"});
  const both = robotProfile({id: "rosy_42", kind: "mobile", online: true, ageS: 12, estop: true});
  const caution = robotProfile({id: "arm_s", kind: "arm", online: true, ageS: 1, alarm: {level: "caution", text: "홀드 중"}});

  const byId = Object.fromEntries(dockEntries([calm, delayed, lost, unknown, both, caution]).map((e) => [e.id, e]));
  assert.deepEqual(byId.rosy_46.marks, []);
  assert.deepEqual(byId.rosy_45.marks, [{kind: "link", state: "delayed", text: "지연 · 3초 전"}]);
  assert.deepEqual(byId.arm_b.marks, [{kind: "link", state: "disconnected", text: "연결 끊김"}]);
  assert.deepEqual(byId.arm_u.marks, [{kind: "link", state: "unknown", text: "정보 없음"}]);
  assert.deepEqual(byId.rosy_42.marks, [
    {kind: "link", state: "delayed", text: "지연 · 12초 전"},
    {kind: "alarm", state: "danger", text: "비상 정지"},
  ]);
  assert.deepEqual(byId.arm_s.marks, [{kind: "alarm", state: "caution", text: "홀드 중"}]);

  assert.equal(byId.rosy_46.label, "rosy_46 이동로봇");
  assert.equal(byId.rosy_45.label, "rosy_45 이동로봇 · 지연 · 3초 전");
  assert.equal(byId.rosy_42.label, "rosy_42 이동로봇 · 지연 · 12초 전 · 비상 정지");
  assert.equal(byId.arm_s.label, "arm_s 로봇암 · 홀드 중");
});

test("filters by kinds and ids", () => {
  const profiles = [
    robotProfile({id: "rosy_42", kind: "mobile", online: true, estop: false}),
    robotProfile({id: "arm_s", kind: "arm", online: true}),
    robotProfile({id: "arm_a", kind: "arm", online: true}),
    robotProfile({id: "arm_b", kind: "arm", online: false}),
  ];
  assert.deepEqual(dockEntries(profiles, {kinds: ["arm"]}).map((e) => e.id), ["arm_s", "arm_a", "arm_b"]);
  assert.deepEqual(dockEntries(profiles, {ids: ["arm_b", "rosy_42"]}).map((e) => e.id), ["rosy_42", "arm_b"]);
  assert.deepEqual(dockEntries(profiles, {kinds: ["arm"], ids: ["arm_a", "rosy_42"]}).map((e) => e.id), ["arm_a"]);
});
