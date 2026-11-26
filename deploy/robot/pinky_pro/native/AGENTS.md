<!-- Parent: ../AGENTS.md -->

# native

**Parent context:** `../AGENTS.md`

## Purpose

D-161 product runtime units for Ubuntu Server 24.04 arm64 with native ROS 2 Jazzy. This directory is copied into every offline ROSY release payload.

## Rules

- `rosy-runtime.target` starts CORE and `rosy-io.service` on first boot with `ROSY_IO_DRIVE_ENABLED=false` (torque off). Enabling drive requires lifted-wheel commissioning; navigation needs explicit approvals and never joins the default target.
- `rosy-core.service` has no `DeviceAllow`; keep `PrivateDevices=true`. Every other device node needs an explicit `DeviceAllow` entry.
- `rosy-core.service` execs `install/lib/core/core`, not `ros2 run`; do not add `SuccessExitStatus`. Core escalates a stuck shutdown with exit code 2; keep that visible as a failure.
- I/O and navigation share the `rosy-io` account and are mutually exclusive. Navigation requires both hardware and navigation approval markers.
- `/etc/rosy/runtime.env` is device-specific and secret-free; checked-in `rosy-runtime.env` is a template, not an identity.
- `/etc/rosy/dev-mode` (D-548) is a root-made bench marker: CORE accepts `rosy-dev-*` tokens (never for SSH), face shows DEV. No image, card or OTA step creates it.
- `rosy-camera.service` reads optional `/etc/rosy/learned-perception.env` (D-373, both off); keep values off `ExecStart`. Image layer: older cards need it hand-installed.
- Docker and Compose are forbidden in these units.
- `native_release.py` verifies the signed manifest and exact payload before stopping services; activation retains `previous`, journals the switch, rolls back on failed health; boot recovery runs before CORE.
- First boot completes before `rosy-sd-provision.service` can admit CORE.
- Diagnostics leaving the device go through `rosy_diag_redact.py` (D-175): black box `rosy_blackbox.py` and `rosy-diag collect --out DIR` (stdlib only, 50 MiB, never overwrites, never reads a denied path). Test from the installed layout.
- `rosy-hw-probe.service` (D-247) is the one root unit opening board devices, read-only; its `DeviceAllow` set is pinned in `test/test_device_surface_contract.py`. It writes only `/run/rosy-boot/hardware.json`; never opens buses while `rosy-io`/`rosy-navigation` run.
- `rosy-face.py` (D-433, D-766) imports `rosy_face_parts/_inputs/_display.py` beside it; they are listed in `PROGRAM_SOURCES` in `test/test_native_systemd_contract.py`. Tests patch `robot_state`/`presentation` on `rosy_face_display`.
- `rosy-auto-update.timer` -> `rosy_auto_update.py run` (D-412) applies signed payload releases only when rollout and robot allow. It and `rosy-release-push.ps1` both hold `/run/rosy-claim` and share `rosy-release-unpack.sh`. Pace: `ROSY_UPDATE_LIMIT_KBPS`.
- `rosy-lowbatt-shutdown.path` (D-27) watches CORE's `battery-shutdown-request.json` and runs `../rosy-lowbatt-shutdown.sh` (age and grace checks, then poweroff).
- `navigation_fallback_host.py` (SLAM to site wall-map fallback) runs only via Host Agent at `machine` grade. It switches `runtime.env` only through `commit_runtime`, and only after CORE's stop evidence (zero velocity >= 2 s, no goal, fresh on shared monotonic clock and boot id).
- `navigation_fallback_host.py` restarts `rosy-navigation` alone, rolls back to the saved 0600 runtime copy on failure, tries once per boot (root `reset` re-arms), never switches back to SLAM; `stage` is refused during a switch and never deletes the map `ROSY_MAP` names.
- `rosy-tailscale-join.service` (D-477) is a one-shot root unit gated on provisioned `/etc/rosy/tailscale-join.json` (0600; absent = LAN-only). It spends the auth key once, rewrites the file without it, and records `/var/lib/rosy/tailscale/join-result.json`. D-418 SSH rules still govern logins.

## Tests

```bash
python3 -m pytest test/test_native_systemd_contract.py test/test_native_release_activation.py test/test_diag_collect.py  test/test_navigation_fallback_host.py -q
```

Run `systemd-analyze verify` in Ubuntu 24.04 before promotion.
