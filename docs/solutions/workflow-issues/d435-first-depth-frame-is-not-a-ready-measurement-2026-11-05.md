---
title: A complete first D435 depth frame can still be a poor measurement input
date: 2026-11-05
last_updated: 2026-11-17
category: workflow-issues
module: deploy/robot/omx/cell_depth.py
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "Capturing a single Z16 frame after starting the cell D435 depth stream"
tags: [omx, realsense, depth, startup]
---

# A complete first D435 depth frame can still be a poor measurement input

## Observation

After USB recovery, the cell's unused depth node returned a complete 640x480 Z16 frame: 614400 bytes and capture exit0. Only20.59% of its pixels were nonzero. A second stream start, again keeping the first frame, returned20.28%. Both files were structurally complete.

With the same640x480/6fps mode, skipping12frames before retaining one returned88.05% and88.99% nonzero pixels in two separate stream starts. No exposure, emitter or laser setting was changed and the active colour viewer was not stopped. A later read found automatic exposure enabled, emitter enabled and laser power150; this does not establish the exposure history of each earlier frame.

The landed depth engine ran on both initial and warmed inputs. Its edge-alignment diagnostic changed from scale0.808/distance7.7px to scale0.632/distance5.44px. Mask alignment still disagreed, and colour/depth exposures were not synchronized. No surface heights, arm transforms or physical acceptance were assigned.

The private 2026-11-05 Decision/VLA workspace record, outside the Git repository, retains acquisition receipts and immutable frame hashes named `restored-depth-capture.json`, `restored-depth-cold-repeat.json`, `restored-depth-warmed-capture.json`, `restored-depth-warm-repeat.json`, and their depth-alignment receipts. The original and warmed raw files are retained separately.

## Guidance

Check that the depth node is unused. Capture beyond startup rather than accepting the first full-size buffer as ready. The verified acquisition command for this observation was:

```sh
v4l2-ctl -d <unused-depth-node> \
  --set-fmt-video=width=640,height=480,pixelformat='Z16 ' \
  --set-parm=6 --stream-mmap=3 --stream-skip=12 \
  --stream-count=1 --stream-to=depth.raw
```

Keep the raw file, command, format, nonzero fraction and independent repeats. Feed the retained frame to `deploy/robot/omx/cell_depth.py` only as a measurement candidate; check its alignment and measurement origins before changing calibration.

### Confirm the D435's own USB link

On 2026-11-13 a scan was first read as “D435 on USB 2” from a 480M branch of `lsusb -t`. Matching the **device ID** corrected that conclusion: `lsusb` identified Intel RealSense D435 `8086:0b07` as Bus 004 Device 009, and that exact bus/device was on a 5000M branch in `lsusb -t`. The depth role `/dev/v4l/by-id/rosy-realsense-d435-depth` resolved to `/dev/video12`; a warmed Z16 read returned 614400 bytes with 87.86% nonzero pixels. The 480M branch belonged to other devices. Check the bus/device pair and depth role before diagnosing USB speed from a root-hub or nearby camera line. This correction establishes the link speed and that a depth frame was readable; it does not establish RGB/depth alignment or physical stack height.

### The timeout must cover the skipped frames (2026-11-17)

Panel r8 saw `capture_top_depth_z16` return None while the same `v4l2-ctl` line worked by hand. The cell was running its 2026-11-13 tools (`~/rosy-omx/current` -> `omx-tools-d3cb734cad`), whose `cell_z_profile.capture_top_depth_z16` gave `v4l2-ctl` a 1.8 s timeout. Skipping 12 frames and keeping 1 at 6 fps needs about 2.2 s; on the cell it took 2.4-2.6 s, so every capture timed out, the exception was swallowed, and the function returned None. Main's `cell_depth` version (12 s default, `'Z16'` then `'Z16 '`) returned 88-90 % valid frames on the same node, and the receipt variant also worked. `v4l2-ctl` 1.32 refuses the three-letter `'Z16'` ("The pixelformat 'Z16' is invalid"), so only the padded `'Z16 '` fallback reads the camera.

`cell_depth._run_v4l2_z16` now never sets the timeout below `MIN_CAPTURE_S` (13 frames at 6 fps + 1.5 s), and `test_omx_cell_depth.py` checks that a 1.8 s request is raised. Before blaming the camera for a None, check which tools revision the cell runs, and compare the timeout with skip+count frames at the set rate.

## Limits and prevention

The measured fraction counts nonzero values, not accurate depths. Twelve skipped frames is an observed setting for this cell and mode, not a universal readiness threshold. The experiment establishes a startup-dependent difference, not its exact firmware/exposure mechanism. If the scene, mode or device changes, repeat the checks. A plausible plane fit or a full-size buffer alone does not establish calibration readiness. Leaving the temporary stream ends this diagnostic; no service restart or guard change is needed.
