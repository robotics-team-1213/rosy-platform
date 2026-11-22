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

function setup(t, { tripHandler, onConfirm } = {}) {
  const beforeDocument = globalThis.document;
  globalThis.document = { activeElement: null, querySelectorAll: () => [] };
  t.after(() => { globalThis.document = beforeDocument; });

  const canvas = {
    classList: { add() {}, toggle() {} },
    tabIndex: 0,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 400 }),
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
  };

  const pageScope = {
    listen() {},
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
    calls.push({ path, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
    if (path.endsWith("/trip")) return tripHandler(path, JSON.parse(init.body));
    if (path.endsWith("/start")) return { trip_id: "trip-1", state: "running" };
    throw new Error(`unexpected call ${path}`);
  };

  const goal = createConsoleGoal({
    pageScope,
    el: (id) => elements[id] || null,
    view,
    auth: { role: "operator", principal: "kim", locked: false, token: "t" },
    inbox: { select() {} },
    log: (text, tone) => logs.push({ text, tone }),
    call,
    render: () => { renders += 1; },
    confirmedAction,
    namedReason: () => "",
    toWorld: () => ({ x: 0, y: 0 }),
    refreshGuide: () => {},
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
  assert.equal(env.view.selectedGoal.status, "DISPATCHED");
  assert.equal(env.view.selectedGoal.statusText, "차로 주행 시작");
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
