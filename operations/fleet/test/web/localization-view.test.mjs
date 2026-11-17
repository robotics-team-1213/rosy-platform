import test from "node:test";
import assert from "node:assert/strict";

const {
  buildLocalizationView,
  createLocalizationPoller,
  enqueuePoseStart,
  stepQueuedStarts,
} = await import("../../../../applications/fleet/web/robot/localization-view.js");
const { TRIP_ERROR_LABEL } = await import("../../../../applications/fleet/web/shared/trip-display.js");
const { REFUSAL_TEXT } = await import("../../../../shared/web/localization-state.js");

test("TRIP_ERROR_LABEL maps SITE_POSE_UNKNOWN via REFUSAL_TEXT", () => {
  assert.equal(TRIP_ERROR_LABEL.SITE_POSE_UNKNOWN, REFUSAL_TEXT.SITE_POSE_UNKNOWN);
});

test("queued start fires once on fresh localized, ends on stop, non-pose refusal, and 120 s", () => {
  const view = { robots: [{ robot_id: "r1", online: true, localization: { state: "UNKNOWN" } }] };
  let fired = 0;
  enqueuePoseStart({ view, robotId: "r1", code: "SITE_POSE_UNKNOWN", request: () => { fired += 1; }, nowMs: 1000_000 });
  // Not localized yet -> stays queued
  stepQueuedStarts({ view, nowMs: 1010_000 });
  assert.equal(fired, 0);
  assert.ok(view.queuedStarts.r1);

  // Pin makes it localized with age 0 -> fires ONCE and drops queue
  stepQueuedStarts({ view, pinnedRobotId: "r1", nowMs: 1011_000 });
  assert.equal(fired, 1);
  assert.equal(view.queuedStarts.r1, undefined);
  stepQueuedStarts({ view, pinnedRobotId: "r1", nowMs: 1012_000 });
  assert.equal(fired, 1);

  // Stop ends queue
  enqueuePoseStart({ view, robotId: "r1", code: "TRIP_POSE_UNTRUSTED", request: () => { fired += 1; }, nowMs: 2000_000 });
  stepQueuedStarts({ view, stoppedRobotId: "r1", nowMs: 2005_000 });
  assert.equal(fired, 1);
  assert.equal(view.queuedStarts.r1, undefined);
  assert.ok(view.queueEndText.r1.includes("정지"));

  // 120 s timeout ends queue
  enqueuePoseStart({ view, robotId: "r1", code: "SITE_POSE_UNKNOWN", request: () => { fired += 1; }, nowMs: 3000_000 });
  stepQueuedStarts({ view, nowMs: 3120_000 });
  assert.equal(fired, 1);
  assert.equal(view.queuedStarts.r1, undefined);
  assert.ok(view.queueEndText.r1.includes("시간 초과"));

  // Non-pose refusal ends queue
  enqueuePoseStart({ view, robotId: "r1", code: "SITE_POSE_UNKNOWN", request: () => { fired += 1; }, nowMs: 4000_000 });
  view.queuedStarts.r1.lastCode = "TRIP_BUSY";
  stepQueuedStarts({ view, nowMs: 4005_000 });
  assert.equal(fired, 1);
  assert.equal(view.queuedStarts.r1, undefined);
});

test("poller queries /localization only for selected or candidates/rotating robots and stops on 503", async () => {
  const calls = [];
  const view = {
    robotSelection: { get: () => "r1" },
    robots: [
      { robot_id: "r1", online: true },
      { robot_id: "r2", online: true },
      { robot_id: "r3", online: true },
    ],
    locByRobot: { r2: { localization: { state: "CANDIDATES" }, candidates: { candidates: [{ x: 1, y: 2, yaw: 0, scan_fit: 0.9 }] } } },
  };
  const poller = createLocalizationPoller({
    view,
    call: async (path) => {
      calls.push(path);
      if (path === "/api/fleet/auto-locate") return { robots: [] };
      if (path === "/api/fleet/robots/r1/localization") {
        const err = new Error("disabled");
        err.status = 503;
        throw err;
      }
      return { localization: { state: "UNKNOWN" }, motion_allowed: false };
    },
  });
  await poller.poll(1000_000);
  assert.ok(calls.includes("/api/fleet/robots/r1/localization"));
  assert.ok(calls.includes("/api/fleet/robots/r2/localization"));
  assert.ok(!calls.includes("/api/fleet/robots/r3/localization"));

  // Second poll skips r1 after 503 LOCALIZATION_DISABLED
  calls.length = 0;
  await poller.poll(1001_000);
  assert.ok(!calls.includes("/api/fleet/robots/r1/localization"));
});

test("revoked gate remembers last_requester and age, and offers relocalize again without auto-call", () => {
  const view = {
    lastRequesterByRobot: { "loc-9": "operator-b" },
    locByRobot: {
      "loc-9": {
        localization: null,
        motion_allowed: false,
        last_operator_request: { revoked: { reason: "mission_obstacle", at: 1792454200.0 } },
      },
    },
  };
  const loc = buildLocalizationView({ robot_id: "loc-9", online: true }, view, () => true, 1792454212_000);
  assert.ok(loc.evidence.includes("operator-b"));
  assert.ok(loc.evidence.includes("12초 전"));
  assert.ok(loc.actions.some((a) => a.id === "relocalize" && !a.disabled));
});

test("createLocalizationPoller drops in-flight stale writes and resets disabled/inFlight on scope invalidation", async () => {
  const { createPageScope } = await import("../../../../shared/web/scope.js");
  const events = { addEventListener() {}, removeEventListener() {} };
  const scope = createPageScope({ events });
  const view = {
    robots: [{ robot_id: "r1", online: true, localization: { state: "LOCALIZED" } }],
    robotSelection: { get: () => "r1" },
  };
  let releaseLoc = null;
  let locCalls = 0;
  let lastSignal = null;
  let blocked = true;
  let fail503 = false;
  const poller = createLocalizationPoller({
    scope,
    view,
    call: async (url, opts = {}) => {
      if (url === "/api/fleet/auto-locate") return { robots: [] };
      if (url === "/api/fleet/robots/r1/localization") {
        locCalls += 1;
        lastSignal = opts.signals?.[0] || null;
        if (fail503) {
          const err = new Error("disabled");
          err.status = 503;
          throw err;
        }
        if (blocked) return new Promise((resolve) => { releaseLoc = () => resolve({ localization: { state: "LOCALIZED" } }); });
        return { localization: { state: "LOCALIZED" }, motion_allowed: true };
      }
      throw new Error(`unexpected url: ${url}`);
    },
  });

  // Mid-poll invalidation aborts signal, ignores late resolution, and clears inFlight.
  const firstPoll = poller.poll(1000);
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(lastSignal && !lastSignal.aborted);
  scope.invalidate();
  assert.equal(lastSignal.aborted, true);
  blocked = false;
  releaseLoc();
  await firstPoll;
  assert.equal(view.locByRobot.r1, undefined);

  // Subsequent poll runs cleanly on renewed epoch.
  await poller.poll(2000);
  assert.equal(view.locByRobot.r1?.localization?.state, "LOCALIZED");

  // 503 marks disabled until scope invalidates; invalidation clears disabled set.
  fail503 = true;
  await poller.poll(3000);
  const callsAfter503 = locCalls;
  await poller.poll(4000);
  assert.equal(locCalls, callsAfter503);
  fail503 = false;
  scope.invalidate();
  await poller.poll(5000);
  assert.equal(locCalls, callsAfter503 + 1);

  scope.dispose();
});
