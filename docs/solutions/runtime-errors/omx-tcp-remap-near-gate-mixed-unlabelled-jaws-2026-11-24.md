---
title: TCP remap must not gate mark_jaws on predictions fitted from unlabelled single-jaw marks
date: 2026-11-24
module: deploy/robot/omx
tags: [omx, remap, tcp_marks, jaw_side, cell_calibrate]
problem_type: runtime-error
applies_when: calibrate.tcp_marks is true during remap and points drop with "blobs outside near" or remap refuses with "jaw sides ambiguous"
---

## Symptom

During `arm_b` 12-point `tcp_marks` remap (with both jaws visible at differing frequencies), points `06` through `10`
rejected repeatable jaw blobs with `blobs outside near`, leaving only one seen pair and causing
`cell_jaw_side.remap_marks` to refuse saving the map (`jaw sides ambiguous: 2 labellings with 1 seen pairs within 3 mm rms put the map 58.2 mm apart`).
Earlier on `arm_a`, `tcp_marks` remap also dropped point `[0.04, 0.17]` when its visible jaw switched sides across the `~54 mm` jaw span.

Additionally, `pivot.merge_px = 12` (a `25x25` morphological dilation) bridged the `~22-28 px` inner gap between open fingers on `arm_b`, fusing both jaws into one large blob and leaving too few two-blob pairs for unambiguous jaw labelling.

## Cause

In `cell_calibrate.remap`, `marks` collects `(pixel, (x, y))` pairs using the TCP coordinate as `(x, y)` before `cell_jaw_side.remap_marks` runs at the end of the loop. When `calibrate.tcp_marks` is enabled, each mark in `marks` is an unlabelled single jaw (`ref` or `other`), which lie `~54 mm` (`~67-76 px` at top-camera scale) apart — larger than `pivot.follow_px` (`60 px`).

Once 4+ unlabelled marks accumulated across both jaws, `consensus(marks, consensus_px)` and `predicted(kept, (x, y))` fitted an affine plane through mixed `ref`/`other` pixels and passed `near` with radius `pivot.follow_px` to `cell_pivot.mark_jaws`. That rejected valid opposite-jaw blobs or extruded skewed predictions (`60-120 px` off).

## Fix

1. In `deploy/robot/omx/cell_calibrate.py` (`remap`), skip raw-`marks` `consensus`/`predicted` `near` prediction when `tcp_marks` is true (`kept = [] if tcp_marks else ...`). Regression test: `test/test_omx_cell_calibrate.py::test_a_tcp_remap_does_not_gate_mark_jaws_on_unlabelled_jaw_predictions`.
2. In cell parameters (`cell-params-stack.json`), set `pivot.merge_px = 6` (`13x13` dilation) so fragmented single-finger blobs merge while both jaws stay distinct (verified by offline replay across both `arm_a` and `arm_b` 2026-11-24 remap tries).

## Watch for

- Never enable `jaw_mark.centre` alongside `calibrate.tcp_marks` (mutually exclusive: `tcp_marks` expects per-jaw blobs to label post-hoc, whereas `jaw_centres` returns midpoints).
- If a `tcp_marks` remap shows repeated `"blobs outside near"` after point 4 or drops pairs despite clear open/close frames, check `jaw_mark.colour` (dark fingers over orange surfaces) and `pivot.merge_px` before tuning `jaw_side`.
