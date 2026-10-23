<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# omx

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

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
| `joint_tune.py` | Follower joint commissioning (IDs 11-16): bounded move of one joint (sag check at torque ON), gripper sweep of its ends; temporary limits/gains, always torque OFF and restored, camera frames per settled position |
| `record_session.py` | One leader→follower LeRobot record/teleoperate session: follower caps raised only for the run, camera services handed over and back, always torque OFF and caps restored |
| `leader_actuator.py` | Drive the Leader as a commanded reference arm under an explicit hands-off attestation: caps raised with torque OFF and read back, Follower-alignment rate, load and hardware-error stops, torque OFF and the found caps restored on every exit (D-846) |
| `two_arm_config.py` | Configuration, Follower caps and gains, Leader gravity bias and the pose/bus helpers shared by the pipeline: schema check, per-arm bus ownership, saved-then-restored servo state (D-846, D-847) |
| `two_arm_pipeline.py` | D-846 two-arm pipeline: `preflight`/`gap`/`park`/`align`/`drive`/`verify` stages, per-stage JSON receipts, a blocked-joint load diagnosis, and the Follower mirroring the Leader's relative motion through the existing follower guard |
| `task-card.example.yaml` | Task card template (`rosy.omx-task-card.v1`): task text, episode timing, dataset name and design; plugged in with `record_session.py --task-card` |
| `omx_autoupdate.py`, `rosy-omx-autoupdate.{service,timer}`, `omx-autoupdate.json.example` | Native release updater for the cell's tools: newest main with green `ci-result`, unpacked to `~/rosy-omx/releases/<sha12>`, `current` switched atomically only while idle (no session lock, devices free, follower torque OFF), smoke check and rollback. `"kind": "service"` runs the same steps for a host service (AI PC rosy-situation, D-805): config paths/smoke, optional lock, unit restart + health check |
| `requirements-cell.lock` | Exact package set of the verified cell venv (LeRobot 0.4.4, CPU torch); omx_autoupdate.py builds one venv per hash of it |
| `requirements-lerobot-export.txt` | Python deps for demonstration export |
| `sim_reach_task.py`, `sim/reach_task.example.json` | `rosy.omx-sim-reach-task.v1` reach-task validator, seeded start sampling, greedy jog plan and readback judge (stdlib; shared with batch export and the evaluator) |
| `sim_reach_teacher.py` | Scripted SIM teacher over Pilot HTTP: unrecorded reset, recorded greedy jogs, automatic `task_outcome` from joint readback, lease renewal, no goal retry; writes `rosy.omx-sim-reach-teacher-results.v1`. Test `test/test_omx_sim_reach_teacher.py` |

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
