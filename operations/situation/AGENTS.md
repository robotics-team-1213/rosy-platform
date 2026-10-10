<!-- Parent: ../AGENTS.md -->

# situation

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-10

## Purpose

`rosy-situation` (D-577 3·4·10), the AI PC situation service. It reads Fleet over REST (state, traffic, line-stuck at 1 Hz, the event cursor), runs deterministic analyzers and posts **facts** (value, confidence, evidence ids) to `POST /api/fleet/ai/facts` as the Fleet role `ai_observer`, plus a heartbeat every 2 s with the owner's `owner_mode`. Facts are shadow: Fleet decides with its rules and CORE re-checks (D-516). Standard library only. `COLCON_IGNORE` keeps colcon off this folder.

## Key Files

| File | Description |
|------|-------------|
| `rosy_situation/service.py` | The service loop, Fleet client, queue/backpressure, JSONL input/fact logs, `analyze` stub |
| `test/test_situation_service.py` | Fake-Fleet unit tests and one in-process real Fleet test |

## For AI Agents

### Working In This Directory

- Never add a robot address, robot token, or any Fleet write other than facts and heartbeat. No command words in facts (Fleet refuses them).
- Analyzers are pure functions of the snapshot (phase (d)); vision is phase (e). Neither is here yet.
- The unit `deploy/ai_pc/rosy-situation.service` is installed on the AI PC only with the owner's consent.

### Testing Requirements

`python tools/remote/remote_pytest.py -- operations/situation/test` (never on the laptop, D-584).

## Dependencies

- Fleet API (`/api/fleet/ai/*`, API Reference). Python >= 3.12, no third-party packages.
