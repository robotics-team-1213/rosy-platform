import {test} from "node:test";
import assert from "node:assert/strict";
import {robotProfile, groupRobots} from "../robot-profile.js";

const pinky = (extra = {}) => ({id: "rosy_40", kind: "mobile", online: true, ageS: 1, battery: {percent: 82, charging: false}, estop: false, task: "C1 대기", place: "C1 충전소", ...extra});
const arm = (extra = {}) => ({id: "arm_a", name: "OMX-AI A", kind: "arm", online: true, ageS: 1, torque: true, servo: {currentMa: 120, temperatureC: 31}, task: "집기", place: "S5 셀", ...extra});

test("a fresh normal robot is quiet: no alarm, fresh link", () => {
  for (const source of [pinky(), arm()]) {
    const profile = robotProfile(source);
    assert.equal(profile.link.state, "fresh");
    assert.equal(profile.alarm, null);
  }
  assert.equal(robotProfile(pinky()).power.text, "82%");
});

test("both kinds share one profile shape and kind labels", () => {
  const [a, m] = [robotProfile(arm()), robotProfile(pinky())];
  assert.deepEqual(Object.keys(a), Object.keys(m));
  assert.equal(a.kindLabel, "로봇암");
  assert.equal(m.kindLabel, "이동로봇");
  assert.equal(a.name, "OMX-AI A");
  assert.equal(m.name, "rosy_40");
});

test("freshness comes from online and age, and the server verdict wins", () => {
  assert.equal(robotProfile(pinky({ageS: 30})).link.state, "delayed");
  assert.equal(robotProfile(pinky({ageS: 30})).link.text, "지연 · 30초 전");
  assert.equal(robotProfile(pinky({online: false})).link.state, "disconnected");
  assert.equal(robotProfile(pinky({online: undefined, ageS: undefined})).link.state, "unavailable");
  assert.equal(robotProfile(pinky({evidence: "delayed", ageS: 1})).link.state, "delayed");
});

test("unknown values are never constants (D-280)", () => {
  const profile = robotProfile({id: "rosy_41", kind: "mobile", online: true});
  assert.equal(profile.power.text, "정보 없음");
  assert.equal(profile.task.text, "정보 없음");
  assert.equal(profile.place.text, "정보 없음");
  const bad = robotProfile(pinky({battery: {percent: 140}}));
  assert.equal(bad.power.text, "정보 없음");
  assert.equal(robotProfile(pinky({battery: {percent: 0}})).power.text, "0%"); // a real 0 is 0
  assert.equal(robotProfile(arm({servo: undefined, torque: undefined})).power.text, "토크 정보 없음");
});

test("a stale link keeps values but marks their age; a lost one hides nothing it cannot know", () => {
  const stale = robotProfile(pinky({ageS: 12}));
  assert.equal(stale.power.text, "82% · 12초 전");
  assert.equal(stale.power.state, "delayed");
  const silent = robotProfile(pinky({online: undefined, ageS: undefined}));
  assert.equal(silent.power.state, "unavailable");
});

test("arm power is torque plus servo readings; torque off is calm text, not an alarm", () => {
  const off = robotProfile(arm({torque: false}));
  assert.equal(off.power.text, "토크 꺼짐 · 전류 120 mA · 온도 31 °C");
  assert.equal(off.power.torque, false);
  assert.equal(off.alarm, null);
  assert.equal(robotProfile(arm({servo: {temperatureC: 40}})).power.text, "토크 켜짐 · 온도 40 °C");
});

test("one alarm only, highest first; severity is separate from freshness", () => {
  assert.deepEqual(robotProfile(pinky({estop: true})).alarm, {level: "danger", text: "비상 정지", tag: "danger", icon: "estop"});
  const low = robotProfile(pinky({battery: {percent: 12}}));
  assert.equal(low.alarm.tag, "caution");
  assert.equal(robotProfile(pinky({battery: {percent: 12, charging: true}})).alarm, null);
  const both = robotProfile(pinky({estop: true, battery: {percent: 5}}));
  assert.equal(both.alarm.tag, "danger");
  const explicit = robotProfile(arm({alarm: {level: "caution", text: "서보 과열 근접"}}));
  assert.equal(explicit.alarm.text, "서보 과열 근접");
  // a delayed link is not a severity: no alarm is invented from staleness
  assert.equal(robotProfile(pinky({ageS: 30})).alarm, null);
  // a lost link keeps a known stop latch visible
  assert.equal(robotProfile(pinky({online: false, estop: true})).alarm.tag, "danger");
});

test("a fresh mobile robot with no safety reading shows unknown safety; an arm does not", () => {
  assert.equal(robotProfile(pinky({estop: undefined})).alarm.tag, "unknown");
  assert.equal(robotProfile(arm()).alarm, null);
});

test("place falls back to a pose; the detail text is trimmed or null", () => {
  assert.equal(robotProfile(pinky({place: undefined, pose: {x: 0.5, y: -0.25}})).place.text, "x 0.50 · y -0.25 m");
  assert.equal(robotProfile(pinky({detail: "  8.7 V  "})).detail, "8.7 V");
  assert.equal(robotProfile(pinky()).detail, null);
});

test("an unknown kind is rejected and groups put arms before mobile robots", () => {
  assert.throws(() => robotProfile({id: "x", kind: "drone"}), RangeError);
  const groups = groupRobots([robotProfile(pinky()), robotProfile(arm()), robotProfile(pinky({id: "rosy_41"}))]);
  assert.deepEqual(groups.map(g => [g.kind, g.label, g.rows.length]), [["arm", "로봇암", 1], ["mobile", "이동로봇", 2]]);
});

test("a stale arm line carries its age once; a non-numeric battery is unknown", () => {
  assert.equal(robotProfile(arm({ageS: 14})).power.text, "토크 켜짐 · 전류 120 mA · 온도 31 °C · 14초 전");
  for (const percent of [null, "", true, "50"]) assert.equal(robotProfile(pinky({battery: {percent}})).power.text, "정보 없음", String(percent));
});
