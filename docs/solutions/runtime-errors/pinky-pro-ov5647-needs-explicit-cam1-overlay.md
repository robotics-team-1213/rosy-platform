---
title: Pinky Pro OV5647 needs an explicit CAM1 boot overlay on the ROSY SD
date: 2026-09-26
last_updated: 2026-09-26
category: runtime-errors
module: deploy/image and deploy/robot on Pinky Pro
problem_type: runtime_error
component: development_workflow
symptoms:
  - "The ROSY SD booted, but camera_auto_detect=1 left the OV5647 sensor undetected."
  - "The same board and camera captured a JPEG with the supplier SD."
root_cause: config_error
resolution_type: code_fix
severity: medium
tags: [pinky-pro, ov5647, camera, cam1, raspberry-pi-5, ubuntu, device-tree, image]
---

# Pinky Pro OV5647 needs an explicit CAM1 boot overlay on the ROSY SD

## Problem

On a Pinky Pro with a Pi 5 rev d04170, the ROSY SD booted but did not detect its OV5647 camera. The supplier SD captured a real 2592×1944 JPEG on the same board and camera. The difference was the boot camera configuration, not evidence that the camera was disconnected.

## Symptoms

- The original ROSY boot config used `camera_auto_detect=1` without an OV5647 overlay; both CSI interfaces were disabled and the sensor did not answer.
- A bounded CAM0 trial returned kernel probe error `-121`. The supplier SD selected CAM1 with `camera_auto_detect=0` and `dtoverlay=ov5647`.
- After the ROSY SD adopted the CAM1 setting and rebooted, the kernel registered `ov5647 11-0036`, `/dev/video0` appeared, and `rosy-hw-probe` reported the camera as `ok`. A diagnostic capture on that ROSY SD produced a real 2592×1944 JPEG, which was opened and visually checked. See [D-192's dated device addendum](../../adr/D-192-hardware-runtime-in-the-image.md) and [the deploy journal](../../../deploy/logs.md).

## What Didn't Work

- Leaving camera auto detection enabled did not enumerate this OV5647 on the ROSY SD.
- Forcing `dtoverlay=ov5647,cam0` did not work on this board; the CAM0 probe returned `-121`. The original config was restored before the CAM1 trial.
- The second physical Pinky was not a valid proof that the ROSY SD was solely at fault: even its supplier SD failed sensor probe `-121` on both CAM0 and CAM1. That unit still needs a camera ribbon, connector, power, or sensor inspection.
- A successful kernel probe alone was insufficient to prove frame capture. The ROSY SD lacked the PiSP/libcamera camera userspace, so the diagnostic capture temporarily ran the supplier camera userspace and then removed it.

## Solution

Set the boot configuration for this verified OV5647 connection:

```ini
[all]
camera_auto_detect=0
dtoverlay=ov5647
```

`deploy/robot/configure-boot-overlay-pi5.sh:32` now accepts `--disable-camera-auto-detect` only with `dtoverlay=ov5647`, stages and verifies the change, and leaves a matching config unchanged on a second call. `deploy/image/customize-rootfs.sh:347` invokes that helper while creating an image. `deploy/image/verify-mounted-image.py:273` rejects a mounted image without the active CAM1 overlay and disabled auto detection. The focused regression is `test/test_boot_overlay_pi5.py:76`.

The tested ROSY SD was also updated directly and rebooted. This proves the boot setting on that device; it does not mean a new image artifact was built or written to another SD card.

## Why This Works

The explicit overlay selects the sensor on the connection that worked on the same physical unit under the supplier SD. On the ROSY SD, the subsequent reboot changed the result from no sensor to the `ov5647 11-0036` probe and an actual captured frame. The image customizer and mounted-image verifier carry that observed setting into future builds and prevent a silent return to auto detection.

## Prevention

- Compare failing and working SD cards on the **same board and camera**, then test each CSI port separately with a reversible config change. A second robot may have a separate hardware fault.
- Verify kernel sensor registration **and** a real frame. Keep those results distinct from product video publication and dashboard streaming.
- Keep the boot setting in image customization and the matching mounted-image check. A source change alone does not validate an ARM64 image artifact or a newly written card.
- Do not count the diagnostic JPEG as product camera support. It used temporary supplier userspace; the running ROSY SD did not supply PiSP/Picamera2 capture or a product live stream.
- Keep the camera userspace separate from the boot overlay fix. [D-288](../../adr/D-288-pinky-pi5-camera-userspace-in-native-image.md) supersedes D-264's camera-only source-build prohibition and pins the official PiSP/libcamera/rpicam-apps/Picamera2 sources for a future native ARM64 image. The source and host checks pass, but no new ARM64 image or SD capture has yet passed acceptance.

The [2026-09-26 readback](../../validation/pinky-camera-capture-2026-09-26/README.md) shows the same boundary on the running ROSY SD: `ov5647 11-0036` is registered, while `rpicam-still` and Picamera2 are absent and the running CORE API is v1.33. A sensor probe therefore cannot stand in for a product screenshot or video.

## Related Issues

- [Validate on a live device before baking an image](../workflow-issues/dev-overlay-validate-live-before-baking-the-image-2026-09-24.md) describes the wider release workflow.
- [Pi 5 WS2812 boot overlay failure](ws2812-lamp-dark-on-ubuntu-pi5-rp1-ws281x-2026-09-26.md) is another hardware case in which a runtime overlay did not replace a boot config and reboot.
