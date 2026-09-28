<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-21 -->

# image

## Purpose

Build a signed Ubuntu Server 24.04 LTS arm64 ROSY OS release image with native ROS 2 Jazzy on **native aarch64**. The scripts refuse x86/QEMU release hosts. Inputs must be pinned in `inputs.lock.yaml`; producing a file is not enough — `verify-artifacts.sh` is the go/no-go.

D-164 fixes the product artifact as
`rosy-os-pinky-pro-<release-id>-arm64.img.xz`. A generic installer ISO is not
a Pinky Pro release artifact.

## Key Files

| File | Description |
|------|-------------|
| `build-image.sh` | Native arm64 image build; requires `--release-id YYYY.MM.DD-NNN` |
| `fetch-base-image.sh` | Fetch/cache the exact HTTPS Ubuntu image and verify size + SHA-256 |
| `image-workspace.sh` | Disposable raw-image expansion, loop/mount lifecycle and fail-closed cleanup |
| `customize-rootfs.sh` | Native chroot ROS 2 Jazzy/ROSY installation and device-neutral systemd staging |
| `verify-mounted-image.py` | Read-only mounted-root package, unit, Docker and device-state checks |
| `finalize-image.sh` | Detached filesystem check, bmap creation and deterministic `.img.xz` compression |
| `create-image-manifest.py` | Unsigned manifest, SBOM, inventories, provenance and checksum handoff |
| `build-native-payload.sh` | Native ARM64 rosdep/colcon build and deterministic inventory export |
| `verify-package-inventory.sh` | Required-package and `ros2 pkg prefix` release-root readback |
| `required-ros-packages.txt` | Mandatory offline Pinky Pro ROS package set |
| `first-boot/` | Ubuntu one-shot identity, NetworkManager and Fleet-bootstrap applicator |
| `inputs.lock.yaml` | Pinned inputs; entries with `verified: false` block the build |
| `verify-inputs.sh` | Fails if lock entries are unverified or missing |
| `verify-artifacts.sh` | Post-build artifact checks (`BUILD_GO`) |

## Subdirectories

- `first-boot/` is staged in the immutable image overlay, outside the switchable
  application release, so an interrupted activation cannot remove recovery.

## For AI Agents

### Working In This Directory

- Do not add an x86 "release" path. Dev QEMU images are not shippable (design 7.1).
- D-161 supersedes the Raspberry Pi OS/container product mechanism. Docker remains development/CI-only and must not be introduced as an on-device product dependency.
- Required Pinky Pro ROS packages are an offline image payload; first boot must not download them.
- Keep the common `.img.xz` device-neutral. Identity, Wi-Fi and Fleet secrets
  enter only through the one-time post-write bundle owned by `deploy/robot/pinky_pro/sd`.
- A signature file's presence is not verification. The signed checksum,
  manifest identity and actual image hash must match before disk discovery.
- Signed base-image provenance, disposable raw-image workspace, native payload,
  release rollback and first-boot overlay staging are implemented. Full Ubuntu
  rootfs customization is still fail-closed in
  `build-image.sh`; `inputs.lock.yaml` retains unverified native-host inputs. Do not
  pretend a shippable image exists.
- Tests: `test/test_ubuntu_native_runtime_contract.py`, `test/test_image_pipeline.py`,
  `test/test_native_ros_payload.py`, `test/test_native_systemd_contract.py`,
  `test/test_native_release_activation.py`, `test/test_first_boot_provisioning.py`,
  `test/test_image_checks.py`.

### Testing Requirements

```bash
python3 -m pytest test/test_ubuntu_native_runtime_contract.py test/test_image_pipeline.py test/test_native_ros_payload.py test/test_native_systemd_contract.py test/test_image_checks.py -v
```

### Common Patterns

`set -euo pipefail`; `ROSY_DIST_DIR` defaults to repo `dist/`.

## Dependencies

### Internal

- Design: `docs/plans/2026-09-21-ubuntu-native-ros-runtime-design.md`
- Signing/storage in `deploy/robot/pinky_pro/release/`

### External

- Native aarch64 Ubuntu 24.04 build host, official Ubuntu Raspberry Pi image, ROS 2 Jazzy apt repository, OpenSSL

<!-- MANUAL: -->
