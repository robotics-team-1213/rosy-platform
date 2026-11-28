
# remote

**Parent context:** `../AGENTS.md`

## Purpose

Run pytest for one committed sha (D-584) on the model, AI or site PC with headroom (D-568), not the laptop; `--pick sim` names a Gazebo host. `remote_sim.py` (D-571) runs headless Gazebo benches. `tools/hooks/pre-push` and `tools/land.py` call it.

## For AI Agents

### Working In This Directory

- Only the committed sha is tested; commit before running. No local fallback: `--local` and `ROSY_TEST_LOCAL` are rejected; with no host reachable it exits "no test host reachable (D-584)".
- Hosts come from `ROSY_TEST_HOSTS`, else gitignored `private/lab-hosts.json` (shape: `hosts.example.json`); a worktree reads the main checkout's copy. Never commit it.
- `place()` skips hosts under the job floor or disk limits; the site PC (`SITE_HOST`, or any host with `~/rosy-jobs/site`) is used only when no other host fits. Locks, reservations and `busy` live in `~/rosy-jobs`.
- Never run a sim on a site host (`~/rosy-jobs/site`, D-571), even if `--pick sim` prints one; `remote_sim.py` refuses `--host site`. Before a demo or field drive, `touch ~/rosy-jobs/busy` on the site PC and remove it afterwards.
- A Gazebo script takes its host from `remote_pytest.py --pick sim`, writes `echo "$$ sim 6 8" > ~/rosy-jobs/sim-$$.lock` there and removes it on exit; `remote_sim.py` does both itself.
- The tool never installs (D-571). Sim capability (D-568 5) is a sudo step a person does (`rosy-host-state install <model|ai> --approve sim`, D-571 2). The site PC needs `uv python install 3.12` (no sudo) for pytest.
- Everything else on a host stays under `~/rosy-test` and `~/rosy-jobs`. Keep the legacy `~/rosy-test/venv` intact; never delete a hash-specific venv while its tests may run.
- Not in the default venv: Chromium (browser jobs install it; browser tests never run on the laptop, D-584), Pinky raw tools, CPU torch, ROS. Ask for `--test-tools pinky-raw` explicitly.
- xdist (D-799): suites in `serial_suites.txt` stay serial; remove a line only after a serial vs `-n` run on a test host gave the same failures.
- Flaky rerun (D-762): only failures listed in `test/flaky_quarantine.txt` rerun once; unlisted failures are never rerun, a lost rerun stays red.
- Lost contact exits 255 and leaves the job, lock and run directory on the host (no kill); a job gone without an exit code is 254. `land.py` stops on anything but 0/1.
- `prepare_test_workspace.py LABEL --owner OWNER --reason REASON [--sha REV]` makes disposable lab workspaces; the host storage timer deletes them (48 h empty, 72 h with a sha). Copy results out first.
- `omx_hotfix.py` deploys files to the site PC only and never starts an arm session. `deploy` refuses unless the tested log names the sha and its last pytest summary has no failure. The host comes from `--host` or `OMX_HOTFIX_HOST` only (D-226).
- `update_ops.py` (D-957) only starts the existing updater or sets holds; every surface's gates (idle, battery, signature, freeze) keep authority. Robot holds are `0<h<=168` hours; `forget-failed` is site-only.
- `site_map.py apply-time` (D-1021) is a dry run unless `--execute`. It refuses a host running rosy-core/rosy-io/rosy-navigation or with unreadable state; a Pinky only with `--robot-maintenance --host <robot> --robot-idle-confirmed <robot>`, one per run.
- `host_ops.py` (D-991) controls PC services when Fleet is down and keeps the Fleet screen's refusals. `fleet_robot_check.py` is read-only: no motion, no real-host access during development.
- Host needs: git, Python 3.12, `flock`, `systemd-run --user`, `nice`, `ionice`; OpenSSH key or Tailscale SSH.
- Change `private/site-map.yaml` in the same step as the site.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/remote-runner-check" -- test/test_remote_pytest.py test/test_remote_sim.py -q
```
