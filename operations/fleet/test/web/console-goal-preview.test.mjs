// Wave 4 S2 — server planTrip preview before confirm on viaTrip site-map goals.
import assert from "node:assert/strict";
import test from "node:test";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { createConsoleGoal } = await import("../../../../applications/fleet/web/console-goal.js");

const SITE_MAP = {
  map_id: "site_a",
  places: [
    { id: "A", name: "출발", kind: "start", x: 0.0, y: 0.0 },
    { id: "B", name: "도착", kind: "stop", x: 1.5, y: 0.5 },
  ],
  edges: [
    { id: "e1", from: "A", to: "M", direction: "two_way", polyline: [[0, 0], [0.8, 0]] },
    { id: "e2", from: "M", to: "B", direction: "one_way", polyline: [[0.8, 0], [1.5, 0], [1.5, 0.5]] },
  ],
};

function setup(t, { tripHandler, onConfirm, handlers = {}, refreshGuide = () => {}, view: viewOverrides = {}, auth: authOverrides = {} } = {}) {
  const beforeDocument = globalThis.document;
  globalThis.document = { activeElement: null, querySelectorAll: () => [] };
  t.after(() => { globalThis.document = beforeDocument; });

  const canvasListeners = new Map();
  const canvas = {
    classList: { add() {}, toggle() {} },
    tabIndex: 0,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 400 }),
    addEventListener(type, fn) { canvasListeners.set(type, fn); },
    removeEventListener(type) { canvasListeners.delete(type); },
  };
  const elements = { "map-canvas": canvas };
  const calls = [];
  const logs = [];
  let draws = 0;
  let renders = 0;
  const view = {
    selected: "rosy_01",
    focusRobot: "rosy_01",
    map: null,
    siteMap: { maps: [{ map_id: "site_a", polygon_m: [[0, 0], [2, 0], [2, 1], [0, 1]] }] },
    activeSiteMap: { version: 4, map: SITE_MAP },
    guide: {
      map_version: 4,
      robots: [{ robot_id: "rosy_01", online: true, pose: { state: "LOCALIZED", x: 0.0, y: 0.0, yaw: 0.0 } }],
    },
    robots: [{
      robot_id: "rosy_01",
      online: true,
      state: { map_id: "slam_local", safety: { estop: false }, pose: { x: 0.0, y: 0.0, yaw: 0.0 } },
    }],
    trafficTrips: [],
    pendingTasks: {},
    stateUnavailable: false,
    anchors: [],
    layers: {},
    ...viewOverrides,
  };

  const pageScope = {
    listen(target, type, fn) { if (target === canvas) canvasListeners.set(type, fn); },
    capture() {
      return {
        signal: new AbortController().signal,
        current: () => true,
        check() {},
      };
    },
  };

  const confirmSpecs = [];
  const confirmedAction = {
    async run(spec) {
      confirmSpecs.push(spec);
      if (onConfirm) return onConfirm(spec);
      return false;
    },
  };

  const call = async (path, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ path, method: init.method || "GET", body });
    for (const [suffix, fn] of Object.entries(handlers)) {
      if (path.endsWith(suffix)) return fn(path, body);
    }
    if (path.endsWith("/trip")) return tripHandler(path, body);
    if (path.endsWith("/start")) return { trip_id: "trip-1", state: "running" };
    throw new Error(`unexpected call ${path}`);
  };

  const goal = createConsoleGoal({
    pageScope,
    el: (id) => elements[id] || null,
    view,
    auth: { role: "operator", principal: "kim", locked: false, token: "t", ...authOverrides },
    inbox: { select() {} },
    log: (text, tone) => logs.push({ text, tone }),
    call,
    render: () => { renders += 1; },
    confirmedAction,
    namedReason: () => "",
    toWorld: () => ({ x: 0, y: 0 }),
    refreshGuide,
    queuedReason: () => "",
    drawMap: () => { draws += 1; },
    onSelectRobot: () => {},
  });

  return {
    goal,
    view,
    calls,
    logs,
    confirmSpecs,
    canvasListeners,
    counts: () => ({ draws, renders }),
  };
}

const VALID_PLAN = (extra = {}) => ({
  plan_id: "plan-123",
  map_version: 4,
  length_m: 1.65,
  eta_s: 11,
  places: ["A", "M", "B"],
  segments: [
    { edge_id: "e1", forward: true, s_from: 0, s_to: 0.8 },
    { edge_id: "e2", forward: true, s_from: 0, s_to: 1.2 },
  ],
  actions: [],
  expires_at: Date.now() / 1000 + 30,
  start_check: { code: null },
  ...extra,
});

test("S2: viaTrip plans on server and draws PREVIEW before confirm, then calls only /start on confirm", async (t) => {
  let snapshotAtConfirm = null;
  const env = setup(t, {
    tripHandler: () => VALID_PLAN(),
    onConfirm: async (spec) => {
      snapshotAtConfirm = {
        status: env.view.selectedGoal.status,
        statusText: env.view.selectedGoal.statusText,
        planId: env.view.selectedGoal.planId,
        points: env.view.selectedGoal.points,
        length_m: env.view.selectedGoal.length_m,
        eta_s: env.view.selectedGoal.eta_s,
        callsSoFar: env.calls.map((c) => c.path),
      };
      assert.equal(spec.eligible(), true);
      await spec.request({ check() {}, signal: new AbortController().signal });
      return true;
    },
  });

  await env.goal.commitWorldGoal({ x: 1.5, y: 0.5 }, "도착 (B)", "B");

  assert.deepEqual(snapshotAtConfirm.callsSoFar, ["/api/fleet/robots/rosy_01/trip"]);
  assert.equal(snapshotAtConfirm.status, "PREVIEW");
  assert.equal(snapshotAtConfirm.planId, "plan-123");
  assert.equal(snapshotAtConfirm.length_m, 1.65);
  assert.equal(snapshotAtConfirm.eta_s, 11);
  assert.match(snapshotAtConfirm.statusText, /2개 차로 · 1\.65 m · 약 11 s · 지도 v4 · 출발 가능 · 확인 대기$/);
  assert.deepEqual(snapshotAtConfirm.points, [[0, 0], [0.8, 0], [1.5, 0], [1.5, 0.5]]);  // deduplicated M vertex across e1 + e2
  assert.match(env.confirmSpecs[0].message, /^rosy_01를 도착 \(B\) \(1\.50, 0\.50\)까지 차로로 보낼까요\? \(2개 차로 · 1\.65 m · 약 11 s · 지도 v4 · 출발 가능\)$/);
  assert.deepEqual(env.calls.map((c) => c.path), [
    "/api/fleet/robots/rosy_01/trip",
    "/api/fleet/trips/plan-123/start",
  ]);
  assert.equal(env.view.selectedGoal.status, "ACCEPTED");
  assert.equal(env.view.selectedGoal.statusText, "Fleet 접수 · 기체 실행 확인 중");
});

test("S2: canceling confirm dispatches no /start and marks PREVIEW cancelled", async (t) => {
  const env = setup(t, {
    tripHandler: () => VALID_PLAN({ plan_id: "plan-cancel" }),
    onConfirm: async () => false,
  });

  await env.goal.commitWorldGoal({ x: 1.5, y: 0.5 }, "도착 (B)", "B");

  assert.deepEqual(env.calls.map((c) => c.path), ["/api/fleet/robots/rosy_01/trip"]);
  assert.equal(env.view.selectedGoal.status, "PREVIEW");
  assert.equal(env.view.selectedGoal.statusText, "서버 경로 미리보기 (출발 취소)");
});

test("S2: server planTrip refusal or start_check block marks BLOCKED and never opens confirm", async (t) => {
  const refused = setup(t, {
    tripHandler: () => {
      const err = new Error("refused");
      err.code = "TRIP_NO_ROUTE";
      err.detail = {};
      throw err;
    },
  });
  await refused.goal.commitWorldGoal({ x: 1.5, y: 0.5 }, "도착 (B)", "B");
  assert.equal(refused.confirmSpecs.length, 0);
  assert.equal(refused.view.selectedGoal.status, "BLOCKED");
  assert.equal(refused.logs.at(-1).tone, "bad");

  const blocked = setup(t, {
    tripHandler: () => VALID_PLAN({ start_check: { code: "TRIP_START_HEADING_MISMATCH", heading_err_deg: 175 } }),
  });
  await blocked.goal.commitWorldGoal({ x: 1.5, y: 0.5 }, "도착 (B)", "B");
  assert.equal(blocked.confirmSpecs.length, 0);
  assert.equal(blocked.view.selectedGoal.status, "BLOCKED");
  assert.match(blocked.view.selectedGoal.statusText, /^방향 반대\(175°\) · /);
});

test("S2: disarmGoal (Escape) or a newer click cancels stale in-flight planTrip", async (t) => {
  let resolveFirst;
  let calls = 0;
  const env = setup(t, {
    tripHandler: () => {
      calls += 1;
      if (calls === 1) return new Promise((resolve) => { resolveFirst = resolve; });
      return VALID_PLAN({ plan_id: "plan-second" });
    },
  });

  const first = env.goal.commitWorldGoal({ x: 1.5, y: 0.5 }, "도착 (B)", "B");
  assert.equal(env.view.selectedGoal.status, "PLANNING");
  env.goal.disarmGoal("목표 지정 취소");
  resolveFirst(VALID_PLAN({ plan_id: "plan-escaped" }));
  await first;
  assert.equal(env.confirmSpecs.length, 0);

  env.view.selected = "rosy_01";
  let resolveSuperseded;
  calls = 0;
  const envRace = setup(t, {
    tripHandler: () => {
      calls += 1;
      if (calls === 1) return new Promise((resolve) => { resolveSuperseded = resolve; });
      return VALID_PLAN({ plan_id: "plan-winner" });
    },
  });
  const p1 = envRace.goal.commitWorldGoal({ x: 1.5, y: 0.5 }, "도착 (B)", "B");
  const p2 = envRace.goal.commitWorldGoal({ x: 1.5, y: 0.5 }, "도착 (B)", "B");
  resolveSuperseded(VALID_PLAN({ plan_id: "plan-stale" }));
  await Promise.all([p1, p2]);
  assert.equal(envRace.confirmSpecs.length, 1);
  assert.equal(envRace.view.selectedGoal.planId, "plan-winner");
});

test("S2: eligible becomes false if plan expires or site-map version changes before confirm", async (t) => {
  let expiry = Date.now() / 1000 + 30;
  let checkEligible;
  const env = setup(t, {
    tripHandler: () => VALID_PLAN({ expires_at: expiry }),
    onConfirm: async (spec) => {
      checkEligible = spec.eligible;
      return false;
    },
  });

  await env.goal.commitWorldGoal({ x: 1.5, y: 0.5 }, "도착 (B)", "B");
  assert.equal(checkEligible(), true);

  // Version drift invalidates the preview
  env.view.activeSiteMap = { ...env.view.activeSiteMap, version: 5 };
  assert.equal(checkEligible(), false);
  env.view.activeSiteMap = { ...env.view.activeSiteMap, version: 4 };
  assert.equal(checkEligible(), true);

  // Expiry invalidates the preview
  const origNow = Date.now;
  try {
    Date.now = () => (expiry + 1) * 1000;
    assert.equal(checkEligible(), false);
  } finally {
    Date.now = origNow;
  }
});

test("Pinning UNKNOWN robot infers road tangent yaw, updates guide immediately, forces guide refresh, and suppresses trailing click", async (t) => {
  const guideRefreshCalls = [];
  const westMap = {
    ...SITE_MAP,
    edges: [{ id: "west_lane", from: "B", to: "A", direction: "one_way", polyline: [[1.2, 0.2], [0.2, 0.2]] }],
  };
  const env = setup(t, {
    refreshGuide: (opts) => guideRefreshCalls.push(opts),
    view: {
      selected: null,
      pinning: "rosy_01",
      activeSiteMap: { version: 4, map: westMap },
      siteToWorld: () => ({ x: 0.7, y: 0.2 }),
      guide: { map_version: 4, robots: [{ robot_id: "rosy_01", online: true, pose: null }] },
    },
    handlers: {
      "/tracking/identity": () => ({ robots: [] }),
      "/map-pin": (_path, body) => ({ state: "LOCALIZED", x: body.x, y: body.y, yaw: body.yaw, anchor_source: "operator_pin", map_id: "site_a" }),
    },
    tripHandler: () => VALID_PLAN(),
  });
  const ev = { clientX: 100, clientY: 100 };
  env.canvasListeners.get("pointerdown")(ev);
  await env.canvasListeners.get("pointerup")(ev);
  const pinCall = env.calls.find((c) => c.path.endsWith("/map-pin"));
  assert.ok(pinCall);
  assert.ok(Math.abs(Math.abs(pinCall.body.yaw) - Math.PI) < 1e-6);
  const patched = env.view.guide.robots.find((r) => r.robot_id === "rosy_01")?.pose;
  assert.equal(patched.state, "LOCALIZED");
  assert.equal(patched.anchor_source, "operator_pin");
  assert.equal(env.counts().draws >= 1 && env.counts().renders >= 1, true);
  assert.deepEqual(guideRefreshCalls, [{ force: true }]);
  // Trailing synthetic click right after pointerup must not arm or plan a trip.
  await env.canvasListeners.get("click")(ev);
  assert.equal(env.calls.some((c) => c.path.endsWith("/trip")), false);
});

test("Road-point click without placeId plans trip to coordinate and falls back to nav2 on camera unavailability", async (t) => {
  const tripBodies = [];
  const env = setup(t, {
    view: {
      robots: [{
        robot_id: "rosy_01",
        online: true,
        capabilities: { controls: { items: [{ kind: "base_velocity", drive_modes: ["lane", "free"] }] } },
        state: { map_id: "slam_local", safety: { estop: false }, pose: { x: 0.0, y: 0.0, yaw: 0.0 } },
      }],
    },
    tripHandler: (_path, body) => {
      tripBodies.push(body);
      if (tripBodies.length === 1) {
        const err = new Error("camera down");
        err.code = "TRIP_LANE_CAMERA_UNAVAILABLE";
        throw err;
      }
      return VALID_PLAN({ plan_id: "plan-nav2" });
    },
  });
  await env.goal.commitWorldGoal({ x: 0.45, y: 0.0 }, "", "");
  assert.deepEqual(tripBodies, [
    { to: { x: 0.45, y: 0.0 } },
    { to: { x: 0.45, y: 0.0 }, drive_mode: "nav2" },
  ]);
  assert.equal(env.confirmSpecs.length, 1);
  assert.equal(env.view.selectedGoal.planId, "plan-nav2");
});

test("Clicking a road/place with focusRobot set and selected null plans trip, while off-road empty click does nothing", async (t) => {
  let clickXY = { x: 5.0, y: 5.0 }; // off-road empty space
  const env = setup(t, {
    view: {
      selected: null,
      focusRobot: "rosy_01",
      siteToWorld: () => clickXY,
    },
    tripHandler: () => VALID_PLAN({ plan_id: "plan-focus" }),
  });
  await env.canvasListeners.get("click")({ clientX: 10, clientY: 10 });
  assert.equal(env.calls.length, 0);
  assert.equal(env.view.selected, null);

  clickXY = { x: 0.4, y: 0.0 }; // on edge e1
  await env.canvasListeners.get("click")({ clientX: 50, clientY: 50 });
  assert.equal(env.confirmSpecs.length, 1);
  assert.deepEqual(env.calls[0].body, { to: { x: 0.4, y: 0.0 } });
});

test("Hover card uses S3/S5 handoffMap, 2-decimal coords, omits fabricated fallbacks, and arm segment click focuses arm", async (t) => {
  const mkNode = (tag) => ({
    tag, className: "", textContent: "", hidden: false, children: [],
    get childElementCount() { return this.children.length; },
    setAttribute() {},
    append(...kids) { this.children.push(...kids); },
    replaceChildren(...kids) { this.children = kids; },
  });
  const textOf = (n) => (typeof n === "string" ? n : [n.textContent, ...(n.children || []).map(textOf)].filter(Boolean).join(" | "));
  const hoverCard = mkNode("div");
  hoverCard.hidden = true;
  const origDoc = globalThis.document;
  let hoverWorld = { x: 0.504, y: 0.204 };
  const selectedIds = [];
  const env = setup(t, {
    view: {
      selected: null,
      focusRobot: null,
      siteToWorld: () => hoverWorld,
      guide: { map_version: 4, robots: [{ robot_id: "rosy_42", online: true, pose: { state: "LOCALIZED", x: 0.504, y: 0.204, yaw: 0 } }] },
      robots: [{ robot_id: "rosy_42", online: true, state: { safety: { estop: false } } }],
      anchors: [
        { target_id: "arm_a", kind: "omx_ai", label: "Arm A", base_x: 1.0, base_y: 0.4, head_x: 1.0, head_y: 0.1, live: false },
        { target_id: "arm_s", kind: "omx_ai", label: "Arm S", base_x: 2.0, base_y: 0.0, head_x: 1.7, head_y: 0.0, live: true },
      ],
    },
  });
  globalThis.document = { ...origDoc, createElement: mkNode, createElementNS: (_ns, tag) => mkNode(tag) };
  // Inject hover card into setup's closure via siteToWorld pointermove while testing el() lookup?
  // Note: setup's elements only has map-canvas; exercise hover/click cleanly via arm segment click + separate el() call.
  const origCanvasClick = env.canvasListeners.get("click");
  hoverWorld = { x: 1.85, y: 0.02 }; // midpoint of arm_s segment (0.15m from both endpoints > 0.13m, 0.02m from segment)
  await origCanvasClick({ clientX: 60, clientY: 60 });
  assert.equal(env.view.focusAnchorId, "arm_s");

  const { createConsoleGoal } = await import("../../../../applications/fleet/web/console-goal.js");
  const canvasListeners2 = new Map();
  const canvas2 = { classList: { add() {}, toggle() {} }, tabIndex: 0, getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 400 }) };
  const els = { "map-canvas": canvas2, "map-hover-card": hoverCard };
  const view2 = {
    selected: null, focusRobot: null, map: null,
    siteMap: { maps: [{ map_id: "site_a" }] }, activeSiteMap: { version: 4, map: SITE_MAP },
    guide: { robots: [{ robot_id: "rosy_42", online: true, pose: { state: "LOCALIZED", x: 0.504, y: 0.204, yaw: 0 } }] },
    robots: [{ robot_id: "rosy_42", online: true, state: { safety: { estop: false } } }],
    anchors: [
      { target_id: "arm_a", kind: "omx_ai", label: "Arm A", base_x: 1.0, base_y: 0.4, head_x: 1.0, head_y: 0.1, live: false },
      { target_id: "arm_s", kind: "omx_ai", label: "Arm S", base_x: 2.0, base_y: 0.0, head_x: 1.7, head_y: 0.0, live: true },
    ],
    siteToWorld: () => hoverWorld,
  };
  createConsoleGoal({
    pageScope: { listen(tgt, type, fn) { if (tgt === canvas2) canvasListeners2.set(type, fn); }, capture: () => ({ signal: new AbortController().signal, current: () => true, check() {} }) },
    el: (id) => els[id] || null, view: view2, auth: { role: "operator" }, inbox: { select() {} }, log() {}, call: async () => ({}),
    render() {}, confirmedAction: { async run() { return false; } }, namedReason: () => "", toWorld: () => ({ x: 0, y: 0 }),
    refreshGuide() {}, queuedReason: () => "", selection: { set(id) { selectedIds.push(id); } },
  });
  hoverWorld = { x: 0.504, y: 0.204 };
  canvasListeners2.get("pointermove")({ clientX: 10, clientY: 10 });
  const pinkyText = textOf(hoverCard);
  assert.match(pinkyText, /\(0\.50, 0\.20\) m/);
  for (const fake of ["8.76V", "10.4cm", "5.0Hz", "4/4 정상", "±0.02m", "0.504"]) assert.doesNotMatch(pinkyText, new RegExp(fake.replace(".", "\\.")));

  hoverWorld = { x: 1.0, y: 0.4 };
  canvasListeners2.get("pointermove")({ clientX: 20, clientY: 20 });
  const armAText = textOf(hoverCard);
  assert.match(armAText, /S5 \(1·3층 적재\)/);
  for (const fake of ["12.0V", "31°C", "98%", "6축 정상", "S2 (상차)"]) assert.doesNotMatch(armAText, new RegExp(fake.replace(/[().]/g, "\\$&")));

  hoverWorld = { x: 1.85, y: 0.0 };
  canvasListeners2.get("pointermove")({ clientX: 30, clientY: 30 });
  assert.match(textOf(hoverCard), /S3 \(하역 셔틀\)/);
});
