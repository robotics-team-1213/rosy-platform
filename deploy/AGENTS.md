<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-22 -->

# deploy

## Purpose

Robot-host delivery: build a signed Ubuntu Server 24.04 arm64 ROSY OS image,
store/activate native ROS 2 Jazzy releases, and run CORE/I/O under least-privilege
systemd services on Raspberry Pi 5 (D-161). Host privilege stays in Host Agent,
never in CORE. Docker Compose is development/CI-only.

## Key Files

Three sibling pipelines below; at this level only the harness records.

| File | Description |
|------|-------------|
| `progress.md` | Current gate snapshot (ARTIFACT/DEVICE). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `image/` | Native aarch64 image build + input/artifact verification (see `image/AGENTS.md`) |
| `release/` | Manifest, signing, storage, updater, Host Agent (see `release/AGENTS.md`) |
| `robot/` | Native product systemd runtime plus development-only Docker/Compose compatibility tools (see `robot/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- CORE is internet-facing and unprivileged. Do not add `nmcli`, `reboot`, or docker-compose control inside `core`.
- Product runtime: `robot/native/rosy-runtime.target` starts CORE only. I/O and navigation are explicit, mutually exclusive hardware modes.
- Compose services remain test/development compatibility only; do not install Docker in a D-161 product image.
- Release images must be built on native arm64, not x86 QEMU (`deploy/image/build-image.sh`).
- `test/` at repo root is the contract suite for this tree; `test/conftest.py` puts `deploy/release` on `sys.path`.

### Testing Requirements

```bash
python3 -m pytest test/ -v
# notable modules: test_host_agent, test_release_*, test_image_*, test_robot_runtime,
# test_pi_wifi_deployment, test_network_*, test_release_boundary_guards,
# test_dds_identity_contracts (pins .env.example / install-pi.sh / compose.yaml identity)
```

### Common Patterns

- Native units use separate `rosy-core`/`rosy-io` users, closed device policy,
  `no-new-privileges`, hardened filesystems and CycloneDDS.
- Secrets and Wi-Fi credentials stay on the host (`/etc/rosy`), not in the image.

## Dependencies

### Internal

- Native payload build context is the repo root (`src/` packages).
- Contract: `docs/reference/rosy-host-agent-contract.md`

### External

- systemd, OpenSSL 3 (Ed25519), Ubuntu Server 24.04 arm64, ROS 2 Jazzy.
  Docker Compose is optional development/CI tooling.

<!-- MANUAL: -->
