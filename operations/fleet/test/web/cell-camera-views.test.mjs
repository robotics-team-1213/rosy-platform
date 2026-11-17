import test from "node:test";
import assert from "node:assert/strict";

// 셀 S(arm_s·S3)에는 측면 카메라가 없고, Pinky 도킹은 천장 Cam ROI로 위에서 본다(D-136:
// Fleet은 영상 바이트를 중계하지 않는다). 이 회귀 시험은 어떤 셀 S 카메라 목록에도 side가
// 없고 도킹 뷰가 /side_camera를 쓰지 않음을 지킨다.
import {chargeBayRows, inspectorTargetsFromRows} from "../../../../applications/fleet/web/charge-bays-model.js";
import {
  visualCardSpecs, inspectorSpecs, CAMERA_WALL_VIEWS, S3_VIEWS, CELL_A_VIEWS, CELL_B_VIEWS, S5_VIEWS,
} from "../../../../applications/fleet/web/cell/cell-real2sim-specs.js";

const body = {
  cells: {
    cell_s: {gate: {phase: "IDLE"}},
    cell_ab: {gate: {phase: "IDLE"}},
  },
  tasks: [],
  pinky_tasks: [{task_id: "t", robot_id: "rosy_46", action: "dock_s3", target_place: "S3"}],
};

const flatten = (views) => JSON.stringify(views);

test("cell S camera views never include the A/B side camera", () => {
  const cards = visualCardSpecs(body);
  const s3 = cards.find(c => c.id === "cell_s");
  assert.ok(!s3.cameraViews.some(v => v.id === "side" || /측면/.test(v.label)));
  assert.deepEqual(S3_VIEWS.map(v => v.id), ["arm_s_top", "arm_s_wrist"]);
  const rows = chargeBayRows({actions: [{robot_id: "rosy_46", action: "wait", reason: "low_battery"}]});
  const modelS3 = rows.cards.find(c => c.id === "cell_s");
  assert.ok(!modelS3.cameraViews.some(v => v.id === "side" || /측면/.test(v.label)));
  const armSInspector = inspectorSpecs(body).find(s => s.id === "arm_s");
  assert.ok(!armSInspector.cameraViews.some(v => v.id === "side" || /측면/.test(v.label)));
  const modelTargets = inspectorTargetsFromRows(rows).find(t => t.id === "arm_s");
  assert.ok(!modelTargets.cameraViews.some(v => v.id === "side" || /측면/.test(v.label)));
});

test("docking views are the ceiling ROI zoom, never /side_camera or a Fleet relay", () => {
  const cards = visualCardSpecs(body);
  const pinky = cards.find(c => c.id === "pinky");
  const dock = pinky.cameraViews.find(v => v.id === "pinky_dock");
  assert.equal(dock.roiTarget, "rosy_46");
  assert.match(pinky.cameraViews[0].label, /천장 Cam/);
  const wallDock = CAMERA_WALL_VIEWS.find(v => v.id === "pinky_dock");
  assert.ok(wallDock.roiTarget && !wallDock.source);
  for (const views of [cards.flatMap(c => c.cameraViews), CAMERA_WALL_VIEWS, S3_VIEWS, S5_VIEWS,
    inspectorSpecs(body).flatMap(s => s.cameraViews)]) {
    assert.ok(!flatten(views).includes("/side_camera"), "도킹/셀 뷰가 /side_camera를 참조하면 안 된다");
    assert.ok(!flatten(views).includes("/api/fleet/pipeline/cell-camera"), "Fleet 중계 URL이 남아 있다");
  }
});

test("an image bound before it is attached is painted once attached", async () => {
  const {createCellFrameFeed} = await import("../../../../applications/fleet/web/shared/cell-frames.js");
  const feed = createCellFrameFeed({call: async () => ({sources: []})});
  const img = {isConnected: false, hidden: false};
  feed.bind(img, {source: "arm_s_top"});
  img.isConnected = true;
  feed.setRunning(true);
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(img.hidden, true);  // unregistered source painted, not dropped as detached
  feed.dispose();
});

test("cell camera names lease the manifest's Vision source ids", async () => {
  const {createCellFrameFeed} = await import("../../../../applications/fleet/web/shared/cell-frames.js");
  const leased = [];
  const call = async (path, init) => {
    if (path === "/api/fleet/vision/sources") return {sources: ["omx_overhead"]};
    leased.push(JSON.parse(init.body).source_id);
    throw Object.assign(new Error("stop"), {status: 403});
  };
  const feed = createCellFrameFeed({call});
  const img = {isConnected: true, hidden: false};
  feed.bind(img, {source: "top"});
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(leased, ["omx_overhead"]);
  feed.dispose();
});

test("scoped cell workspaces strictly isolate cell_s (arm_s) from cell_ab (arm_a/arm_b) and pinky", () => {
  const s3Cards = visualCardSpecs(body, {scope: "cell_s"});
  assert.deepEqual(s3Cards.map(c => c.id), ["cell_s"]);
  const s3Inspectors = inspectorSpecs(body, {scope: "cell_s"});
  assert.deepEqual(s3Inspectors.map(s => s.id), ["arm_s"]);
  assert.deepEqual(s3Inspectors[0].cameraViews.map(v => v.id), ["arm_s_wrist", "arm_s_top"]);
  assert.ok(!s3Inspectors.flatMap(s => s.buttons).some(b => b.preset?.startsWith("s5_") || b.pinkyAction));

  const s5Cards = visualCardSpecs(body, {scope: "cell_ab"});
  assert.deepEqual(s5Cards.map(c => c.id), ["cell_ab"]);
  assert.ok(!s5Cards[0].buttons.some(b => b.preset === "full_s3_to_s5_pipeline" || b.preset?.startsWith("s3_")));
  const s5Inspectors = inspectorSpecs(body, {scope: "cell_ab"});
  assert.deepEqual(s5Inspectors.map(s => s.id), ["arm_a", "arm_b"]);
  assert.ok(s5Inspectors.flatMap(s => s.cameraViews).every(v => ["top", "side", "arm_a_wrist", "arm_b_wrist"].includes(v.id)));
  assert.ok(!s5Inspectors.flatMap(s => s.buttons).some(b => b.preset?.startsWith("s3_") || b.preset === "full_s3_to_s5_pipeline" || b.pinkyAction));
  assert.ok(!s5Inspectors.find(s => s.id === "arm_a").buttons.some(b => b.preset === "s5_tier2_arm_b"));
  assert.ok(!s5Inspectors.find(s => s.id === "arm_b").buttons.some(b => b.preset === "s5_tier1_arm_a" || b.preset === "s5_tier3_arm_a"));

  const cellACards = visualCardSpecs(body, {scope: "cell_a"});
  assert.deepEqual(cellACards.map(c => c.id), ["cell_a"]);
  assert.deepEqual(CELL_A_VIEWS.map(v => v.id), ["top", "side", "arm_a_wrist"]);
  assert.ok(!cellACards[0].cameraViews.some(v => v.id === "arm_b_wrist" || v.id.startsWith("arm_s")));
  assert.ok(!cellACards[0].buttons.some(b => b.preset === "s5_tier2_arm_b" || b.preset?.startsWith("s3_")));
  const cellAInspectors = inspectorSpecs(body, {scope: "cell_a"});
  assert.deepEqual(cellAInspectors.map(s => s.id), ["arm_a"]);

  const cellBCards = visualCardSpecs(body, {scope: "cell_b"});
  assert.deepEqual(cellBCards.map(c => c.id), ["cell_b"]);
  assert.deepEqual(CELL_B_VIEWS.map(v => v.id), ["top", "side", "arm_b_wrist"]);
  assert.ok(!cellBCards[0].cameraViews.some(v => v.id === "arm_a_wrist" || v.id.startsWith("arm_s")));
  assert.ok(!cellBCards[0].buttons.some(b => b.preset === "s5_tier1_arm_a" || b.preset === "s5_tier3_arm_a" || b.preset?.startsWith("s3_")));
  const cellBInspectors = inspectorSpecs(body, {scope: "cell_b"});
  assert.deepEqual(cellBInspectors.map(s => s.id), ["arm_b"]);
});

