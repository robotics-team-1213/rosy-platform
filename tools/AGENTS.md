
# tools

**Parent context:** `../AGENTS.md`

Commands a developer runs from the workspace; not installed on the robot, not a ROS package. Usage lives in each script's docstring and `--help`; `ls` lists them.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `harness/` | D-61 module harness and affected-test selector (`harness/AGENTS.md`) |
| `hooks/` | D-346 pre-push fast gate (`hooks/AGENTS.md`) |
| `remote/` | `remote_pytest.py` on lab test PCs, never laptop pytest (D-584) |
| `release/` | Artifact download, signed payload prep (`release/AGENTS.md`) |
| `sim/` | Host sims composing several packages; not a second product tree |
| `capture/` | Supervised edge-capture drives over CORE API (`capture/AGENTS.md`) |
| `device_test/` | D-512 agent-run device test (`device_test/AGENTS.md`) |
| `calibration/` | D-47 `run_calibration.py` (`--dry-run`, `--offline`) (`calibration/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Placement: a script serving one module that imports no other package lives in that module's `tools/`. One that composes several packages lives in a root group here; inside a package it adds an undeclared cross-package import.
- Robot install and image build stay in `deploy/`. Session files go under `data/teleop`, `data/drive` (untracked), never here.
- `pr_land.py` and pre-push refuse a commit lacking a Safety-Review trailer on a safety path (D-430); `publish_main.py` re-checks Safety-Review on its range.
- `land_isolation.py`: an alone-run test of a safety-tagged source that was not reached stops the landing. Close an open record only by running its files.
- `land_isolation` and `rosy-land-events.jsonl` have no backup: a known single point of loss.
- `land_logs.py`: a `logs.md` conflict where a side edited, dropped or reordered a base entry needs a human.
- `publish_main.py` (D-868): dry run unless `--apply`. It never syncs, forces, closes or reopens. A secret-scan hit exits 9 (commit, path, rule, never the value). Needs a green FULL land record for the SHA and a Safety-Review check of its range.
- `publish_main.py --merge-when-green` merges only when mergeable and `ci-result` is green.
- `worktrees.py` (D-761/D-1070): cap 14 + main (D-886); `prune --apply` archives unlanded idle branches to `refs/archive/`, never deletes teammate branches.
- `release/publish_payload_release.py` (D-412): a canary timeout before start exits 4 and changes nothing (D-985); `--withdraw --reason` retracts.
- `ssh/rosy_ssh_*.py` (D-418): tokens and login codes are never printed; the share zip never holds the passphrase.
- Shell scripts compute the repo root from their own path; no machine-specific absolute paths. `graphify_pipeline.py`: [analysis artifact locations](../docs/reference/analysis-artifact-locations.md); never recreate `graphify-out` beside source.
- Retired WSL sync scripts are frozen in `docs/reference/legacy-tools/wsl`; use `remote/` and `deploy/`.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/tools-check" -- test/architecture/test_folder_layout.py test/test_run_data.py test/test_pr_land.py -q
```

JPEG relay source belongs to `integrations/simulation/gazebo/scripts/sim_jpeg_relay.py`; review smoke to `learning/curation/perception/tools/review_app_smoke.py`.
