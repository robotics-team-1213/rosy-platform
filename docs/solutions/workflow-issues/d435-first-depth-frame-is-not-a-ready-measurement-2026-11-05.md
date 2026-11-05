---
title: A complete first D435 depth frame can still be a poor measurement input
date: 2026-11-05
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

## Limits and prevention

The measured fraction counts nonzero values, not accurate depths. Twelve skipped frames is an observed setting for this cell and mode, not a universal readiness threshold. The experiment establishes a startup-dependent difference, not its exact firmware/exposure mechanism. If the scene, mode or device changes, repeat the checks. A plausible plane fit or a full-size buffer alone does not establish calibration readiness. Leaving the temporary stream ends this diagnostic; no service restart or guard change is needed.
