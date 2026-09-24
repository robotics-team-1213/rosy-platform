<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-23 -->

# robot

## Purpose

On-device runtime for Ubuntu Server 24.04 arm64 + native ROS 2 Jazzy (D-161).
Product services live under `native/`: CORE starts by default without device access;
I/O and navigation are explicit hardware modes. Dockerfile/Compose remain only for
development and CI compatibility and are not installed in the product image.

## Key Files

| File | Description |
|------|-------------|
| `native/` | Product systemd target/services, non-secret environment template, provisioning gate and readiness probe |
| `Dockerfile` | Development/CI-only legacy container build |
| `compose.yaml` | Development/CI-only legacy slice runner; never a product-image dependency |
| `runtime-mode.sh` | Modes: `core` \| `motor` \| `hardware` (not `io`); hardware selects `ROSY_NAVIGATION_BACKEND=localization|slam` |
| `entrypoint.sh` | Container entry |
| `install-pi.sh` | First-boot install on Pi. `--preset` (mode/alias) or `--slices` (must match a preset, include `core`); both map to `ROSY_RUNTIME_MODE`. vision/omx/ai: not installable yet |
| `configure-uart-pi5.sh` | Pi 5 UART (`ttyAMA4` for Dynamixel) |
| `deploy-from-windows.ps1` | Copy/deploy from a Windows host |
| `dev/` | D-179 bench overlay. Not part of the product install path |
| `verify/` | On-device and Windows checks: `verify-pi.sh`, `verify-motors.sh`, `verify-power.sh`, `device-readback.sh` |
| `collect-rosy-diagnostics.ps1` | D-175 L2 puller: key-only BatchMode SSH with a pinned `%LOCALAPPDATA%\Rosy\known_hosts` (accept-new), runs `rosy-diag collect`, copies the bundle to `evidence\<device>\<boot_id>\` without overwriting. SSH unreachable + `-CardDisk <serial>`: copies the card's FAT32 `rosy-diag\` (no elevation) and prints the elevated `deploy\sd\read-card-diagnostics.py` command. `-PrintPlan` runs nothing |
| `verify/verify-motors.sh` | Refuses to probe the UART whenever it cannot establish that the motor runtime is down |
| `capture-vendor-baseline.sh` | Pre-G0 vendor stock image (card A) passive, secret-redacted evidence capture; closes upstream research UNKNOWNs and gives G0–G5 reference values. Contract pinned + mutation-proven by `test/test_capture_vendor_baseline.py`; I2C probing is opt-in and raw output requires review before repository admission |
| `commission-pinky.py` / `commissioning_session.py` | Ordered G0-G5 evidence recorder; G5 binds MCAP telemetry and generated map hashes; operator procedure is `docs/deployment/pinky-pro-first-device-runbook.md` |
| `measure-dds-baseline.sh` | Phase 0 DDS baseline (D-34). Requires `hardware` mode; records each topic's pre-attach subscriber count because attaching `ros2 topic bw` creates the traffic it measures |
| `rosy-runtime.service` | Legacy Compose unit retained for development compatibility; product images enable `native/rosy-runtime.target` |
| `rosy-lowbatt-shutdown.service` / `.path` / `.sh` | D-27: host watches CORE sentinel file and halts |
| `rosy-release-recover.service` / `release-recover.sh` | Failed-release recovery |
| `rosy-release-push.ps1` | D-230: operator-PC entry point that scp's a signed native payload release to an existing robot and runs `native/activate-release.sh` (or `native/rollback-release.sh`), no card re-flash. Verifies the signature/checksums locally first (reuses `deploy/release/signing.py`); `-PrintCommands` shows the exact ssh/scp sequence without touching the network |
| `rosy-release-unpack.sh` | Remote helper `rosy-release-push.ps1` copies over: atomically places a release tarball under `/opt/rosy/releases/<id>`, refusing an id that already exists with different content |
| `requirements-core.txt` / `requirements-io.txt` | pip constraints per image |
| `.env.example` | Compose env template (do not commit secrets) |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `config/` | Pi 5 lite profile, capabilities, example rosy.yaml (see `config/AGENTS.md`) |
| `dev/` | Bench CORE overlay. Does not reinstall `/opt/rosy` (see `dev/AGENTS.md`) |
| `native/` | D-161 native systemd product runtime (see `native/AGENTS.md`) |
| `verify/` | Install checks and secret-free device readback (see `verify/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Healthcheck: `GET http://127.0.0.1:8080/api/v1`.
- D-161 product paths must not call Docker or Compose. Do not wire the legacy
  `rosy-runtime.service` into a product image.
- CORE is the only required slice. vision/omx/ai are catalogued with `enabled: false` and no compose service; do not start them.
- `rosy-core` has **no** `/dev` devices and no Docker socket. Do not add them.
- Host proc/sys bind-mounts are read-only for dashboard telemetry (`ROSY_HOST_ROOT=/host`).
- Low-battery shutdown: CORE writes `battery-shutdown-request.json`; the host unit executes halt (sentinel age 900 s, grace cap 600 s). CORE must not call shutdown itself (D-27).
- `rosy-runtime.service` **Requires** `rosy-release-recover.service` — `Wants=` would make recovery advisory.
- `ROS_DOMAIN_ID` has **no default** — it is derived from `ROSY_ROBOT_NUMBER`
  (`40 + N`, namespace `rosy_%02d`) at install time and `compose.yaml` uses the
  `${VAR:?}` form so an unset identity stops the runtime (D-33). A default here is
  what shipped every unit as 42/`rosy_01`. CycloneDDS URI `file:///etc/rosy/cyclonedds.xml`.

### Testing Requirements

D-144 keeps mapping orthogonal to the runtime slice: `slam` is valid only in
`hardware`, selects the mapping capability overlay and SLAM readiness, and makes
the maps mount writable. Localization keeps the maps mount read-only.

```bash
python3 -m pytest test/test_native_systemd_contract.py test/test_robot_runtime.py test/test_release_boundary_guards.py -v
```

### Common Patterns

Native services source `/opt/ros/jazzy/setup.bash` and
`/opt/rosy/current/install/setup.bash`. Namespace remains
`__ns:=/${ROSY_NAMESPACE}`. Compose YAML anchors apply only to development/CI.

## Dependencies

### Internal

- Build context `../..` (repo root)
- Config overlays: `config/board.yaml` (`slices` / `presets`) plus `capabilities.{core,motor,hardware}.yaml`. `pi5-lite` is an alias resolved by `config/resolve-mode.sh`.

### External

- systemd, Ubuntu Server 24.04 arm64, native ROS 2 Jazzy. Docker Compose is optional development/CI tooling.

<!-- MANUAL: -->
