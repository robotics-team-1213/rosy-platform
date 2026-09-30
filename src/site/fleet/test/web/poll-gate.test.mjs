import test from "node:test";
import assert from "node:assert/strict";

import { NO_MAP_RETRY_MS, createPollGate, isRouteAbsent } from "../../fleet/server/web/poll-gate.js";

test("a 404 without a detail code means the route is not installed", () => {
  assert.equal(isRouteAbsent(404, undefined), true);
  assert.equal(isRouteAbsent(404, "NO_MAP"), false);
  assert.equal(isRouteAbsent(500, undefined), false);
  assert.equal(isRouteAbsent(undefined, undefined), false); // network failure
});

test("an absent route stays closed until reset", () => {
  const gate = createPollGate();
  assert.equal(gate.due(0), true);
  assert.equal(gate.fail(404, undefined, 0), "absent");
  assert.equal(gate.absent, true);
  assert.equal(gate.due(10 ** 12), false);
  gate.reset();
  assert.equal(gate.due(0), true);
  assert.equal(gate.absent, false);
});

test("transient failures keep retrying on the next tick", () => {
  const gate = createPollGate({ slowCodes: { NO_MAP: NO_MAP_RETRY_MS } });
  for (const [status, code] of [[500, undefined], [502, "UPSTREAM"], [undefined, undefined], [404, "OTHER"]]) {
    assert.equal(gate.fail(status, code, 0), "retry");
    assert.equal(gate.due(0), true);
  }
});

test("NO_MAP backs off to the slow cadence instead of stopping", () => {
  const gate = createPollGate({ slowCodes: { NO_MAP: NO_MAP_RETRY_MS } });
  assert.equal(NO_MAP_RETRY_MS, 30000);
  assert.equal(gate.fail(404, "NO_MAP", 1000), "slow");
  assert.equal(gate.absent, false);
  assert.equal(gate.due(1000 + 5000), false);
  assert.equal(gate.due(1000 + NO_MAP_RETRY_MS - 1), false);
  assert.equal(gate.due(1000 + NO_MAP_RETRY_MS), true);
  gate.ok();
  assert.equal(gate.due(0), true);
});

test("a gate without slow codes treats NO_MAP-like codes as transient", () => {
  const gate = createPollGate();
  assert.equal(gate.fail(404, "NO_MAP", 0), "retry");
  assert.equal(gate.due(0), true);
});

// 태블릿 점검 수치: 꺼진 라우트 4개가 1 분에 몇 번 두드려지는지 모의한다.
test("disabled features cost at most two 404s per minute after the first minute", () => {
  const dispatch = createPollGate();
  const discovery = createPollGate();
  const enrollment = createPollGate();
  const map = createPollGate({ slowCodes: { NO_MAP: NO_MAP_RETRY_MS } });
  const pollers = [
    { gate: dispatch, every: 1000, code: undefined },
    { gate: discovery, every: 5000, code: undefined },
    { gate: enrollment, every: 5000, code: undefined },
    { gate: map, every: 5000, code: "NO_MAP" },
  ];
  let hitsFirst = 0;
  let hitsSecond = 0;
  for (let t = 0; t < 120000; t += 1000) {
    for (const p of pollers) {
      if (t % p.every !== 0 || !p.gate.due(t)) continue;
      p.gate.fail(404, p.code, t);
      if (t < 60000) hitsFirst += 1; else hitsSecond += 1;
    }
  }
  assert.ok(hitsFirst <= 5, `first minute ${hitsFirst}`);
  assert.equal(hitsSecond, 2);
});
