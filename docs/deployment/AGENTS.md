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
| `pinky-release-artifact-selection.md` | D-325 path selector: none, native payload, flashable image, or fail-closed review |
| `site-ceiling-camera-console-runbook.md` | 현장 천장 카메라(Rosy Cam)·관제 운영: CA 고정 페어링, mDNS 사이트 찾기(D-391), 카메라 위치, 맵 자동 맞춤(D-375), 로봇 등록·모드, 규칙 점검, 문제 해결 |
| `pinky-pro-ir-line-calibration-runbook.md` | D-344 §12 IR line calibration with the read-only tool: four placements, checks, sign check, where the YAML and CORE revision go |
| `pinky-pro-commissioning-body-templates.md` | Exact operator-attested G3-G5 JSON bodies; G5 binds MCAP and generated YAML/PGM hashes; invalid until physically measured |
| `learned-perception-operators.md` | D-373 operator guide: `rosy_ml` setup and doctor, shadow deliver/rollback/harvest, lock and history, site auto-delivery install |
| `robot-ssh-access.md` | D-418 운영자·수신자 안내: 화면 코드 기기 키 등록(`tools/ssh/rosy_ssh_enroll.py`), 임시 비밀번호 API(curl/PowerShell, 끄기), 팀 키 묶음 만들기·넘기기·회수(`tools/ssh/rosy_ssh_share.py`), R1–R3 보안 메모 |
| `tailnet-remote-access.md` | D-477 테일넷 운영 안내: tailnet 승격·초대·ACL, auth key 보관(`private/`), 로봇 가입(번들·수동 join)과 확인, site 방화벽 `tailscale0`, 팀원 접속 요약, 회수 |
| `learned-perception-pinky.md` | D-373 Pinky first-deploy runbook: layer table, new SD vs bench card, unit hand-install, `/etc/rosy/learned-perception.env` switch, first shadow measurement, capture/harvest, rollback |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Align steps with `deploy/robot/pinky_pro/` scripts (`install-pi.sh`, `deploy-from-windows.ps1`, `runtime-mode.sh`). Modes are `core` / `motor` / `hardware`. Those three drive the **development Compose** path; the product path is `deploy/robot/pinky_pro/native/` units under `rosy-runtime.target` (D-161/D-246).
- Do not write an operator step that requires Docker to reach the motor UART or a safety gate. Every gate must be passable with the container runtime absent (D-246).
- UART on Pi 5 is documented in `deploy/robot/pinky_pro/configure-uart-pi5.sh` (default motor device `/dev/ttyAMA4`).
- Do not enable `lidar.standby_stop` until `power-bench-verification.md` passes. `pi5-acceptance-checklist.md` gates are HOLD until field sign-off.
- A simulated or host-built map never satisfies G5. The device session must retain bounded MCAP telemetry, the generated YAML/PGM pair, their hashes, navigation evidence, and the final stopped/E-stop state.
- D-145's native GitHub workflow produces an unsigned payload only. Offline Ed25519 signing and publication verification remain separate mandatory gates.
- Use `pinky-release-artifact-selection.md` before a Pinky build. `artifact_impact.py` is advisory and fails closed; it never grants signing, install, motion, or acceptance approval.

### Testing Requirements

Contracts: `test/test_robot_runtime.py`, `test/test_pi_wifi_deployment.py`, `test/test_dds_identity_contracts.py` (the commissioning and renumber procedures in these runbooks). Hardware steps are manual (`pi5-acceptance-checklist.md`).

### Common Patterns

Korean operator prose; commands are copy-pasteable bash/pwsh.

## Dependencies

### Internal

- `deploy/robot/pinky_pro/`, `deploy/robot/pinky_pro/image/`, `deploy/robot/pinky_pro/release/`

### External

- Product: Ubuntu Server 24.04 arm64, native ROS 2 Jazzy, systemd.
- Development/CI only: Raspberry Pi OS Lite 64-bit, Docker Compose, nmcli.

<!-- MANUAL: -->
