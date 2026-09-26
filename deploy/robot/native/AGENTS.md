<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-22 | Updated: 2026-09-22 -->

# native

## Purpose

D-161 product runtime units for Ubuntu Server 24.04 arm64 with native ROS 2
Jazzy. This directory is copied into every offline ROSY release payload.

## Rules

- `rosy-runtime.target` starts CORE only. Hardware services require explicit
  commissioning and must never be added to the default target.
- `rosy-core.service` has no `DeviceAllow`; keep `PrivateDevices=true`.
- `rosy-core.service` execs the core entry script (`install/lib/core/core`), not
  `ros2 run`, so systemd supervises the node directly; do not add `SuccessExitStatus`.
  A signal death of the main process is a clean stop to systemd, so core escalates a
  stuck shutdown with exit code 2 — keep that visible as a failure.
- I/O/navigation share the `rosy-io` account and are mutually exclusive.
- Every device node must be named by an explicit `DeviceAllow` entry.
- Navigation requires both hardware and navigation approval markers.
- `/etc/rosy/runtime.env` is device-specific and secret-free. The checked-in
  `rosy-runtime.env` is a template, not a usable identity.
- Docker and Compose are forbidden in these units.
- `native_release.py` verifies the signed manifest and exact native payload before
  stopping runtime services. Activation retains `previous`, journals the switch,
  and rolls back on failed health; boot recovery runs before CORE.
- First boot must complete before `rosy-sd-provision.service` can admit CORE.
- Diagnostics that leave the device go through `rosy_diag_redact.py` (D-175): the boot-partition
  black box (`rosy_blackbox.py`) and the L2 bundle `rosy-diag collect --out DIR`
  (`rosy-diag` wrapper -> `rosy_diag_collect.py`, stdlib only, bounded 50 MiB, never overwrites,
  never reads a denied path). Test from the installed layout, not only the repo path.

- `rosy-hw-probe.service` (D-247) is the one root unit that opens board devices for
  observation: read-only, known addresses only, its exact `DeviceAllow` set is pinned in
  `test/test_device_surface_contract.py`. It writes only `/run/rosy-boot/hardware.json`;
  `rosy-hw-probe.path` reruns it when CORE writes `/run/rosy/hw-probe.request`.
  While `rosy-io`/`rosy-navigation` run it never opens their buses.

## Tests

```bash
python3 -m pytest test/test_native_systemd_contract.py test/test_native_release_activation.py test/test_diag_collect.py -q
```

Run `systemd-analyze verify` in an Ubuntu 24.04 root before artifact promotion.
