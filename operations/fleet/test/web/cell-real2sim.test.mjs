import test from "node:test";
import assert from "node:assert/strict";

import {
  REAL2SIM_PATH,
  EVALUATE_PATH,
  RUNS_PATH,
  PROMOTE_PATH,
  CELL_TASKS_PATH,
  readoutPairs,
  loopRows,
  stageRows,
  sysidRows,
  surveyRows,
  runRows,
  cellTaskSummaryPairs,
  cellTaskRows,
  visualCardSpecs,
  inspectorSpecs,
} from "../../../../applications/fleet/web/cell/cell-real2sim.js";

test("real2sim routes point to the cell-app pipeline endpoints", () => {
  assert.equal(REAL2SIM_PATH, "/api/fleet/cell-app/real2sim-pipeline");
  assert.equal(EVALUATE_PATH, "/api/fleet/cell-app/real2sim-pipeline/evaluate");
  assert.equal(RUNS_PATH, "/api/fleet/cell-app/real2sim-pipeline/runs");
  assert.equal(PROMOTE_PATH, "/api/fleet/cell-app/real2sim-pipeline/promote-physics");
  assert.equal(CELL_TASKS_PATH, "/api/fleet/pipeline/cell-tasks");
});

test("readoutPairs, loopRows, stageRows, sysidRows, surveyRows, and runRows format the pipeline", () => {
  const sample = {
    active: {
      id: "20261110-1231",
      camera_check: {pads: 3, worst_mm: [0.0, 1.9], within_3mm: true},
      ship_fixation: {
        berth_kit: "v16-modular",
        arm_a_gap_dy_mm: 26.75,
        arm_b_gap_dy_mm: 28.75,
        nominal_spacer_dy_mm: 39.0,
        belt_to_stopper_flat_mm: 26.0,
        stopper_drop_mm: 20.0,
        within_v16_yaw_budget: true,
      },
    },
    cad_inventory: {
      revision: "ship-cell-2026-11-12",
      mesh_count: 14,
      berth_kit: "v16-modular",
      temp_bridge: "v7",
      temp_plate: "v11",
    },
    sysid_summary: {
      twin_camera_outline_px: 2.8,
      twin_camera_limit_px: 3.0,
      best_fit_id: "fit-servo-run3",
      best_holdout_rms_deg: 0.41,
      fits: [
        {
          id: "fit-servo-run3",
          arm: "arm_b",
          base: "registers-20261109",
          keys: ["frictionloss", "damping"],
          episodes_hold: 11,
          base_hold_mean_deg: 0.448,
          fitted_hold_mean_deg: 0.41,
          ok: true,
          verdict: "held-out mean 0.448 -> 0.410 deg over 11 episodes",
        },
      ],
      next_experiments: [
        {
          constant: "arm_a.joint1.kp",
          relative_width: 11.0,
          known: "assumed",
          experiment: "servo: fit on recorded episodes",
        },
      ],
    },
    runs: [
      {
        run_id: "r2s-20261110-1231-001",
        status: "QUEUED",
        snapshot_id: "20261110-1231",
        berth_kit: "v16-modular",
        physics: "servo-antijitter-20261112",
        rerun_stages: ["rehandle", "stack"],
        cli_command: "python3 tools/sim/omx_real2sim.py pipeline ...",
      },
    ],
    diff: {changed: {temp_plates: ["a-1 12 mm"]}, rerun: ["rehandle", "stack"], gaps: ["G-17"]},
    loop_steps: [
      {step: "1", direction: "real", title: "관측 (Capture)", tool: "omx_real2sim.py capture", status: "ready", summary: "ok"},
    ],
    stages: [
      {stage: "mujoco", stage_order: 1, track: "learning_and_physics", role: "stage1", rerun: ["stack"], flags: ["--cam-jitter"]},
      {stage: "isaac", stage_order: 2, track: "learning_and_physics", role: "stage2", release_case: "nominal-palletizing-v21-ship-r08-berth-v16", isaac_handoff: {schema: "rosy.omx-isaac-handoff.v1"}},
    ],
  };
  const pairs = readoutPairs(sample);
  assert.equal(pairs.length, 6);
  assert.match(pairs[0][1], /STL 14개/);
  assert.match(pairs[1][1], /26\.75 mm/);
  assert.match(pairs[2][1], /하향 20 mm/);
  assert.match(pairs[4][1], /0\.41° \(fit-servo-run3\)/);
  const lRows = loopRows(sample);
  assert.equal(lRows.length, 1);
  assert.equal(lRows[0][3], "정상 · 준비됨");
  const sRows = stageRows(sample);
  assert.equal(sRows.length, 2);
  assert.equal(sRows[0][0], "Stage 1");
  assert.equal(sRows[1][0], "Stage 2");
  assert.match(sRows[1][4], /rosy\.omx-isaac-handoff\.v1/);
  const fRows = sysidRows(sample);
  assert.equal(fRows.length, 1);
  assert.equal(fRows[0][0], "fit-servo-run3");
  assert.equal(fRows[0][4], "통과 (승격 가능)");
  const eRows = surveyRows(sample);
  assert.equal(eRows.length, 1);
  assert.equal(eRows[0][0], "arm_a.joint1.kp");
  const rRows = runRows(sample);
  assert.equal(rRows.length, 1);
  assert.equal(rRows[0][0], "r2s-20261110-1231-001");

  const tSummary = cellTaskSummaryPairs({
    summary: {total: 3, queued: 1, running: 1, completed: 1},
    cells: {
      cell_s: {gate: {phase: "ARM_IN_BED_ZONE", amr_motion_inhibited: true}},
      cell_ab: {gate: {phase: "RELEASED", amr_motion_inhibited: false}},
    },
  });
  assert.equal(tSummary.length, 3);
  assert.match(tSummary[0][1], /전체 3건/);
  assert.match(tSummary[1][1], /AMR 잠금 ON/);

  const tRows = cellTaskRows({
    tasks: [
      {
        task_id: "live-e2e-cell-s-arm-s-v3",
        cell_id: "cell_s",
        arm_id: "arm_s",
        src_site: "pinky",
        dst_site: "belt",
        tier: 1,
        displaced_to: "belt_far",
        status: "COMPLETED",
        hardware_telemetry: {stop_event: {folded: true, state: [-0.07, -58.53, 50.96, 50.28, -4.71, 49.38]}},
      },
    ],
  });
  assert.equal(tRows.length, 1);
  assert.equal(tRows[0][0], "live-e2e-cell-s-arm-s-v3");
  assert.match(tRows[0][2], /복구: belt_far/);
  assert.match(tRows[0][4], /folded: true/);

  const vCards = visualCardSpecs({
    cells: {
      cell_s: {gate: {phase: "CLAIMED", amr_motion_inhibited: true}},
      cell_ab: {gate: {phase: "RELEASED", amr_motion_inhibited: false}},
    },
    tasks: [
      {
        task_id: "live-e2e-cell-s-arm-s-v3",
        cell_id: "cell_s",
        arm_id: "arm_s",
        status: "COMPLETED",
        hardware_telemetry: {stop_event: {folded: true, state: [0.0, -58.0, 50.0, 50.0, -5.0, 58.1]}},
      },
    ],
    pinky_tasks: [
      {task_id: "pinky-task-01", robot_id: "rosy_42", action: "dock_and_unload_s3", target_place: "S3"},
    ],
  });
  assert.equal(vCards.length, 3);
  assert.equal(vCards[0].id, "cell_s");
  assert.deepEqual(vCards[0].cameraViews.map(v => v.id), ["arm_s_top", "arm_s_wrist"]);
  assert.match(vCards[0].folded_state, /folded: true/);
  assert.equal(vCards[1].id, "cell_ab");
  assert.deepEqual(vCards[1].cameraViews.map(v => v.id), ["top", "side", "arm_a_wrist", "arm_b_wrist"]);
  assert.equal(vCards[2].id, "pinky");
  assert.deepEqual(vCards[2].cameraViews.map(v => v.id), ["pinky_dock", "arm_s_top"]);
  assert.equal(vCards[2].cameraViews[0].roiTarget, "rosy_42");
  assert.ok(vCards.every(c => !c.cameraUrl && c.cameraViews.every(v => !v.url)), "중계 URL이 없다(D-136)");
  assert.equal(vCards[2].buttons[0].pinkyAction, "dock_and_unload_s3");
  assert.equal(vCards[2].buttons[1].decisionSubject, "rosy_42");
  assert.equal(vCards[2].buttons[2].zoneId, "STG_C2");
  assert.equal(vCards[0].buttons[1].decisionSubject, "cell_s");
  assert.equal(vCards[0].buttons[2].visionCheckCell, "cell_s");
  assert.equal(vCards[0].cameraViews.length, 2);
  assert.equal(vCards[1].cameraViews.length, 4);
  assert.equal(vCards[2].cameraViews.length, 2);
  assert.ok(vCards[0].buttons.some(b => b.clearArmHold === "cell_s"));
  assert.ok(vCards[1].buttons.some(b => b.clearArmHold === "cell_ab"));
  assert.ok(vCards[0].buttons.some(b => b.humanSafetyCell === "cell_s"));
  assert.ok(vCards[0].buttons.some(b => b.zoneId === "EXP_S3_BELT"));
  assert.ok(vCards[2].buttons.some(b => b.cableGuardToggle === true));

  const iSpecs = inspectorSpecs({
    cells: {
      cell_s: {gate: {phase: "CLAIMED", amr_motion_inhibited: true}},
      cell_ab: {gate: {phase: "RELEASED", amr_motion_inhibited: false}},
    },
    arm_holds: {arm_b: {held: true, reason: "alignment deadline exceeded"}},
    arm_live_states: {
      arm_a: {joints_deg: [0.8, -62.5, 53.3, 51.7, 45.0, 50.0], folded: true, temp_c: 31.0, current_ma: 38.0, age_s: 1.4, fresh: true, substage: "Fold Home 대기"},
    },
    tasks: [
      {
        task_id: "live-e2e-cell-s-arm-s-v3",
        cell_id: "cell_s",
        arm_id: "arm_s",
        status: "COMPLETED",
        hardware_telemetry: {stop_event: {folded: true, state: [0.0, -58.0, 50.0, 50.0, -5.0, 58.1]}},
      },
    ],
  });
  assert.deepEqual(iSpecs.map(s => s.id), ["arm_s", "arm_a", "arm_b", "cell_s", "cell_ab", "rosy_46", "rosy_45", "rosy_42"]);
  assert.equal(iSpecs[0].cameraViews[0].id, "arm_s_wrist");
  assert.equal(iSpecs[1].cameraViews[0].id, "arm_a_wrist");
  assert.equal(iSpecs[2].cameraViews[0].id, "arm_b_wrist");
  assert.deepEqual(iSpecs[0].dualPair, ["arm_s_top", "arm_s_wrist"]);
  assert.deepEqual(iSpecs[1].dualPair, ["top", "arm_a_wrist"]);
  assert.match(iSpecs[0].telemetryRows[1][1], /folded=true/);
  assert.match(iSpecs[1].telemetryRows[1][1], /\[LIVE · 1초 전\]/);
  assert.match(iSpecs[2].telemetryRows[3][1], /홀드 활성/);
});
