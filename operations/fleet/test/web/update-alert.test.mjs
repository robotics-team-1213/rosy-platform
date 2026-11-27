// A stalled cell updater is one row in the console queue (the one alert surface) and leaves with the stall.
import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { updateAlertRows, createUpdateAlertReader } = await import("../../../../applications/fleet/web/work/update-alerts.js");

const DEVICES = "rosy-omx-devices-autoupdate.service";
const body = (alert) => ({ hosts: [{ host: "arm-cell", channels: [
  { unit: DEVICES, state: "ok", alert }, { unit: "rosy-site-tools-autoupdate.service", state: "ok" }] }] });

test("one row per stalled channel with a stable key, so repeated polls never stack", () => {
  const first = updateAlertRows(body({ age_s: 3700, reason: "observer_stale" }));
  const later = updateAlertRows(body({ age_s: 11000, reason: "rate_limited" }));
  assert.equal(first.length, 1);
  assert.equal(first[0].key, later[0].key);
  assert.equal(first[0].severity, "warn");
  assert.equal(first[0].robotId, "arm-cell");
  assert.match(first[0].text, /omx-devices · 1시간째 .* · observer_stale$/);
  assert.equal(first[0].next.href, "/console/maintenance#host-services");
});

test("short and unknown ages read plainly; a viewer's row has no reason", () => {
  assert.match(updateAlertRows(body({ age_s: 600 }))[0].text, /10분째 정상 단계 없음$/);
  assert.match(updateAlertRows(body({ age_s: null }))[0].text, /마지막 정상 기록 없음$/);
});

test("the reader polls once a minute, keeps rows on a failed read and drops them when the stall ends", async (t) => {
  let now = 1_000_000, reply = body({ age_s: 7200 }), calls = 0;
  t.mock.method(Date, "now", () => now);
  const view = {};
  const read = createUpdateAlertReader(async () => { calls++; if (!reply) throw new Error("down"); return reply; }, view);
  const life = { current: () => true };
  await read(life);
  await read(life);
  assert.deepEqual([calls, view.updateAlerts.length], [1, 1]);
  now += 60_000; reply = null;
  await read(life);
  assert.deepEqual([calls, view.updateAlerts.length], [2, 1]);
  now += 60_000; reply = body(undefined);
  await read(life);
  assert.equal(view.updateAlerts.length, 0);
});

test("no alert, no row", () => {
  assert.deepEqual(updateAlertRows(body(undefined)), []);
  assert.deepEqual(updateAlertRows(null), []);
});
