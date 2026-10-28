<!-- Parent: ../AGENTS.md -->

# situation

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-11 (D-630 responsibility holders)

## Purpose

`rosy-situation` (D-577 3·4·10), the AI PC situation service. It reads Fleet over REST (state, traffic, line-stuck at 1 Hz, the event cursor), runs deterministic analyzers and posts **facts** (value, confidence, evidence ids) to `POST /api/fleet/ai/facts` as the Fleet role `ai_observer`, plus a heartbeat every 2 s with the owner's `owner_mode`. Facts are shadow: Fleet decides with its rules and CORE re-checks (D-516). Standard library only. `COLCON_IGNORE` keeps colcon off this folder.

## Key Files

| File | Description |
|------|-------------|
| `rosy_situation/service.py` | The service loop, Fleet client, queue/backpressure, JSONL input/fact logs |
| `rosy_situation/assessment.py`, `snapshot_assessment.py` | D-652 immutable necessity criteria and current CORE snapshot adapter; Fleet installs only these pure modules plus `__init__.py`, consumers remain shadow |
| `rosy_situation/analyzers/stuck_scene.py` | `Analyzer`: stuck and traffic facts plus shadow `trip_route_check` from trip/map pose and planned segments; existing `rosy_situation.analyzers` exports remain |
| `rosy_situation/analyzers/traffic_watch.py` | `TrafficWatch` (`analyzer:traffic_watch@1`, phase (d)): wait cycles cross-checked with Fleet's `wait_cycle`, stale-input false cycles, waiting-but-moving, livelock, stalled trips, long UNKNOWN units; existing `deadlock` module aliases this implementation |
| `rosy_situation/incidents/context.py` | Source-aware incident context drafts; existing `incident_context` module identity remains |
| `rosy_situation/incidents/vision.py` | Existing bounded local vision assessments; `vlm` aliases this module, preserving monkeypatch state |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
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
