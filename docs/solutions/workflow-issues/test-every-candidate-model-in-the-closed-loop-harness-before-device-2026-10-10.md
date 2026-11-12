---
title: Test every candidate model in the SIM closed loop before the device; per-frame IoU hides wall false positives
date: 2026-10-10
last_updated: 2026-11-12
category: workflow-issues
module: SIM closed-loop harness, learned paint candidates
problem_type: workflow_issue
component: development_workflow
symptoms:
  - "candidate 28e8454d paints white wall/baseboard, boundary reads -21 to -25 degrees, false junction_transverse"
  - "candidate 62db9403 misses lines on the wall side"
  - "neither showed in per-frame IoU; the threshold paint completes the same lap"
root_cause: missing_validation
resolution_type: workflow_improvement
severity: high
tags: [sim, closed-loop, model, iou, paint_model_revision, candidate, sim2real]
---

# Test every candidate model in the SIM closed loop before the device

## Problem

Per-frame IoU looked acceptable for both candidates. Closed-loop SIM runs with our own models showed wall false positives and wall-side line misses that the controller turned into false junctions.

## Rule

- Run each candidate in the closed-loop harness before any device trial.
- Compare against the threshold baseline on the same lap; if threshold completes it and the model does not, the model is not ready.
- Count only frames whose `paint_model_revision` matches the candidate. Frames served by the fallback otherwise inflate the result (see `docs/solutions/logic-errors/learned-paint-frame-count-gate-drops-slow-masks-2026-10-10.md`).

## Evidence

SIM runs on the model PC (not the laptop); `keep_debug` fields `paint_source_used`, `paint_model_revision`.

### 2026-11-12: arrival alone gave a false model PASS

The Fleet lap reached its destination while the recorder's ROS `cv_bridge` image callback crashed against NumPy 2. Its `.ready` file existed, but no camera frames or `keep_debug` survived. The arrival result therefore said nothing about the model. The recorder now decodes raw ROS images without `cv_bridge`; the drivable run requires recorded `keep_debug` during nonzero `cmd_vel`, at least 99% `learned_drivable`, and the requested revision on every learned frame. It reports fallback frames and whether the run was pure model. A missing trace fails the run. This gate is still a lane lap check, not a charging-bay pit-out or field acceptance.

On the model PC, the first corrected trace had 1,496 matching observations of 1,500 during motion and four fallback frames. The strict all-frame gate correctly rejected a claim of pure model use; the later 99% gate retains those four frames in the result instead of hiding them. See `tools/sim/fleet_trips.py`, `tools/sim/fleet_trip_recorder.py`, and the 2026-11-12 workspace record for the raw run paths.
