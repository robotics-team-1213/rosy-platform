# Ubuntu Native ROS Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce and prove a Pinky Pro product SD image based on Ubuntu Server 24.04 arm64 with native ROS 2 Jazzy and the complete offline ROSY package payload.

**Architecture:** Build from a digest-pinned official Ubuntu Raspberry Pi image on native ARM64, install ROS and ROSY natively, and run least-privilege CORE/I/O services under systemd. Preserve the D-22 safety boundary while eliminating Docker from the product runtime.

**Tech Stack:** Ubuntu Server 24.04 LTS, ROS 2 Jazzy debs, colcon, systemd, NetworkManager, Bash, Python/pytest, YAML, native ARM64 Raspberry Pi 5 build host.

---

## Execution rule

D-161 is an immediate source and product-direction transition. It does not waive any
evidence gate. Every task starts with a failing executable contract, implements only the
required behavior, runs focused and regression tests, and commits an independently
reviewable change. Never write the connected SD card until Tasks 1-7 are green and the
operator has confirmed the exact target disk.

### Task 1: Freeze the Ubuntu-native product contract

**Files:**
- Modify: `docs/reference/ROSY ADR Log.md`
- Modify: `deploy/image/inputs.lock.yaml`
- Modify: `deploy/image/build-image.sh`
- Create: `test/test_ubuntu_native_runtime_contract.py`
- Create: `docs/plans/2026-09-21-ubuntu-native-ros-runtime-design.md`
- Create: `docs/plans/2026-09-21-ubuntu-native-ros-runtime.md`

**Step 1:** Add assertions for Ubuntu 24.04/Noble arm64, native Jazzy, no product
container runtime, mandatory Pinky Pro packages, D-161 and explicit HOLD states.

**Step 2:** Run `python -m pytest test/test_ubuntu_native_runtime_contract.py -q` and
confirm failure against the Raspberry Pi OS/container contract.

**Step 3:** Record D-161, replace the image-input schema, update the fail-closed builder,
and write this design/plan.

**Step 4:** Re-run the focused test plus
`python -m pytest test/test_image_pipeline.py test/test_image_checks.py -q`.

**Step 5:** Commit as `docs(runtime): adopt Ubuntu native ROS product baseline`.

### Task 2: Acquire and verify the official Ubuntu base image

**Files:**
- Create: `deploy/image/fetch-base-image.sh`
- Modify: `deploy/image/verify-inputs.sh`
- Modify: `deploy/image/inputs.lock.yaml`
- Modify: `test/test_image_pipeline.py`

**Step 1:** Add failing tests for exact HTTPS URL, published SHA-256, file-size sanity,
checksum mismatch rejection and offline cache reuse.

**Step 2:** Implement a non-root fetch/verify command. It must never accept an unpinned
`latest` URL or infer success from HTTP status alone.

**Step 3:** Capture the exact Canonical source and checksum in the lock only after live
verification on the release host.

**Step 4:** Run focused tests and verify that an altered byte fails checksum validation.

**Step 5:** Commit as `feat(image): pin verified Ubuntu Noble arm64 base`.

### Task 3: Build the offline ROS 2 and ROSY payload

**Files:**
- Create: `deploy/image/build-native-payload.sh`
- Create: `deploy/image/required-ros-packages.txt`
- Create: `deploy/image/verify-package-inventory.sh`
- Create: `test/test_native_ros_payload.py`
- Modify: `deploy/image/build-image.sh`

**Step 1:** Add failing tests for apt key fingerprint, Jazzy repository, rosdep resolution,
required package completeness, source revision and deterministic inventory output.

**Step 2:** On native ARM64, install pinned Jazzy debs into the image root and build the
workspace with `colcon build --merge-install --install-base <release>/install`.

**Step 3:** Generate an inventory containing OS deb versions and all ROSY packages.
Validate every entry with a clean environment and `ros2 pkg prefix`.

**Step 4:** Prove the first boot succeeds with network disabled and no required package
download attempt.

**Step 5:** Commit as `feat(image): stage offline native ROSY payload`.

### Task 4: Replace product Compose services with hardened systemd units

**Files:**
- Create: `deploy/robot/native/rosy-core.service`
- Create: `deploy/robot/native/rosy-io.service`
- Create: `deploy/robot/native/rosy-navigation.service`
- Create: `deploy/robot/native/rosy-runtime.target`
- Create: `deploy/robot/native/rosy-runtime.env`
- Create: `test/test_native_systemd_contract.py`

**Step 1:** Write failing unit-contract tests for users, dependencies, restart policy,
device isolation, environment, readiness and hardware/navigation gates.

**Step 2:** Implement CORE without device access and I/O with only board-profile devices.
Keep navigation disabled until its evidence gate is approved.

**Step 3:** Run `systemd-analyze verify` in Ubuntu 24.04 and execute failure-injection
tests for CORE crash, I/O crash, stale `cmd_vel`, reboot and power interruption.

**Step 4:** Confirm the driver issues zero RPM within the accepted deadman bound.

**Step 5:** Commit as `feat(runtime): add least-privilege native systemd services`.

### Task 5: Add atomic activation and rollback

**Files:**
- Create: `deploy/robot/native/activate-release.sh`
- Create: `deploy/robot/native/rollback-release.sh`
- Create: `test/test_native_release_activation.py`
- Modify: `deploy/image/verify-artifacts.sh`

**Step 1:** Test signed-manifest verification, atomic `current` symlink replacement,
service restart order, failed-health rollback and power-loss recovery.

**Step 2:** Implement activation that refuses unsigned, incomplete or architecture-wrong
payloads and retains the last accepted release.

**Step 3:** Prove rollback without network access or Docker.

**Step 4:** Commit as `feat(runtime): add atomic native release rollback`.

### Task 6: Port first-boot personalization to Ubuntu

**Files:**
- Modify: `deploy/image/first-boot/rosy-first-boot.sh`
- Modify: `deploy/image/first-boot/rosy-first-boot.service`
- Modify: `deploy/image/personalize-sd.ps1`
- Modify: `test/test_first_boot_provisioning.py`
- Modify: `test/test_sd_personalization.py`

**Step 1:** Add failing Ubuntu tests for NetworkManager, hostname, immutable device UID,
secret file mode, one-shot consumption and safe fallback.

**Step 2:** Apply the `rosy-pinky-xxxx` identity contract without logging Wi-Fi secrets.
Do not embed plaintext credentials in Git, image manifests or command transcripts.

**Step 3:** Verify a network-disabled boot and a wrong-credential recovery path.

**Step 4:** Commit as `feat(provisioning): port Pinky identity to Ubuntu first boot`.

### Task 7: Produce release evidence before touching media

**Files:**
- Modify: `deploy/image/verify-artifacts.sh`
- Modify: `docs/deployment/pi5-acceptance-checklist.md`
- Create: `docs/validation/<release-id>/artifact-report.md`

**Step 1:** Build on native ARM64 and capture base digest, full image SHA-256, SBOM,
package inventory, source revision, signature and secret-scan result.

**Step 2:** Mount the artifact read-only and verify OS release, systemd units, users,
device policy, `/opt/ros/jazzy`, ROSY payload and absence of a product Docker dependency.

**Step 3:** Only then set ARTIFACT to GO. MEDIA, BOOT, DEVICE and FLEET remain HOLD.

**Step 4:** Commit as `docs(validation): capture Ubuntu native artifact evidence`.

### Task 8: Write, boot and accept the exact SD/device

**Files:**
- Modify: `docs/validation/<release-id>/artifact-report.md`
- Create: `docs/validation/<release-id>/device-report.md`

**Step 1:** Enumerate disks twice, confirm the removable target by model/serial/capacity,
show a plan, require the existing explicit erase confirmation, then write the image.

**Step 2:** Read the entire media back and compare its digest. Set MEDIA to GO only on
exact readback.

**Step 3:** Boot Pinky Pro and capture Ubuntu release, kernel/firmware, systemd status,
`ros2 pkg prefix` for every required package, ROS graph and device-node ownership.

**Step 4:** Exercise stop/deadman, reboot, power loss, network loss and first-boot replay.
Set BOOT and DEVICE independently from their physical evidence.

**Step 5:** With two Pinky robots, prove unique identities, isolated ROS domains, Fleet
enrollment, heartbeat, mission arbitration and group emergency stop before FLEET GO.

**Step 6:** Commit as `docs(validation): accept Ubuntu native Pinky device`.

## Final regression gate

Run from the repository root:

```bash
python3 -m pytest src/core/core/test/ src/core/control/test/ src/site/fleet/test \
  src/apps/omx_adapter/test src/apps/games/test test/ -q
```

Host tests do not replace native ARM64 build, SD readback, Raspberry Pi boot or physical
motor safety evidence. Report each gate separately.

## 2026-09-22 implementation checkpoint

- Task 5 is source-complete: signed native releases are verified before runtime stop,
  activated with atomic `current`/`previous` links, health-checked, rolled back without
  network or Docker, and recovered from an interrupted switch before CORE starts.
- Task 6 is source-complete: the Windows writer creates the per-card one-time bundle
  from a DPAPI-protected Wi-Fi credential over stdin, copies it only to the selected
  SD boot partition, and Ubuntu first boot binds it to the Pi serial before CORE.
- Task 7 remains HOLD. The immutable overlay is staged in the native payload, but a
  native ARM64 host must still install it into the pinned Ubuntu image, produce the
  SBOM/signature, and pass read-only artifact verification before any SD is erased.
