<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# omx

## Purpose

Workstation development and simulation preparation for the OMX-AI workcell: a separate ROS 2 Jazzy OCI image built from an immutable ROBOTIS source lock, host-inventory placement preflight, and Gazebo/pilot probe scripts. It is not part of the Pinky Pi image and not an accepted field actuator runtime. The runtime profile stays disabled (no joint map, hardware plugin, serial or camera identity). Field control is one native systemd instance per workcell (D-246).

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Current contract, host inventory, multi-workcell preflight, build and probe usage |
| `stack.lock.yaml` | Pins the official ROBOTIS source set to immutable revisions |
| `fetch_sources.py` | Fetches the locked sources into the build context |
| `Dockerfile`, `Dockerfile.pilot` | Workstation image and pilot-simulation image |
| `compose.yaml`, `entrypoint.sh` | Development container shell and entrypoint |
| `host_inventory.py`, `host-inventory.yaml.example` | Static `rosy.omx-host-inventory.v1` loader and a disabled placement template |
| `preflight.py` | Multi-workcell preflight over the host inventory |
| `run_pilot_sim.sh`, `probe_*.py`, `probe_*.sh` | Simulation and pilot probes (vendor owner, Fleet ROS vendor sim, pilot HTTP, pilot recording) |
| `requirements-lerobot-export.txt` | Python deps for demonstration export |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `patches/` | Source patches applied on top of the locked ROBOTIS sources (action-only, sim gates, headless Gazebo) |
| `sim/` | Simulation cell profile (`cell_profile.yaml`) |

## For AI Agents

### Working In This Directory

- Keep OMX inputs here; do not move them under `pinky_pro/` and do not add ARM64 product-image content.
- Change `stack.lock.yaml` only to another immutable revision; never a branch name.
- Do not enable a runtime profile or invent joint, serial, or camera identities. Those need device acceptance first.
- Example/template files must stay free of real hosts, addresses, and credentials (public repo).

### Testing Requirements

```bash
python3 -m pytest test/test_omx_workstation.py test/test_omx_host_inventory.py \
  test/test_omx_multi_preflight.py test/test_omx_vendor_stack_lock.py -q
python3 -m pytest test/architecture/test_document_placement.py -q
```

### Common Patterns

- Static YAML contracts with a schema id (`rosy.omx-host-inventory.v1`) validated by a loader, checked by the tests above.
- Evidence from probe runs goes to `docs/validation/`, not here.

## Dependencies

### Internal

- `src/products/omx/` (adapter and packages), `docs/plans/2026-09-26-omx-ai-workstation-runtime.md`, `docs/plans/2026-09-26-site-host-placement-design.md`

### External

- ROBOTIS `open_manipulator` ROS 2 packages (pinned), ROS 2 Jazzy, Docker/OCI, Gazebo for sim probes
