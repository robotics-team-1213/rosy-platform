import test from "node:test";
import assert from "node:assert/strict";

import {
  classifyTracking, trackingStatusLine, offsetLabel, OFFSET_WARN_M, TRACKING_STATUS_TEXT,
  preferMarkers, positionRows, displayLeaseMs, trackingDriftSample, calibrationDriftVerdict,
  rememberTrackingPoses, CALIBRATION_DRIFT_POLLS, CALIBRATION_DRIFT_M,
  serverCalibrationDrift, effectiveDriftVerdict,
} from "../../fleet/server/web/tracking-layer.js";

const source = (changes = {}) => ({
  source_id: "ceiling_north", map_id: "map_v2_fleet", status: "OK",
  calibration_revision: "paint-3f9a1c2b7d40", age_ms: 120, fps: 3, last_error: null, relearn_seq: 0,
  ...changes,
});

const body = (changes = {}) => ({
  ts: 10, lease_s: 1, gate_m: 0.3, use: "display-only",
  sources: [source()],
  robots: [
    { robot_id: "rosy_02", status: "MATCHED", source_id: "ceiling_north", offset_m: 0.2,
      camera: { x: 1.2, y: 0.4, footprint_m: 0.18, score: 0.8 }, pose: { x: 1.0, y: 0.4 },
      pose_frame_verified: true },
    { robot_id: "rosy_01", status: "MATCHED", source_id: "ceiling_north", offset_m: 0.05,
      camera: { x: 2, y: 1, footprint_m: 0.18, score: 0.9 }, pose: { x: 2.05, y: 1 },
      pose_frame_verified: false },
    { robot_id: "rosy_03", status: "NO_DETECTION", source_id: "ceiling_north", offset_m: null,
      camera: null, pose: { x: 3, y: 1 }, pose_frame_verified: true },
  ],
  unknown: [{ source_id: "ceiling_north", x: 0.5, y: 0.5, footprint_m: 0.2, score: 0.4 }, { x: "bad" }],
  ...changes,
});

test("fresh marker wins per robot; delayed or absent marker falls back without keeping old pose", () => {
  const tracking = classifyTracking(body());
  const markers = [{ robot_id: "rosy_01", state: "fresh", x: 2, y: 1, age_ms: 120 }];
  assert.deepEqual(preferMarkers(tracking, markers).robots.map(r => r.robotId), ["rosy_02"]);
  assert.deepEqual(preferMarkers(tracking, [{ ...markers[0], state: "delayed" }]), tracking);
  assert.deepEqual(preferMarkers(tracking, []), tracking);
  assert.deepEqual(preferMarkers(tracking, [{ ...markers[0], age_ms: 1200 }]), tracking);
});

test("only matched robots with finite numbers are drawn; unknowns become grey points", () => {
  const out = classifyTracking(body());
  assert.deepEqual(out.robots.map((r) => [r.robotId, r.warn, r.verified]),
    [["rosy_01", false, false], ["rosy_02", true, true]]);
  assert.deepEqual(out.robots[1].camera, { x: 1.2, y: 0.4 });
  assert.deepEqual(out.robots[1].pose, { x: 1.0, y: 0.4 });
  assert.deepEqual(out.unknown, [{ x: 0.5, y: 0.5 }]);
  assert.deepEqual(classifyTracking(null), { robots: [], unknown: [] });
  assert.equal(OFFSET_WARN_M, 0.15);
});

test("an offset exactly at the threshold is not orange", () => {
  const out = classifyTracking(body({ robots: [{ ...body().robots[0], offset_m: 0.15 }] }));
  assert.equal(out.robots[0].warn, false);
});

test("the status line names each source state, fps and unverified frames", () => {
  assert.deepEqual(trackingStatusLine(body()), {
    state: "ok", text: "관제 카메라 추적: ceiling_north 추적 중 · 3.0 fps · 위치 상태 미보고 1대",
  });
  assert.deepEqual(trackingStatusLine(body({ sources: [source({ status: "LEARNING" })], robots: [] })), {
    state: "warn", text: "관제 카메라 추적: ceiling_north 배경 학습 중",
  });
  assert.equal(trackingStatusLine(body({ sources: [source({ last_error: "CALIBRATION_MISMATCH" })],
    robots: [] })).text, "관제 카메라 추적: ceiling_north 보정 불일치");
  assert.equal(trackingStatusLine(body({ sources: [source({ status: "BLIND" })], robots: [] })).text,
    "관제 카메라 추적: ceiling_north 알 수 없음(BLIND)");
  assert.deepEqual(trackingStatusLine({ sources: [] }), { state: "none", text: "관제 카메라 추적 소스 없음" });
  for (const key of ["OK", "LEARNING", "CALIBRATION_REQUIRED", "SCENE_CHANGED", "STALE", "NONE"]) {
    assert.equal(typeof TRACKING_STATUS_TEXT[key], "string");
  }
});

test("Fleet's detection refusals are named instead of the detector state", () => {
  const line = (code) => trackingStatusLine(body({ sources: [source({ last_error: code })], robots: [] }));
  assert.deepEqual(line("MAP_MISMATCH"), { state: "warn", text: "관제 카메라 추적: ceiling_north 지도 불일치" });
  assert.equal(line("DETECTION_STALE").text, "관제 카메라 추적: ceiling_north 검출 지연(거부)");
  assert.equal(line("DETECTION_FUTURE").text, "관제 카메라 추적: ceiling_north 검출 시각 오류(거부)");
  assert.equal(line("DETECTION_OUT_OF_ORDER").text, "관제 카메라 추적: ceiling_north 검출 순서 오류(거부)");
});

test("the offset label is in whole centimetres", () => {
  assert.equal(offsetLabel({ robotId: "rosy_02", offsetM: 0.204 }), "rosy_02 · 차이 20 cm");
});

test("a configured marker is drawn without a CORE map pose", () => {
  const out = classifyTracking(body({ robots: [{ robot_id: "rosy_01", status: "MARKER",
    camera: { x: 1, y: 2 }, pose: null, offset_m: null, pose_frame_verified: false }] }));
  assert.equal(out.robots.length, 1);
  assert.equal(out.robots[0].pose, null);
  assert.equal(out.robots[0].measured, true);
  assert.equal(offsetLabel(out.robots[0]), "rosy_01 · 마커 관측");
});

test("map coordinates retain signs, metres and measured versus inferred provenance", () => {
  const out = classifyTracking({ robots: [{ robot_id: "rosy_01", status: "MARKER",
    camera: { x: -1.234, y: .456 }, pose: null, offset_m: null }],
    unknown: [{ x: .25, y: -.5 }] });
  assert.deepEqual(positionRows(out), [
    { name: "rosy_01", x: "-1.23", y: "0.46", basis: "마커 관측" },
    { name: "미확인 1", x: "0.25", y: "-0.50", basis: "무마커 추론 · 이름 미확정" },
  ]);
  assert.deepEqual(positionRows(classifyTracking(null)), []);
});

test("display lease subtracts server age and transport delay and never exceeds one second", () => {
  assert.equal(displayLeaseMs({ lease_s: 1, sources: [{ status: "OK", age_ms: 400 }] }, 250), 350);
  assert.equal(displayLeaseMs({ lease_s: 1, sources: [{ status: "OK", age_ms: 900 }] }, 200), 0);
  assert.equal(displayLeaseMs({ lease_s: 5, sources: [] }), 1000);
});

test("drift samples only count still robots with a pose, never marker measurements", () => {
  const tracking = { robots: [
    { robotId: "rosy_01", camera: { x: 1, y: 1 }, pose: { x: 1, y: 1 }, offsetM: 0.9 },   // 정지 · 어긋남
    { robotId: "rosy_02", camera: { x: 2, y: 2 }, pose: { x: 2.5, y: 2 }, offsetM: 1.2 },  // 움직임 — 제외
    { robotId: "rosy_03", camera: { x: 3, y: 3 }, pose: null, offsetM: null, measured: true },
    { robotId: "rosy_04", camera: { x: 4, y: 4 }, pose: { x: 4, y: 4 }, offsetM: 0.05 },   // 정지 · 정상
  ] };
  const previous = new Map([["rosy_01", { x: 1, y: 1 }], ["rosy_02", { x: 2, y: 2 }],
    ["rosy_03", { x: 3, y: 3 }], ["rosy_04", { x: 4, y: 4 }]]);
  assert.deepEqual(trackingDriftSample(tracking, previous), { robotId: "rosy_01", distanceM: 0.9 });
  // 첫 폴링(직전 자세 없음)·빈 추적 — 잴 게 없다.
  assert.equal(trackingDriftSample(tracking, new Map()), null);
  assert.equal(trackingDriftSample(null, previous), null);
});

test("calibration drift needs every one of the last polls above the limit", () => {
  const sample = (distanceM) => ({ robotId: "rosy_01", distanceM });
  assert.equal(calibrationDriftVerdict([]), null);
  assert.equal(calibrationDriftVerdict([sample(0.9), sample(0.9)]), null);        // 폴링 수 부족
  assert.deepEqual(calibrationDriftVerdict([sample(0.9), sample(0.5), sample(0.7)]),
    { robotId: "rosy_01", distanceM: 0.9 });                                       // 연속 초과
  assert.equal(calibrationDriftVerdict([sample(0.9), sample(0.5), null, sample(0.9), sample(0.9)]), null); // 연속 끊김
  assert.equal(calibrationDriftVerdict([sample(0.9), sample(0.9), sample(0.2)]), null); // 마지막 폴링 정상
  assert.equal(calibrationDriftVerdict([null, null, null]), null);
  assert.equal(CALIBRATION_DRIFT_POLLS, 3);
  assert.equal(CALIBRATION_DRIFT_M, 0.4);
});

test("pose memory keeps matched poses for the next poll's stillness check", () => {
  const poses = rememberTrackingPoses({ robots: [
    { robotId: "rosy_01", pose: { x: 1, y: 2 } },
    { robotId: "rosy_02", pose: null, measured: true },
  ] });
  assert.deepEqual(Object.fromEntries(poses), { rosy_01: { x: 1, y: 2 } });
  assert.equal(rememberTrackingPoses(null).size, 0);
});

test("the server-side calibration check reads stale source rows and keeps the worst", () => {
  const row = (source_id, calibration_drift) => ({ source_id, calibration_drift });
  const sources = [
    row("ceiling_a", { state: "ok", max_move_m: 0.1, rotation_deg: 0.5 }),
    row("ceiling_b", { state: "stale", max_move_m: 0.55, rotation_deg: 1.4, checked_at: 7 }),
    row("ceiling_c", null),
    row("ceiling_d", { state: "stale", max_move_m: "bad" }),
    row("ceiling_e", { state: "stale", max_move_m: 0.4, rotation_deg: "x" }),
    { source_id: "ceiling_f" },
  ];
  assert.deepEqual(serverCalibrationDrift(sources),
    { sourceId: "ceiling_b", maxMoveM: 0.55, rotationDeg: 1.4 });
  assert.deepEqual(serverCalibrationDrift([row("ceiling_e", sources[4].calibration_drift)]),
    { sourceId: "ceiling_e", maxMoveM: 0.4, rotationDeg: null });
  assert.equal(serverCalibrationDrift([row("ceiling_a", sources[0].calibration_drift)]), null);
  assert.equal(serverCalibrationDrift([]), null);
  assert.equal(serverCalibrationDrift(undefined), null);
});

test("a live robot-sample verdict outranks the server check; no robots falls back to it", () => {
  const robot = { robotId: "rosy_01", distanceM: 0.9 };
  const staleServer = [{ source_id: "ceiling_north",
    calibration_drift: { state: "stale", max_move_m: 0.55, rotation_deg: 9 } }];
  assert.deepEqual(effectiveDriftVerdict(robot, staleServer),
    { origin: "robots", robotId: "rosy_01", distanceM: 0.9 });
  assert.deepEqual(effectiveDriftVerdict(null, staleServer),
    { origin: "server", sourceId: "ceiling_north", distanceM: 0.55, rotationDeg: 9 });
  // 서버 판정이 ok이거나 없으면 그림도 돌아간다.
  assert.equal(effectiveDriftVerdict(null,
    [{ source_id: "x", calibration_drift: { state: "ok", max_move_m: 0.1 } }]), null);
  assert.equal(effectiveDriftVerdict(null, []), null);
  assert.equal(effectiveDriftVerdict(null, undefined), null);
});
