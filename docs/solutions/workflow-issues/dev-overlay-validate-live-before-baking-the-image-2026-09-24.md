---
title: Validate a fix live on the device with the dev overlay before re-baking it into the image
date: 2026-09-24
category: workflow-issues
module: deploy/robot/dev/core_dev_overlay.py (real device rosy-pinky-e4us, release 2026.09.24-010)
problem_type: best_practice
component: development_workflow
severity: medium
applies_when:
  - a fix targets something only the real device exposes (UART wiring, console/getty contention, elevated Windows console state, disk identity, first-boot networking)
  - host pytest and CI for the affected area are already green
  - the fix could be baked directly into the next image build without being run against the physical hardware first
tags: [dev-overlay, device-validation, host-tests-insufficient, image-build, pinky-pro, field-testing]
---

# Validate a fix live on the device with the dev overlay before re-baking it into the image

## Context

Bringing up Pinky Pro release `2026.09.24-010` on the real device `rosy-pinky-e4us` surfaced six
real, verified defects in one session — a QuickEdit console freeze in the SD-card writer, an
interrupted write that made a card's identity unrecognizable to itself, a test-only `openssl` PATH
fixup masking a real "not found" failure on operator PCs, a first-boot Wi-Fi path that deleted its
own retry profile on a single failed attempt, a kernel-console/getty conflict that starved the LiDAR
UART, and a dashboard reporting safety/capability state from configuration rather than live
readiness. Host `pytest` and CI were green for all six areas beforehand. None of the six were
visible without running on the physical board: they depend on real Windows console state, a real
interrupted-write disk history, a real operator PC's `PATH`, real Wi-Fi activation timing near a
phone hotspot, real UART wiring contention, and a real hardware-runtime `rosy-io` process — none of
which a host test or CI runner reproduces.

`deploy/robot/dev/core_dev_overlay.py` exists specifically to close this gap: it lets a fix be
applied and exercised live on the running device (reloading units, mounting overlays) before that
fix is folded into the image that future cards are written from.

## Guidance

- For a class of defect that only the physical device can expose (device-specific timing, real
  peripheral contention, a real operator machine's environment, a real interrupted write's on-disk
  state), do not treat a green host-pytest/CI run as sufficient signal that a fix works. Validate it
  live on the device with the dev overlay first.
- Only after the live-device validation confirms the fix, fold it into the artifact that ships to
  new cards — the base image build (`deploy/image/customize-rootfs.sh` and friends) or the writer
  script itself — so every future device gets the fix baked in rather than needing the same retrofit.
- Treat "host tests are green" and "the fix works on the device" as two separate claims that must
  each be established; the first is necessary but never sufficient for defects in this class.

## Why This Matters

This session found six real defects in areas CI and host pytest already called passing. Each defect
would have shipped in the next image build, or blocked the next physical card write, had the live
device not been used to validate first. The dev overlay makes that validation cheap — a fix can be
tried and reverted on the running unit without a full image rebuild — so there is little cost to
doing it before committing a fix to the base image.

## When to Apply

- Any fix under `deploy/robot/`, `deploy/image/`, or `deploy/sd/` that touches device-specific
  environment, timing, or peripheral state.
- Any fix diagnosed from a real-device symptom (a specific error code, a specific timeout, a
  specific journal timestamp) rather than from a host-reproducible test failure.

## Examples

The UART console-contention fix
([ubuntu-console-and-getty-steal-the-lidar-uart-2026-09-24.md](../runtime-errors/ubuntu-console-and-getty-steal-the-lidar-uart-2026-09-24.md))
was applied live via the dev overlay on `rosy-pinky-e4us`, confirmed against real `sllidar` health
output (`SL_RESULT_OPERATION_TIMEOUT` before, `OK` / DenseBoost 10 Hz after), and only then folded
into `configure-uart-pi5.sh` for the base image build.

## Related

- [ubuntu-console-and-getty-steal-the-lidar-uart-2026-09-24.md](../runtime-errors/ubuntu-console-and-getty-steal-the-lidar-uart-2026-09-24.md)
- [호스트 pytest가 초록이어도 Gazebo 인식 경로는 실제로 돌려서 렌더된 값을 재야 한다](sim-perception-green-host-tests-hide-live-gazebo-defects-2026-09-22.md)
