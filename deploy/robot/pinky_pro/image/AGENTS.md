<!-- Parent: ../AGENTS.md -->

# image

**Parent context:** `../AGENTS.md`

## Purpose

Build a signed Ubuntu Server 24.04 LTS arm64 ROSY OS release image with native ROS 2 Jazzy on **native aarch64**. Scripts refuse x86/QEMU release hosts. Inputs are pinned in `inputs.lock.yaml` (`verified: false` blocks the build); `verify-artifacts.sh` is the go/no-go, not the file's existence. D-164: artifact is `rosy-os-pinky-pro-<release-id>-arm64.img.xz`; a generic installer ISO is not a release artifact. Design: `docs/plans/2026-09-21-ubuntu-native-ros-runtime-design.md`.

## For AI Agents

### Working In This Directory

- Do not add an x86 "release" path. Dev QEMU images are not shippable (design 7.1).
- D-161 supersedes the Raspberry Pi OS/container mechanism. Docker is development/CI-only, never an on-device product dependency.
- Required ROS packages (`required-ros-packages.txt`) are an offline image payload; first boot must not download them.
- Keep the common `.img.xz` device-neutral. Identity, Wi-Fi and Fleet secrets enter only through the one-time post-write bundle owned by `deploy/robot/pinky_pro/sd`.
- `first-boot/` is staged in the immutable image overlay, outside the switchable release, so an interrupted activation cannot remove recovery.
- A signature file's presence is not verification: signed checksum, manifest identity and actual image hash must match before disk discovery.
- Full Ubuntu rootfs customization is still fail-closed in `build-image.sh`; `inputs.lock.yaml` keeps unverified native-host inputs. Do not pretend a shippable image exists.
- Scripts use `set -euo pipefail`; `ROSY_DIST_DIR` defaults to repo `dist/`; signing/storage lives in `deploy/robot/pinky_pro/release/`.

### Testing Requirements

```bash
python3 -m pytest test/test_ubuntu_native_runtime_contract.py test/test_image_pipeline.py test/test_native_ros_payload.py test/test_native_systemd_contract.py test/test_image_checks.py -v
```

Also `test_native_release_activation.py`, `test_first_boot_provisioning.py`.

<!-- MANUAL: -->
