---
title: Ubuntu's stock kernel console and serial-getty hold the RPLIDAR C1's UART on a Raspberry Pi 5
date: 2026-09-24
category: runtime-errors
module: deploy/robot/configure-uart-pi5.sh (LiDAR driver, Pi 5, Pinky Pro real device rosy-pinky-e4us)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "sllidar returned SL_RESULT_OPERATION_TIMEOUT against the RPLIDAR C1 on first boot of the hardware-runtime image"
  - "stopping serial-getty@ttyAMA0 changed the failure to 0x80008004 instead of fixing it, because the kernel console was still writing to the port"
  - "health went OK with DenseBoost at 10 Hz only after removing the console entry from cmdline.txt and rebooting"
tags: [lidar, uart, raspberry-pi-5, ubuntu, serial-console, getty, sllidar, base-image]
root_cause: config_error
resolution_type: code_fix
severity: high
---

# Ubuntu's stock kernel console and serial-getty hold the RPLIDAR C1's UART on a Raspberry Pi 5

## Problem

Stock Ubuntu's Raspberry Pi `cmdline.txt` ships `console=serial0,115200`. With `enable_uart=1` set
(required for the robot's UART hardware), `serial0` resolves to `ttyAMA0` on a Pi 5 — the same UART
the RPLIDAR C1 is wired to. Two things held that port before `sllidar_node` could use it: the kernel
console itself (writing boot/kernel messages to the port), and `serial-getty@ttyAMA0` (agetty,
waiting for a login on that port). `sllidar_node` failed with `SL_RESULT_OPERATION_TIMEOUT`.
Stopping only the getty service did not fix it — the kernel console was still an independent writer
to the port, and the failure just changed shape (`0x80008004`). Only removing the `console=` entry
from `cmdline.txt` and rebooting, so the kernel stopped treating the UART as a console at all,
cleared the port.

## Symptoms

- `sllidar_node` health check: `SL_RESULT_OPERATION_TIMEOUT` against `/dev/ttyAMA0` on first hardware
  boot.
- After `systemctl stop serial-getty@ttyAMA0`: a different failure, `0x80008004`, because the kernel
  console was still writing to the port.
- After removing `console=serial0,115200` (or the resolved `ttyAMA0` equivalent) from
  `cmdline.txt` and rebooting: health OK, DenseBoost scan rate 10 Hz.

## What Didn't Work

- Stopping the getty alone. It removes one writer (agetty) but not the other (the kernel console),
  so the port is still contended.

## Solution

`deploy/robot/configure-uart-pi5.sh` isolates every UART bus the robot uses — LiDAR (`ttyAMA0`) and
motor (`ttyAMA4`) — from both the kernel console and any serial getty, on both a running device and
a mounted image being baked (`--image-root`, used from `deploy/image/customize-rootfs.sh`, D-192):

```bash
# Ubuntu's raspi cmdline.txt ships console=serial0,115200. With enable_uart=1
# serial0 is UART0 on the Pi 5, so the kernel console and serial-getty@ttyAMA0
# (agetty) hold the RPLIDAR C1 port and sllidar_node times out
# (rosy-pinky-e4us, 2026-09-24). The debug UART (ttyAMA10) is not touched.
CMDLINE_FILE="$(dirname "$CONFIG_FILE")/cmdline.txt"
CONSOLE_PATTERN='^console=(serial0|ttyAMA0|ttyAMA4)(,|$)'
MASKED_GETTYS=("serial-getty@ttyAMA0.service" "serial-getty@ttyAMA4.service")
```

The script strips any `console=` token matching the LiDAR or motor UARTs from `cmdline.txt` and
masks the matching `serial-getty@*` units, while leaving the debug UART (`ttyAMA10`) untouched. This
branch (`fix/lidar-uart-console`, PR #39, open) is being folded into the base image build so a fresh
image boots with both buses already isolated, rather than requiring the retrofit step on every
device.

## Why This Works

A UART port can be claimed by more than one Linux subsystem at once — the kernel console driver and
a getty are two independent, unrelated consumers of the same device node. Removing only one leaves
the other still able to write to (and thus interfere with) the port. Removing the port from
`cmdline.txt`'s console list stops the kernel from treating it as a console entirely, and masking the
getty stops a login prompt from being spawned on it — together they leave the UART free for
`sllidar_node` to own exclusively.

## Prevention

- When adopting a base image (here: stock Ubuntu for Raspberry Pi) for a robot with dedicated UART
  hardware, audit every UART the robot uses against that image's default `cmdline.txt` console
  entries and `serial-getty@*` units — not just the ones a driver's own troubleshooting guide
  mentions.
- This class of contention is invisible to host tests and CI: it only appears on the actual UART
  wiring of the actual board. Validating fixes like this one against the real device before folding
  them into the base image found this together with five other defects in the same 2026-09-24
  session that host pytest and CI had all reported green — see
  [dev-overlay-validate-live-before-baking-the-image-2026-09-24.md](../workflow-issues/dev-overlay-validate-live-before-baking-the-image-2026-09-24.md).

## Related Issues

- [OpenCV 4.6의 bare aruco.DetectorParameters()는 널 포인터라 필드 하나만 써도 import에서 segfault가 난다](opencv-4-6-aruco-detector-parameters-segfault-2026-09-24.md)
- [dev-overlay-validate-live-before-baking-the-image-2026-09-24.md](../workflow-issues/dev-overlay-validate-live-before-baking-the-image-2026-09-24.md)
