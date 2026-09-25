# Rosy OS ARM64 build notes

This is the current Raspberry Pi 5 boundary for Rosy OS. The host is Raspberry
Pi OS Lite 64-bit; the ROS 2 Jazzy userland is built and run in the containers
defined by `deploy/robot/compose.yaml`.

## Source and container builds

For a development workspace, build the ROS packages from the repository root:

```bash
cd src
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
```

For the device image, build from `deploy/robot` after creating the installer
managed `.env`:

```bash
cd deploy/robot
docker compose --env-file .env build rosy-core
docker compose --env-file .env --profile motor build rosy-motor
docker compose --env-file .env --profile hardware build rosy-io
```

The image targets are intentionally separate. `rosy-core` owns the FastAPI and
`rclpy` middleware; `rosy-motor` is a motor commissioning path; `rosy-io` is the
full Pinky Pro motor, LiDAR, and Nav2 adapter path. Use `runtime-mode.sh` to
select a mode rather than starting containers by hand.

## Current package boundary

The absorbed `src/runtime/sensing` package is part of the Rosy OS source tree and
is covered by the host and ROS graph tests. Its pure sensing, OpenCV, planning,
calibration, and safety-policy code is reusable from the workspace. D-66 keeps
it out of the `rosy-core` image; the opt-in sensor adapter is fail-closed
without the Control slice. The legacy full-stack launch is still not an
operational Compose mode. Do not enable that launch beside CORE because it can publish a
competing final `cmd_vel`. Camera/Picamera2 access and hardware launch wiring
remain separate transition gates.

The wiringPi/ws2811 based IMU, ADC, LCD, LED, and lamp drivers also remain
outside the first accepted device image until their Pi 5 compatibility and
physical tests pass. Their source packages may still be built in a workspace
where the required hardware dependencies are installed.

## ARM64 acceptance boundary

An ARM64 build is a build result only. Release acceptance additionally needs
the immutable image digest, Pi install/readback, runtime health, ROS graph and
deadman checks, and the physical Pinky Pro checklist in
`docs/deployment/pi5-acceptance-checklist.md`. Camera/OpenCV capture and any
OMX arm are separate hardware gates; this note does not advertise either as
ready.

The old upstream clone-and-delete instructions are retained in
`legacy-arm64-guide.md` for provenance only and must not be used for a Rosy OS
deployment.

## Native unsigned payload workflow (D-145)

Use the manual `Build native ARM64 unsigned payload` GitHub workflow when a
separate native ARM64 build host is unavailable. Supply a release ID and the
ID of the offline key that will later sign the bundle. The default ROS base is
the digest-pinned multi-platform manifest already recorded below.

The workflow runs `arm64_release_builder.py` on `ubuntu-24.04-arm`, packages
the two OCI archives, runtime files, unsigned manifest, and builder JSON, then
uploads an archive plus SHA-256 for seven days. Download and verify that
checksum before importing the payload into the offline signing environment.
Use `import_unsigned_payload.py` rather than extracting it manually. The
importer checks the canonical archive identity, checksum, member paths and
types, expanded-size limits, builder/manifest/provenance agreement, every
declared payload hash, and both nested Docker configs as `linux/arm64` before
atomically exposing the output directory.

This artifact is deliberately named `unsigned`. It does not satisfy ARTIFACT
or G0 by itself, and the workflow has no secret or release-write permission.
Only the separate offline signing and publication verification path may turn
it into a release bundle.

## 2026-09-13 builder verification

Docker Desktop `desktop-linux` reports `linux/arm64`. The first real execution
probe and a clean `f0ba2cf` build failed with `exec format error`, which exposed
that the builder had no registered ARM64 emulator. Installing the `arm64`
binfmt handler and rerunning the probe produced `aarch64`.

The clean `ac81f2f` workspace then built
`rosy-core:arm64-validation-ac81f2f` successfully for `linux/arm64`:

```text
image ID: sha256:8aea3a0eaf9b20e0af27e70acc1e923c1830ac0577c2191a4ad9955637c02bd5
architecture: arm64
os: linux
```

The image entrypoint sources both ROS Jazzy and the Rosy workspace; through
that supported path, `python3` imported `rclpy`, OpenCV `4.6.0`, `rosy_core`,
and `rosy_control` and reported `aarch64`. A direct `--entrypoint python3`
probe is invalid because it bypasses the ROS environment setup.

This is a reproducible Core image candidate, not a release artifact. Keep
ARTIFACT at `HOLD` until the `io` image, manifest, signing, registry digest,
Pi install/readback, and physical checklist gates also pass.

The same clean workspace also built
`rosy-io:arm64-validation-ac81f2f` successfully. Its image ID is
`sha256:fcee5a58f657460f6b470cde94ada9c13692a48d38df4be51ec0083caa1f0622`
(`arm64/linux`, approximately 3.50 GB). The supported entrypoint path
registered `rclpy`, `sllidar_ros2`, and `rosy_bringup`; Python imported
OpenCV `4.6.0`, `serial`, and `dynamixel_sdk`; and both
`rosy_bringup/bringup_robot.launch.py --show-args` and
`rosy_navigation/hardware.launch.py --show-args` resolved successfully.

The IO image includes the full Nav2/LiDAR userland, but these checks do not
claim serial-device access, motor movement, map availability, or camera
capture. Those remain Device/FIELD gates.

Do not reuse the `ac81f2f` core/io IDs as D-66 evidence. That core image
ships OpenCV and `rosy_control`.

## 2026-09-17 D-66 QEMU HOLD

Host: Docker Desktop 29.7.2 builder `desktop-linux`, binfmt `aarch64` via
`tonistiigi/binfmt`. Source: `4fb2874` plus Dockerfile workarounds on
`chore/public-release-prep`. Tag attempted:
`rosy-core:arm64-validation-4fb2874`. **No image loaded. ARTIFACT stays HOLD.**

Hub `ros:jazzy-ros-base` linux/arm64 pushed 2026-09-16
(index `sha256:c3706ef0a0aa45413c07803cf433602f543b22e45b4855f6fca955c2d8ecc4e8`,
arm64 `sha256:064675e31a58565a0eb6e757e20ddf35c9544021869221dd7e5da89f43b13558`)
ships hollow files. AMD64 of the same tag is fine. Ubuntu arm64 `.deb`s are
fine. `docker cp` evidence:

| path | arm64 Hub image |
|---|---|
| `/usr/lib/python3.12/os.py` | 0 bytes (amd64: 39786) |
| `/usr/lib/python3.12/encodings/__init__.py` | 0 bytes (amd64: 5884) |
| `/usr/share/python3` `.py` | 6 zero-byte files (debpython) |
| `/usr/lib/python3/dist-packages` colcon `.py` | 240 zero-byte files |
| `/usr/bin/gcc` | missing |
| `/usr/bin/make` | 0 bytes |
| `/usr/bin/cmake` | real, 10489912 bytes |
| cmake `Modules/*.cmake` | 0 bytes |

Workarounds committed: `restore-hollow-python.sh` skips when no 0-byte `.py`
files exist; otherwise it reinstalls CPython stdlib/minimal first, then
dpkg owners of remaining 0-byte files under `/usr` **and `/opt/ros`**.
`restore-hollow-toolchain.sh` skips when gcc/g++/make and a
`CMakeDetermineCCompiler.cmake` module are present and non-empty. Host
guard: `python -m pytest test/test_restore_hollow.py -q`. `set -eo`
without nounset around `setup.bash`, and `test -d install`. Proven in
one-shot containers: `python3 -c 'print(123)'`, `pip 24.0`, `numpy 1.26.4`,
colcon discovering `rosy_interfaces`. Not proven: a loaded D-66 core image.

QEMU then failed `apt-get` (`Method http has died unexpectedly`) and later
`exec /bin/bash: exec format error` on cached ARM64 layers. Reinstalling
binfmt restores alpine `uname -m = aarch64` but does not stay stable across
long `buildx --platform linux/arm64` runs on this host.

Next ARTIFACT path is a native Pi 5 `linux/arm64` build, or a pinned
pre-2026-09-16 `ros:jazzy-ros-base` arm64 digest. Do not treat this QEMU
session as Device or ARTIFACT GO.

## Compose and installer syntax verification

On 2026-09-13, the deployment shell scripts passed `bash -n` as a complete
set:

```text
C:\Program Files\Git\bin\bash.exe -n deploy/robot/*.sh
=> exit 0
```

With the required identity variables (`ROS_DOMAIN_ID=41`,
`ROSY_NAMESPACE=rosy_01`, `ROSY_ROBOT_NUMBER=1`, and a data generation),
`docker compose -f deploy/robot/compose.yaml config --profiles` reported the
declared `hardware` and `motor` profiles. Rendering both profiles with the
Compose global options (`--profile motor --profile hardware`) resolved all
three services, preserved the identity values, and mapped the configured
devices as `/dev/ttyAMA4 -> /dev/rosy-motor` and `/dev/ttyAMA0 -> /dev/ttyAMA0`.

This is configuration-rendering evidence only. It does not prove that those
device nodes exist on a Pi, that a serial driver opens them, or that a motor,
LiDAR, camera, or OMX arm moves safely.
