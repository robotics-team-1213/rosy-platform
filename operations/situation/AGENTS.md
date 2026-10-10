<!-- Parent: ../AGENTS.md -->

# situation

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-10 (D-577 (d) traffic_watch)

## Purpose

`rosy-situation` (D-577 3·4·10), the AI PC situation service. It reads Fleet over REST (state, traffic, line-stuck at 1 Hz, the event cursor), runs deterministic analyzers and posts **facts** (value, confidence, evidence ids) to `POST /api/fleet/ai/facts` as the Fleet role `ai_observer`, plus a heartbeat every 2 s with the owner's `owner_mode`. Facts are shadow: Fleet decides with its rules and CORE re-checks (D-516). Standard library only. `COLCON_IGNORE` keeps colcon off this folder.

## Key Files

| File | Description |
|------|-------------|
| `rosy_situation/service.py` | The service loop, Fleet client, queue/backpressure, JSONL input/fact logs |
| `rosy_situation/analyzers.py` | `Analyzer` (`analyzer:stuck_scene@1`): `rear_blocked`, `path_blocked_by_robot`, `stalled` from the snapshot |
| `rosy_situation/deadlock.py` | `TrafficWatch` (`analyzer:traffic_watch@1`, phase (d)): wait cycles cross-checked with Fleet's `wait_cycle`, stale-input false cycles, waiting-but-moving, livelock, stalled trips, long UNKNOWN units; run inside `Analyzer` after the proposals, shadow only |
| `test/test_situation_service.py` | Fake-Fleet unit tests and one in-process real Fleet test |
| `test/test_analyzers.py` | Analyzer facts on synthetic snapshots |
| `test/test_deadlock.py` | Traffic facts on synthetic snapshots, incl. a stale-pose false cycle and a quiet hour |

## For AI Agents

### Working In This Directory

- Never add a robot address, robot token, or any Fleet write other than facts and heartbeat. No command words in facts (Fleet refuses them).
- Analyzers are deterministic over the snapshot sequence (phase (d)); vision is phase (e), not here. A new fact kind is a D-577 amendment and a Fleet `FACT_KINDS` entry in the same change.
- The unit `deploy/ai_pc/rosy-situation.service` is installed on the AI PC only with the owner's consent.

### Testing Requirements

`python tools/remote/remote_pytest.py -- operations/situation/test` (never on the laptop, D-584).

## Dependencies

- Fleet API (`/api/fleet/ai/*`, API Reference). Python >= 3.12, no third-party packages.
