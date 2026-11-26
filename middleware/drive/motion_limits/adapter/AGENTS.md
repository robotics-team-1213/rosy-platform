<!-- Parent: ../AGENTS.md -->

# safety/ (legacy comparison node and reusable sensing)

**Parent context:** `../AGENTS.md`

## Purpose
The legacy safety velocity gate fuses lidar sectors, US, IR, IMU and camera, applies drive calibration, and publishes comparison-runtime commands. In the Rosy OS target CORE owns final commands (D-38); this node must not publish motor commands beside RosBridge. Hardware deadman behavior requires separate verification.

`SafetyNode(sensor_only=True)` omits command/estop/legacy calibration authority endpoints and returns from tick after sensing. It is an internal constructor mode, not an operational launch selection. `sensor_state` alone has no freshness lease; `bind_policy_handoff` supplies shared observation clocks, revision and candidate-specific translation/tracking evidence (camera, odom tracks, same odom→base_link pose) to CORE. Missing evidence fails closed. Never treat it as a complete safety decision.

Modules: `node.py` (SafetyNode(Node, Bumper, Hazard, Gate, Scale), 20 ms tick), `bumper.py`, `hazard.py`, `gate.py`, `scale.py`, `ros_edges.py` (`RosEdges`, D-171/D-766).

## For AI Agents

### Working In This Directory
- SafetyNode is the sole final publisher only in the legacy comparison graph; wander/control publish semantic candidates. The OS target uses CommandManager/RosBridge. Do not enable both final publishers.
- Shared semantic command restriction lives in `control/command_gate.py`, without ROS. Keep sensor geometry, evidence freshness, calibrated sweep checks and drive-sign conversion distinct; this function alone does not prove a safe motor command.
- Tilt-reverse synthesis is explicitly opted into by SafetyNode. A CORE safety evaluator may restrict a selected candidate, but recovery must submit a separate candidate through CORE arbitration.
- Hazard *detection* lives here; hazard *response policy* lives in `control/recover.hazard_action` — don't duplicate.
- The e-stop chain crosses nodes by design (engage zeros commands, cross-publishes `/wander/cmd 'stop'` and `/calib/step 'abort'`); keep it intact when touching `hazard.py`.
- `/estop/state` needs latched QoS (depth 1, RELIABLE, TRANSIENT_LOCAL) so late joiners see the latch.
- `publish_heard` and `publish_float` skip the publish while `get_subscription_count()==0`. Only diagnostic/wander topics may use them; stop inputs (`min_range`, `us_range`, `rear_range`, `cliff`, `blocked`, ...) publish every tick.
- The gate halts on obstacle/cliff/tilt/pickup/estop/stale > 0.5 s and re-publishes the last raw command every 20 ms. `ir_looks_like_cliff` ignores 4095 (ADC saturation, never a cliff) with hysteresis.
- D-171 track 1: `bumper.py`, `hazard.py`, `gate.py`, `scale.py`, `obstacles.py` import no ROS; `node.py` (via `ros_edges.py`) builds every message, TF lookup and parameter write for them. `evidence.py` still builds `String` itself (`KNOWN_ROS_LEAKS`).
- Sector ranges use the 10th percentile (`scan_pctl`) against single-beam spikes; `ignore_m` drops chassis hits. Thresholds come from `config/robot.yaml` + `config/cliff_calib.yaml`. Comments cite measured limits (lidar 5 cm min, US 2 cm blind zone).

### Testing Requirements
- `python3 -m pytest test/test_command_gate.py test/test_configured_operation.py test/test_scale.py -q` covers semantic restrictions and the node adapter. Sensor geometry and physical stopping still require device acceptance.

<!-- MANUAL: -->
