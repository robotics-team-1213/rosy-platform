import test from "node:test";
import assert from "node:assert/strict";

// 셀 S(arm_s·S3)에는 측면 카메라가 없고, Pinky 도킹은 천장 Cam ROI로 위에서 본다(D-136:
// Fleet은 영상 바이트를 중계하지 않는다). 이 회귀 시험은 어떤 셀 S 카메라 목록에도 side가
// 없고 도킹 뷰가 /side_camera를 쓰지 않음을 지킨다.
import {chargeBayRows, inspectorTargetsFromRows} from "../../../../applications/fleet/web/charge-bays-model.js";
import {
  visualCardSpecs, inspectorSpecs, CAMERA_WALL_VIEWS, S3_VIEWS, S5_VIEWS,
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
