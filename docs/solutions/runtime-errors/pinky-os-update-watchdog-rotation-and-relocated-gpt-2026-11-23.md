---
title: "Pinky OS update stalls on early-boot journald rotation and relocated 32 GB backup GPT"
date: "2026-11-23"
category: runtime-errors
module: deploy/robot/pinky_pro/native
problem_type: runtime_error
component: os_update_preflight
symptoms:
  - "os_update_watchdog.admit raised OS_WATCHDOG_HOLD after days of uptime even though config.txt, /proc/cmdline, /sys/class/watchdog/watchdog0, and systemctl show all proved BCM2835 watchdog was active at 10s"
  - "os_media.capture raised OS_MEDIA_HOLD: GPT: unsupported header on a 32,044,482,560-byte SD card whose backup GPT resided at LBA 62586879 instead of os-media.json raw_size_bytes (LBA 60817407)"
root_cause: journal_rotation_and_relocated_backup_gpt
resolution_type: code_fix
severity: high
tags: [pinky, os-update, watchdog, journald, gpt, os_media, b8xy, y8xs]
---

## Cause

Two real-hardware OS preflight failures were diagnosed on live Pi 5 robots (`rosy-pinky-b8xy` running `2026.10.29-001` since 2026-10-12 and `rosy-pinky-y8xs` running `2026.10.29-002`):

1. **Watchdog observation vs. journal rotation (`os_update_watchdog.py`)**:
   `admit()`/`observe()` required `journalctl --boot=<id> --grep=watchdog|Watchdog` to print PID 1's early-boot `Using hardware watchdog ...` and `Watchdog running with a timeout of 10s.` messages. On long-running robots, `systemd-journald` rotates those early-boot entries (e.g., `b8xy` earliest retained `_PID=1` entry was `__MONOTONIC_TIMESTAMP=22394695` us = 22.4s after boot), so `journalctl --grep=...` exited `1` with empty output despite `/boot/firmware/config.txt`, `/proc/cmdline`, `/sys/class/watchdog/watchdog0/*`, and `systemctl show` confirming the 10s hardware watchdog was live.

2. **Relocated backup GPT on larger physical media (`os_media.py`)**:
   `os_media.capture()` validated GPT strictly at `layout["raw_size_bytes"]` (`31,138,512,896` B / LBA `60817407`). On `y8xs`'s `32,044,482,560`-byte SD card, the primary GPT header at LBA 1 pointed `backup_lba` to physical disk end `62586879`, causing `parse_gpt(..., layout["raw_size_bytes"], "bootstrap")` to fail with `GPT: unsupported header` even though all six partitions, GUIDs, and `provision_role` were identical.

## Fix & Invariants

1. `os_update_watchdog.observe()` preserves strict firmware/cmdline/sysfs/`systemctl show` checks and `_journal()` verification whenever `watchdog|Watchdog` lines exist, and only falls back when `journalctl --grep=...` returns `returncode in (0, 1)` with empty stdout/stderr: it queries `journalctl --boot=<hex> --output=json --no-pager --lines=+1 _PID=1` and requires `_BOOT_ID` match, `_is_pid1(first)`, and `__MONOTONIC_TIMESTAMP > 10_000_000` (proving early-boot records rotated out while PID 1's live watchdog configuration remains active).
2. `os_media.capture()` retries `parse_gpt(read_at, disk_bytes, "bootstrap")` on `ValueError` only when `disk_bytes > layout["raw_size_bytes"]`, and accepts only when every field other than `raw_size_bytes` (`disk_guid`, `provision_role`, and all six partition definitions) matches `os-media.json` verbatim.

## Hardware Rollout Constraint

- Robots whose frozen `/opt/rosy/os-bootstrap` predates these fixes hit the frozen bootstrap code during source preflight: `b8xy` (`media OK`, `watchdog FAIL` from journal rotation) can self-clear `watchdog` via one reboot (which produces fresh early-boot PID 1 watchdog logs), whereas `y8xs` (`media FAIL` on frozen `2026.10.29-002`) cannot pass frozen GPT admission over OTA and requires a one-time physical reflash with an OS image built from this fix.
