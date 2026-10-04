<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-06 | Updated: 2026-09-06 -->

# safety/ (legacy comparison node and reusable sensing)

## Purpose
The legacy safety velocity gate fuses lidar sectors, US, IR, IMU and camera, applies drive calibration, and publishes comparison-runtime commands. In the Rosy OS target runtime CORE owns final commands (D-38). This node must not publish motor commands beside RosBridge. Hardware deadman behavior requires separate verification.

`SafetyNode(sensor_only=True)` omits command/estop/legacy calibration authority endpoints and returns from tick after sensing. It is an internal constructor mode, not an operational launch selection yet. `sensor_state` alone has no freshness lease; `bind_policy_handoff` supplies the shared observation clocks, revision and available candidate-specific translation/tracking evidence to CORE. Tracking evidence is captured from camera, odom tracks and the same odom→base_link pose; missing evidence fails closed. Never treat it as a complete safety decision.

## Key Files
| File | Description |
|------|-------------|
| `node.py` | SafetyNode(Node, Bumper, Hazard, Gate, Scale), 20 ms tick; latched `/estop/state` (depth 1, RELIABLE, TRANSIENT_LOCAL); dual same-value aliases `/safety/can_reverse` ≡ `/safety/rear_clear` (deprecated pattern, like `/safety/mode`) |
| `bumper.py` | Lidar sector ranges (10th-percentile to kill single-beam spikes), US, rear sectors, full-circle exit judge (best all-around gap) → `/safety/*` range topics incl. `/safety/exit_yaw`/`exit_range` |
| `hazard.py` | ESTOP/CLIFF/TILT/PICK detection: latched e-stop (`/estop`, `/estop/cmd`), `ir_looks_like_cliff` (4095-saturation ignore + hysteresis); on engage zeros commands and cross-publishes `/wander/cmd 'stop'` + `/calib/step 'abort'`
| `gate.py` | The command gate: halt on obstacle/cliff/tilt/pickup/estop/stale>0.5 s, tilt-reverse creep, `cmd_linear_sign` flip, re-publishes last raw command every 20 ms |
| `scale.py` | Narrow-map auto-cal: corridor width L+R → `map_range`/`open_max` HUD scaling |

## For AI Agents

### Working In This Directory
- SafetyNode is the sole final publisher only in the legacy comparison graph; wander/control publish semantic candidates. The OS target uses CommandManager/RosBridge instead. Do not enable both final publishers.
- Shared semantic command restriction lives in `control/command_gate.py`, without ROS. Keep sensor geometry, evidence freshness, calibrated sweep checks and drive-sign conversion distinct; this function alone does not prove a safe motor command.
- Legacy tilt reverse synthesis is explicitly opted into by SafetyNode. A CORE safety evaluator may restrict a selected candidate, but recovery must submit a separate candidate through CORE arbitration.
- Hazard *detection* lives here; hazard *response policy* lives in `control/recover.hazard_action` — don't duplicate.
- The e-stop chain crosses nodes by design (engage → wander stop + calib abort); keep it intact when touching `hazard.py`.
- Latched QoS (TRANSIENT_LOCAL depth 1) is required on `/estop/state` so late joiners see the latch.

### Testing Requirements
- `python3 -m pytest test/test_command_gate.py test/test_configured_operation.py test/test_scale.py -q` covers semantic restrictions and their node adapter. Sensor geometry and physical stopping still require device acceptance.
- Thresholds come from `config/robot.yaml` + `config/cliff_calib.yaml` (4095 = ADC saturation, never a cliff).

### Common Patterns
- 10th-percentile sector ranges (`scan_pctl`) to kill single-beam spikes; `ignore_m` drops chassis hits.
- Comments cite measured hardware limits (lidar 5 cm min, US 2 cm blind zone).

## Dependencies

### Internal
- Publishes the `/safety/*` vocabulary wander consumes (`control/` policies make decisions from it).
- Cross-publishes `/wander/cmd`, `/calib/step` on e-stop.

### External
- `rclpy.qos` (latched), `sensor_msgs` LaserScan/Range/Imu.

<!-- MANUAL: -->
