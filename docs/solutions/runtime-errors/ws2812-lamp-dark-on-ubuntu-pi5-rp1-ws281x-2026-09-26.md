---
title: The Pinky Pro WS2812 lamp stays dark on the Ubuntu Pi 5 image until five separate rp1_ws281x problems are fixed
date: 2026-09-26
category: runtime-errors
module: deploy/image (lamp driver, Pi 5, Pinky Pro real device rosy-pinky-e4us)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "lamp_control and a bench ws2811 test had no /dev/ws281x_pwm to open on the native image"
  - "the vendor rp1_ws281x_pwm module failed to compile against linux-headers 6.8.0-1064-raspi (incompatible-pointer-types on .remove)"
  - "ws2811_init returned 'Hardware revision is not supported' on board revision 0xd04171"
  - "after the module loaded and ws2811_render returned success for every frame, the lamp still stayed dark"
tags: [ws2812, ws281x, lamp, rp1, pwm, raspberry-pi-5, ubuntu, device-tree, kernel-module, pinky-pro]
root_cause: incomplete_setup
resolution_type: environment_setup
severity: medium
---

# The Pinky Pro WS2812 lamp stays dark on the Ubuntu Pi 5 image until five separate rp1_ws281x problems are fixed

## Problem

The Pinky Pro lamp is 8 WS2812 LEDs (GBR order) on GPIO19. On a Pi 5 the pinned
`rpi_ws281x` library (the upstream snapshot pinned as `rpi_ws281x_commit` in `deploy/image/inputs.lock.yaml`) does not drive
the pin itself. It writes pixel data to `/dev/ws281x_pwm`, which the out-of-tree kernel
module `rp1_ws281x_pwm` provides, and the module sends that data through RP1 PWM0 and DMA.
The vendor image shipped that module and a runtime overlay. Our Ubuntu native image
(kernel `6.8.0-1064-raspi`) ships neither, so the lamp could not be driven at all.

## Symptoms

- `/dev/ws281x_pwm` was absent. The D-247 probe reported the lamp as `driver_missing`.
- The module did not build against 6.8 headers.
- `ws2811_init` rejected the board as an unsupported hardware revision.
- The worst one: the module loaded, the pin mux read `alt3 (pwm0)`, every
  `ws2811_render` returned `WS2811_SUCCESS`, and the lamp stayed dark. Only a person
  looking at the robot noticed.

## What Didn't Work

- **Runtime `dtoverlay`.** It fails on this Ubuntu raspi kernel with "no matching
  platform found". The camera and IMU overlays fail the same way. Overlays have to go
  into `config.txt`, followed by a reboot.
- **The vendor overlay as-is.** It targets `/axi/pcie@1000120000/rp1`. On this kernel the
  node is `/axi/pcie@120000/rp1`, so the fragment never applies.
- **Treating a clean render as proof.** Every call succeeded while the data went out on
  the wrong pin (see cause 5).

## Solution

All five fixes were needed. They were verified on `rosy_18` on 2026-09-26, and a person
watched the lamp go white, red, green, then blue.

1. **Build the module for the image kernel.** Install `linux-headers-<kver>` and `make`,
   then run `make -C /lib/modules/<kver>/build M=rp1_ws281x_pwm modules`. On kernels older
   than 6.11 the platform driver's remove callback must be `.remove_new`. The upstream
   code uses the newer `void` form:
   ```c
   .probe = rp1_ws281x_pwm_probe,
   .remove_new = rp1_ws281x_pwm_remove,   /* was .remove = ... */
   ```
   Install the `.ko` under `/lib/modules/<kver>/extra` and run `depmod`. It then loads
   automatically from its OF alias `rp1-ws281x-pwm`.
2. **Use an overlay retargeted to this kernel's RP1 path, with the GPIO19 pin mux.**
   Install it as `/boot/firmware/overlays/rosy-ws281x.dtbo` and add `dtoverlay=rosy-ws281x`
   to `config.txt`:
   ```dts
   fragment@0 { target = <&rp1_gpio>; __overlay__ {
       rosy_ws281x_pins: rosy_ws281x_pins { function = "pwm0"; pins = "gpio19"; bias-disable; }; }; };
   fragment@1 { target-path = "/axi/pcie@120000/rp1"; __overlay__ { ...
       ws281x_pwm@98000 { compatible = "rp1-ws281x-pwm"; ... dmas = <&rp1_dma 0x18>;
           pinctrl-names = "default"; pinctrl-0 = <&rosy_ws281x_pins>; status = "okay"; }; }; };
   ```
3. **Add a udev rule for the device node:**
   `SUBSYSTEM=="misc", KERNEL=="ws281x_pwm", GROUP="gpio", MODE="0660"`.
4. **Add the Pi 5 rev 1.1 board ids to `rpihw.c`.** The pinned table stops at `0xd04170`.
   This board reports `0xd04171` in `/proc/device-tree/system/linux,revision`. Adding
   `0xd04171`, `0xc04171` and `0xb04171` as `RPI_HWVER_TYPE_PI5` fixes `ws2811_init`.
   `lamp_control` links `rpi_ws281x` statically, so the image build must apply the same
   patch. Otherwise the shipped node fails the same way.
5. **Select PWM channel 3.** The module has `static int pwm_channel = 2;`, which is a
   `module_param`. PWM0 channel 2 is GPIO18, the LCD backlight. GPIO19 is channel 3.
   Install `/etc/modprobe.d/rosy-ws281x.conf` with:
   ```
   options rp1_ws281x_pwm pwm_channel=3
   ```
   `/sys/module/rp1_ws281x_pwm/parameters/pwm_channel` should then read `3`. This was the
   fix that made the lamp light.

## Why This Works

The library reaches the LEDs through four layers: board detection, the kernel module,
the device tree, and the PWM channel. Each layer fails differently.
- Board detection fails loudly.
- The kernel build fails loudly.
- A device-tree path that does not match fails silently: the node is simply never
  created.
- A wrong channel fails completely silently. The PWM block clocks correct WS2812 data
  out of a pin that is not wired to the lamp. Nothing in software can tell the
  difference.

## Prevention

- For any light or sound, the check a person does ("did you see it?") is the result.
  A clean return code is not. D-247 decision 6 exists for this reason.
- When vendoring a Pi overlay, compare every `target-path` against `/proc/device-tree`
  on the target kernel. Pi OS and Ubuntu name the RP1 PCIe node differently.
- When porting a vendor driver, read its `module_param` defaults. The vendor setup
  passed `pwm_channel` in a place we did not copy.

## Related Issues

- ADR D-247 (device card, slice 2), D-169 (the lamp stays bench-only), D-165 (pinned
  hardware dependencies)
- [ubuntu-console-and-getty-steal-the-lidar-uart-2026-09-24.md](ubuntu-console-and-getty-steal-the-lidar-uart-2026-09-24.md):
  another case where a Pi OS assumption breaks on the Ubuntu image
