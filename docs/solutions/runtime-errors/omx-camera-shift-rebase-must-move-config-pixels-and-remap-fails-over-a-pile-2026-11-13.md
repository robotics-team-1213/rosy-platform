---
title: A top-camera shift needs the config's pixel regions rebased too, and a remap cannot run over a pile
date: 2026-11-13
module: deploy/robot/omx
tags: [omx, calibration, camera-shift, remap, push]
problem_type: runtime-error
applies_when: a cell's top camera moved and the map is rebased instead of remapped, or a remap is planned while objects lie on the cell
---

## Symptom

On arm_s the upkeep reported `camera_moved` (about 48 px). After the map was rebased, every `cell_push --dry-run`
on the pile came back `refused: path not clear` with `off the surface` along the whole lane, and `cell_align plan`
then crashed in `cvtColor` (empty image) while observing the destination.

Earlier, `cell_calibrate auto` (remap) over the same cell stopped: the remap grid points lay over a pile of boxes,
`mark_jaws` found no jaws at any of them, the third `load` failed, the arm parked, and the scene check refused to save.

## Cause

- The calibration (`calibration.json`) holds the pixel↔arm maps, but the cell config holds its own pixel regions:
  `sites.*.surface_px`, `sites.*.auto_roi`, `markings_px` and `rois`. Rebasing only the map left these in the old
  camera's pixels, so the floor polygon no longer covered the floor ("off the surface").
- Shifting those regions by the same homography pushed the belt's polygon outside the 640×480 frame (y -5, x 669);
  the ROI crop was then empty and OpenCV raised.
- The remap hovers the empty jaws at fixed arm points; with boxes under them the jaws are not found in the top view.

## Fix (verified on the cell)

1. ORB+RANSAC homography from `preflight.reference_top` to the current frame (359 inliers, reprojection median 1.07 px).
2. Move every calibration point's pixel by it and refit (`cell_calibration.site_record`); keep the arm points.
3. Move the config's `surface_px`, `markings_px`, `auto_roi`, `rois` by the same homography, then clamp to the frame.
4. Save the current frame as the new reference. Back up all three files first.
`cell_calibrate check` then shows `camera_moved: false`; `cell_align plan` and `cell_push --dry-run` run again.

This rebase is not a touch-verified map: the loo error stays what it was (floor 11.7 mm, belt 25.4 mm).

## Later the same night: remap marks empty, and a site map off by 150 px

- A clear-scene remap marked 2 of 15 points. The jaws had not moved between the closed and open frames: the session's
  state refreshed the jaw value about once a second, and `grip_to` took 0.6 s of an unchanged reading as "stopped".
  Fixed in `cell_pipeline_stages.grip_to` (1.5 s, with a test); the next remap marked 12 of 14.
- The board site had its own map, fitted with two extra points; at (-0.15, -0.12) it was ~150 px off while the floor
  map sat on the jaws in the remap frame. Check a site map by drawing its predicted pixel on a frame with the jaws hovering
  at a known point before trusting a plan there.
- A box measured at pan -161 deg is outside arm_s's joint1 limit (+-149 deg): no grip or push can reach it, and the remap
  points around it fail IK. Check the target's pan angle before calibrating toward it.

## Next time

- After a camera shift, rebase map **and** config pixels together, clamp to the frame, before any plan.
- Do not run a remap while objects sit under its grid points; clear them, or rebase instead.
- The script used live is `~/rosy-test/omx-record-prep-20261019/rebase_map_20261113.py` on the control PC (map part only);
  shortcut: not yet a `cell_calibrate` step — make it one (map + config pixels + clamp) once a second cell needs it.
