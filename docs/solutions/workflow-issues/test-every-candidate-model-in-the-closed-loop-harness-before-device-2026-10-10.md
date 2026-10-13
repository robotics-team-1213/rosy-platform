---
title: Test every candidate model in the SIM closed loop before the device; per-frame IoU hides wall false positives
date: 2026-10-10
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
