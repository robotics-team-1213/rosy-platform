<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-22 | Updated: 2026-09-22 -->

# native

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

D-161 product runtime units for Ubuntu Server 24.04 arm64 with native ROS 2
Jazzy. This directory is copied into every offline ROSY release payload.

## Rules

- `rosy-runtime.target` starts CORE and `rosy-io.service` on first boot. The
  image has `ROSY_IO_DRIVE_ENABLED=false`, so I/O observes devices with motor
  torque off. Enabling drive requires lifted-wheel commissioning; navigation
  still requires explicit approvals and never joins the default target.
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
- `rosy-camera.service` also reads the optional `/etc/rosy/learned-perception.env`
  (D-373; template `learned-perception.env.example`, both off). The launch file parses
  `ROSY_LEARNED_SHADOW` / `ROSY_CAPTURE` strictly; keep the values off the `ExecStart` line.
  The unit is image layer: a card baked earlier needs the unit hand-installed.
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

- `rosy-auto-update.timer` → `rosy_auto_update.py run` (D-412) stages and applies signed
  GitHub payload releases only when the rollout and the robot allow it; state lives in
  `/var/lib/rosy/updates/`. It and `rosy-release-push.ps1` both hold `/run/rosy-claim`
  (`rosy_claim.py`) and share `rosy-release-unpack.sh`. Tests: `test/test_rosy_auto_update.py`,
  `test/test_rosy_claim.py`.

- `rosy-tailscale-join.service` (D-477) is a one-shot root unit, condition-gated on the
  provisioned `/etc/rosy/tailscale-join.json` (0600; absent → the robot stays LAN-only).
  `rosy-tailscale-join.py` spends the auth key once (`tailscale up`, `--accept-dns=false`),
  rewrites the file in place without the key, and records the outcome in
  `/var/lib/rosy/tailscale/join-result.json`. tailscaled itself is the package unit
  (image installs the pinned deb); D-418's SSH rules still govern every login. Test:
  `test/test_rosy_tailscale_join.py`.

## Tests

```bash
python3 -m pytest test/test_native_systemd_contract.py test/test_native_release_activation.py test/test_diag_collect.py -q
```

Run `systemd-analyze verify` in an Ubuntu 24.04 root before artifact promotion.
