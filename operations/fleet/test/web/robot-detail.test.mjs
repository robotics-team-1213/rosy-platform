import test from "node:test";
import assert from "node:assert/strict";

function makeEl(tagName) {
  const attrs = new Map();
  const classes = new Set();
  const listeners = new Map();
  const children = [];
  const node = {
    tagName: tagName.toUpperCase(),
    dataset: {},
    children,
    childNodes: children,
    parentElement: null,
    tabIndex: 0,
    hidden: false,
    open: false,
    _text: "",
    get className() { return [...classes].join(" "); },
    set className(v) { classes.clear(); for (const c of String(v || "").split(/\s+/).filter(Boolean)) classes.add(c); },
    classList: {
      add: (...xs) => xs.forEach(x => classes.add(x)),
      remove: (...xs) => xs.forEach(x => classes.delete(x)),
      toggle: (x, f) => (f === undefined ? !classes.has(x) : f) ? classes.add(x) : classes.delete(x),
      contains: x => classes.has(x),
    },
    get childElementCount() { return children.length; },
    get firstElementChild() { return children[0] || null; },
    get textContent() { return node._text || children.map(c => c.textContent).join(""); },
    set textContent(v) { node._text = String(v ?? ""); children.length = 0; },
    setAttribute(k, v) {
      attrs.set(k, String(v));
      if (k === "id") node.id = String(v);
    },
    getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
    hasAttribute(k) { return attrs.has(k); },
    removeAttribute(k) { attrs.delete(k); },
    toggleAttribute(k, force) {
      const on = force === undefined ? !attrs.has(k) : Boolean(force);
      if (on) attrs.set(k, ""); else attrs.delete(k);
      return on;
    },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    removeEventListener() {},
    dispatchEvent() {},
    append(...nodes) {
      for (const n of nodes) {
        if (!n) continue;
        if (typeof n === "string") { children.push({_text: n, get textContent() { return this._text; }}); continue; }  // 텍스트 마디
        n.parentElement = node;
        children.push(n);
      }
    },
    appendChild(n) { node.append(n); return n; },
    replaceChildren(...nodes) { children.length = 0; node.append(...nodes); },
    remove() {
      if (!node.parentElement) return;
      const idx = node.parentElement.children.indexOf(node);
      if (idx >= 0) node.parentElement.children.splice(idx, 1);
      node.parentElement = null;
    },
    matches() { return false; },
    closest() { return null; },
    contains(target) { return target === node || children.some((c) => typeof c.contains === "function" && c.contains(target)); },
    querySelectorAll(sel) {
      const out = [];
      const walk = (cur) => {
        for (const c of cur.children) {
          if (c.classList && sel.startsWith(".") && c.classList.contains(sel.slice(1))) out.push(c);
          else if (c.classList && sel === ".robot-row" && c.classList.contains("robot-row")) out.push(c);
          else if (c.classList && sel === ".robot-view" && c.classList.contains("robot-view")) out.push(c);
          else if (c.dataset && sel === "[data-robot-profile]" && c.dataset.robotProfile !== undefined) out.push(c);
          else if (c.dataset && sel === "[data-sample]" && c.dataset.sample !== undefined) out.push(c);
          if (Array.isArray(c.children)) walk(c);
        }
      };
      walk(node);
      return out;
    },
    querySelector(sel) {
      if (sel.startsWith("#")) {
        const id = sel.slice(1);
        const walk = (cur) => {
          if (!Array.isArray(cur?.children)) return null;
          for (const c of cur.children) {
            if (c.id === id) return c;
            const hit = walk(c);
            if (hit) return hit;
          }
          return null;
        };
        return walk(node);
      }
      return node.querySelectorAll(sel)[0] || null;
    },
    focus() {},
  };
  return node;
}

const byId = new Map();
globalThis.document = {
  createElement: makeEl,
  getElementById: (id) => byId.get(id) || null,
  activeElement: null,
  addEventListener() {},
  removeEventListener() {},
};
globalThis.window = {
  matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {} }),
  dispatchEvent() {},
};
globalThis.CustomEvent = class CustomEvent { constructor(type, init) { this.type = type; this.detail = init?.detail; } };
globalThis.cancelAnimationFrame = () => {};

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);

const { createSelection } = await import("../../../../shared/web/selection.js");
const { createRoster, selectRobot } = await import("../../../../applications/fleet/web/robot/roster.js");
const { fleetRobotProfile } = await import("../../../../applications/fleet/web/robot/roster-presentation.js");

test("fleetRobotProfile maps battery, online, and alarm", () => {
  const p = fleetRobotProfile({
    robot_id: "rosy_01",
    online: true,
    state_age_s: 1,
    power_health: { battery: { percent: 63, voltage: 12.1 } },
    state: { safety: { estop: false }, pose: { x: 1.2, y: -0.4, yaw: 0 } },
  }, { stateUnavailable: false, receivedAtMs: Date.now(), trafficTrips: [], robotNames: {} });
  assert.equal(p.id, "rosy_01");
  assert.equal(p.kind, "mobile");
  assert.ok(p.power.text.includes("63%"));
  assert.equal(p.alarm, null);
});

test("selectRobot syncs createSelection and clears map pick state", () => {
  const selection = createSelection(null);
  const view = {
    robots: [{ robot_id: "rosy_01" }],
    selected: "rosy_01",
    pinning: "rosy_01",
    cursor: { col: 1, row: 1 },
    robotSelection: selection,
  };
  assert.equal(selectRobot(view, "rosy_01"), true);
  assert.equal(selection.get(), "rosy_01");
  assert.equal(view.selected, null);
  assert.equal(view.pinning, null);
  assert.equal(view.cursor, null);
});

test("robot detail renders C14 row, phase-2 slots, pinned battery 63%, and one C15 3D view", () => {
  const ws = makeEl("div"); ws.id = "robot-workspace";
  const empty = makeEl("div"); empty.id = "robot-workspace-empty";
  byId.set("robot-workspace", ws);
  byId.set("robot-workspace-empty", empty);
  const selection = createSelection("rosy_01");
  const view = {
    robots: [{
      robot_id: "rosy_01",
      online: true,
      state_age_s: 0.5,
      power_health: { battery: { percent: 63, voltage: 12.2 } },
      state: { mode: "IDLE", safety: { estop: false }, pose: { x: 1, y: 2, yaw: 0 } },
    }],
    selected: null,
    pinning: null,
    cursor: null,
    colors: ["#111"],
    formation: null,
    stateUnavailable: false,
    receivedAtMs: Date.now(),
    trafficTrips: [],
    pendingTasks: {},
    robotPeers: [],
    robotNames: {},
    addresses: {},
    robotSelection: selection,
  };
  const disposers = [];
  const scope = {
    guard: (fn) => fn,
    capture: () => ({ check() {}, current: () => true, signal: null }),
    onDispose: (fn) => disposers.push(fn),
    interval() {},
    listen() {},
  };
  const roster = createRoster({
    scope,
    el: (id) => byId.get(id) || null,
    view,
    log() {},
    call: async () => ({}),
    render() {},
    streamEvidence: () => null,
    isOperator: () => true,
    confirmedAction: { cancel() {} },
  });
  roster.workspace();
  assert.equal(empty.hidden, true);
  assert.equal(ws.children.length, 1);
  const card = ws.children[0];
  assert.equal(card.querySelectorAll(".robot-row").length, 1);
  assert.equal(card.querySelectorAll(".robot-view").length, 1);
  for (const id of ["detail-refusal", "detail-now", "detail-localization", "detail-skill"]) {
    assert.ok(card.querySelector(`#${id}`), `missing #${id}`);
  }
  // B3: arm_skill가 없으면 스킬 칸은 조용히 비어 있다(없는 값을 지어내지 않는다).
  assert.equal(card.querySelector("#detail-skill").childElementCount, 0);
  assert.ok(card.textContent.includes("63%"));
  for (const fn of disposers) fn();
});

// B3 (계획 6.2 R3·R4): 로봇 행 글자·#detail-skill·3D 상태 줄이 같은 C20 표를 쓴다.
const ARM_SKILL = { sample: true, lifecycle: "running", executor: "act", policyId: "act-pick",
  version: "0123456789abcdef0123", step: { n: 3, of: 5 }, guard: "ok" };

test("a running arm skill is the robot row's task text with no tag; #detail-skill carries the readout", () => {
  const robot = { robot_id: "arm_a", kind: "arm", online: true, state_age_s: 0.5,
    power_health: { battery: { percent: 63 } }, state: { safety: { estop: false }, arm_skill: ARM_SKILL } };
  const profile = fleetRobotProfile(robot, { stateUnavailable: false, receivedAtMs: Date.now(), trafficTrips: [] });
  assert.equal(profile.task.text, "실행 중 3/5");   // 행 글자 = C20 표 (정상 진행은 조용하다)
  assert.equal(profile.alarm, null);
  const stopped = fleetRobotProfile({ ...robot, state: { safety: { estop: false }, arm_skill: { ...ARM_SKILL, lifecycle: "stopped", guard: "estop" } } },
    { stateUnavailable: false, receivedAtMs: Date.now(), trafficTrips: [] });
  assert.deepEqual(stopped.alarm, { level: "danger", text: "정지 · HOLD", tag: "danger" });

  const ws = makeEl("div"); ws.id = "robot-workspace";
  byId.set("robot-workspace", ws);
  const empty = makeEl("div"); empty.id = "robot-workspace-empty";
  byId.set("robot-workspace-empty", empty);
  const view = { robots: [robot], selected: null, pinning: null, cursor: null,
    colors: ["#111"], formation: null, stateUnavailable: false, receivedAtMs: Date.now(), trafficTrips: [],
    pendingTasks: {}, robotPeers: [], robotNames: {}, addresses: {}, robotSelection: createSelection("arm_a") };
  const disposers = [];
  const scope = { guard: (fn) => fn, capture: () => ({ check() {}, current: () => true, signal: null }),
    onDispose: (fn) => disposers.push(fn), interval() {}, listen() {} };
  const roster = createRoster({ scope, el: (id) => byId.get(id) || null, view, log() {},
    call: async () => ({}), render() {}, streamEvidence: () => null, isOperator: () => true,
    confirmedAction: { cancel() {} } });
  roster.workspace();
  const card = ws.children[0];
  const skillSlot = card.querySelector("#detail-skill");
  assert.ok(skillSlot.querySelector(".detail-skill-line").textContent.includes("실행 중 3/5"));
  assert.ok(skillSlot.querySelector("[data-sample]"), "샘플 상태는 sampleTag가 이름을 밝힌다");
  const strip = skillSlot.querySelector(".detail-skill-readout");
  assert.ok(strip.textContent.includes("학습 정책"));
  assert.ok(strip.textContent.includes("act-pick@01234567"));
  assert.ok(strip.textContent.includes("3/5"));
  for (const fn of disposers) fn();
});
