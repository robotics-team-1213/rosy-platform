/**
 * C15 robot 3D model: the pure half of robot-3d.js (no DOM, no three.js; node tests it). Reads the small URDFs that
 * tools/robot_meshes.py writes, maps reported joints to URDF joint values, builds the text that says what the picture shows,
 * and computes camera presets.
 *
 *   parseUrdf(text) -> {name, links: {name: {mesh, xyz, rpy}}, joints: [{name, type, parent, child, xyz, rpy, axis, lower,
 *                       upper, mimic}], root}
 *   parseStl(arrayBuffer) -> Float32Array   binary STL positions, 9 floats per triangle (the web meshes are binary STL in metres)
 *   jointAngles(model, values) -> {angles: {joint: rad}, ignored: [name]}   values {jointName: rad}; unknown or non-finite
 *                       names are ignored (never drawn as 0), revolute values clamp to the limits, a mimic follows its master
 *   jointsFromList(values, names) -> {name: rad}                            positional telemetry to the URDF names
 *   describeRobot({kind, name, selected, joints, pose, link, skill}) -> {summary, detail}   summary is shown, detail is the joint/pose list;
 *                       skill is one finished text (executor and step, e.g. `규칙 운반 · 2/5`) appended to the summary; text only: a proposed but
 *                       not executed target is never drawn, so the picture shows measured joints and the line says what is running
 *   fitView(dir, points, fovDeg, aspect, fill = 0.75) -> {distance, shift}   camera distance (and sideways target shift) that fills the view with the points
 *   fitDistance(...) -> distance only
 *
 * Joint and pose values are never constants: a missing one reads EVIDENCE_LABEL.unavailable (D-280).
 */
import {EVIDENCE_LABEL} from "./core_ui_logic.js";
import {ROBOT_KIND_LABEL} from "./robot-profile.js";

const nums = text => (text || "0 0 0").trim().split(/\s+/).map(Number);
const attrs = text => Object.fromEntries([...text.matchAll(/([\w:-]+)="([^"]*)"/g)].map(match => [match[1], match[2]]));
const finite = value => typeof value === "number" && Number.isFinite(value);

export function parseUrdf(text) {
  const model = {name: "", links: {}, joints: [], root: null};
  let link = null, joint = null;
  for (const [, closing, tag, body, selfClosed] of String(text).matchAll(/<(\/?)([\w:]+)([^>]*?)(\/?)>/g)) {
    const a = attrs(body);
    if (closing) { if (tag === "link") link = null; if (tag === "joint") joint = null; continue; }
    if (tag === "robot") model.name = a.name || "";
    else if (tag === "link") { link = model.links[a.name] = {mesh: null, xyz: [0, 0, 0], rpy: [0, 0, 0]}; }
    else if (tag === "joint") { joint = {name: a.name, type: a.type, parent: "", child: "", xyz: [0, 0, 0], rpy: [0, 0, 0], axis: [0, 0, 1], lower: -Infinity, upper: Infinity, mimic: null}; model.joints.push(joint); }
    else if (tag === "mesh" && link) link.mesh = a.filename;
    else if (tag === "origin") { const target = joint || link; if (target) { target.xyz = nums(a.xyz); target.rpy = nums(a.rpy); } }
    else if (joint && tag === "parent") joint.parent = a.link;
    else if (joint && tag === "child") joint.child = a.link;
    else if (joint && tag === "axis") joint.axis = nums(a.xyz);
    else if (joint && tag === "limit") { if (a.lower !== undefined) joint.lower = Number(a.lower); if (a.upper !== undefined) joint.upper = Number(a.upper); }
    else if (joint && tag === "mimic") joint.mimic = {joint: a.joint, multiplier: Number(a.multiplier ?? 1)};
    if (selfClosed && tag === "link") link = null;
  }
  const children = new Set(model.joints.map(item => item.child));
  model.root = Object.keys(model.links).find(name => !children.has(name)) ?? null;
  if (!model.root) throw new Error("URDF has no root link");
  for (const item of model.joints) if (!model.links[item.parent] || !model.links[item.child]) throw new Error(`URDF joint ${item.name} names an unknown link`);
  return model;
}

export function parseStl(buffer) {
  const view = new DataView(buffer), count = view.byteLength >= 84 ? view.getUint32(80, true) : -1;
  if (count < 0 || view.byteLength !== 84 + 50 * count) throw new Error("not a binary STL");
  const out = new Float32Array(count * 9);
  for (let i = 0; i < count; i++) for (let k = 0; k < 9; k++) out[i * 9 + k] = view.getFloat32(84 + 50 * i + 12 + 4 * k, true);
  return out;
}

export function jointAngles(model, values = {}) {
  const angles = {}, ignored = [];
  const movable = new Map(model.joints.filter(item => item.type === "revolute" || item.type === "continuous").map(item => [item.name, item]));
  for (const [name, raw] of Object.entries(values || {})) {
    const item = movable.get(name);
    if (!item || !finite(raw)) { ignored.push(name); continue; }
    angles[name] = item.type === "revolute" ? Math.min(item.upper, Math.max(item.lower, raw)) : raw;
  }
  for (const item of movable.values()) {
    if (item.mimic && finite(angles[item.mimic.joint]) && !(item.name in angles)) angles[item.name] = angles[item.mimic.joint] * item.mimic.multiplier;
  }
  return {angles, ignored};
}

export function jointsFromList(values, names) {
  return Object.fromEntries(names.flatMap((name, index) => (finite(values?.[index]) ? [[name, values[index]]] : [])));
}

const JOINT_LABEL = {joint1: "관절 1", joint2: "관절 2", joint3: "관절 3", joint4: "관절 4", joint5: "관절 5", gripper_joint_1: "그리퍼"};
const degrees = rad => `${Math.round(rad * 180 / Math.PI)}°`;
export const headingDeg = yaw => { const d = ((yaw * 180 / Math.PI) % 360 + 540) % 360 - 180; return Math.round(d === -180 ? 180 : d); };

/** {summary, detail}: summary = kind, name, selected and one short link state (what is shown); detail = joints or pose (the accessible description and a toggletip). */
export function describeRobot({kind, name, selected = false, joints, pose, link, skill}) {
  let detail;
  if (kind === "arm") {
    const shown = Object.keys(JOINT_LABEL).filter(key => finite(joints?.[key]));
    detail = shown.length ? shown.map(key => `${JOINT_LABEL[key]} ${degrees(joints[key])}`).join(" · ") : `관절 ${EVIDENCE_LABEL.unavailable}`;
  } else {
    const placed = finite(pose?.x) && finite(pose?.y) ? `위치 x ${pose.x.toFixed(2)} · y ${pose.y.toFixed(2)} m` : `위치 ${EVIDENCE_LABEL.unavailable}`;
    detail = `${placed} · ${finite(pose?.yaw) ? `방향 ${headingDeg(pose.yaw)}°` : `방향 ${EVIDENCE_LABEL.unavailable}`}`;
  }
  const state = link?.state ? link.text || EVIDENCE_LABEL[link.state] || EVIDENCE_LABEL.unavailable : null;
  if (link?.state && link.state !== "fresh") detail = `마지막 보고 기준 · ${detail}`; // a late report's values are the last known ones
  const summary = [`${ROBOT_KIND_LABEL[kind] ?? kind} ${name || EVIDENCE_LABEL.unavailable}`, selected ? "선택됨" : "선택 안 됨", ...(state ? [state] : []), ...(skill ? [skill] : [])].join(" · ");
  return {summary, detail};
}

/**
 * fitView: distance of a camera looking at the box centre along `dir` (unit vector from the centre to the camera, Z up) at which the
 * box's corners (relative to the centre) fill `fill` of the limiting half-extent of the view: the robot fills about 75% of the shorter side.
 */
export function fitView(dir, points, fovDeg, aspect, fill = 0.75) {
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = v => { const n = Math.hypot(...v) || 1; return v.map(x => x / n); };
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const right = norm(cross([-dir[0], -dir[1], -dir[2]], [0, 0, 1])), up = cross(right, [-dir[0], -dir[1], -dir[2]]);
  const t = Math.tan(fovDeg * Math.PI / 360) * fill;
  const rs = points.map(p => dot(p, right)), us = points.map(p => dot(p, up));
  const ox = (Math.max(...rs) + Math.min(...rs)) / 2, oy = (Math.max(...us) + Math.min(...us)) / 2; // centre the silhouette, not the box
  const distance = Math.max(...points.map((p, i) => dot(p, dir) + Math.max(Math.abs(us[i] - oy) / t, Math.abs(rs[i] - ox) / (t * aspect))));
  return {distance, shift: [0, 1, 2].map(k => right[k] * ox + up[k] * oy)};
}
export const fitDistance = (dir, points, fovDeg, aspect, fill) => fitView(dir, points, fovDeg, aspect, fill).distance;

// Unit view directions (x forward, y left, z up) and distance multipliers of the bounding radius.
const PRESETS = {iso: {dir: [0.8, -0.9, 0.55]}, front: {dir: [1, 0, 0.12]}, side: {dir: [0, -1, 0.12]}, top: {dir: [0.001, 0, 1]}};
export const presetDirection = name => { const d = PRESETS[name]?.dir; if (!d) throw new RangeError(`unknown camera preset ${name}`); const n = Math.hypot(...d); return d.map(x => x / n); };
export const CAMERA_PRESETS = Object.freeze(Object.keys(PRESETS));
export const PRESET_LABEL = Object.freeze({iso: "기본", front: "정면", side: "옆", top: "위"});
