<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-25 -->

# deployment

## Purpose

Operator runbooks for Raspberry Pi 5: first Wi-Fi image, runtime services, power-bench, acceptance, and release key/retention.

**Runtime model:** the product robot runs **natively** — Ubuntu Server 24.04 arm64
+ ROS 2 Jazzy + systemd (D-161). Docker is development/CI tooling only, never a
product-image dependency (D-197). Per-device difference is a profile/slice
choice; a container sidecar is allowed only for a declared workload outside the
safety plan (D-246).

## Key Files

| File | Description |
|------|-------------|
| `raspberry-pi-runtime.md` | Device permissions, native systemd product runtime plus the development/CI Compose path, core/motor/hardware modes |
| `pinky-pro-board-support.md` | First ROSY OS board: mode-specific capabilities, LiDAR hardware slice |
| `raspberry-pi-wifi-image.md` | Headless SD burn, Wi-Fi, SSH, Windows deploy |
| `arm64-build-notes.md` | Current ARM64/Pi build and runtime boundary notes |
| `legacy-arm64-guide.md` | Historical upstream instructions kept for provenance; do not use for deployment |
| `pi5-acceptance-checklist.md` | Physical acceptance tests |
| `power-bench-verification.md` | Power/idle/standby bench |
| `release-signing-key.md` | Ed25519 signing key handling |
| `release-retention.md` | How many signed releases to keep |
| `pinky-pro-first-device-runbook.md` | Fail-closed G0-G5 first physical Pinky Pro commissioning, including the hardware SLAM/MCAP map run |
| `pinky-pro-commissioning-body-templates.md` | Exact operator-attested G3-G5 JSON bodies; G5 binds MCAP and generated YAML/PGM hashes; invalid until physically measured |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Align steps with `deploy/robot/` scripts (`install-pi.sh`, `deploy-from-windows.ps1`, `runtime-mode.sh`). Modes are `core` / `motor` / `hardware`. Those three drive the **development Compose** path; the product path is `deploy/robot/native/` units under `rosy-runtime.target` (D-161/D-246).
- Do not write an operator step that requires Docker to reach the motor UART or a safety gate. Every gate must be passable with the container runtime absent (D-246).
- UART on Pi 5 is documented in `deploy/robot/configure-uart-pi5.sh` (default motor device `/dev/ttyAMA4`).
- Do not enable `lidar.standby_stop` until `power-bench-verification.md` passes. `pi5-acceptance-checklist.md` gates are HOLD until field sign-off.
- A simulated or host-built map never satisfies G5. The device session must retain bounded MCAP telemetry, the generated YAML/PGM pair, their hashes, navigation evidence, and the final stopped/E-stop state.
- D-145's native GitHub workflow produces an unsigned payload only. Offline Ed25519 signing and publication verification remain separate mandatory gates.

### Testing Requirements

Contracts: `test/test_robot_runtime.py`, `test/test_pi_wifi_deployment.py`, `test/test_dds_identity_contracts.py` (the commissioning and renumber procedures in these runbooks). Hardware steps are manual (`pi5-acceptance-checklist.md`).

### Common Patterns

Korean operator prose; commands are copy-pasteable bash/pwsh.

## Dependencies

### Internal

- `deploy/robot/`, `deploy/image/`, `deploy/release/`

### External

- Product: Ubuntu Server 24.04 arm64, native ROS 2 Jazzy, systemd.
- Development/CI only: Raspberry Pi OS Lite 64-bit, Docker Compose, nmcli.

<!-- MANUAL: -->
