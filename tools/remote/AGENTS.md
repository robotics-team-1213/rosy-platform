<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-08 | Updated: 2026-10-08 -->

# remote

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-08

## Purpose

Run pytest for one commit on the model PC (OMEN), then the AI PC, instead of the Windows laptop. `tools/hooks/pre-push` and `tools/land.py` use it.

## Key Files

| File | Description |
|------|-------------|
| `remote_pytest.py` | Picks the first reachable host in `ROSY_TEST_HOSTS` (default `rosy@100.98.162.71 ai@100.108.76.123`, 5 s ssh probe), ships the commit as a git bundle into `~/rosy-test/repo` (a clone of the public origin), checks it out as a detached worktree under `~/rosy-test/runs/`, runs each invocation with `-q -rfE -p no:cacheprovider` under `systemd-run --user --scope -p MemoryMax=6G`, copies each log back and removes the worktree. Venvs `~/rosy-test/venvs/<deps-sha>` (no system site-packages) follow the CI test-job install (`device-python-requirements.txt`, test tools, receiver crypto, platform wheels) plus the `deploy/site/requirements-fleet.txt` pins the device set lacks and pip numpy/pillow/opencv-python-headless for CI's apt packages and the playwright package (no browser; `*_browser.py` import it at collection), end with `pip check`, and are built once per input hash. Different hashes do not block each other's pytest. No reachable host fails the gate; `--local` or `ROSY_TEST_LOCAL=1` is for explicit diagnostics. Test `test/test_remote_pytest.py` |

## For AI Agents

### Working In This Directory

- Only the committed sha is tested; commit before running. The local fallback tests the working tree.
- Everything on a host stays under `~/rosy-test`. Do not install anything else there; another person uses the AI PC GPU and other sessions run Gazebo on the model PC.
- Other sessions run `~/rosy-test/venv/bin/python` directly. Keep that legacy environment intact. Never delete a hash-specific venv while its tests may run; prune unused hashes by hand.
- Not shipped by the venv: the Chromium browser (so `--browser` runs stay local), the Pinky raw tools and CPU torch (CI installs them only for those suites), and ROS (not sourced, as on the laptop).

### Testing Requirements

```bash
python -m pytest test/test_remote_pytest.py -q
```

## Dependencies

### External

- OpenSSH client with key or Tailscale SSH login to the hosts; on each host git, `/usr/bin/python3` 3.12, `flock`, `systemd-run --user`, optional `uv`

<!-- MANUAL: -->
