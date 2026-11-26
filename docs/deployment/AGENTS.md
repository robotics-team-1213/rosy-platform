<!-- Parent: ../AGENTS.md -->

# deployment

**Parent context:** `../AGENTS.md`

## Purpose

Operator runbooks for Raspberry Pi 5: first Wi-Fi image, runtime services, power-bench, acceptance, release key/retention. `ls` lists them. **Runtime model:** the product robot runs **natively** on Ubuntu Server 24.04 arm64 + ROS 2 Jazzy + systemd (D-161). Docker is development/CI tooling only, never a product-image dependency (D-197); a container sidecar is allowed only for a declared workload outside the safety plan (D-246).

## For AI Agents

### Working In This Directory

- Align steps with `deploy/robot/pinky_pro/` scripts. Modes `core`/`motor`/`hardware` drive the development Compose path; the product path is `deploy/robot/pinky_pro/native/` units under `rosy-runtime.target` (D-161/D-246). UART on Pi 5: `configure-uart-pi5.sh` (motor device `/dev/ttyAMA4`).
- Never write an operator step that needs Docker to reach the motor UART or a safety gate; every gate must pass with the container runtime absent (D-246).
- Do not enable `lidar.standby_stop` until `power-bench-verification.md` passes. `pi5-acceptance-checklist.md` gates stay HOLD until field sign-off.
- A simulated or host-built map never satisfies G5: the device session keeps bounded MCAP telemetry, the generated YAML/PGM pair and hashes, navigation evidence and the final stopped/E-stop state (`pinky-pro-first-device-runbook.md` G0-G5;
- body templates in `pinky-pro-commissioning-body-templates.md` are invalid until physically measured).
- D-145's native GitHub workflow produces an unsigned payload only; offline Ed25519 signing (`release-signing-key.md`) and publication verification stay separate mandatory gates.
- Open `pinky-release-artifact-selection.md` (D-325) before any Pinky build; `artifact_impact.py` is advisory, fails closed, and never grants signing, install, motion or acceptance approval. `site-overlay-return-to-signed.md` (D-868) returns hand-overlaid R images to a signed candidate.
- Do not deploy from `legacy-arm64-guide.md` (provenance only) or `github-updates.md` (legacy container-bundle updater); start with the artifact selection.
- Topic runbooks: IR line calibration D-344 section 12, learned perception D-373 (`learned-perception-operators.md`, `learned-perception-pinky.md`), robot SSH D-418, tailnet D-477, site camera/console D-391 and map fit D-375 (`site-ceiling-camera-console-runbook.md`,
- `site-map-change-and-robot-recognition-runbook.md`).

### Testing Requirements

Contracts: `test/test_robot_runtime.py`, `test/test_pi_wifi_deployment.py`, `test/test_dds_identity_contracts.py`. Hardware steps are manual (D-584 for the pytest part, remote). Operator prose is Korean with copy-pasteable bash/pwsh.

### Dependencies

- Product: Ubuntu Server 24.04 arm64, native ROS 2 Jazzy, systemd.
- Development/CI only: Raspberry Pi OS Lite 64-bit, Docker Compose, nmcli.
