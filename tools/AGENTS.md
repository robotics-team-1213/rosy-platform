<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-09-24 -->

# tools

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

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
| `worktree_rules.py` | D-790 rules `worktrees.py` and `land.py` share: landed clean worktrees wait 1 h, `stale_history` (more than 2,000 commits not in main or a fork at/before the history rewrite `ad86fca808`), orphan summary, zip archive under `$ROSY_SCRATCH/worktree-orphans/` verified before removal. Test `test/test_worktrees_tool.py` |
| `land_checks.py` | D-790 `land.py` helpers: NEW failures (1-5, not under a safety root) rerun once each alone; all passing -> `LOAD-FLAKY`, landing continues, ids appended to `<git-common-dir>/rosy-flaky-candidates.txt` for review; a stopping round's NEW ids rerun once on `main` and the ones red there too print as `MAIN-RED` (main is broken: fix main in a small branch first; still not landing); scratch folder and origin distance. Test `test/test_land.py` |
| `land_cache.py` | `land.py` pytest invocations passed across runs, in `<git-common-dir>/rosy-land-cache.jsonl` (JSON lines, bad lines ignored, trimmed past 2,000): reused when the same argv passed on the same git tree with the same `remote_pytest.deps` hash, or (`--tests auto`) on an ancestor whose delta the D-436 selector maps to none of its paths (not FULL, no delete/rename, known-failure lists unchanged; then no land record for pre-push). Each invocation's clean pass (0 NEW, no LOAD-FLAKY, its own evidence usable) is kept even when another invocation of the run failed; invocations whose last run had a NEW failure are marked in `rosy-land-failed.json` and run alone first; lint, safety-review, size-range and node always run; `--no-cache` turns it off. Test `test/test_land.py` |
| `worktrees.py` | D-761/D-790 worktree gateway: `new <short-name> <type>/<topic>` (type check, report of removable worktrees, cap 50, `--prune`, `--force-over-cap`, owner note in `branch.<b>.description`), `prune [--apply] [--snapshot] [--all] [--idle-hours N]` (any owner's when clean + merged + unlocked + no ignored data + idle 72 h, the caller's own at once when its branch also has a commit of its own in the reflog; `--snapshot`, for a person or the dispatcher, takes the caller's own dirty or unmerged ones unless `--all`, keeps uncommitted work under `refs/wip/<date>/<name>` and keeps unmerged branches), `status` (dot-named entries and plain files under `.worktrees/` are not listed or counted; owner or `unknown`, whether the caller may remove, verdicts incl. `orphan` with its content, `landed-dirty`, `stale-history`). D-790: anyone's landed clean worktree goes after 1 h, orphans are removed or archived and verified, `new --from REF` refuses a stale-history ref, `new --owner`, the cap refusal names each removable worktree. `land.py` reports removable worktrees at the start of a landing (`--prune` applies) and harness lint warns at the cap. Test `test/test_worktrees_tool.py` |
| `land.py` | D-510/D-762 stage 0 local landing from a topic worktree: waits its turn in the D-803 landing queue (`land_queue.py`; `--queue-timeout`, `--no-queue` for incidents), then merge `main`, lint, the D-430 §5 `Safety-Review` rule (`harness/safety_review.py`) on the commits the landing adds, the affected tier on the lab PCs (`remote/remote_pytest.py`) plus the real-Chromium tests `test/browser_scope.py` maps the changed paths to (run with `ROSY_RUN_BROWSER_TESTS=1`, never all browser suites), `known_failures` compare, `--ff-only`. A FULL selection (folder moves, removed modules, packaging/source layout, harness and guard rules, CI workflows, shared foundation code) runs the lab full tier (`full_invocations`: CI's full matrix unsharded, root `test/`, every registered module suite and the selection's own suites) and lands only with 0 NEW, printing its wall-clock time; when main moves, later rounds, and a later run whose branch added only merges of main since (`land_full.py`), run only the selection of main's delta since the FULL-tested main; no host means no landing (D-584). After landing it reports how far local `main` is ahead of `origin/main`. Never pushes. Tests `test/test_land.py`, `test/test_land_record.py` |
| `packaging/fleet_sources.py` | D-652 Fleet build-time holder/wheel/sdist composition; source archive embeds its own `_build` copy, installed runtime excludes build support |
| `hooks/` | D-346 pre-push fast gate (harness lint + contract suites, ~3 min) and its installer |
| `land_queue.py` | D-803 landing queue for `land.py`: one FIFO ticket per run under `<git-common-dir>/rosy-land-queue/` (`<start ns>-<pid>.json`: pid, host, start, branch, status `preparing`/`waiting`/`turn`; written by rename). A turn starts when no ticket is in its turn and no earlier ticket is waiting; a `preparing` ticket (its FULL tier before the turn) keeps its place and blocks no one, position and who is ahead printed while waiting, `QueueError` after the timeout; stale tickets (PID gone on this host, or not refreshed for 3 h) removed by the next reader; released from `land.main`'s `finally` and `atexit`. Tests `test/test_land_queue.py`, `test/test_land.py` |
| `jira_refs.py` | Jira 키 관례(`docs/reference/atlassian-integration.md`): `check`는 브랜치·커밋 메시지의 키를 알려 주기만 하고 `--strict`일 때만 exit 1, `report --range A..B`는 범위의 커밋을 키별로 묶은 Markdown/JSON 표(스프린트 리뷰용). git 기록만 읽고 네트워크·토큰을 쓰지 않는다. Stdlib only; test `test/test_jira_refs.py` |
| `land_logs.py` | `land.py`'s logs.md conflict rule: `## ` entries compared as multisets with the merge base (a side may move only its own new entries; an edited, dropped or reordered base entry needs a human; an entry new on both sides is kept once), the other side's new entries inserted in date order after the last base entry so lint's date order holds. Test `test/test_land.py` |
| `land_merge.py` | `land.py`'s conflict auto-resolution, split from `land.py` (pure move): which conflicted paths it resolves (ADR Log rows union + sort, `logs.md` via `land_logs.py`, `adr_gaps.txt` union, `index.md`/generated files take main's side) and the bytes; `plan` touches nothing, `land.merge` applies it. `landed_gaps`: after a merge of main, `land.py` drops and commits `adr_gaps.txt` lines whose ADR now exists (merge=union brings them back). Test `test/test_land.py` |
| `land_events.py`, `land_stats.py` | What each `land.py` run did, one JSON line per event in `<git-common-dir>/rosy-land-events.jsonl` (queue, turn, round, tests with verdict pass/flaky/new/unusable, landed, stop); `land_stats.py [--days N] [--json]` prints per day landings, stops, queue wait and turn p50/p90 and the new/flaky/unusable share of judged invocations. Writing never stops a landing. Test `test/test_land_events.py`, `test/test_land.py` |
| `land_full.py` | D-803 6: a branch's green FULL tier outlives the `land.py` run that passed it. Records the FULL-tested candidate and main in `<git-common-dir>/rosy-land-full/<branch>.json`; a later run reuses that main (main-delta selection only) while the candidate is in HEAD, the recorded main is in `main`, and the branch added only merges of main equal to git's own merge (or differing only in auto-resolved records); removed on landing. Test `test/test_land.py` |
| `land_guards.py` | `land.py`'s guard round: with `--tests auto`, `test/architecture` and `test/test_harness_contracts.py` run first on the lab PCs and a NEW failure stops before the long round (a main move meanwhile starts the next round); skipped when the selection is guards only. Test `test/test_land.py` |
| `release/download_artifact.py` | Download one GitHub Actions artifact (`--run` + `--name`, or `--artifact-id`) in parallel resumable byte ranges with MB/rate/ETA progress, an exact API-size check and optional `--extract DIR` (CRC check, no path traversal). Token from `GH_TOKEN` or `gh auth token`; neither it nor the signed URL is printed. Stdlib only; test `test/test_download_artifact.py` |
| `release/prepare_payload_release.py` | One command from a `build-native-payload.yml` run to a signed payload tarball: download (via `download_artifact.py`) or `--artifact-dir`, required-package check, read-only per-robot ROS ABI check over SSH (`--robot`, `--skip-abi`), atomic extract (refuses an existing dir), sign, pack, then prints the `rosy-release-push.ps1` lines. Never pushes. Test `test/test_prepare_payload_release.py` |
| `ssh/rosy_ssh_enroll.py` | D-418 1: give this PC its own ed25519 key on one robot via an administrator login code (`POST /api/v1/host/ssh/keys`, label `dev:<name>`), host keys into `~/.ssh/known_hosts_rosy`, an idempotent managed `Host` block in `~/.ssh/config`, token logged out in `finally` and never printed. Stdlib + OpenSSH; Windows/macOS/Linux. Fake CORE in test `test/test_rosy_ssh_enroll.py` |
| `ssh/rosy_ssh_core.py` | D-418: the HTTPS CORE client both ssh tools load by path (pinned certificate via `--ca-file`, `--insecure` on a bench LAN, no redirects, no env proxies); not a command |
| `ssh/rosy_ssh_share.py` | D-418 3: `create` a passphrase-locked team key (OpenSSH bcrypt checked before anything is registered), register `team:<name>` on each `--robot`, build flat `rosy-<team>.zip` that unpacks to the `~/.ssh/rosy-<team>/` its config names (key, config, known_hosts, Korean README; never the passphrase) plus a non-secret `rosy-<team>.robots.txt` with the revoke command; `revoke --name|--label`, `list`; `--via-operator-key` reads the login code over ssh. Test `test/test_rosy_ssh_share.py`. Guide `docs/deployment/robot-ssh-access.md` |
| `release/publish_payload_release.py` | D-412: publish a prepared signed tarball as GitHub Release `payload-<id>` with a signed `rollout.json` (sorted keys, LF), watch the canary's `rosy_auto_update.py status --json` over SSH, then re-sign with `canary_ok=true` or `withdrawn=true`; `--resume`, `--withdraw --reason`. Audit JSONL under `$ROSY_SCRATCH/rosy-rollout-evidence`. Fake `gh`/ssh/clock in test `test/test_publish_payload_release.py` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `harness/` | Reads each module's `progress.md` and `logs.md` (see `harness/AGENTS.md`) |
| `hooks/` | D-346 pre-push fast gate and its installer (see `hooks/AGENTS.md`) |
| `remote/` | `remote_pytest.py`: run pytest for one commit on the model PC, AI PC or site PC by measured headroom, `--pick sim` for Gazebo hosts (D-568), never falls back to laptop pytest (D-584) (see `remote/AGENTS.md`) |
| `release/` | Artifact download and signed payload preparation (see `release/AGENTS.md`) |
| `sim/` | Local sim probes, `sim_verify.sh`, and host simulations that compose several packages (`simulate_line_follow.py`, `simulate_semantic_road.py`). Not a second product tree (see `sim/AGENTS.md`) |
| `perception/` | `rosy_ml.py` and operator SSH orchestration across curation/registry/training/evaluation; no runtime writer (see `perception/AGENTS.md`) |
| `perception_prototype/` | Unreviewed camera-estimation and real-video replay prototypes (D-205). Replaced by the reviewed P2 replay tool (see `perception_prototype/AGENTS.md`). The reviewed replay is in `learning/evaluation/perception/`; data, artifacts and trainers have separate learning owners (D-637) |
| `capture/` | Supervised edge-capture drives over the CORE API (`edge_drive.py`: nudge with an advisory D-424 body check, CAMERA_LINE capture drive, recording start/stop, exposure watch); see `capture/AGENTS.md` |
| `device_test/` | D-512 agent-run device test: `run.py --robot <name> --plan plans/<plan>.yaml` (`--preflight-only`, then `--camera-verdict`), temporary CORE overlay with readback and byte-exact restore, D-379 recording, 10 Hz status/events JSONL, `summary.json` with `sha256:` digests (see `device_test/AGENTS.md`) |
| `calibration/` | D-47 addendum 2026-10-01: `run_calibration.py` (protocol v1, one command, `--dry-run`/`--offline`), `analyze_session.py` (wheel/LiDAR-yaw/camera fits from recordings), `store_cli.py` (list/accept/reject/pin), `test/` (see `calibration/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Placement rule: a script that serves one module and imports no other package (its own test launches it, or it only measures that module) lives in that module's `tools/`, e.g. `operations/fleet/tools/fleet_gather_bench.py`. A script that composes several packages lives in a root group even if one module's test launches it — putting it inside a package would add an undeclared cross-package import (`test_every_cross_package_use_is_declared`); e.g. `tools/sim/simulate_line_follow.py` and `simulate_semantic_road.py` compose control with core, core_events and core_features. Root `tools/` keeps workspace entry points (`fix_ament_resource.sh`, `run_fleet_sim.sh`, `run_data.py`, `dashboard_drive.py`, `fleet_console.ps1`) and cross-module groups (`harness/`, `sim/`).
- A script that one module installs or that its own test launches stays in that module. `bringup/scripts/rosy_env.sh` and `tools/sim/gazebo/run_track260905.sh` are examples.
- Robot install and image build stay in `deploy/`.
- Do not put teleop notes or drive bags here. Session files go under `data/teleop` and `data/drive` and stay untracked. Learning clips stay in `data/teleop/learning/`.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/tools-check" -- test/architecture/test_folder_layout.py test/test_run_data.py test/test_download_artifact.py test/test_prepare_payload_release.py test/test_publish_payload_release.py test/test_rosy_ssh_enroll.py test/test_rosy_ssh_share.py -q
```

### Common Patterns

Shell scripts compute the repo root from their own path. They do not embed a machine-specific absolute path.

Use `python tools/graphify_pipeline.py build` for the CORE code-only trial and `query --run <run-path> <symbol>` for freshness-checked reads. Outputs use `DEV_SESSION` when available, otherwise the developer PC's user cache; `--output` overrides the parent outside the repository. The child process receives `GRAPHIFY_OUT` and `PYTHONPYCACHEPREFIX`. Follow [analysis artifact locations](../docs/reference/analysis-artifact-locations.md). Do not recreate `graphify-out` beside source or change global settings for other projects. CLI smoke success does not establish retrieval quality or replace harness test selection.

## Dependencies

### Internal

- `integrations/simulation/gazebo` for `run_fleet_sim.sh`
- `data/` for `run_data.py`

### External

- ROS 2 Jazzy when running the fleet sim

<!-- MANUAL: -->

JPEG relay source belongs to `integrations/simulation/gazebo/scripts/sim_jpeg_relay.py`; review smoke belongs to `learning/curation/perception/tools/review_app_smoke.py`. Retired WSL synchronization scripts are frozen in `docs/reference/legacy-tools/wsl`; use current remote and deployment tools.
