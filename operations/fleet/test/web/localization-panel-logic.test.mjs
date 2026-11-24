import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./resolve-console-assets.mjs", import.meta.url);

const {
  bindingSpanM,
  buildBindingPayload,
  captureBindingSample,
  confirmReason,
  relocalizeReason,
  summarizeLocalizationPanel,
} = await import("../../../../applications/fleet/web/localization-panel-logic.js");

const SAMPLE_ROBOT = {
  robot_id: "rosy_45",
  online: true,
  capabilities: { navigation: { goal_navigation: false }, withheld: { reason: "navigation_absent" } },
  state: {
    online: true,
    map_grid_id: "occupancy:417b0b362237",
    pose_frame: "odom",
    pose: { x: 0.0, y: 0.0, yaw: 0.0 },
    velocity: { linear: 0.0, angular: 0.0 },
    safety: { estop: false },
    localization: { state: "CANDIDATES", pose_frame: "odom" },
  },
};

test("summarizeLocalizationPanel reports candidates, binding, and track state clearly", () => {
  const view = summarizeLocalizationPanel({
    robot: SAMPLE_ROBOT,
    locPayload: {
      localization: { state: "CANDIDATES", pose_frame: "odom" },
      candidates: { candidates: [{ x: -0.53, y: 0.20, yaw: -0.02, scan_fit: 0.9959 }] },
    },
    bindingPayload: { matches: false, reason: "MAP_BINDING_REQUIRED", robot_grid_id: "occupancy:417b0b362237" },
    trackRow: { robot_id: "rosy_45", state: "CONFIRMED", x: 0.76, y: -0.20, age_s: 0.3 },
  });
  assert.equal(view.locState, "CANDIDATES");
  assert.equal(view.candidates.length, 1);
  assert.equal(view.bestFit, 0.9959);
  assert.equal(view.navReady, false);
  assert.equal(view.bindingMatched, false);
  assert.equal(view.trackConfirmed, true);
  assert.match(view.locLabel, /후보 1건/);

  const bound = summarizeLocalizationPanel({
    robot: {
      ...SAMPLE_ROBOT,
      capabilities: { navigation: { goal_navigation: true } },
      state: { ...SAMPLE_ROBOT.state, localization: { state: "LOCALIZED", pose_frame: "map" }, pose: { x: -0.53, y: 0.2, yaw: 0 } },
    },
    locPayload: { localization: { state: "LOCALIZED", pose_frame: "map" } },
    bindingPayload: { matches: true, slam_camera_gap_m: 0.031 },
    trackRow: { robot_id: "rosy_45", state: "CONFIRMED", x: 0.76, y: -0.20, age_s: 0.2 },
  });
  assert.equal(bound.navReady, true);
  assert.equal(bound.bindingMatched, true);
  assert.match(bound.kvRows[2][1], /0\.03 m/);
});

test("confirmReason and relocalizeReason enforce auth, fit, localized, and estop guards", () => {
  const loc = {
    localization: { state: "CANDIDATES" },
    candidates: { candidates: [{ x: -0.53, y: 0.2, yaw: 0, scan_fit: 0.99 }] },
  };
  assert.equal(confirmReason({ robot: SAMPLE_ROBOT, locPayload: loc, candidateIndex: 0, isOperator: true, operatorReason: "op-only", namedReason: "", stateUnavailable: false }), "");
  assert.equal(confirmReason({ robot: SAMPLE_ROBOT, locPayload: loc, candidateIndex: 0, isOperator: false, operatorReason: "op-only", namedReason: "", stateUnavailable: false }), "op-only");
  assert.match(confirmReason({ robot: SAMPLE_ROBOT, locPayload: loc, candidateIndex: 0, isOperator: true, namedReason: "이름 있는 토큰 필요", stateUnavailable: false }), /토큰/);

  const lowFit = { ...loc, candidates: { candidates: [{ x: 0, y: 0, yaw: 0, scan_fit: 0.72 }] } };
  assert.match(confirmReason({ robot: SAMPLE_ROBOT, locPayload: lowFit, candidateIndex: 0, isOperator: true, namedReason: "", stateUnavailable: false }), /적합도/);

  assert.equal(relocalizeReason({ robot: SAMPLE_ROBOT, locPayload: loc, isOperator: true, namedReason: "", stateUnavailable: false }), "");
  const estopped = { ...SAMPLE_ROBOT, state: { ...SAMPLE_ROBOT.state, safety: { estop: true } } };
  assert.match(relocalizeReason({ robot: estopped, locPayload: loc, isOperator: true, namedReason: "", stateUnavailable: false }), /비상정지/);
});

test("captureBindingSample and buildBindingPayload enforce D-1022 stationary/track/span guards", () => {
  assert.match(captureBindingSample({ robot: SAMPLE_ROBOT, trackRow: { state: "CONFIRMED", x: 0, y: 0, age_s: 0.2 } }).reason, /위치 확정/);

  const localized = {
    ...SAMPLE_ROBOT,
    state: { ...SAMPLE_ROBOT.state, pose_frame: "map", pose: { x: 0.1, y: 0.2, yaw: 0 }, localization: { state: "LOCALIZED", pose_frame: "map" } },
  };
  const moving = { ...localized, state: { ...localized.state, velocity: { linear: 0.05, angular: 0.0 } } };
  assert.match(captureBindingSample({ robot: moving, trackRow: { state: "CONFIRMED", x: 0.7, y: -0.2, age_s: 0.2 } }).reason, /정지/);
  assert.match(captureBindingSample({ robot: localized, trackRow: { state: "CONFIRMED", x: 0.7, y: -0.2, age_s: 2.0 } }).reason, /오래되어/);

  const pts = [
    [[0.1, 0.2], [0.7, -0.2]],
    [[0.9, 0.2], [1.5, -0.2]],
    [[0.9, 1.0], [1.5, 0.6]],
    [[0.1, 1.0], [0.7, 0.6]],
  ];
  let samples = [];
  for (const [rPt, sPt] of pts) {
    const bot = { ...localized, state: { ...localized.state, pose: { x: rPt[0], y: rPt[1], yaw: 0 } } };
    const res = captureBindingSample({
      robot: bot,
      trackRow: { state: "CONFIRMED", x: sPt[0], y: sPt[1], age_s: 0.2 },
      existingSamples: samples,
      existingGridId: samples.length ? "occupancy:417b0b362237" : null,
    });
    assert.equal(res.ok, true);
    samples = res.samples;
  }
  assert.ok(bindingSpanM(samples) >= 1.0);
  const body = buildBindingPayload(samples);
  assert.equal(body.pairs.length, 3);
  assert.equal(body.holdout.length, 1);
});
