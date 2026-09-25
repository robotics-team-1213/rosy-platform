---
name: rosy-hw-bringup
description: Use when bringing up, re-checking, or diagnosing Pinky Pro board devices on a Rosy robot — ADC/battery/IR/ultrasonic reads 4095 or times out, BNO055 IMU shows zero acceleration or /dev/i2c-0 is missing, camera probe fails with -121, LiDAR or odometry seems dead, the WS2812 lamp stays dark, the buzzer is silent, rosy-hw-probe or the dashboard device card says needs_human/no_response, or wheels must be enabled for a drive test.
---

# Pinky Pro hardware bring-up and diagnosis

## Overview

Two rules decide most outcomes:

1. **Read, don't poke.** Known addresses only, one bus timeout ends that bus, never
   change a device mode to "see more". `rosy-hw-probe` already implements this (D-247).
2. **Light and sound are judged by a person, not a return code.** A clean
   `ws2811_render` once drove the wrong pin for hours. Ask; confirm they acted.

Get onto the robot first with **rosy-device-access** (key-only `rosy@<robot-ip>`, `sudo -n`).

## First look

```bash
rssh 'sudo -n rosy-hw-probe --stdout' | python -m json.tool   # full observation, prints only
rssh 'sudo -n cat /run/rosy-boot/hardware.json'              # last boot/refresh result
```

States: `ok`, `no_response`, `bus_missing`, `driver_missing`, `needs_human`, `not_measured`
(another unit holds the bus — while `rosy-io` runs, judge LiDAR/motors/ADC by topic rates).
The device list and pins are in `deploy/robot/config/board.yaml`.

## Per-device judgement

| Device | Bus | Judge by | Trap |
|---|---|---|---|
| ADC MCU | `/dev/i2c-1` 0x08 | write register, wait ~6 ms, read 2 bytes, `raw = (d0<<4) + (d1>>4)`. Registers: battery 0xF8, IR0 0x88, IR1 0xC8, IR2 0x98, ultrasonic 0xD8. Battery V = raw/4096×4.096/(13/28), 6.0–8.8 V | Hold the D-192 `flock` on the bus fd (boot display shares it). **4095 on IR/ultrasonic = nothing detected**, not a fault. Every read times out + `i2c_designware ... controller timed out` = MCU wedged: **full battery power cycle**; a Pi reboot does not clear it |
| IMU BNO055 | `/dev/i2c-0` 0x28 | chip id reg 0x00 = `0xA0`, SYS_STATUS 0x39, SYS_ERR 0x3A = 0 | After power-on it is in CONFIG mode with **zero accel — normal**. Never write the mode. No `/dev/i2c-0` = missing `dtoverlay=i2c0-pi5,pins_0_1` in `config.txt` |
| Camera OV5647 | CSI | kernel probe line in `dmesg`, CSI node `status` | `failed with error -121` on the used port = I2C NACK = **hardware** (cable, connector, sensor). No image or overlay change fixes it. An empty second port answering -121 is fine |
| LiDAR C1 | `/dev/ttyAMA0` | `ros2 topic hz /<ns>/scan` ≈ 10 Hz | Timeout/`0x80008004` = console or getty on the UART (see solutions doc) |
| Motors XL330 ×2 | `/dev/rosy-motor` | `odom`, `joint_states` ≈ 30 Hz; torque-free ping only while `rosy-io` is stopped | — |
| Lamp WS2812 ×8 | GPIO19, RP1 PWM0 ch 3 | a person sees it | `/dev/ws281x_pwm` missing = module not built/loaded. Needs all five fixes incl. `options rp1_ws281x_pwm pwm_channel=3` (default 2 is GPIO18, the LCD backlight) |
| Buzzer | **BCM 4** on the Pro | a person hears it | BCM 22 is the sibling boards' pin. Enable via `ROSY_BUZZER_ENABLED=true`, `ROSY_BUZZER_PIN=4` in `/etc/rosy/boot-display.env` |

Topic rates need the runtime environment:

```bash
rssh 'sudo -n bash -c "set -a; . /etc/rosy/runtime.env; set +a; . /opt/ros/jazzy/setup.bash; . /opt/rosy/current/install/setup.bash; timeout 8 ros2 topic hz /\$ROSY_NAMESPACE/scan"'
```

Runtime `dtoverlay` fails on the Ubuntu raspi kernel ("no matching platform found"). Every
overlay goes in `/boot/firmware/config.txt`, then reboot and check `boot_id`.

## Human-in-the-loop confirmation

For light, sound, "does it detect my hand", or which pin a part is on:

1. Tell the person exactly what will happen and when; ask with **AskUserQuestion** (fixed
   options such as "saw white / saw nothing / not at the robot"), never a free-text guess.
2. For sensors, sample over a window **while** the person acts, then ask whether they did.
   A flat 4095 window with nobody's hand in front proves nothing.
3. Finding an unknown pin: **pitch-coded bisection.** Play half the candidates at 500 Hz,
   pause, the other half at 3000 Hz; ask "low or high?". Halve again. Counting "which beep
   number" fails — people lose count.
4. Record who confirmed what and when. No confirmation = the state stays `needs_human`.

## Motor-mode promotion (native)

Only when the task asks for driving, with the **wheels lifted** and the person at the
robot confirming it (AskUserQuestion).

```bash
rssh 'sudo -n cp -a /etc/rosy/runtime.env /etc/rosy/runtime.env.bak-$(date +%s)'
rssh "sudo -n sed -i -e '/^ROSY_IO_DRIVE_ENABLED=/d' -e 's/^ROSY_RUNTIME_MODE=.*/ROSY_RUNTIME_MODE=motor/' /etc/rosy/runtime.env && echo ROSY_IO_DRIVE_ENABLED=true | sudo -n tee -a /etc/rosy/runtime.env >/dev/null"
rssh 'sudo -n grep -E "^ROSY_(RUNTIME_MODE|IO_DRIVE_ENABLED)=" /etc/rosy/runtime.env'   # expect motor / true
rssh 'sudo -n systemctl restart rosy-core && sudo -n systemctl start rosy-io'
```

Check `GET /api/v1/host/commissioning` (`runtime_mode: motor`), `motor/ready` true, then a
short low-speed hold and a deadman stop (0.5 s). Revert: restore the backup, restart
`rosy-core`, stop `rosy-io`. Motors never resume on their own after a revert.

## Never do

- `i2cdetect` / full-bus scans; `I2C_SLAVE_FORCE`; writing BNO055 or ADC registers.
- Reboot the Pi to "fix" the ADC; call the lamp or buzzer working because a call returned 0.
- `dtoverlay -r` without a name; hand-edit the device then forget it (D-190: fixes land in the repo and the image).

## Background

- `docs/solutions/runtime-errors/ws2812-lamp-dark-on-ubuntu-pi5-rp1-ws281x-2026-09-26.md` — the five lamp fixes
- `docs/solutions/workflow-issues/pinky-pro-board-facts-need-a-person-at-the-robot-2026-09-26.md` — buzzer pin, wedged ADC, 4095, BNO055
- `docs/solutions/runtime-errors/ubuntu-console-and-getty-steal-the-lidar-uart-2026-09-24.md` — LiDAR UART
- ADRs D-165 (pinned hardware deps), D-190 (boot display, buzzer), D-192 (hardware runtime, flock, drive flag), D-247 (device card, probe rules), D-260 (status by sound/light/LCD)
- `deploy/robot/native/rosy-hw-probe.py` — the reference implementation of every read above
