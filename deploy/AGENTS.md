<!-- Parent: ../AGENTS.md -->

# deploy

**Parent context:** `../AGENTS.md`

## Purpose

Deployment and provisioning surfaces for ROSY device and site hosts. Pinky builds a signed Ubuntu Server 24.04 arm64 image, activates native ROS 2 Jazzy releases, and runs CORE/I/O under least-privilege systemd services on Raspberry Pi 5 (D-161). The site path hosts Fleet, Vision, and Caddy separately. Host privilege stays in Host Agent, never in CORE. Docker Compose under `robot/` is development/CI compatibility; OMX OCI files are simulation preparation, not an accepted field actuator runtime.

Surfaces differ in host, lifecycle, and acceptance evidence; membership under `deploy/` does not imply one image, host, or release unit. Layout: `ls` and each subfolder's `AGENTS.md` (`robot/pinky_pro/`, `robot/omx/`, `site/`, `model_pc/`, `ai_pc/`). Neo 2 under `hosts/sdk/` is unsupported; `robot/rasptank_metal/` is a descriptor only.

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- CORE is internet-facing and unprivileged. Do not add `nmcli`, `reboot`, or docker-compose control inside `core`.
- Pinky runtime: `rosy-runtime.target` starts CORE and no-motion I/O. Motor drive needs commissioned device mode and an explicit drive flag; navigation stays separately approved and mutually exclusive with I/O.
- Compose services are test/development only; do not install Docker in a D-161 product image.
- Release images are built on native arm64, not x86 QEMU (`robot/pinky_pro/image/build-image.sh`).
- Native units use separate `rosy-core`/`rosy-io` users, closed device policy, `no-new-privileges`, hardened filesystems and CycloneDDS.
- Secrets and Wi-Fi credentials stay on the host (`/etc/rosy`), not in the image.
- Root `test/` is the contract suite; `test/conftest.py` puts `deploy/robot/pinky_pro/release` on `sys.path`.

### Testing Requirements

```bash
python3 -m pytest test/ -v
```

Pins: `test_dds_identity_contracts` (`.env.example` / `install-pi.sh` / `compose.yaml` identity), `test_release_boundary_guards`.

Contract: `docs/reference/rosy-host-agent-contract.md`.

<!-- MANUAL: -->
