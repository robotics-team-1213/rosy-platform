# D-143 IR / camera line-follow validation

Status: **HOST SIMULATION PASS / PHYSICAL DEVICE HOLD**

## What was exercised

- A differential-drive planar model fed each controller output into the next
  robot pose, so this is a closed-loop host simulation rather than a fixed
  sample playback.
- Each changed pose generated either three calibrated IR ADC values or a new
  synthetic BGR frame. Those passed through the production detectors and the
  selected-source CORE manager.
- Curves and lower confidence reduced linear speed; the configured 0.10 m/s cap
  was never exceeded.
- A stale sample stopped immediately. Continued loss latched `LOST` and emitted
  one `nav.lane_lost` event; a new observation did not auto-resume motion.

## Result

| Mode | Cross-track start -> finish | Straight | Tightest turn | Stale stop | Loss latch |
|---|---:|---:|---:|---|---|
| IR_LINE | 3.50 cm -> -0.03 cm | 0.08997 m/s | 0.02595 m/s | PASS | PASS |
| CAMERA_LINE | 3.50 cm -> 0.006 cm | 0.03117 m/s | 0.01642 m/s | PASS | PASS |

Artifacts:

- `result.json`: deterministic samples and assertions
- `line_follow_simulation.svg`: closed-loop cross-track convergence plot
- `dashboard_camera_line.png`: shipped dashboard markup with simulated camera
  tracking state

## Reproduce

```powershell
$env:PYTHONPATH="src/core/control;src/core/core_common;src/core/core_events;src/core/core_features"
python tools/simulate_line_follow.py `
  --output docs/validation/line-follow-modes-2026-09-21
```

On a ROS 2 host with the `control` package installed, the sensing-only observer
can be launched without adding another motion publisher:

```bash
ros2 launch control line_follow.launch.py namespace:=rosy_01 \
  start_camera:=true start_ir_adc:=true
```

Before selecting `IR_LINE`, set `ir_calibration_enabled: true` only after
measuring all six black/white endpoint values in the host-mounted
`deploy/robot/config/line_follow.yaml` (or set `ROSY_LINE_FOLLOW_CONFIG_PATH`
to a robot-specific file). This does not require rebuilding the image.

`CAMERA_LINE` remains fail-closed until the selected backend reports a verified
manual exposure and white-balance lock. The V4L2 fallback checks both control
readbacks after the configured settle interval.

## Not yet proven

This host run does not prove Pinky Pro camera orientation/exposure, physical IR
polarity/endpoints, floor/line materials, ROS DDS timing, wheel response, or
safe driving clearance. Those remain device acceptance gates for the connected
robot.
