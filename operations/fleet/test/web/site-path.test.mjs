import test from "node:test";
import assert from "node:assert/strict";

import { fleetRow, proxyRow, visionRow } from "../../fleet/server/web/site-path.js";

test("before any sample the three rows are still checking", () => {
  for (const row of [proxyRow(null), fleetRow(null), visionRow(null)]) {
    assert.equal(row.word, "확인 중");
  }
});

test("proxy is up only for healthz 200 and the exact ok body", () => {
  assert.equal(proxyRow({ finished: true, status: 200, body: { status: "ok" } }).word, "정상");
  assert.equal(proxyRow({ finished: true, status: 200, body: { status: "ok", extra: 1 } }).word, "끊김");
  assert.equal(proxyRow({ finished: true, status: 200, body: { status: "ready" } }).word, "끊김");
  assert.equal(proxyRow({ finished: false }).word, "끊김");
});

test("fleet is up when the state request finishes, including 401", () => {
  assert.equal(fleetRow({ finished: true, status: 200 }).word, "정상");
  assert.equal(fleetRow({ finished: true, status: 401 }).word, "정상");
  assert.equal(fleetRow({ finished: true, status: 500 }).word, "정상");
  assert.equal(fleetRow({ finished: false }).word, "끊김");
});

test("vision names an empty list and a dropped connection apart from a finished 503", () => {
  assert.deepEqual(visionRow({ finished: true, status: 200, names: ["ceiling_north"] }),
    { name: "Vision", word: "ceiling_north", kind: "good" });
  assert.equal(visionRow({ finished: true, status: 200, names: [] }).word, "없음");
  assert.equal(visionRow({ finished: false }).word, "끊김");
  const disabled = visionRow({ finished: true, status: 503, names: [] });
  assert.equal(disabled.word, "응답 503");
  assert.notEqual(disabled.word, "끊김");
});
