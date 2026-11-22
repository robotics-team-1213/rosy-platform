---
title: A tier place must not count the box it stands on as an occupant
date: 2026-11-18
module: deploy/robot/omx
tags: [omx, stacking, tier, occupancy, preflight]
problem_type: logic-error
applies_when: a carry places onto a tier site (layer > 0) and a pre-motion check looks for boxes already at the destination
---

## Symptom

arm_b carries to `pallet-l1` (tier 2 on the ship's left column) were refused before any motion with the destination
"occupied", while the camera showed only the bottom-row box the new one was meant to stand on.

## Cause

`cell_auto_evidence.pre_motion_frame` listed every box whose centre lay in the destination footprint as an occupant.
On a tier site the footprint always contains the support box below, so a tier place could never pass.

## Fix

For a destination with `layer` > 0, a box whose `layers_below` is less than the destination layer is support, not an
occupant (`test/test_omx_cell_tier_place_occupancy.py`). A box at or above the target layer still blocks.
`cell_return_held.py` had its own copy of the check; both now call `cell_auto_evidence.not_support`.

## Watch for

The rule depends on `layers_below` being read. The stack depth read is flaky (about one read in three fails with
"no tier covers 50 % of its own top face"); an unread support has no `layers_below` and still counts as an occupant,
which is the safe side.
