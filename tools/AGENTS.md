<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-09-24 -->

# tools

## Purpose

Commands a developer runs from the workspace. These are not installed on the robot and they are not a ROS package.

## Key Files

| File | Description |
|------|-------------|
| `fix_ament_resource.sh` | Recreate `resource/<pkg>` markers under the domain groups |
| `run_fleet_sim.sh` | Start multi-robot Gazebo and the Fleet console from the repo root |
| `run_data.py` | Create `data/teleop` and `data/drive` sessions |
| `dashboard_drive.py` | Headless Playwright driver for the CORE dashboard: `status`, `mode`, `teleop` (stop latency), `screenshot` (skill `rosy-dashboard-drive`) |
| `web_visible_roles.py` | Role-surface measurement harness: real CORE TestClient + headless Chromium across roles, surfaces, and viewports; exit 1 on missing button kinds, page errors, horizontal overflow, or a failed first response |
| `harness/` | Module index generator (`rosy_harness.py`) |
| `hooks/` | D-346 pre-push fast gate (harness lint + contract suites, ~2 min) and its installer |
| `release/download_artifact.py` | Download one GitHub Actions artifact (`--run` + `--name`, or `--artifact-id`) in parallel resumable byte ranges with MB/rate/ETA progress, an exact API-size check and optional `--extract DIR` (CRC check, no path traversal). Token from `GH_TOKEN` or `gh auth token`; neither it nor the signed URL is printed. Stdlib only; test `test/test_download_artifact.py` |
| `release/prepare_payload_release.py` | One command from a `build-native-payload.yml` run to a signed payload tarball: download (via `download_artifact.py`) or `--artifact-dir`, required-package check, read-only per-robot ROS ABI check over SSH (`--robot`, `--skip-abi`), atomic extract (refuses an existing dir), sign, pack, then prints the `rosy-release-push.ps1` lines. Never pushes. Test `test/test_prepare_payload_release.py` |
| `release/publish_payload_release.py` | D-406: publish a prepared signed tarball as GitHub Release `payload-<id>` with a signed `rollout.json` (sorted keys, LF), watch the canary's `rosy_auto_update.py status --json` over SSH, then re-sign with `canary_ok=true` or `withdrawn=true`; `--resume`, `--withdraw --reason`. Audit JSONL under `X:\DevTemp\rosy-rollout-evidence`. Fake `gh`/ssh/clock in test `test/test_publish_payload_release.py` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `harness/` | Reads each module's `progress.md` and `logs.md` |
| `sim/` | Local sim probes, `sim_verify.sh`, and host simulations that compose several packages (`simulate_line_follow.py`, `simulate_semantic_road.py`). Not a second product tree |
| `perception/` | D-356 learned-loop tooling: `dataset/`, `model/`, `training/`, `test/` (see `perception/AGENTS.md`) |
| `calibration/` | D-47 addendum 2026-10-01: `run_calibration.py` (protocol v1, one command, `--dry-run`/`--offline`), `analyze_session.py` (wheel/LiDAR-yaw/camera fits from recordings), `store_cli.py` (list/accept/reject/pin), `test/` |
| `perception/prototype/` | Unreviewed camera-estimation and real-video replay prototypes (D-205). Replaced by the reviewed P2 replay tool |

## For AI Agents

### Working In This Directory

- Placement rule: a script that serves one module and imports no other package (its own test launches it, or it only measures that module) lives in that module's `tools/`, e.g. `src/site/fleet/tools/fleet_gather_bench.py`. A script that composes several packages lives in a root group even if one module's test launches it — putting it inside a package would add an undeclared cross-package import (`test_every_cross_package_use_is_declared`); e.g. `tools/sim/simulate_line_follow.py` and `simulate_semantic_road.py` compose control with core, core_events and core_features. Root `tools/` keeps workspace entry points (`fix_ament_resource.sh`, `run_fleet_sim.sh`, `run_data.py`, `dashboard_drive.py`, `fleet_console.ps1`) and cross-module groups (`harness/`, `perception/`, `sim/`).
- A script that one module installs or that its own test launches stays in that module. `bringup/scripts/rosy_env.sh` and `control/tools/gz/run_track260905.sh` are examples.
- Robot install and image build stay in `deploy/`.
- Do not put teleop notes or drive bags here. Session files go under `data/teleop` and `data/drive` and stay untracked. Learning clips stay in `data/teleop/learning/`.

### Testing Requirements

```bash
python -m pytest test/architecture/test_folder_layout.py test/test_run_data.py test/test_download_artifact.py test/test_prepare_payload_release.py test/test_publish_payload_release.py -q
```

### Common Patterns

Shell scripts compute the repo root from their own path. They do not embed a machine-specific absolute path.

## Dependencies

### Internal

- `src/sim/gz_sim` for `run_fleet_sim.sh`
- `data/` for `run_data.py`

### External

- ROS 2 Jazzy when running the fleet sim

<!-- MANUAL: -->
