# `control` inside Rosy OS

This is the absorbed ROS 2 package in `Rosy OS/src/control`. It owns
reusable sensing, OpenCV preprocessing, calibration records, planning, and
safety evidence. `core` owns the external API, the policy consumer, and
the only final `cmd_vel` publisher. The old standalone Control checkout is not
a runtime dependency.

## Canonical development checks

Run the package and CORE tests from the Rosy OS repository root. The source
tree is not installed on a plain host, so include both package roots when
running without a colcon overlay:

```bash
PYTHONPATH=src/control:src python3 -m pytest src/control/test/ -q
PYTHONPATH=src/core:src/control:src python3 -m pytest src/core/test/ -q
```

On PowerShell, use `$env:PYTHONPATH="$PWD/src/core;$PWD/src/control;$PWD/src"`
before the CORE command (and omit the first entry for the Control-only
command). A sourced colcon install overlay provides the same imports.

Build in a ROS 2 Jazzy environment:

```bash
source /opt/ros/jazzy/setup.bash
cd /opt/rosy
colcon build --merge-install --packages-up-to core pinky_pro
source install/setup.bash
```

A passing host test or build proves source and ROS-simulation behavior only.
It does not prove a Device install, sensor capture, motor motion, payload
handling, or Pinky Pro arm operation.

## Device flow

The supported Device baseline is Raspberry Pi OS Lite 64-bit with the signed
Rosy OS release installed at `/opt/rosy`:

```bash
cd /opt/rosy/deploy/robot
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
