# Raspberry Pi 5 Wi-Fi Deployment Kit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a secret-safe deployment kit for flashing Raspberry Pi OS Lite, provisioning Rosy over Wi-Fi, and verifying LAN, Internet, service, and dashboard readiness without Ethernet.

**Architecture:** Raspberry Pi Imager owns device-specific Wi-Fi, hostname, user, and SSH settings. Versioned shell/PowerShell scripts transfer the committed revision, install Docker from its official Debian repository, configure core-only Rosy startup, and report network/application gates independently.

**Tech Stack:** Raspberry Pi OS Lite 64-bit, NetworkManager/nmcli, Bash, PowerShell/OpenSSH, Docker Engine/Compose, systemd, pytest static contracts.

---

### Task 1: Deployment contract tests

**Files:**
- Create: `test/test_pi_wifi_deployment.py`

**Steps:**
1. Add tests asserting installer/verifier/uploader/runtime-mode files exist, contain no hard-coded secrets, use the official Docker apt repository, default to core-only, and keep Wi-Fi/Internet/dashboard gates distinct.
2. Run `python -m pytest test/test_pi_wifi_deployment.py -q` and confirm missing-file failures.
3. Commit only after the following tasks turn the contract green.

### Task 2: Runtime mode wrapper and systemd integration

**Files:**
- Create: `deploy/robot/runtime-mode.sh`
- Modify: `deploy/robot/rosy-runtime.service`
- Modify: `deploy/robot/.env.example`

**Steps:**
1. Implement `core` and `hardware` modes with `core` as the default and explicit invalid-mode failure.
2. Route systemd start/stop through the wrapper while retaining network-online and Docker ordering.
3. Run the focused contract tests and `bash -n`.
4. Commit as `feat(runtime): add core-only deployment mode`.

### Task 3: Raspberry Pi installer

**Files:**
- Create: `deploy/robot/install-pi.sh`

**Steps:**
1. Add root/model/arm64/Raspberry Pi OS and Internet preflights.
2. Install Docker Engine/Buildx/Compose from the official Debian arm64 repository without `get.docker.com`.
3. Install the committed release into `/opt/rosy`, preserve existing config/data, generate first-use API tokens on-device, write core-only runtime mode, build `rosy-core`, and enable the service only after health succeeds.
4. Run focused tests and `bash -n`.
5. Commit as `feat(deploy): add idempotent Raspberry Pi installer`.

### Task 4: Network and dashboard verifier

**Files:**
- Create: `deploy/robot/verify/verify-pi.sh`

**Steps:**
1. Report WLAN radio/association, SSID, IPv4, default route, DNS, external HTTPS, Docker/service status, local FastAPI and dashboard status.
2. Support `--require-internet`; otherwise report Internet absence as WARN after installation.
3. Print the `.local` and IPv4 dashboard URLs without exposing credentials.
4. Run focused tests and `bash -n`.
5. Commit as `feat(deploy): add Wi-Fi readiness verifier`.

### Task 5: Windows transfer helper

**Files:**
- Create: `deploy/robot/deploy-from-windows.ps1`

**Steps:**
1. Require a clean tracked Git revision unless `-AllowDirty` is explicit; archive only `HEAD`.
2. Compute SHA-256, upload archive/checksum through SCP, verify remotely, and invoke the Pi installer through interactive SSH without bypassing host-key checks.
3. Parse with PowerShell AST and run static contract tests.
4. Commit as `feat(deploy): add Windows-to-Pi release transfer`.

### Task 6: Operator guide

**Files:**
- Create: `docs/deployment/raspberry-pi-wifi-image.md`
- Modify: `docs/deployment/raspberry-pi-runtime.md`
- Modify: `README.md`

**Steps:**
1. Document exact Raspberry Pi Imager selections, including KR localisation/WLAN country, hostname, SSH public key and Wi-Fi.
2. Document first boot discovery, transfer/install commands, generated token retrieval/removal, dashboard URLs, client isolation, Internet gates, core-to-hardware promotion, and rollback.
3. Distinguish local validation from physical `HOLD` gates.
4. Run documentation/static contract tests.
5. Commit as `docs: add Raspberry Pi Wi-Fi deployment runbook`.

### Task 7: Full verification and review

**Files:**
- Modify as required only for verified issues.

**Steps:**
1. Run focused deployment tests and all existing core/deadman/runtime tests.
2. Run `bash -n` in a Linux container, PowerShell AST parsing, `node --check`, `compileall`, Compose config, and `git diff --check`.
3. Build the `rosy-core` image and inspect the installed scripts/assets.
4. Request final code/security review.
5. Record physical Pi/WLAN acceptance as `HOLD`, not as completed.
