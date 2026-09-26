<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

# docking

## Purpose

Docking state machine (DNC-002–003). Map pose is only for staging; final approach is sensor closed-loop. Whole action runs in `DOCKING` mode so Fleet/Nav cannot preempt.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `manager.py` | `DockingManager` (state, lock, mode seams, default-dock phases, battery return); re-exports `DockPhase`, `DockingExecutor`, `DockingConfig` from `model.py` |
| `model.py` | `DockPhase`, `DockingExecutor` protocol, `DockingConfig` |
| `parking_phases.py` | `ParkingPhases`: the parking-only pose phases (turns, creep acquire, approach, align, settle/reseat, distance backoff), called only under the manager's lock; no state or lock of its own |
| `database.py` | `DockDatabase`, `DockInstance`, `DockType`, `DockError` |
| `detector.py` | `DockDetector` protocol + `SimulatedDetector` |
| `charging.py` | `ChargingConfirmation` (contact vs current) |
| `agent.py` | Poll client for dock `GET /status` (urllib only; required `load_present`/`charging`) |
| `parking.py` | Parking dock type (no contacts): spot pose from one tag observation, odometry carry, turn/approach/settle control laws (`docs/plans/2026-09-23-lane-network-parking-design.md`) |
| `feed.py` | `DockObservationFeed` / `FeedDetector`: the detector port fed by control's `dock/observation` evidence, stamped and freshness-checked |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Design: `docs/plans/2026-09-02-docking-station-design.md`.
- Pinky Pro `src/products/pinky_pro/config/capabilities.yaml` has `docking.supported: false` — keep capability checks.
- ROS-free: inject clock and detector. Do not subscribe to scans here.

### Testing Requirements

```bash
python3 -m pytest src/runtime/services/test/test_docking.py -v
```

### Common Patterns

Phases inside `DOCKING`; never drive by map coordinates at the contact.

## Dependencies

### Internal

- `protocol.schemas` DockingStatus / DockState
- `services.py` builds `DockingManager` with `SimulatedDetector` by default

### External

None.

<!-- MANUAL: -->
