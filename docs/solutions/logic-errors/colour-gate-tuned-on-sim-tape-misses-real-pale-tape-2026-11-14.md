---
title: A colour gate tuned on the sim's tape colour missed the real, paler tape
date: 2026-11-14
module: integrations/perception lane_keep_lines, middleware/perception bay_line_observer, operations/overhead map_register and world_261026_auto
problem_type: logic_error
component: perception
severity: high
symptoms:
  - "Every pink-tape test passes, but on the real mat Pinky's pink mask finds nothing and the bay line shows up in the white lane mask."
  - "The ceiling registration counts the bay guide tape as lane paint that the site map does not have."
root_cause: thresholds_from_simulation
resolution_type: code_fix
applies_when:
  - "Setting or reviewing an HSV or colour gate for floor tape, markers or containers."
  - "Adding tape or paint to the site that a white-paint detector also looks at."
tags: [perception, hsv, pink-tape, d-1013, sim-to-real, ceiling-camera]
---

# Measure a colour gate on real frames from every camera that reads it

## What happened
The D-1013 pink paint source and the bay line observer both used H 140-170, S >= 80. The tests rendered the tape with the 261026 world's diffuse (0.95, 0.15, 0.85 RGB, about H 154, S 215), so they passed.

The real parking-mat tape is much paler. On 2026-11-14:
- rosy_42's front camera read it at H 172-175, S 49-78.
- The ceiling phone read it at H 167-172, S 40-74.

The old gate caught 0% of the tape. The white masks gate saturation only (Pinky S <= 80, ceiling S <= 70), so they took 72-86% (Pinky) and 59-67% (ceiling) of it as lane paint.

Nothing failed loudly: the bay line observer fails closed, and the lane keeper simply saw one more white line.

## Fix
- **One pink gate:** H 145-179, S >= 35, V >= 60. It is defined in `lane_keep_lines` and imported by `bay_line_observer`.
- **White masks:** Pinky's `floor_white_mask`, the ceiling `_line_mask` and the world_261026 white mask all drop that gate explicitly. Saturation cannot separate the two, because the real tape's S overlaps the white bound.
- **Tests:** they carry the measured real colours (median and pale tenth) and an orange negative.

## How it was verified
The patch was replayed on the real frames, kept in the workspace record 2026-11-14 pink-bay-tape-colour-panel:
- the pink mask caught 96-97% of the tape;
- 0% of the pink landed in any white mask;
- orange caught as pink: 0 px;
- the ceiling auto-calibration stayed at rms 11.2 mm.

## Next time
- Grab one frame from each camera that reads the colour and measure the H, S and V percentiles before choosing bounds. Pinky: `/<ns>/camera/preview/raw/compressed` with best-effort QoS. Ceiling: a Fleet vision lease.
- Put the measured real colour in the test, next to the sim colour.
- Whenever new coloured tape goes down, check that it stays out of every white-paint mask.
- Saturated tape (S >= 110) widens the margin. A worn, pale tape is the first to fall through.
