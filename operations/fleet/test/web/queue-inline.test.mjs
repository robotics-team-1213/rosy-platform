// D-540 3 — queue rows open into their decision; robot cards fold to one line unless they must not.
import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { createRoster, mustExpand } = await import("../../../../applications/fleet/web/roster.js");
const { groupRows, groupText, openDecisionKey, queueRowText, createQueues } = await import("../../../../applications/fleet/web/queues.js");
const { createInboxPanel } = await import("../../../../applications/fleet/web/inbox.js");
const { deadlockView, replanView } = await import("../../../../applications/fleet/web/trip-replan.js");

const nominal = (extra = {}) => ({ robot_id: "a", online: true, state: { safety: { estop: false } }, ...extra });

test("the four must-expand states: offline, E-stop latched, safety not nominal, calibration", () => {
  assert.equal(mustExpand(nominal()), false);
  assert.equal(mustExpand(nominal({ online: false })), true);
  assert.equal(mustExpand(nominal({ state: null })), true);                          // no state = offline
  assert.equal(mustExpand(nominal({ state: { safety: { estop: true } } })), true);    // latched
  assert.equal(mustExpand(nominal({ state: { safety: {} } })), true);                 // safety unknown
  assert.equal(mustExpand(nominal({ state: {} })), true);
  assert.equal(mustExpand(nominal({ calibration: { label: "카메라 보정", holder: "kim" } })), true);
});

test("all four safety exceptions stay ahead of nominal robots even without a queue row", () => {
  const { needsAttention } = createRoster({ scope: {onDispose() {}, interval() {}}, view: { stateUnavailable: false, trafficTrips: [], endedTrips: [] }, streamEvidence: () => null });
  assert.equal(needsAttention(nominal()), false);
  for (const row of [nominal({ online: false }), nominal({ state: null }),
    nominal({ state: { safety: { estop: true } } }), nominal({ state: { safety: {} } }),
    nominal({ calibration: { holder: "kim" } })]) assert.equal(needsAttention(row), true);
});

test("one queue row is open: the operator's pick while it lives, else the most urgent decision", () => {
  const keys = ["a|stuck", "b|replan"];
  assert.equal(openDecisionKey(keys, null), "a|stuck");
  assert.equal(openDecisionKey(keys, { key: "b|replan", open: true }), "b|replan");
  assert.equal(openDecisionKey(keys, { key: "a|stuck", open: false }), null);
  assert.equal(openDecisionKey(keys, { key: "gone|stuck", open: true }), "a|stuck");
  assert.equal(openDecisionKey([], null), null);
});

const view = { robots: [], formation: null, stateUnavailable: false, receivedAtMs: Date.now(), trafficTrips: [] };
const { attentionItems } = createRoster({ scope: {onDispose() {}, interval() {}}, view, streamEvidence: () => null });

test("an offline stuck robot keeps its decision row after the disconnect row", () => {
  const items = attentionItems({ robot_id: "a", online: false, state: null, line_stuck: { stuck_id: "s" } });
  assert.deepEqual(items.map((item) => [item.severity, item.decision]), [["warn", undefined], ["crit", "stuck"]]);
});

test("a trip held for a changed route is a critical replan row; a running trip is not", () => {
  view.trafficTrips = [{ trip_id: "t1", robot_id: "a", hold: { reason: "replan", plan: { places: [] } } },
    { trip_id: "t2", robot_id: "b", hold: null }];
  assert.deepEqual(attentionItems(nominal()).filter((item) => item.decision).map((item) => item.decision), ["replan"]);
  assert.equal(attentionItems(nominal({ robot_id: "b" })).length, 0);
  view.trafficTrips = [];
});

test("replan slot: confirm needs an operator and a plan; cancel (a stop) needs only an operator", () => {
  const held = { trip_id: "t1", robot_id: "a",
    hold: { reason: "replan", plan: { places: ["p1", "p2"] }, length_m: 3.14, eta_s: 41.6 } };
  assert.deepEqual(replanView(held, { operator: true }),
    { facts: "바뀐 경로 3.1 m · 약 42초 · 장소 2곳", confirmReason: "", cancelReason: "" });
  assert.equal(replanView(held, { operator: false }).confirmReason, "운영자 권한이 필요합니다");
  assert.equal(replanView(held, { operator: true, busy: true }).cancelReason, "답을 보내는 중");
  const named = replanView(held, { operator: true, named: "이름 있는 운영자 로그인이 필요합니다" });
  assert.equal(named.confirmReason, "이름 있는 운영자 로그인이 필요합니다");  // a move (D-540 9)
  assert.equal(named.cancelReason, "");                                   // a stop stays open
  const failed = { ...held, hold: { reason: "lap", plan: null, code: "PLAN_NO_ROUTE" } };
  const spec = replanView(failed, { operator: true });
  assert.equal(spec.confirmReason, "다시 계산한 경로가 없습니다");
  assert.equal(spec.cancelReason, "");
  assert.match(spec.facts, /PLAN_NO_ROUTE/);
});

test("deadlock slot (D-577 d): Fleet's decision per robot, AI facts for this robot, existing trip routes only", () => {
  const traffic = { wait_cycle: ["a", "b", "signal:z1"], resolver: [
    { robot_id: "a", trigger: "wait_cycle", decision: "replan" }, { robot_id: "b", trigger: "wait_cycle", decision: "wait" }] };
  const facts = [{ kind: "wait_cycle_stale_input", robot_ids: ["a", "b"], confidence: 0.7, observed_at: 1 },
    { kind: "wait_cycle_stale_input", robot_ids: ["a", "b"], confidence: 0.8, observed_at: 2 },  // newest wins
    { kind: "wait_cycle_stale_input", robot_ids: ["a", "b"], confidence: 0.7, observed_at: 0 },
    { kind: "waiting_but_moving", robot_ids: ["c"], confidence: 0.8 }];
  const held = { trip_id: "t1", robot_id: "a", hold: { reason: "replan", plan: { places: [] } } };
  assert.deepEqual(deadlockView(traffic, held, facts, "a", { operator: true }), {
    lines: ["a · 해결기 다른 길 계획", "b · 해결기 다른 로봇 대기", "AI 참고 · 낡은 입력의 교착일 수 있음 · a, b · 신뢰도 80%"],
    confirmReason: "", cancelReason: "" });
  const named = deadlockView(traffic, held, [], "a", { operator: true, named: "이름 있는 운영자 로그인이 필요합니다" });
  assert.equal(named.confirmReason, "이름 있는 운영자 로그인이 필요합니다");   // a move needs a named operator
  assert.equal(named.cancelReason, "");                                    // a stop stays open
  assert.equal(named.lines.at(-1), "AI 사실 없음");
  const running = deadlockView(traffic, { trip_id: "t2", robot_id: "b", hold: null }, facts, "b", { operator: true });
  assert.equal(running.confirmReason, "확인할 바뀐 경로가 없습니다");
  assert.equal(running.cancelReason, "");
  const none = deadlockView({ wait_cycle: ["a", "b"], resolver: [] }, null, [], "a", { operator: false });
  assert.equal(none.lines[0], "a · 해결기 판단 전");
  assert.equal(none.confirmReason, "운영자 권한이 필요합니다");
  assert.equal(deadlockView(traffic, null, [], "a", { operator: true }).cancelReason, "열린 운행이 없습니다");
  const disagree = [{kind: "wait_cycle_confirmed", robot_ids: ["a", "b"], confidence: 0.7,
    value: {fleet_agrees: false}, observed_at: 3}];
  assert.match(deadlockView(traffic, held, disagree, "a", {operator: true}).lines.at(-1), /Fleet 순환과 불일치/);
});

test("a later row of the same robot hides the name and its colon", () => {
  // Field check 2026-10-10: ": Rosy Cam이 rosy_41를 찾지 못합니다" started with a bare colon.
  assert.equal(queueRowText(": 교통 대기", true), ": 교통 대기");
  assert.equal(queueRowText(": Rosy Cam이 rosy_41을 찾지 못합니다", false), "Rosy Cam이 rosy_41을 찾지 못합니다");
});

test("one warn cause on many robots is one row; decisions and single causes stay their own rows", () => {
  const battery = ": 배터리 값 멈춤 — 센서 연결 확인";
  const rows = [
    { robotId: "rosy_001", text: battery, key: "rosy_001|0" },
    { robotId: "rosy_002", text: ": 연결 끊김", key: "rosy_002|1" },
    ...["rosy_003", "rosy_004", "rosy_005", "rosy_006"].map((robotId, i) => ({ robotId, text: battery, key: `${robotId}|${i}` })),
    { robotId: "rosy_007", text: battery, decision: "stuck", key: "rosy_007|stuck" },
  ];
  const out = groupRows(rows);
  assert.deepEqual(out.map((row) => row.key), ["group|" + battery, "rosy_002|1", "rosy_007|stuck"]);
  assert.deepEqual(out[0].group, ["rosy_001", "rosy_003", "rosy_004", "rosy_005", "rosy_006"]);
  assert.equal(groupText(battery, out[0].group),
    "배터리 값 멈춤 — 센서 연결 확인 · 5대 (rosy_001 · rosy_003 · rosy_004 외 2대)");
  assert.equal(groupText(": 연결 끊김", ["a", "b"]), "연결 끊김 · 2대 (a · b)");
});

// B-1 — a bare-bones element good enough for fillQueues/syncRows and the inbox reader: tags, .class
// selectors, datasets and text nodes. Real-browser behaviour (open <details>, focus) has Chromium coverage.
class El {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.id = ""; this.className = ""; this.text = ""; this.parentElement = null;
    this.children = []; this.dataset = {}; this.hidden = false; this.attributes = new Map(); this.listeners = {};
  }
  append(...nodes) { for (const one of nodes) { if (typeof one !== "string") one.parentElement = this; this.children.push(one); } }
  replaceChildren(...nodes) { for (const one of nodes) if (typeof one !== "string") one.parentElement = this; this.children = [...nodes]; }
  get childElementCount() { return this.children.length; }
  get firstElementChild() { return this.children.find((child) => child.nodeType !== 3) ?? null; }
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this.children = []; this.text = String(value); }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  removeAttribute(name) { this.attributes.delete(name); }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  focus() {}
  matches(selector) {
    return selector.startsWith("#") ? this.id === selector.slice(1)
      : selector.startsWith(".") ? this.className.split(/\s+/).includes(selector.slice(1))
      : this.tagName === selector.toUpperCase();
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  querySelectorAll(selector) {
    const found = [];
    for (const child of this.children) {
      if (child.nodeType === 3) continue;
      if (child.matches(selector)) found.push(child);
      found.push(...child.querySelectorAll(selector));
    }
    return found;
  }
}

function fakeConsole(t) {
  const nodes = new Map();
  const make = (tag, id) => { const el = new El(tag); el.id = id; nodes.set(id, el); return el; };
  const panel = new El("div"); panel.className = "queues-panel";
  for (const list of ["warning-list", "critical-list"]) {
    const box = new El("div"); box.append(make("ul", list)); panel.append(box);
  }
  for (const head of ["warning-head", "critical-head"]) make("div", head).append(new El("b"), new El("small"));
  const document = {
    createElement: (tag) => new El(tag),
    createTextNode: (text) => ({nodeType: 3, textContent: text}),
    getElementById: (id) => nodes.get(id) ?? make("div", id),
    querySelector: (selector) => [panel, ...nodes.values()].find((node) => node.matches(selector)) ?? null,
    querySelectorAll(selector) {  // exactly the inbox read: '#critical-list > li, #warning-list > li'
      const rows = [];
      for (const part of selector.split(",")) {
        const hit = part.trim().match(/^#([\w-]+) > (\w+)$/);
        if (hit) rows.push(...(nodes.get(hit[1])?.children ?? []).filter((child) => child.matches?.(hit[2])));
      }
      return rows;
    },
  };
  const before = {document: globalThis.document, location: globalThis.location};
  globalThis.document = document;
  globalThis.location = {search: ""};
  t.after(() => { globalThis.document = before.document; globalThis.location = before.location; });
  return {el: (id) => document.getElementById(id)};
}

const STALE_ROBOT = (age) => ({ robot_id: "a", online: true, state_age_s: age, state: { safety: { estop: false },
  battery_status: { level: "warning" }, docking: { state: "DOCK_FAILED" },
  capabilities_degraded: ["cam"], navigation: "FAILED" } });
const STALE_VIEW = () => ({ robots: [], formation: null, stateUnavailable: false,
  receivedAtMs: Date.now() - 1000, trafficTrips: [], endedTrips: [] });

test("B-1: a stale robot renders one folded rollup row; an open <details> survives the next fillQueues", (t) => {
  const {el} = fakeConsole(t);
  const view = STALE_VIEW();
  const { fillQueues } = createQueues({ scope: {}, el, view, render: () => {}, streamEvidence: () => null });
  view.robots = [STALE_ROBOT(6)];
  fillQueues();
  const list = el("warning-list");
  assert.equal(list.children.length, 1);  // not four separate battery/dock/degraded/goal rows
  const li = list.children[0], details = li.querySelector("details"), summary = li.querySelector("summary");
  assert.equal(li.dataset.folded, "1");
  assert.equal(li.dataset.foldedKind, "배터리 부족|도킹 실패|성능 저하 [cam]|목표 실패");
  assert.match(summary.textContent, /^a: 상태 오래됨 — \d+초 전 값 · 지연 경고 4건$/);
  assert.equal(li.querySelector(".hint").textContent,
    "이전 스냅샷 경고: 배터리 부족 · 도킹 실패 · 성능 저하 [cam] · 목표 실패");
  details.open = true;  // the operator reads the causes
  view.robots = [STALE_ROBOT(8)];  // 1 Hz later the same robot is only older
  fillQueues();
  assert.equal(list.children[0], li);  // the same li, summary and open state survive the repaint
  assert.equal(li.querySelector("summary"), summary);
  assert.equal(li.querySelector("details").open, true);
  assert.match(summary.textContent, /지연 경고 4건$/);
});

test("B-1: the inbox reads the folded summary line; an age tick stays read, a changed cause set is unread", (t) => {
  const {el} = fakeConsole(t);
  const view = STALE_VIEW();
  const { fillQueues } = createQueues({ scope: {}, el, view, render: () => {}, streamEvidence: () => null });
  view.robots = [STALE_ROBOT(6)];
  fillQueues();
  const inbox = createInboxPanel({ scope: { listen() {} }, el, readView: () => view });
  inbox.refresh();
  inbox.select("inbox");  // the operator reads it
  assert.equal(el("header-unread").textContent, "");
  inbox.select("status");  // back to the status tab, where a new exception can be unread again
  view.robots = [STALE_ROBOT(9)];  // only the age moved
  fillQueues();
  inbox.refresh();
  assert.equal(el("header-unread").textContent, "");
  view.robots = [{ ...STALE_ROBOT(9), state: { ...STALE_ROBOT(9).state, battery_status: { level: "ok" } } }];
  fillQueues();
  inbox.refresh();  // the folded cause set changed: a genuinely new exception
  assert.equal(el("header-unread").textContent, "1");
  assert.match(el("inbox-current").textContent, /지연 경고 3건/);
});
