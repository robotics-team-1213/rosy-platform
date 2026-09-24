# control inside Rosy OS

This is the absorbed ROS 2 package under `Rosy OS/src/control`.
It supplies reusable sensing, OpenCV preprocessing, calibration, planning,
and safety evidence. `core` owns the external API, policy consumer, and
only final `cmd_vel` publisher. The old standalone Control checkout is not a
runtime dependency.

## Canonical development commands

Run pure logic and package tests from the Rosy OS repository root. For a
source-only host, expose the package roots explicitly:

```bash
PYTHONPATH=src/control:src python3 -m pytest src/control/test/ -q
PYTHONPATH=src/core:src/control:src python3 -m pytest src/core/test/ -q
```

PowerShell equivalent: set `$env:PYTHONPATH` to the semicolon-separated
`src/core;src/control;src` paths before the CORE command. A sourced
colcon install overlay provides these imports as well.

Build the package in a ROS 2 Jazzy environment:

```bash
source /opt/ros/jazzy/setup.bash
cd /opt/rosy
colcon build --merge-install --packages-up-to core
source install/setup.bash
```

The ROS graph and physical acceptance checks are separate. A host test or a
successful build does not prove a Device install, sensor capture, motor motion,
or Pinky Pro arm operation.

## Canonical Device flow

The Device is Raspberry Pi OS Lite 64-bit with the Rosy OS release installed at
`/opt/rosy`. Keep the runtime stationary while installing and reading back the
identity and release evidence:

```bash
cd /opt/rosy/deploy/robot
sudo ROSY_ROBOT_NUMBER=1 bash ./install-pi.sh
sudo ./verify-pi.sh
sudo ./runtime-mode.sh up
sudo ./device-readback.sh --json
```

`install-pi.sh` owns `ROS_DOMAIN_ID` and `ROSY_NAMESPACE` derivation. Do not
write identity values into `.env` by hand. Enable `motor` or `hardware` only
after the stationary core, immutable image digest, ROS graph, and single
publisher checks are GO. Enable calibration and camera profiles only after the
matching generation and sensor readback are retained.

## Package boundaries

- `control/control`, `planning`, and `sensing` contain ROS-free decisions
  and deterministic tests.
- `control/safety` can run as a sensor-only worker owned by CORE. It must
  not create a second command, raw-command, e-stop, or final decision authority.
- `camera_detect_node` publishes camera evidence and `camera/telemetry`; it is
  not a cliff detector or a grasp planner.
- `core` binds accepted evidence to the policy and publishes the final
  command. The Device Compose profiles keep core, motor, and hardware access
  separate.
- Legacy `control` launch and console entry points remain only for parity
  tests. Never start the legacy final publisher beside `core`.

## Evidence gates

Record source/local/ROS-simulation results separately from artifact, Device, and
FIELD results. The current software suites are local evidence. ARM64 image
publication, Pi readback, CSI timing, motor deadman, box/pallet handling, and
OMX model/mount/interlock acceptance each require their own evidence record.

Historical standalone Control instructions are preserved in the workspace
archive; they are not part of the Rosy OS install path.
