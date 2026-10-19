# `control` inside ROSY Platform

This is the absorbed ROS 2 distribution in `middleware/perception`. It installs
reusable sensing, OpenCV preprocessing, calibration records, planning, and
safety evidence. `core` owns the external API, the policy consumer, and
the only final `cmd_vel` publisher. The old standalone Control checkout is not
a runtime dependency.

| Source holder | Preserved Python identity |
|---|---|
| `sensors/sensing` | `control.sensing` |
| `front_camera/perception` | `control.sensing.perception`, including drivable/learned backends |
| `../drive/{safety,tracking,recovery,calibration}` | `control.control` modules |
| `../drive/planning/grid` | `control.planning` |
| `../drive/motion_limits/adapter` | `control.safety` |
| `../drive/tracking/wander` | `control.wander` |

`control/` retains provider and ROS composition plus source compatibility
facades. `setup.py` installs each old import once; only `control.control`
combines modules from several holders. Its sdist snapshots the declared Drive
sources internally so it can build without the repository. ROS package name,
console scripts and `share/control/{config,launch,map,web}` remain the same.

## Canonical development checks

Run pytest through the remote runner from the repository root (D-584):

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<session>" -- middleware/perception/test/
python test/known_failures.py "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<session>/run-1.txt"
```

Build in a ROS 2 Jazzy environment:

```bash
source /opt/ros/jazzy/setup.bash
cd /opt/rosy
colcon build --merge-install --base-paths $(python3 tools/harness/colcon_roots.py)
source install/setup.bash
```

A passing host test or build proves only the checks actually executed.
It does not prove a Device install, sensor capture, motor motion, payload
handling, or Pinky Pro arm operation.

## Device flow

The supported Device baseline is Ubuntu Server 24.04 arm64 with the signed
ROSY Platform release installed at `/opt/rosy`:

```bash
cd /opt/rosy/deploy/robot/pinky_pro
sudo ROSY_ROBOT_NUMBER=1 bash ./install-pi.sh
sudo ./verify-pi.sh
sudo ./runtime-mode.sh up
sudo ./device-readback.sh --json
```

The installer derives `ROS_DOMAIN_ID` and `ROSY_NAMESPACE` from the robot
number. Do not write identity values into `.env` by hand. Keep the `core`
profile stationary until readback proves the identity, active generation,
immutable image digest, systemd/core health, ROS graph health, and exactly one
final `cmd_vel` publisher. Enable `motor` or `hardware` only after that gate.

## Package boundaries

- `control`, `planning`, and `sensing` contain ROS-free decisions and
  deterministic tests.
- `safety` may run as a sensor-only worker owned by CORE. It must not create a
  second command, raw-command, e-stop, or final-decision authority.
- `camera_detect_node` publishes camera evidence and `camera/telemetry`; the
  current worker is preprocessing only, not semantic box or grasp detection.
- Calibration is context-bound to Device identity, generation, schema, and
  digest. A mismatch fails closed before a worker is created.
- Legacy launch and console entry points remain for parity tests only. Never
  start their final publisher beside `core`.

## Promotion gates

Record source, local, and ROS-simulation evidence separately from artifact,
Device, and FIELD evidence. Promote in this order:

1. Signed ARM64 artifact and manifest verification.
2. Pi installation, identity verification, and JSON readback.
3. Stationary CORE graph and sensor-only calibration/readback.
4. Camera/OpenCV frame quality and timing on the real Pi.
5. Motor UART, deadman, e-stop, stale-input, and stop-distance trials.
6. Nav2/Control backend acceptance and box/pallet placement trials.
7. OMX model, mount, power, hand-eye, collision interlock, grasp/release, and
   recovery trials.

Any failed gate keeps the last known-good generation active and leaves later
capabilities disabled. Historical standalone Control instructions are kept in
the workspace archive and are not part of the Rosy OS install path.
