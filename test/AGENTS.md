<!-- Parent: ../AGENTS.md -->

# test

**Parent context:** `../AGENTS.md`

ROS-free repository architecture, installation, deployment, motor/network and cross-owner learning tests. Pytest runs on remote test PCs or CI, never this laptop (D-584). CI runs `python3 -m pytest test/ -v` apart from the package-level suites. `conftest.py` adds `deploy/robot/pinky_pro/release` to `sys.path`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `learning/perception/` | 99-file learning regression suite; fixtures shared |
| `architecture/` | Repo-structure tests (see `architecture/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Inject clocks, command ports and filesystem roots; never call `nmcli`/`reboot`. Assert explicit result enums (`APPLIED` / `LIMITED` / `REJECTED` / `DRIVER_ERROR`).
- Keep tests ROS-free. Import `bringup.motor_control` and `deploy/robot/pinky_pro/release` modules directly.
- A new deploy script gets a contract test here; CI covers this tree.
- Do not mock away the refusal paths in Host Agent; they are the product.
- `known_failures.txt`: delete a line in the commit that fixes it; never add one to hide your own failure. `flaky_quarantine.txt` (D-762): only with flake evidence, never to hide your own failure.
- Changing SITE_STA / relay wording in one doc without the others fails `test_network_topology_contracts.py`.
- In `test_dashboard_browser.py`, `window.__apiCalls` proves the click fired, not that the handler finished; wait on the visible outcome. Run it before shipping dashboard JS.
- Gate every real-Chromium test with `pytest.mark.skipif(not browser_tests_enabled(), ...)` from `browser_harness.py`; never read `ROSY_RUN_BROWSER_TESTS` or `ROSY_BROWSER_TESTS` directly (a second name silently skipped tests until 2026-10-07).
- Bind local servers through `safe_listener()` or `free_port()`, not port 0 (`net::ERR_UNSAFE_PORT`). A test loading a new page family gets a `SCOPE` entry in `browser_scope.py`.
- Browser tests run on the test PCs, never this laptop (34 min to 2 h 26 min, MemoryError flakes). `land.py` adds the mapped ones; by hand: `-- ROSY_RUN_BROWSER_TESTS=1 <paths>` to `remote_pytest.py`. See `docs/reference/developer-guide.md` 「브라우저 시험」.
- A new guard, gate or contract test is not believed until mutation-proven: change the guarded thing, see red, restore, see green, and confirm the mutation landed (`docs/solutions/workflow-issues/inability-to-check-recorded-as-clean-result.md`).
- Safety contracts stay: `test_release_boundary_guards.py` (CORE holds no host privilege, D-22), `test_dynamixel_driver_safety.py` (RPM cap), `test_signal_contract.py` (fail-safe boot, token fail-closed).

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/repo-test" -- test/ -v
# Browser tests: leading ROSY_*=value words are the job's environment on the test PC.
t=$(python test/browser_scope.py <changed paths...>) && python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/browser" -- ROSY_RUN_BROWSER_TESTS=1 $t
```



