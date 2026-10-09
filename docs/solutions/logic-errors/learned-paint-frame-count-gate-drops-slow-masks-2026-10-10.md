---
title: The learned-paint frame-count gate silently drops masks slower than every_n frame periods
date: 2026-10-10
category: logic-errors
module: LearnedPaintWorker.mask_for (learned paint, D-570)
problem_type: logic_error
component: service_layer
symptoms:
  - "Pi 5 inference takes 240-300 ms and 0 of 84 live frames on 9dfk used the learned mask"
  - "SIM run F: 0 of 552 frames learned"
  - "forcing every_n=1 gave 0% learned frames in turns"
  - "the overlay validator skipped the whole overlay when one value was out of range (every_n allowed only 1-2)"
root_cause: missing_validation
resolution_type: code_fix
severity: high
tags: [paint, learned-paint, every_n, staleness, overlay, keep_debug, sim2real]
---

# The learned-paint frame-count gate silently drops masks slower than every_n frame periods

## Problem

`LearnedPaintWorker.mask_for` serves a mask only if `index - tag <= every_n`. The effective cutoff is therefore `every_n x frame period` (250 ms at `every_n` 2 and 8 Hz). That is stricter than the 1.5x stamp gate and the `stale_s` 0.6 gate, so it is the gate that decides. A model slower than the cutoff never reaches the controller and the fallback paint (threshold) drives instead, with no error.

## Symptoms

- Live on 9dfk: Pi 5 inference 240-300 ms, 0/84 frames used the learned mask.
- SIM run F: 0/552.
- `every_n=1` made it worse: 0% learned in turns.
- A single out-of-range overlay value (`every_n` was allowed only 1-2) made the validator skip the WHOLE overlay, so unrelated settings in it vanished too.

## Root cause

Three staleness gates stacked (frame count, stamp ratio, seconds). Only the tightest one matters and nobody had computed it in milliseconds. Nothing reported which gate dropped a frame.

## Rule

- Always read `keep_debug` `paint_source_used` (and `paint_model_revision`) before claiming the model drives. Model loaded and running is not model used.
- When several staleness gates exist, convert each to milliseconds at the real frame rate and compare with measured inference latency.
- A validator must reject the one bad value, not drop the entire overlay.

## Fix

D-570: ego-motion compensated reuse of the last mask, with `every_n` 4. Result: live 100% while stationary, SIM 95-99%.

## Evidence

- ADR D-570 in `docs/adr/`; `keep_debug` fields `paint_source_used`, `paint_model_revision`.
- Related: `docs/solutions/logic-errors/default-key-for-a-renamed-setting-collides-with-old-overlays-2026-10-02.md` (another overlay pitfall).
