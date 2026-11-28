import test from "node:test";
import assert from "node:assert/strict";

import { visualCardSpecs } from "../../../../applications/fleet/web/cell/cell-real2sim-specs.js";
import { actionGroup } from "../../../../applications/fleet/web/cell/cell-real2sim-views.js";

test("cell card buttons fall into operator groups, stop and hold controls kept apart", () => {
  const tasks = [{task_id: "t1", cell_id: "cell_s", arm_id: "arm_s", status: "QUEUED", robot_id: "rosy_42"}];
  const [s, ab, pinky] = visualCardSpecs({tasks});
  const groupOf = (card, key) => card.buttons.filter(b => b[key]).map(actionGroup);
  for (const card of [s, ab, pinky]) assert.deepEqual([...new Set(groupOf(card, "humanSafetyCell"))], ["safety"]);
  assert.deepEqual(groupOf(s, "clearArmHold"), ["safety"]);
  assert.deepEqual(groupOf(s, "visionCheckCell"), ["safety"]);
  assert.deepEqual(groupOf(s, "cancelTaskId"), ["task"]);
  assert.deepEqual(groupOf(s, "bedConfirmTaskId"), ["task"]);
  assert.equal(actionGroup({preset: "s3_recover_belt_far"}), "recover");
  assert.equal(actionGroup({preset: "s3_shuttle"}), "run");
  assert.equal(actionGroup({zoneId: "EXP_S3_BELT"}), "move");
  assert.equal(actionGroup({decisionSubject: "cell_s"}), "run");
});
