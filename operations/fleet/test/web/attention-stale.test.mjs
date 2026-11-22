import test from "node:test";
import assert from "node:assert/strict";

import { STALE_STATE_S, staleAgeS } from "../../../../applications/fleet/web/state-age.js";

const T0 = 1_000_000;
const row = (extra) => ({ robot_id: "a", online: true, state_age_s: 0.4, ...extra });

test("hub row 2.5 s old + received 3 s ago is stale (5.5 s)", () => {
  assert.equal(STALE_STATE_S, 5);
  assert.equal(staleAgeS(row({ state_age_s: 2.5 }), T0, T0 + 3000), 6);
});

test("REST row 0.4 s old + received 1 s ago is unchanged", () => {
  assert.equal(staleAgeS(row(), T0, T0 + 1000), null);
});

test("REST row received 6 s ago is stale", () => {
  assert.equal(staleAgeS(row(), T0, T0 + 6000), 6);
});

test("offline, missing field and never-received views are not judged", () => {
  assert.equal(staleAgeS(row({ online: false, state_age_s: null }), T0, T0 + 60000), null);
  assert.equal(staleAgeS({ robot_id: "a", online: true }, T0, T0 + 60000), null);
  assert.equal(staleAgeS(row({ state_age_s: 9 }), undefined, T0), 9);
});

// The real attentionItems, with the browser's "/common/..." imports mapped to shared/web.
const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
const { createRoster } = await import("../../../../applications/fleet/web/roster.js");

const view = { robots: [], formation: null, stateUnavailable: false, receivedAtMs: null };
const { attentionItems } = createRoster({ scope: {onDispose() {}, interval() {}}, view, streamEvidence: () => null });
const STUCK = { stuck_id: "stuck-abc" };
const full = (extra) => ({ robot_id: "a", online: true, state: { safety: { estop: false } },
  line_stuck: STUCK, state_age_s: 0.4, ...extra });
const texts = (items) => items.map((i) => `${i.severity}${i.text}`);

test("attentionItems: hub 2.5 s + 3 s old with a stuck gives crit and warn", () => {
  view.receivedAtMs = Date.now() - 3000;
  const items = attentionItems(full({ state_age_s: 2.5 }));
  assert.deepEqual(items.map((i) => i.severity), ["crit", "warn"]);
  assert.match(items[0].text, /차선 추종이 막혔습니다 \(상태 \d+초 전 값\)/);
  assert.match(items[1].text, /^: 상태 오래됨 — \d+초 전 값$/);
});

test("attentionItems: REST 0.4 s + 1 s old is exactly today's output", () => {
  view.receivedAtMs = Date.now() - 1000;
  assert.deepEqual(texts(attentionItems(full())), ["crit: 판단 요청 — 차선 추종이 막혔습니다"]);
  assert.deepEqual(attentionItems(full({ state_age_s: undefined })), attentionItems(full()));
});

test("attentionItems: offline gives only the disconnect item, however old", () => {
  view.receivedAtMs = Date.now() - 60000;
  const items = attentionItems({ robot_id: "a", online: false, state: null, state_age_s: null });
  assert.equal(items.length, 1);
  assert.equal(items[0].severity, "warn");
});

test("attentionItems: D-511 lane compliance WARN/ACT name the margin in cm; OK/UNKNOWN add nothing", () => {
  view.receivedAtMs = Date.now() - 1000;
  const lane = (level, margin_m, moving = true) => full({ line_stuck: null, lane_compliance: { level, margin_m, moving } });
  assert.deepEqual(texts(attentionItems(lane("WARN", 0.012))), ["warn: 차로 가장자리 접근 — 여유 1 cm"]);
  assert.deepEqual(texts(attentionItems(lane("ACT", -0.034))), ["crit: 차로 이탈 — 몸체가 가장자리를 3 cm 넘음"]);
  assert.deepEqual(attentionItems(lane("OK", 0.05)), []);
  assert.deepEqual(attentionItems(lane("UNKNOWN", null)), []);
});

test("attentionItems: D-511 WARN with a negative margin says the body is over, not a margin", () => {
  view.receivedAtMs = Date.now() - 1000;
  const items = attentionItems(full({ line_stuck: null, lane_compliance: { level: "WARN", margin_m: -0.006, moving: true } }));
  assert.deepEqual(texts(items), ["warn: 차로 가장자리 접근 — 몸체가 가장자리를 1 cm 넘음"]);
});

test("attentionItems: D-511 a still robot raises no lane item", () => {
  view.receivedAtMs = Date.now() - 1000;
  for (const moving of [false, undefined]) {
    assert.deepEqual(attentionItems(full({ line_stuck: null, lane_compliance: { level: "ACT", margin_m: -0.05, moving } })), []);
  }
});

test("a running trip shows its live AI route deviation without a wait cycle", () => {
  view.receivedAtMs = Date.now();
  view.trafficTrips = [{ robot_id: "a", trip_id: "lap-a", map_version: 5 }];
  const fact = { kind: "trip_route_check", robot_ids: ["a"], observed_at: Date.now() / 1000,
    ttl_s: 3, confidence: 0.8, value: { status: "OFF_ROUTE", offset_m: 0.05, limit_m: 0.03 },
    evidence: { trip_id: "lap-a", map_version: 5 } };
  const robot = full({ line_stuck: null });
  try {
    view.trafficAi = [fact];
    assert.deepEqual(texts(attentionItems(robot)), ["warn: AI 경로 편차 관찰 — 허용 경계보다 2 cm 밖 · 위치 확인 필요"]);
    // A newer judgement clears the older warning, including when input is unavailable.
    for (const status of ["ON_ROUTE", "UNKNOWN"]) {
      view.trafficAi = [fact, { ...fact, observed_at: fact.observed_at + 0.1, value: { status } }];
      assert.deepEqual(attentionItems(robot), []);
    }
    for (const changed of [
      { observed_at: fact.observed_at - 10 }, { observed_at: NaN }, { ttl_s: NaN },
      { robot_ids: ["b"] }, { evidence: { trip_id: "old-lap", map_version: 5 } },
      { evidence: { trip_id: "lap-a", map_version: 4 } },
      { value: { status: "OFF_ROUTE", offset_m: NaN, limit_m: 0.03 } },
    ]) {
      view.trafficAi = [{ ...fact, ...changed }];
      assert.deepEqual(attentionItems(robot), []);
    }
    view.trafficAi = [fact];
    view.trafficTrips = [];
    assert.deepEqual(attentionItems(robot), []);
  } finally {
    view.trafficAi = [];
    view.trafficTrips = [];
  }
});

test("attentionItems: D-550 8 an unbounded Fleet motion is one warn row; bounded and idle add nothing", () => {
  view.receivedAtMs = Date.now() - 1000;
  const rule = (rule_m) => full({ line_stuck: null, rule_m });
  assert.deepEqual(texts(attentionItems(rule({ state: "unbounded", motion: "goal", reason: "no_goal_lease" }))),
    ["warn: 한도 없는 움직임 — 관제가 끊겨도 로봇이 계속 갑니다 (목표 임대 없음)"]);
  assert.equal(attentionItems({ robot_id: "a", online: false, state: null }).length, 1);
  assert.deepEqual(attentionItems(rule({ state: "bounded", motion: "goal", reason: null })), []);
  assert.deepEqual(attentionItems(rule({ state: "idle", motion: null, reason: null })), []);
  assert.deepEqual(attentionItems(rule(undefined)), []);
});

// B-1 (IEC 62682 alarm summarization): 오래된 스냅샷 하나가 낸 주의는 로봇마다 한 행으로 묶는다.
// queues.js is already loaded through roster.js; the same module instance carries createQueues.
const { createQueues, groupRows } = await import("../../../../applications/fleet/web/queues.js");
const queues = createQueues({ scope: {onDispose() {}, interval() {}}, view, render: () => {}, streamEvidence: () => null });
const SNAPSHOT_WARN_STATE = { safety: { estop: false }, battery_status: { level: "warning" },
  docking: { state: "DOCK_FAILED" }, capabilities_degraded: ["cam"], navigation: "FAILED" };

test("B-1: a stale snapshot folds its four state warns into one per-robot rollup row", () => {
  view.receivedAtMs = Date.now() - 1000;
  const items = attentionItems(full({ line_stuck: null, state_age_s: 6, state: SNAPSHOT_WARN_STATE }));
  assert.equal(items.length, 1);
  assert.match(items[0].text, /^: 상태 오래됨 — \d+초 전 값 · 지연 경고 4건$/);
  assert.equal(items[0].key, "a|stale-snapshot");
  assert.equal(items[0].noGroup, true);
  assert.deepEqual(items[0].foldedDetails, ["배터리 부족", "도킹 실패", "성능 저하 [cam]", "목표 실패"]);
});

test("B-1: the same robot fresh keeps the four warns as separate property-clean rows", () => {
  view.receivedAtMs = Date.now() - 1000;
  assert.deepEqual(attentionItems(full({ line_stuck: null, state_age_s: 0.4, state: SNAPSHOT_WARN_STATE })), [
    { severity: "warn", text: ": 배터리 부족" },
    { severity: "warn", text: ": 도킹 실패" },
    { severity: "warn", text: ": 성능 저하 [cam]" },
    { severity: "warn", text: ": 목표 실패" },
  ]);
});

test("B-1: critical battery, E-stop, power_health, lane and replan rows never fold", () => {
  view.receivedAtMs = Date.now() - 1000;
  const stale = (extra) => full({ line_stuck: null, state_age_s: 6, ...extra });
  const cases = [
    [stale({ state: { safety: { estop: false }, battery_status: { level: "critical" } } }), ": 배터리 위험"],
    [stale({ state: { safety: { estop: true } } }), ": 비상 정지 걸림"],
    [stale({ state: { safety: {} } }), ": 정지 상태 미확인"],
    [stale({ power_health_age_s: 0.3, power_health: { battery: { evidence: "fresh", sample_age_s: 0.2,
      stale_after_s: 5, percent: 30, level: "warning", charging_state: "unknown" } } }),
      ": 배터리 경고 — 충전·절전 확인"],
    [stale({ lane_compliance: { level: "WARN", margin_m: 0.012, moving: true } }),
      ": 차로 가장자리 접근 — 여유 1 cm"],
  ];
  for (const [robot, kept] of cases) {
    const items = attentionItems(robot);
    assert.ok(!items.some((item) => item.foldedDetails), kept);
    assert.ok(items.some((item) => item.text.startsWith(kept)), kept);
    assert.match(items.at(-1).text, /^: 상태 오래됨 — \d+초 전 값$/);  // a plain stale row, not a rollup
  }
  view.trafficTrips = [{ trip_id: "t1", robot_id: "a", hold: { reason: "replan", plan: { places: [] } } }];
  try {
    const items = attentionItems(stale({}));
    assert.ok(items.some((item) => item.decision === "replan"));
    assert.ok(!items.some((item) => item.foldedDetails));
  } finally { view.trafficTrips = []; }
});

test("B-1: two stale rollups with the same text stay separate; ordinary warns still group", () => {
  const rollup = (robotId, causes) => ({ robotId, severity: "warn", key: `${robotId}|stale-snapshot`, noGroup: true,
    text: `: 상태 오래됨 — 6초 전 값 · 지연 경고 ${causes.length}건`, foldedDetails: causes });
  const rows = [rollup("a", ["배터리 부족"]), rollup("b", ["목표 실패"]),
    { robotId: "c", severity: "warn", text: ": 교통 대기", key: "c|0" },
    { robotId: "d", severity: "warn", text: ": 교통 대기", key: "d|1" }];
  const out = groupRows(rows);
  assert.deepEqual(out.map((row) => row.key), ["a|stale-snapshot", "b|stale-snapshot", "group|: 교통 대기"]);
  assert.deepEqual(out[0].foldedDetails, ["배터리 부족"]);  // a's causes never leak into b's row
  assert.deepEqual(out[2].group, ["c", "d"]);
});

test("B-1: attentionKey is blind to age ticks and flips when the folded cause set changes", () => {
  view.receivedAtMs = Date.now() - 6000;
  const robot = { robot_id: "a", online: true, line_stuck: null, state_age_s: 6,
    state: { safety: { estop: false }, battery_status: { level: "warning" } } };
  const key = queues.attentionKey(robot);
  robot.state_age_s = 15;                          // the same warnings, only older
  assert.equal(queues.attentionKey(robot), key);
  robot.state.docking = { state: "DOCK_FAILED" };  // a new cause joins the fold
  assert.notEqual(queues.attentionKey(robot), key);
});
