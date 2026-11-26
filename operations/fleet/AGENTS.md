<!-- Parent: ../AGENTS.md -->

# fleet

**Parent context:** `../AGENTS.md`

## Purpose

Fleet-side seed (ROSY-FLEET-SRS-001 FOR-001~004): formation geometry and slot assignment, the leader-to-N-followers reference relay (D-31), the FOR-004 formation session (arm, relay, watch, hold), and the **Fleet server v1** (`fleet console`), the site orchestrator that gathers N robots on one screen and scatters goals, cancels and all-stop (site-fabric design section 2). SiteHub is contract gather/scatter with no ROS and no UI; the UI lives in `server/`. Consumes the robot contract only, never modifies `core`, imports `core_common.protocol.schemas` (D-18). No ROS imports in this package. Module map and authorities: [fleet/AGENTS.md](fleet/AGENTS.md); call map: [docs/call-map.md](docs/call-map.md) (screens: D-540).

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- `formation/` and `swarm/arming.py` are pure: no `httpx`, `websockets`, `asyncio` or `rclpy`. `test/test_boundaries.py` walks the import graph.
- The relay forwards leader frames byte-for-byte and never synthesizes one. A stopped stream reads 0 Hz, never the last frame repeated.
- HOLD (FOR-004) pauses the relay; it is not a new endpoint (design 6.4, D-35 candidate). Everything refusable without touching a robot is decided in `arming.py` before `relay.pause()`: a rejected `reform` leaves a running formation untouched.
- Never modify `core` from here; a missing robot-contract feature is a finding for an API Ref cycle.
- `setup.py`/`package.xml`: `core_common` is `exec_depend` for colcon order only (D-126); `tools/packaging/fleet_sources.py` owns source composition. D-652 installs three pure `rosy_situation` files only (no AI service, analyzers or vision); D-657 reuses the external execution wheel.
- `fleet/server/console/console.py` (`FleetConsole`) is a D-430 safety file and the one place that remembers dispatched goals (D-12). Static UI under `fleet/server/web/`: CSP `style-src 'self'`, no inline styles.
- Safe-by-design pure/advisory modules never send to robots: `site_rules*.py` (D-982, may only tighten defaults), `traffic/lane_traffic.py` (D-517, the single user of run-block grants), `trip_preview.py` (D-767). `traffic/rule_m.py` (D-550/D-760) only warns, never refuses.
- Trip lease (D-541): opens only if `fleet.trip_lease_required` is true; new uuid `lease_id` per trip, no reuse. A 404, 409, `renewed:false` or unconfirmed `ttl_s` ends the trip `stopped/lease_lost`, never reopened. The lease owner is the robot REST token, which must be Fleet-only (D-541 1);
- `app.py` rejects it if equal to the control token.
- D-661 `incidents/handoff.py` and `notifications.py` hold named human ownership and the team notification journal, separate from the stuck resolver and from final device authority.
- Tests use fakes (`test/fakes.py`, `fake_signals.py`) and `settle()` polling, never wall-clock `sleep`.

### Testing Requirements

D-584: run through a remote test PC.

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<name>/fleet" -- operations/fleet/test -q
python -m flake8 operations/fleet --max-line-length=120
```

No ROS needed (`conftest.py` sets `sys.path`). Browser tests (`*_browser.py`) are opt-in: `t=$(python test/browser_scope.py <changed paths...>) && ROSY_RUN_BROWSER_TESTS=1 python -m pytest $t`. Run the full set on the site PC or model PC, not the laptop (`docs/reference/developer-guide.md` browser section). Serve test pages via `browser_harness.safe_listener()`, never port 0.

### Notes

- `robots.yaml` maps `robot_id` to `RobotEndpoint(base_url, token)`; tokens are device-local (D-30).
- `SlotAssigner` is a `Protocol` (greedy v1, swappable, FOR-002). `FormationSession` states: IDLE / ARMING / RUNNING / HOLDING / STOPPED; `pending_triggers` accrue while holding and block `resume()` until cleared.

