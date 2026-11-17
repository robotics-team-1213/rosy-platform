import {test} from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {parseUrdf, parseStl, jointAngles, jointsFromList, describeRobot, fitDistance, fitView, presetDirection, headingDeg} from "../robot-3d-model.js";

const urdf = name => parseUrdf(fs.readFileSync(new URL(`../meshes/${name}`, import.meta.url), "utf8"));

test("the OMX-F URDF parses to a tree with a root, 8 meshes and a mimic gripper", () => {
  const omx = urdf("omx-f.urdf");
  assert.equal(omx.root, "world");
  assert.equal(Object.values(omx.links).filter(link => link.mesh).length, 8);
  assert.deepEqual(omx.joints.map(joint => joint.name).slice(0, 2), ["world_fixed", "end_effector_joint"]);
  assert.deepEqual(omx.joints.find(joint => joint.name === "gripper_joint_2").mimic, {joint: "gripper_joint_1", multiplier: -1});
  assert.deepEqual(omx.joints.find(joint => joint.name === "joint2").axis, [0, 1, 0]);
});

test("the Pinky URDF has a body and two mirrored wheels", () => {
  const pinky = urdf("pinky-pro.urdf");
  assert.equal(pinky.root, "base_footprint");
  assert.equal(pinky.links.body.mesh, "pinky-body.stl");
  assert.equal(pinky.joints.find(joint => joint.name === "l_wheel_joint").xyz[1], -pinky.joints.find(joint => joint.name === "r_wheel_joint").xyz[1]);
});

test("joint values: unknown and non-finite are ignored, never drawn as 0; limits clamp; mimic follows", () => {
  const omx = urdf("omx-f.urdf");
  const {angles, ignored} = jointAngles(omx, {joint1: 1, joint2: Number.NaN, nope: 3, joint3: 99, gripper_joint_1: 0.4});
  assert.equal(angles.joint1, 1);
  assert.equal(angles.joint3, 2 * Math.PI);
  assert.equal(angles.gripper_joint_2, -0.4);
  assert.deepEqual(ignored.sort(), ["joint2", "nope"]);
  assert.equal("joint2" in angles, false);
  assert.deepEqual(jointsFromList([0.1, undefined, 0.3], ["joint1", "joint2", "joint3"]), {joint1: 0.1, joint3: 0.3});
});

test("the summary says kind, name, selection and one link state; the detail carries joints or pose, missing values as unavailable", () => {
  assert.deepEqual(describeRobot({kind: "arm", name: "OMX-AI A", selected: true, joints: {joint1: Math.PI / 2}}), {summary: "로봇암 OMX-AI A · 선택됨", detail: "관절 1 90°"});
  assert.match(describeRobot({kind: "arm", name: "A"}).detail, /관절 .*(없|불가|확인)/);
  const mobile = describeRobot({kind: "mobile", name: "rosy_40", pose: {x: 0.5, y: -0.25, yaw: Math.PI}});
  assert.equal(mobile.summary, "이동로봇 rosy_40 · 선택 안 됨");
  assert.equal(mobile.detail, "위치 x 0.50 · y -0.25 m · 방향 180°");
  const late = describeRobot({kind: "mobile", name: "r", link: {state: "delayed", text: "지연 · 14초 전"}});
  assert.equal(late.summary, "이동로봇 r · 선택 안 됨 · 지연 · 14초 전");
  assert.match(late.detail, /^마지막 보고 기준 · 위치 /);
  assert.equal(describeRobot({kind: "mobile", name: "r", link: {state: "fresh", text: "최신"}}).summary, "이동로봇 r · 선택 안 됨 · 최신");
  assert.equal(headingDeg(-Math.PI), 180);
  assert.equal(headingDeg(3 * Math.PI / 2), -90);
});

test("fitDistance fills about 75% of the limiting side and flips the limiting axis with the aspect", () => {
  const box = [-1, 1].flatMap(x => [-1, 1].flatMap(y => [-1, 1].map(z => [x * 0.2, y * 0.05, z * 0.05])));
  const dir = [0, -1, 0]; // side view: the box is 0.4 wide in x (screen right), 0.1 tall
  const landscape = fitDistance(dir, box, 35, 4 / 3), portrait = fitDistance(dir, box, 35, 0.5);
  assert.ok(portrait > landscape, "a narrow view needs more distance for a wide robot");
  const t = Math.tan(35 * Math.PI / 360);
  // the far-plane width at the box centre depth is ~ 2 t aspect d; the robot (0.4 wide) fills 75% of it
  assert.ok(Math.abs(0.4 / (2 * t * (4 / 3) * (landscape - 0.05)) - 0.75) < 0.02);
});

test("binary STL parsing rejects a wrong length and reads positions", () => {
  const buffer = new ArrayBuffer(84 + 50), view = new DataView(buffer);
  view.setUint32(80, 1, true);
  [1, 2, 3, 4, 5, 6, 7, 8, 9].forEach((value, i) => view.setFloat32(96 + 4 * i, value, true));
  assert.deepEqual([...parseStl(buffer)], [1, 2, 3, 4, 5, 6, 7, 8, 9]);
  assert.throws(() => parseStl(new ArrayBuffer(90)));
});

test("fitView centres the silhouette: the shift is the silhouette centre across the view, the 75% identity holds around it", () => {
  const points = [[0, 0, 0], [0.4, 0, 0], [0, 0.02, 0.02], [0.4, 0.02, 0.02]];
  const side = fitView([0, -1, 0], points, 35, 4 / 3);
  assert.ok(Math.abs(side.shift[0] - 0.2) < 1e-9 && Math.abs(side.shift[1]) < 1e-9, "centred on x 0.2 across the side view");
  const t = Math.tan(35 * Math.PI / 360);
  assert.ok(Math.abs(0.4 / (2 * t * (4 / 3) * (side.distance - 0.01)) - 0.75) < 0.03);
  assert.throws(() => presetDirection("under"));
  assert.ok(presetDirection("top")[2] > 0.99 && presetDirection("front")[0] > 0.9);
});

test("the 3D facts line only appends the finished skill text; nothing else changes", () => {
  const base = {kind: "arm", name: "OMX-AI A", selected: true, joints: {joint1: 0}};
  assert.equal(describeRobot(base).summary, "로봇암 OMX-AI A · 선택됨");
  const withSkill = describeRobot({...base, skill: "규칙 운반 · 2/5"});
  assert.equal(withSkill.summary, "로봇암 OMX-AI A · 선택됨 · 규칙 운반 · 2/5");
  assert.equal(withSkill.detail, describeRobot(base).detail);
});
