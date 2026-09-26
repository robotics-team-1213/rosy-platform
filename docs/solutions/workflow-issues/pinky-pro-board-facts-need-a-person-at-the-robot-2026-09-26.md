---
title: Pinky Pro board facts that only a person at the robot could settle — buzzer pin, wedged ADC, idle sensor values
date: 2026-09-26
category: workflow-issues
module: deploy/robot/native (rosy-hw-probe, rosy-boot-display) on Pinky Pro rosy-pinky-e4us
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "bringing up or re-checking a Pinky Pro board over SSH"
  - "a device reads as dead, pinned at full scale, or zero"
  - "a pin is recorded as unconfirmed and a person could still check it"
tags: [pinky-pro, buzzer, gpio, adc, i2c, bno055, human-in-the-loop, bring-up, raspberry-pi-5]
---

# Pinky Pro board facts that only a person at the robot could settle — buzzer pin, wedged ADC, idle sensor values

## Context

We checked rosy_18 remotely on 2026-09-25 and 2026-09-26 (the D-247 device card). Several
readings looked like faults but weren't, one fault looked unfixable but wasn't, and one
recorded "fact" was wrong. Each was settled only when a person at the robot did something
or reported what they heard or saw.

## Guidance

- **The Pro buzzer is BCM 4, not BCM 22.** BCM 22 is what the two sibling boards use and
  what D-190 assumed. It stayed silent at 2 kHz with 50 % duty, and also when held high.
  - We found the pin by splitting the D-190 allowed set
    `{4,5,6,16,17,20,21,23,24,26}` in half each round. One half played a low tone
    (500 Hz) and then the other half a high tone (3000 Hz); the person said "low" or
    "high". Three rounds narrowed it to `{4,5}` and then to 4.
  - Counting "which beep number" failed: the person could not keep count.
  - With `ROSY_BUZZER_ENABLED=true` and `ROSY_BUZZER_PIN=4` in
    `/etc/rosy/boot-display.env`, the normal CORE_READY beep sounds (10 % duty).
- **The ADC MCU on i2c-1 (0x08) can wedge.** When it does, every read times out, the
  kernel logs `i2c_designware ... controller timed out`, and battery/IR/ultrasonic are
  gone.
  - A Pi reboot does not clear it: the Pinky board stays powered.
  - Only a full power cycle with the battery switch clears it.
  - On a dead bus, each address costs about 1 s, so a full scan takes about 2 minutes.
    Probe only the known addresses, and stop the bus at the first timeout.
- **4095 on IR 0–2 and the ultrasonic channel means "nothing detected"**, not a fault. A
  hand moved them (IR about 1900–4095, ultrasonic 56–4095).
  - A sampling window in which nobody put anything in front of the sensors showed a flat
    4095. That proves nothing either way.
  - Ask the person to move a hand during the window, and confirm they did.
- **After power-on the BNO055 is in CONFIG mode and reports zero acceleration.** Judge it
  by chip id `0xA0` and `SYS_ERR`, never by motion values.
  - Its bus `/dev/i2c-0` exists only with `dtoverlay=i2c0-pi5,pins_0_1` in `config.txt`.
  - Runtime `dtoverlay` does not work on the Ubuntu raspi kernel.
- **Don't dev-overlay current `main` CORE onto an older release.** After the D-241–D-243
  source moves, CORE from `main` looks up a `pinky_pro` robot package. Release 012 does
  not ship it, so CORE crash-looped and took the dashboard down until the overlay was
  cleared. Build a release from `main` instead. For UI checks, render the dashboard
  locally with the device's real `hardware.json`.

## Why This Matters

Each of these would otherwise be recorded wrong: the buzzer as "broken or unconfirmed",
the ADC as "dead", the sensors as "stuck", and the IMU as "not moving". D-247 decision 6
(a test action plus a person's confirmation) and the probe's rules (known addresses only,
4095 means OK, chip id for the IMU) came from these checks.

## When to Apply

Any Pinky Pro bring-up, and any check where a device reads full-scale, zero, or silent.
First ask whether a person could settle it in thirty seconds.

## Examples

Pitch-coded bisection, run as root on the robot (RPi.GPIO over lgpio, chip 4 = `pinctrl-rp1`):
```python
group([4, 5, 6, 16, 17], 500, "LOW")    # person: heard low?
time.sleep(2)
group([20, 21, 23, 24, 26], 3000, "HIGH")
```

## Related

- [ws2812-lamp-dark-on-ubuntu-pi5-rp1-ws281x-2026-09-26.md](../runtime-errors/ws2812-lamp-dark-on-ubuntu-pi5-rp1-ws281x-2026-09-26.md)
- ADR D-247, D-190 (buzzer pin), D-192 (ADC flock), D-169
