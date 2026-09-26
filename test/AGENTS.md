<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

# test

## Purpose

Host-side pytest for deploy/release/motor/network contracts. These tests do **not** need a ROS overlay; CI runs `python3 -m pytest test/ -v` separately from the `src/runtime/*/test` suites. `conftest.py` inserts `deploy/release` onto `sys.path` so modules shipped as scripts remain importable.

## Key Files

| File | Description |
|------|-------------|
| `conftest.py` | Adds `deploy/release` to `sys.path` |
| `test_motor_control.py` | Differential-drive contracts: geometry, limits, APPLIED/LIMITED/REJECTED |
| `test_bringup_motor_contracts.py` | Bringup wiring of MotorController |
| `test_dynamixel_driver_safety.py` | RPM cap and encoder rollover in Dynamixel driver |
| `test_dynamixel_probe.py` | UART probe helpers |
| `test_host_agent.py` | Host Agent decision layer (refusals, roles, audit) |
| `test_image_checks.py` | Image content/layout checks |
| `test_image_pipeline.py` | Image build input lock / pipeline |
| `test_network_provisioner.py` | Wi-Fi / nmcli provisioning |
| `test_network_topology_contracts.py` | Pins ADR D-26 / CORE SRS / OS design / Implementation Plan on `SITE_STA` + opt-in `RELAY_AP_STA` |
| `test_pi_wifi_deployment.py` | SD-card Wi-Fi/SSH first-boot contracts |
| `test_pinky_commissioning.py` | Ordered G0-G5 session, evidence hashing, and first-device runbook contracts |
| `test_dds_identity_contracts.py` | Pins ADR D-33: identity derives from one robot number, with no default in the template, installer or compose. Drives the real installer through bash rather than asserting the call exists |
| `test_nav2_bandwidth_contracts.py` | Pins ADR D-34 publish rates against the dashboard poll they are matched to, including the launch-time rewritten params file |
| `test_release_boundary_guards.py` | CORE must not hold host privilege (D-22) |
| `test_release_layout.py` | On-disk release layout |
| `test_release_manifest.py` | Manifest schema |
| `test_release_signing.py` | Ed25519 signing |
| `test_arm64_payload_workflow.py` | Manual native ARM64 workflow, digest pin, unsigned artifact and retention contracts |
| `test_release_storage.py` | Release store / retention |
| `test_release_updater.py` | Activate/rollback updater |
| `robot_contracts.py` | Shared ROOT/DEPLOY/compose helpers |
| `known_failures.txt` | Pre-existing failures on main (node id + reason). Delete a line in the commit that fixes it; never add one to hide your own failure |
| `known_failures.py` | `python test/known_failures.py run.txt` compares saved `pytest -rfE` output with the list; exit 1 = a new failure |
| `test_known_failures.py` | The comparison and that every listed id names a real test |
| `browser_harness.py` | Shared helpers for the optional Chromium regressions (launch/error-collection/confirm-stub/screenshot, D-153 capture tooling) |
| `test_robot_runtime.py` | compose/D-22/D-27/runtime-mode contracts |
| `test_nav2_hardware_slice.py` | Hardware Nav2 launch, D-2/D-4, packaging |
| `test_dashboard_browser.py` | Optional Chromium regression (teleop zero + field-settings saves + traffic stage/apply + camera lifecycle + irreversible mode-change confirm + D-153 G2 state-matrix captures); skipped unless `ROSY_RUN_BROWSER_TESTS=1` |
| `test_dashboard_drive.py` | `tools/dashboard_drive.py` against the `test_dashboard_browser.py` fixtures; skips without Playwright/Chromium |
| `test_games_board_browser.py` | Optional Chromium regression for the D-101 laptop match board (real `games/host/preview` server + `games/web` assets); skipped unless `ROSY_RUN_BROWSER_TESTS=1` |
| `test_dock_contract.py` | Dock firmware contract: `/status` fields, no Wi-Fi secrets in `firmware/dock/` sources |
| `test_signal_contract.py` | Signal controller contract (ROSY-SIGNAL-001): fail-safe boot, conflict guard, token fail-closed, no secrets in `firmware/signal/` sources |
| `test_sd_personalization.py` | Pinky public identity, one-time bundle schema, checksum, and secret-redaction contracts |
| `test_sd_writer_contract.py` | Non-destructive Windows PlanOnly, two-probe physical-disk, credential, confirmation, and writer boundary |

## Subdirectories

None (ignore `__pycache__/`).

## For AI Agents

### Working In This Directory

- Keep tests ROS-free. Import `bringup.motor_control` / `deploy/release` modules directly.
- If you add a deploy script, add a contract test here — CI only started covering this tree after a comment in `.github/workflows/ci.yml`.
- Do not mock away the refusal paths in Host Agent; they are the product.
- Changing SITE_STA / relay wording in one doc without the others fails `test_network_topology_contracts.py`.
- In `test_dashboard_browser.py`, waiting on `window.__apiCalls` proves the click fired, not that the handler finished — the fetch stub records the call before it answers. Wait on the visible outcome (the message element) or the assertion races the promise.
- Run it before shipping dashboard JS: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py`. Opt-in tests that are never run are not coverage.
- A new guard, gate or contract test is not believed until it has been **mutation-proven**: change the thing it guards, watch it go red, restore, watch it go green — and confirm the mutation actually landed before trusting the red. Assertions on source text are the easiest to write as tautologies, so mutate them harder, not less (`docs/solutions/workflow-issues/inability-to-check-recorded-as-clean-result.md`).

### Testing Requirements

```bash
python3 -m pytest test/ -v
python3 -m pytest test/test_motor_control.py test/test_host_agent.py -v
```

### Common Patterns

- Inject clocks, command ports, and filesystem roots. Do not call `nmcli`/`reboot` in tests.
- Assert explicit result enums (`APPLIED` / `LIMITED` / `REJECTED` / `DRIVER_ERROR`).

## Dependencies

### Internal

- `src/devices/pinky_pro/bringup/bringup/motor_control.py`, `dynamixel_driver.py`
- `deploy/release/*`, `deploy/robot/*`, `deploy/image/*`

### External

- pytest, PyYAML; OpenSSL only if a test shells out to signing fixtures

<!-- MANUAL: -->
