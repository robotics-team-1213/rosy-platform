# D-491 crosswalk on the real camera and IR — rosy-pinky-9dfk, 2026-10-07

**Scope:** DEVICE evidence for the D-491 detector and IR pattern. Not a release, not an acceptance of the IR guard (still off, IR uncalibrated on this robot).

**Robot state:** release 2026.10.07-051, runtime `motor`, keep mode with `camera_ground_source: NOMINAL` and operator overrides pitch 0.2115 rad, height 0.0549 m. No camera_profile record. Track 260919, bottom-east crosswalk, outer lane next to the wall.

## Method

1. Low-speed CORE teleop (0.03 m/s pulses of 5 cm, then 0.02 m/s continuous), operator token, mode back to IDLE after each run.
2. Raw camera frames after each 5 cm step with the odom pose (`camera-steps.json`); the D-491 detector (`crosswalk_stripes.py` via `LaneKeeper`) run offline on them with the robot's own nominal profile and overrides.
3. IR ADC (`ir_sensor/range`, left/centre/right) and odom logged together at 20 Hz on the robot while crossing (`cross1.csv`, `cross2.csv`: unix time, odom x, odom y, L, C, R).

## Results

| Item | Result |
|---|---|
| Detector, frames in BEV range | 5 of 5 (frames 0–1 had the crosswalk beyond 0.43 m) |
| Camera near edge in odom, robot overrides | 0.517–0.533 m (stable within 1.6 cm) |
| IR white span in odom (IR row x + 0.0295 m) | 0.575–0.690 m, length 0.115 m (true bar length 0.120 m: odom within 4 %) |
| IR levels | white C≈1250, R≈1150; carpet L≈3100, C≈2350, R≈2300 (white reads lower) |
| IR pattern on this pass | L carpet, C and R white for the whole crossing → weighted error ≈ +0.5 → today's guard: false `lane_edge_right` |
| Camera vs IR, overrides (h 0.0549) | near −5.2 cm, far −6.4 cm |
| Camera vs IR, URDF height 0.0634, pitch 0.2115 | near −1.1 cm, far −1.4 cm |

## Conclusions

- The along-lane stripe detector works on the real 320x240 camera at 0.2–0.43 m.
- On the real mat a crosswalk under the IR row reads as one side plus centre, not the STL's alternating phases; the D-491 rest covers left/right/centre alike.
- The robot's height override is about 1 cm low; a measured camera_profile record is the fix (calibration runner needed an HTTPS fix first: `fix/calibration-runner-tls`).
- Along-track camera error at 0.3 m is about 1.5 cm with good geometry: `crosswalk_range_error_fraction` 0.05.

Not done here: IR calibration endpoints for the left channel, a calibrated camera record, a release with D-491, a guarded drive with `ir_guard_enabled`.
