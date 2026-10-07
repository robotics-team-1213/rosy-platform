---
title: The floor IR can be calibrated without hand placement by crossing a straight line at an angle under LiDAR-wall pose
date: 2026-10-07
category: workflow-issues
module: middleware/perception/tools/device/ir_line_calibrate.py, docs/deployment/pinky-pro-ir-line-calibration-runbook.md (rosy-pinky-9dfk)
problem_type: best_practice
component: development_workflow
severity: medium
applies_when:
  - "no one can place the robot and tape by hand for the four runbook phases"
  - "the track has a straight boundary line with clear floor on both sides"
  - "the robot's pose can be measured from its LiDAR against known walls"
tags: [ir, line-calibration, d-344, d-491, pinky, lidar-pose, field-procedure]
---

# The floor IR can be calibrated without hand placement by crossing a straight line at an angle under LiDAR-wall pose

## Context

The runbook places the robot by hand four times (carpet, then tape under the left, centre and right sensor) and checks signs by moving tape. On 2026-10-07 the IR on 9dfk had to be calibrated remotely. The first two attempts failed:

- A diagonal drive guided by overhead pixels never reached the line and ended beside a crosswalk.
- An odom-guided turn landed the robot on the wrong segment.

The 260919 lines also sit close to other paint. The west block's west line is about 1 cm from the crosswalk bars, so many segments cannot be crossed cleanly.

## Guidance

1. **Pick a clean straight segment from the map, not the image.** Read the line edges from the STL paint raster (`lane_graph.paint_masks`). Use the west block's south line, y −0.431..−0.407, straight to x ≈ −0.76. Choose a stretch with nothing else painted within the crossing path, and stop short of where the line bends.
2. **Cross at about 25 deg with the line on one known side.** At 25 deg the sensor spacing across the line (0.02 · cos 25 = 18 mm) is below the 24 mm tape width, yet each sensor still gets a single-sensor window of about 12 mm across the line, about 29 mm along the path. The side the line approaches from fixes the expected order: from the right it is R → R+C → C → L+C → L. That order is the sign check.
3. **Step and hold.** Move 6 mm (0.02 m/s for 0.3 s), stop for 1.2 s, and log IR and odom on the robot at 20 Hz. Each stop gives about 21 still samples. Stop the sweep on the LiDAR-wall pose, never on odom: when the left sensor has passed the far edge, or before the line bends.
4. **Cut phases from still windows.** Carpet: the stops before the line. Each sensor phase: stops where only that channel reads white and the others read carpet. Drop windows that sit half on an edge. Write `{"schema": "rosy.control.ir_line_calibration/1", "phases": {...}}` and run `python tools/device/ir_line_calibrate.py compute --session <file>` on the PC. It applies the runbook's checks (≥20 samples, span, 6σ separation, readback signs).
5. **Apply and verify as the runbook says.**
   - Put only the observer block in `/etc/rosy/ir_calibration.yaml` (ASCII, root 0644).
   - Add `line_follow.ir_calibration_revision` to the CORE overlay, after a backup.
   - Restart `rosy-camera` and `rosy-core`.
   - Check that the journal says `IR calibration overlay ... loaded`.
   - Check that `IR_LINE` observations carry `ir_calibrated: true` and the same revision.

## Why This Matters

The crossing gave a clean R → C → L sequence on the first correctly placed try. All checks passed: spans 1773–1950, noise at most 136, readback left −0.86, centre −0.03, right +0.91. The left channel reads about 1.4× higher than the others on both carpet and tape, so per-channel endpoints are needed.

The map-predicted crossing lagged the IR by about 2 cm. Treat LiDAR-wall pose against the STL paint as good to a couple of centimetres, not millimetres.

The real crosswalk also read differently from the STL model: a centred crossing showed C+R white, not the alternating phases. So IR expectations derived from the map need a real pass before anyone relies on them.

The method repeated on the second robot the same day. 8kcn was driven from the site PC rather than the laptop (D-508). It crossed the inner lane line at 30 deg on the first try: R → R+C → C → L+C → L. All checks passed: spans 1557–2030, read-back left −1.00, centre +0.06, right +1.00.

Three findings from that run:

- **Single-sensor tape readings are not the darkest readings.** A sensor alone on the tape read higher (right about 850) than the same sensor read when its neighbour was also on the tape (about 370). 9dfk did the same. This is probably light leaking between neighbouring sensors. The runbook takes each channel's tape value from single-sensor windows, which matches how the tape usually sits under the sensors in operation, so keep those windows.
- **Reject wall estimates outside the arena.** Through a gap in the wall the rear beams reached 3.2 m. Averaged with the front wall, that moved x by 0.8 m. Drop any per-wall estimate that falls beyond the opposite inner face, and take the wall as the farthest cluster of at least 15 points, not a percentile.
- **Use the paint itself as the x reference.** The overhead image and LiDAR disagreed by 7 cm in x. Stepping forward until the IR first saw the crosswalk bars put the bar edge within 1 cm of the STL position. That confirmed the LiDAR x and showed the overhead was off. Crosswalk bars only pulled the raw IR to about 1700, against about 300 on the line tape, so don't use a tape threshold to detect bars.

## When to Apply

When remote IR calibration is needed on a mapped track. Keep the hand procedure when someone is on site; it needs no driving.

## Examples

Still-window medians across the line (white reads low):

```text
y=-0.3609  L=3124 C=2460 R= 907   ..R
y=-0.3803  L=3033 C= 312 R= 275   .CR
y=-0.3916  L=2760 C= 272 R=1935   .C.
y=-0.3984  L=1416 C= 284 R=1896   LC.
y=-0.4036  L=1275 C=1854 R=2081   L..
y=-0.4251  L=2912 C=2112 R=2026   ...
```

Endpoints and the revision digest stay on the robot. The public repo records only this summary, as the runbook asks.

## Related

- `docs/solutions/workflow-issues/field-scripts-driving-a-real-robot-need-clearance-identity-and-wall-pose-2026-10-07.md`
- D-344 §12 IR guard, D-491 crosswalk zones (the guard stays off until D-491 ships)
