import test from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";

register("./resolve-console-assets.mjs", import.meta.url);

const { OMX_CELL_DEFS } = await import("../../../../applications/fleet/web/roster-cards.js");
const {
  armEffectivePose,
  armPositionLine,
  armCameraChannels,
  mobileCameraChannels,
} = await import("../../../../applications/fleet/web/shared/robot-profile.js");

const SAMPLE_OBS_CAMERAS = [
  { source_id: "omx_overhead", label: "S5 상단", role: "overhead", arm_id: null },
  { source_id: "omx_side", label: "S5 측면", role: "side", arm_id: null },
  { source_id: "omx_wrist_a", label: "arm_a 손목", role: "wrist", arm_id: "arm_a" },
  { source_id: "omx_wrist_b", label: "arm_b 손목", role: "wrist", arm_id: "arm_b" },
  { source_id: "omx_arm_s_top", label: "S3 상단", role: "overhead", arm_id: null },
  { source_id: "omx_arm_s_wrist", label: "arm_s 손목", role: "wrist", arm_id: "arm_s" },
];

test("armEffectivePose and armPositionLine prefer finite anchor coords and fall back to OMX_CELL_DEFS", () => {
  const defA = OMX_CELL_DEFS.find((d) => d.target_id === "arm_a");
  assert.deepEqual(armEffectivePose(defA, {}), { x: 0.551, y: 0.365, yaw: -1.57 });
  assert.equal(armPositionLine(defA, {}, "cell_ab"), "S5 · cell_ab · (0.55, 0.36) m");

  assert.deepEqual(
    armEffectivePose(defA, { base_x: -0.002, base_y: 0.42, head_yaw: 0.5 }),
    { x: -0.002, y: 0.42, yaw: 0.5 },
  );
  assert.equal(
    armPositionLine(defA, { base_x: -0.002, base_y: 0.42 }, "cell_ab"),
    "S5 · cell_ab · (0.00, 0.42) m",
  );

  assert.equal(armEffectivePose({ stationId: "CELL" }, {}), undefined);
  assert.equal(armPositionLine({ stationId: "CELL" }, {}, "cell_x"), "CELL · cell_x");
});

test("armCameraChannels includes wrist/overhead/side/roi for arm_a and arm_b", () => {
  const aChannels = armCameraChannels("arm_a", SAMPLE_OBS_CAMERAS);
  assert.deepEqual(aChannels, [
    { id: "wrist", label: "손목", source: "omx_wrist_a" },
    { id: "overhead", label: "상단", source: "omx_overhead" },
    { id: "side", label: "측면", source: "omx_side" },
    { id: "roi", label: "천장 확대 (ROI)", roiTarget: "arm_a" },
  ]);

  const bChannels = armCameraChannels("arm_b", SAMPLE_OBS_CAMERAS);
  assert.deepEqual(bChannels.map((c) => c.source || c.roiTarget), [
    "omx_wrist_b",
    "omx_overhead",
    "omx_side",
    "arm_b",
  ]);
});

test("arm_s camera channels NEVER include side, omx_side, or 측면", () => {
  const sChannels = armCameraChannels("arm_s", SAMPLE_OBS_CAMERAS);
  assert.deepEqual(sChannels, [
    { id: "wrist", label: "손목", source: "omx_arm_s_wrist" },
    { id: "overhead", label: "상단", source: "omx_arm_s_top" },
    { id: "roi", label: "천장 확대 (ROI)", roiTarget: "arm_s" },
  ]);
  for (const ch of sChannels) {
    assert.notEqual(ch.id, "side");
    assert.notEqual(ch.source, "side");
    assert.notEqual(ch.source, "omx_side");
    assert.doesNotMatch(ch.label, /측면/);
  }

  const poisoned = [...SAMPLE_OBS_CAMERAS, { source_id: "omx_side", label: "측면", role: "side", arm_id: "arm_s" }];
  const sPoisoned = armCameraChannels("arm_s", poisoned);
  assert.ok(!sPoisoned.some((ch) => ch.source === "omx_side" || /측면/.test(ch.label)));
});

test("mobileCameraChannels offers D-801 front WHEP and D-136 ceiling ROI", () => {
  assert.deepEqual(mobileCameraChannels("rosy_46"), [
    { id: "front", label: "전면 카메라" },
    { id: "roi", label: "천장 확대 (ROI)", roiTarget: "rosy_46" },
  ]);
});
