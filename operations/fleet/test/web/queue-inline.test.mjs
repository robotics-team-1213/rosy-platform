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
  get lastElementChild() { return [...this.children].reverse().find((child) => child.nodeType !== 3) ?? null; }
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this.children = []; this.text = String(value); }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  removeAttribute(name) { this.attributes.delete(name); }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  focus() { this.focused = true; }
  scrollIntoView() {}
  click() {  // a DOM-enough click: handlers get a preventable event
    const event = {prevented: false, preventDefault() { this.prevented = true; }};
    this.listeners.click?.(event);
    return event;
  }
  matches(selector) {
    const data = selector.match(/^\[data-([\w-]+)\]$/);  // e.g. [data-message-summary] (camelCase dataset)
    if (data) return this.dataset[data[1].replace(/-(\w)/g, (_, c) => c.toUpperCase())] !== undefined;
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
  const panel = make("section", "queues-panel"); panel.className = "queues-panel"; panel.dataset.open = "false";
  const container = new El("div"); container.className = "queues-container";
  for (const list of ["warning-list", "critical-list"]) {
    const box = new El("div"); box.append(make("ul", list)); container.append(box);
  }
  panel.append(container, make("p", "queues-empty"), make("button", "queues-close"));
  for (const head of ["warning-head", "critical-head"]) make("div", head).append(new El("b"), new El("small"));
  const bell = make("ui-button", "fleet-inbox"); bell.append(make("span", "header-unread"));
  const listeners = {};
  const document = {
    body: new El("body"),
    activeElement: null,
    listeners,
    createElement: (tag) => new El(tag),
    createTextNode: (text) => ({nodeType: 3, textContent: text}),
    getElementById: (id) => nodes.get(id) ?? make("div", id),
    addEventListener(type, fn) { listeners[type] = fn; },
    querySelector: (selector) => [panel, container, ...nodes.values()].find((node) => node.matches(selector)) ?? null,
    querySelectorAll(selector) {  // supports '#critical-list > li, #warning-list > li'
      const rows = [];
      for (const part of selector.split(",")) {
        const hit = part.trim().match(/^#([\w-]+) > (\w+)$/);
        if (hit) rows.push(...(nodes.get(hit[1])?.children ?? []).filter((child) => child.matches?.(hit[2])));
      }
      return rows;
    },
  };
  document.activeElement = document.body;
  const before = {document: globalThis.document, location: globalThis.location};
  globalThis.document = document;
  globalThis.location = {search: ""};
  t.after(() => { globalThis.document = before.document; globalThis.location = before.location; });
  return {el: (id) => document.getElementById(id), document};
}

const STALE_ROBOT = (age) => ({ robot_id: "a", online: true, state_age_s: age, state: { safety: { estop: false },
  battery_status: { level: "warning" }, docking: { state: "DOCK_FAILED" },
  capabilities_degraded: ["cam"], navigation: "FAILED" } });
const STALE_VIEW = () => ({ robots: [], formation: null, stateUnavailable: false, stateLoaded: true,
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

test("C25: the bell badge counts active alerts while open and clears on lock", (t) => {
  const {el, document} = fakeConsole(t);
  const view = STALE_VIEW();
  let locked = false;
  const { fillQueues } = createQueues({ scope: { guard: (fn) => fn }, el, view, render: () => {}, streamEvidence: () => null });
  view.robots = [STALE_ROBOT(6)];
  fillQueues();
  const inbox = createInboxPanel({
    scope: { listen(target, type, fn) { target?.addEventListener?.(type, fn); } },
    el, readView: () => view, isLocked: () => locked,
  });
  inbox.refresh();
  assert.equal(el("header-unread").textContent, "1");
  assert.equal(el("header-unread").hidden, false);
  assert.equal(el("fleet-inbox").dataset.crit, undefined);
  assert.match(el("fleet-inbox").getAttribute("aria-label"), /^알림 창 · 활성 알림 1건$/);

  document.listeners["rosy:inbox"]({ preventDefault() {} });
  assert.equal(el("queues-panel").dataset.open, "true");
  assert.equal(el("header-unread").textContent, "1");  // opening stays live until resolved
  document.listeners.keydown({ key: "Escape", defaultPrevented: false, preventDefault() {} });
  assert.equal(el("queues-panel").dataset.open, "false");

  view.robots = [{ ...STALE_ROBOT(0), line_stuck: { stuck_id: "s" } }];
  fillQueues();
  inbox.refresh();
  assert.equal(el("header-unread").textContent, "5");
  assert.equal(el("queues-summary").textContent, "최우선 1건 · 주의 4건");
  assert.equal(el("warning-head").querySelector("b").textContent, "주의 요망 4건 · 1대");
  assert.equal(el("critical-head").querySelector("b").textContent, "최우선 개입 요망 1건 · 1대");
  assert.equal(el("fleet-inbox").dataset.crit, "true");
  assert.match(el("fleet-inbox").getAttribute("aria-label"), /최우선 1건/);
  assert.equal(el("fleet-inbox").getAttribute("data-ui-tooltip"), "활성 알림 5건");
  assert.equal(el("fleet-inbox").getAttribute("title"), null);

  locked = true;
  inbox.clear();
  assert.equal(el("queues-panel").dataset.open, "false");
  assert.equal(el("header-unread").textContent, "");
  assert.equal(el("header-unread").hidden, true);
});

test("B-2: jumpToQueueRow opens the drawer and exact folded row and focuses its summary", (t) => {
  const {el} = fakeConsole(t);
  const view = STALE_VIEW();
  const { fillQueues } = createQueues({ scope: {}, el, view, render: () => {}, streamEvidence: () => null });
  view.robots = [STALE_ROBOT(6)];
  fillQueues();
  const inbox = createInboxPanel({ scope: { listen() {} }, el, readView: () => view });
  inbox.refresh();
  const li = el("warning-list").children[0];
  assert.equal(inbox.jumpToQueueRow("a|stale-snapshot"), true);
  assert.equal(el("queues-panel").dataset.open, "true");
  assert.equal(li.querySelector("details").open, true);
  assert.equal(li.querySelector("summary").focused, true);
});

test("B-2: jumpToQueueRow opens a closed decision row once and never re-closes an open one", (t) => {
  const {el} = fakeConsole(t);
  const view = STALE_VIEW();
  let renders = 0;
  const { fillQueues } = createQueues({ scope: { guard: (fn) => fn }, el, view, render: () => renders++, streamEvidence: () => null });
  view.robots = [{ robot_id: "a", online: false, state: null, line_stuck: { stuck_id: "s" } }];
  view.queueChoice = { key: "a|stuck", open: false };  // the operator had it closed
  fillQueues();
  const inbox = createInboxPanel({ scope: { listen() {} }, el, readView: () => view });
  inbox.refresh();
  const toggle = el("critical-list").children.find((child) => child.dataset.decision === "stuck").querySelector(".queue-row");
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(inbox.jumpToQueueRow("a|stuck"), true);
  assert.equal(el("queues-panel").dataset.open, "true");
  assert.equal(view.queueChoice.open, true);  // the queues.js disclosure handler ran
  assert.equal(renders, 1);
  assert.equal(toggle.focused, true);
  fillQueues();  // the poll applies the choice: aria-expanded flips to true
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  inbox.jumpToQueueRow("a|stuck");  // a second jump must not toggle it closed
  assert.equal(view.queueChoice.open, true);
  assert.equal(renders, 1);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
});

test("a pending CORE pause proof blocks resume while cancel stays available", () => {
  const hold = { reason: "fleet_hold", stop: { confirmed: false } };
  const pending = replanView({ hold }, { operator: true });
  assert.ok(pending.facts.length > 0);
  assert.equal(pending.confirmReason, pending.facts);
  assert.equal(pending.cancelReason, "");
  hold.stop.confirmed = true;
  assert.equal(replanView({ hold }, { operator: true }).confirmReason, "");
});

test("T-D: fillQueues sorts critical rows as overdue -> decision -> admin-held estop", (t) => {
  const { el } = fakeConsole(t);
  const view = STALE_VIEW();
  const { fillQueues } = createQueues({ scope: { guard: (fn) => fn }, el, view, render: () => {}, streamEvidence: () => null });
  view.robots = [
    { robot_id: "r_admin", online: true, state: { safety: { estop: true } } },
    { robot_id: "r_stuck", online: true, line_stuck: { resolver: { escalated: "waiting", age_s: 5 } }, state: { safety: { estop: false } } },
    { robot_id: "r_over", online: true, line_stuck: { resolver: { escalated: "waiting", age_s: 45 } }, state: { safety: { estop: false } } },
  ];
  fillQueues();
  const keys = el("critical-list").children.map((n) => n.dataset.key);
  assert.deepEqual(keys, ["r_over|stuck", "r_stuck|stuck", "r_admin|0"]);
});
