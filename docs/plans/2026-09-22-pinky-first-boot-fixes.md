# Pinky First-Boot Fixes and Boot Indicator Plan (D-173)

> Execute task-by-task with test-driven development: write the failing contract
> first, then the fix. Do not write physical media until Tasks 1-8 are green,
> release `003` is signed and verified, and the operator reconfirms the disk.

**Goal:** Make the next Pinky Pro card boot to a running CORE that people can
see (board LED, HDMI console, mDNS) and operators can reach (per-card SSH key),
then rewrite the same card with the same identity and pass runbook G0-G2.

**Evidence baseline:** card `rosy-pinky-e4us`, release `2026.09.22-002`, journal
boot `23fe37a5`. Extracted read-only to `F:\tmp\rosy-release\cards\diag\`.

---

## Task 1: Reproduce F1 in the installed layout, then fix it (P0)

**Files:**
- Create: `test/test_native_runtime_installed_layout.py`
- Modify: `deploy/robot/native/native_release.py`
- Modify: `deploy/image/build-native-payload.sh`

1. Copy `deploy/robot/native/*` into `tmp/opt/rosy/native-runtime/` exactly as
   `build-native-payload.sh` does, run `python3 native_release.py --help` and
   `recover-release.sh` against a fixture `/opt/rosy`. Expect `No module named 'signing'`.
2. Install `deploy/release/signing.py` beside the runtime and resolve modules from
   the script's own directory first, then the repository path.
3. Green on both layouts. Commit `fix(native): run release recovery from the installed layout`.

## Task 2: Execute entrypoints inside the mounted image (F5)

**Files:**
- Modify: `deploy/image/verify-mounted-image.py`, `deploy/image/customize-rootfs.sh`
- Modify: `deploy/image/test/test_verify_mounted_image.py`

1. Test that verification fails when a runtime entrypoint cannot import.
2. In the ARM64 chroot, run the recovery dry-run and the first-boot `--help`.
3. Commit `test(image): execute native entrypoints in the mounted rootfs`.

## Task 3: Apply the hostname live (F2)

**Files:**
- Modify: `deploy/image/first-boot/rosy-first-boot.py`
- Modify: `test/test_first_boot_provisioning.py`

1. Test that apply calls the injected live-hostname setter after writing `/etc/hostname`,
   and that avahi is asked to reload.
2. Use `hostnamectl set-hostname` (fall back to `hostname`) through the existing
   command-runner seam so the ROS-free fixture stays hermetic.
3. Commit `fix(first-boot): apply the device hostname to the running system`.

## Task 4: Per-card operator SSH key (F3)

**Files:**
- Modify: `deploy/sd/provision.schema.json`, `deploy/sd/personalization.py`,
  `deploy/sd/create-provision-bundle.py`, `deploy/sd/prepare-rosy-sd.ps1`
- Modify: `deploy/image/first-boot/rosy-first-boot.py`
- Tests: `test/test_sd_personalization.py`, `test/test_sd_writer_contract.py`,
  `test/test_first_boot_provisioning.py`

1. Bundle field `operator.ssh_authorized_keys` (ed25519/ecdsa public keys only;
   reject private-key material). Writer flag `-OperatorPublicKey <path>`, recorded
   in the plan by fingerprint.
2. First boot creates the `rosy` login user (no password), installs keys mode 0600.
3. Runbook `ssh rosy@<name>.local` becomes true. Commit `feat(sd): per-card operator SSH key`.

## Task 5: Boot status indicator T0 (F4)

**Files:**
- Create: `deploy/robot/native/rosy-boot-status.py`, `rosy-boot-status.service`,
  `rosy-boot-status.timer` (or path/OnFailure hooks)
- Create: `test/test_boot_status.py`
- Modify: `deploy/image/customize-rootfs.sh`, `deploy/robot/native/rosy-runtime.target`

1. Pure function: systemd unit states + provisioning state → stage
   (`BOOTING`, `PROVISIONED`, `CORE_READY`, `FAILED:<unit>`). Test every branch.
2. Sinks, each isolated and failure-tolerant: `/run/rosy/boot-status.json`,
   ACT LED trigger (`heartbeat` ready, `timer` fast blink failed), `/etc/issue`
   banner (name, IP, stage), avahi `_rosy._tcp` service with TXT `stage=`.
3. Root oneshot outside CORE, `Wants=` only; runs on runtime success and on
   `OnFailure=` of recover/first-boot/core. Commit `feat(native): boot status indicator (D-173 T0)`.

## Task 6: ROS home and log directory for rosy-core (F6)

**Files:** `deploy/robot/native/rosy-core.service`, `test/test_native_systemd_contract.py`

1. Contract: `Environment=ROS_HOME=/var/lib/rosy/ros ROS_LOG_DIR=/var/lib/rosy/log`
   inside `StateDirectory`. Commit `fix(native): give rosy-core a writable ROS home`.

## Task 7: Reflash the same device identity (F7)

**Files:** `deploy/sd/prepare-rosy-sd.ps1`, `test/test_sd_writer_contract.py`

1. `-ReprovisionReceipt <receipt.json>`: allow registry reuse only when UID, name and
   robot number match that receipt; the new receipt records `supersedes`.
2. Commit `feat(sd): rewrite a card for an existing device identity`.

## Task 8: Read-only card diagnostics tool (F8)

**Files:** `deploy/sd/read-card-diagnostics.py`, `test/test_card_diagnostics.py`

1. Promote the session extractor: open the physical disk read-only, parse ext4,
   copy provisioning state, `/etc/rosy`, units and journal; never read
   `NetworkManager/system-connections`. Test with an ext4 fixture image.
2. Commit `feat(sd): read-only card diagnostics without wsl --mount`.

## Task 9: Release 003 and rewrite the same card

1. Merge Tasks 1-8, tag the merge commit `release/2026.09.22-003`, run
   `build-pinky-image.yml`, sign with the pilot key, verify.
2. `-PlanOnly -PlanPath` with `-ReprovisionReceipt` (identity 18 kept) and
   `-OperatorPublicKey`, then the elevated write with readback.
3. Boot and check within 5 minutes: ACT heartbeat, `rosy-pinky-e4us.local`,
   `_rosy._tcp stage=CORE_READY`, `ssh rosy@…`, `GET :8080/api/v1`.
4. Run runbook G0-G2 and record evidence. Update D-172/D-173 tables.

## Deferred (new ADRs)

- **T1 LCD status card:** narrow D-169 exception for a display-only unit
  (`/dev/spidev0.0`, gpiochip) after bench SPI evidence.
- **T2 Buzzer:** run `deploy/robot/capture-vendor-baseline.sh` on a vendor OS card
  to identify the pin and service, then decide.
