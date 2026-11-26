<!-- Parent: ../AGENTS.md -->
# server

**Parent context:** `../AGENTS.md`

## Purpose

The control-PC Fleet server v1: site orchestrator and console UI (site-fabric design section 2). It gathers N robots' state and scatters goals, cancels and all-stop. Missions stay on the Fleet side (D-12): this server, not the robot, remembers dispatched goals. Non-package source holders (D-750, D-798) such as `evidence/`, `sitemap/`, `pose/`, `recognition/`, `rightofway/`, `ledger/`, `console/`, `cell/`, `auth/`, `tracking/` keep the `fleet.server.*` import names; the operational ledger keeps one SQLite/process/transaction owner. UI source: [applications/fleet/web](../../../../applications/fleet/web/AGENTS.md).

## For AI Agents

### Working In This Directory

- Gather in v1 is polling; the robot `FleetAgent` outbound WS (design 3) later changes only the `snapshot()` source.
- Robot pose is CORE's TF `map` to `<ns>base_footprint`, a site-shared frame. Never create per-robot `rosy_XX/map`: it breaks this view and CORE goal delivery.
- All-stop returns 200 even on partial failure. Legacy `stopped` counts CORE HTTP replies, not confirmed stops or a physical E-stop (D-298); unanswered robots show as unknown and need a device readback.
- `console/estop_fanout.py` (safety) delivers all-stop to every robot concurrently; only never-connected requests retry (max 3 within 5 s); lost replies and read timeouts are UNKNOWN, never resent (D-271 5).
- Never wait for formation release before stopping; e-stop also releases the formation so followers do not chase stale references.
- `console/traffic_arbitration.py` (safety mixin: route occupancy, yield, queued missions, localization trust, `cancel`, `hold_for_localization`) keeps `goal`/`_goal` send order in `console.py`.
- `tether_watch.py` (D-526, safety) sends the existing robot E-Stop on radius+0.15 m, 405 deg rotation or 2 s pose loss, then ends the trip; latched, a tether POST re-arms; no return motion.
- `host_control_routes.py` (D-524): POST only for named operators; reboot is a 10-minute schedule that the PC helper refuses during an arm session or live work (D-991); allowlisted unit restarts only; forced-command SSH keys under `/run/rosy-fleet-host-control/`; no process names or shell;
- 503 without config or login.
- Read-only advisory services never send to robots: `identity.py` (D-472, LED blink request only, no command reads), `lane_compliance_service.py` (D-511), `teach_service.py` (D-494 6, writes drafts only), `map_pose_service.py` (D-494 3), `signals.py` (ROSY-SIGNAL-001, kept apart from `swarm/`),
- `traffic.py` (pure geometry).
- Only Fleet sees both routes, so Fleet orders crossings (D-12). The later-issued mission yields. `goal()` sends first, then reads the route and cancels into the queue on conflict. Unreadable route: do not block.
- In a formation the leader takes goals, followers never (D-20). One formation per site; refuse a second. Release never refuses.
- CSP `style-src 'self'`: no `style` attributes or `el.style.x =`; use classes. The server holds robots.yaml operator tokens: default bind is loopback; non-loopback requires `--token` (`cli.run_console` enforces).
- Does not replace the robot-local CORE `/dashboard` (D-23). Model-feedback dispatch (D-657) stays Fleet-owned; Decision owns contracts/catalog only. `auth/` forwards to [Account](../../../account/AGENTS.md) (D-962).

### Testing Requirements

D-584: `tools/remote/remote_pytest.py` on `operations/fleet/test/test_server_console.py`, `test_server_app.py` (needs fastapi), `test_server_traffic.py`, `test_server_formation.py`. Fake robots, no network.
