<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-08 | Updated: 2026-10-09 -->

# remote

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-09

## Purpose

Run pytest for one commit on whichever of the model PC (OMEN), AI PC and site PC has headroom (D-568), instead of the Windows laptop, and tell Gazebo scripts which host to use (`--pick sim`). `tools/hooks/pre-push` and `tools/land.py` use it.

## Key Files

| File | Description |
|------|-------------|
| `remote_pytest.py` | Measures every host in `ROSY_TEST_HOSTS` (default `rosy@100.98.162.71 ai@100.108.76.123 robttt@100.82.51.8`) with one ssh `PROBE` (nproc, load1, MemAvailable/MemTotal, Python 3.12 at `/usr/bin/python3` or `~/.local/bin/python3.12`, ROS `ros_gz_sim`+`nav2_bringup`, `~/rosy-jobs/busy`, `~/rosy-jobs/site`, live `~/rosy-jobs/*.lock` and unexpired `*.resv` budgets; dead-pid locks and expired reservations removed; only the `ROSYPROBE` line is parsed) and `place()`s a job class (`NEEDS`: pytest 2 cores/6 GB, sim 6 cores/8 GB) on hosts above the floor, most headroom first; a site host (`SITE_HOST` or any host with `~/rosy-jobs/site`, whatever its ssh name) minus a Fleet reserve of 2 cores/4 GB, only when no other host fits. Every host decision is printed to stderr. If no host is above the pytest floor it uses the reachable non-site hosts anyway (warning); sim never falls back. `--pick sim|pytest` prints only the chosen host (exit 1 if none) and reserves its budget there for 10 min (`pick-*.resv`). Several invocations are spread over the chosen hosts at once (`k % n`, codes in invocation order, D-553), writes a 75-min reservation `~/rosy-jobs/<run>.resv` and ships the commit as a git bundle into `~/rosy-test/repo` (a clone of the public origin), checks it out as a detached worktree under `~/rosy-test/runs/`, runs each invocation with `-q -rfE -p no:cacheprovider` under `systemd-run --user --scope -p MemoryMax=6G` (site PC adds `CPUQuota=400%`) and `nice -n 15 ionice -c3`, holding `~/rosy-jobs/<run>.lock` (`<pid> pytest 2 6`, replaces the reservation), copies each log back and removes the worktree. Venvs `~/rosy-test/venvs/<deps-sha>` (no system site-packages) follow the CI test-job install (`device-python-requirements.txt`, test tools, receiver crypto, platform wheels) plus the `deploy/site/requirements-fleet.txt` pins the device set lacks and pip numpy/pillow/opencv-python-headless for CI's apt packages and the playwright package (no browser; `*_browser.py` import it at collection), end with `pip check`, and are built once per input hash. Different hashes do not block each other's pytest. Every ssh step (copy, venv, cleanup) runs under `nice -n 15 ionice -c3`; on a site host also inside `systemd-run --user --scope -p MemoryMax=6G -p CPUQuota=400%`. No reachable host fails the gate; `--local` or `ROSY_TEST_LOCAL=1` is for explicit diagnostics. Test `test/test_remote_pytest.py` |

## For AI Agents

### Working In This Directory

- Only the committed sha is tested; commit before running. The local fallback tests the working tree.
- A Gazebo script takes its host from `python tools/remote/remote_pytest.py --pick sim`, writes `echo "$$ sim 6 8" > ~/rosy-jobs/sim-$$.lock` on that host and removes it on exit. Before a demo or field drive, `touch ~/rosy-jobs/busy` on the site PC; remove it afterwards.
- The tool never installs: sim capability (`ros-jazzy-ros-gz ros-jazzy-navigation2 ros-jazzy-nav2-bringup ...`, D-568 5) is a sudo step a person does. The site PC (Ubuntu 26.04, system Python 3.14) needs `uv python install 3.12` (no sudo) for pytest; it has it since 2026-10-09 and carries the `~/rosy-jobs/site` marker. Put that marker on any host that runs live Fleet.
- Everything else on a host stays under `~/rosy-test` (and `~/rosy-jobs` for locks). Do not install anything else there; another person uses the AI PC GPU and other sessions run Gazebo on the model PC.
- Other sessions run `~/rosy-test/venv/bin/python` directly. Keep that legacy environment intact. Never delete a hash-specific venv while its tests may run; prune unused hashes by hand.
- Not shipped by the venv: the Chromium browser (so `--browser` runs stay local), the Pinky raw tools and CPU torch (CI installs them only for those suites), and ROS (not sourced, as on the laptop).

### Testing Requirements

```bash
python -m pytest test/test_remote_pytest.py -q
```

## Dependencies

### External

- OpenSSH client with key or Tailscale SSH login to the hosts; on each host git, Python 3.12 (`/usr/bin/python3` or uv's `~/.local/bin/python3.12`), `flock`, `systemd-run --user`, `nice`, `ionice`, optional `uv`

<!-- MANUAL: -->
