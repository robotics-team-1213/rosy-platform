import test from "node:test";
import assert from "node:assert/strict";

import { STALE_STATE_S, staleAgeS } from "../../fleet/server/web/state-age.js";

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
const { createRoster } = await import("../../fleet/server/web/roster.js");

const view = { robots: [], formation: null, stateUnavailable: false, receivedAtMs: null };
const { attentionItems } = createRoster({ view, streamEvidence: () => null });
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
