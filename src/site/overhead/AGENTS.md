# overhead

Receive-only `rosy-overhead/1` WebSocket ingest adapter (D-257, D-261). ROS-free, no `cmd_vel`, no marker detection (that is D-257 §3, not this ADR's scope).

`android/` (the Kotlin/CameraX app) is out of scope for this package's Python code and owned by a parallel branch — do not create files there from here.

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_python. No ROS exec_depend |
| `setup.py` / `setup.cfg` | Package install, `rosy_overhead` console script |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `protocol/vectors.json` | Shared `rosy-overhead/1` test vectors — Kotlin and Python both read this file. Do not edit without checking both sides |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `overhead/` | Python package: `protocol.py` (pure, stdlib), `ingest.py` (websockets server), `cli.py` (`rosy_overhead receive`) |
| `protocol/` | `vectors.json` only — no Python here |
| `test/` | ROS-free pytest, `conftest.py` bootstraps `sys.path` without a colcon install |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- `protocol/vectors.json` is the source of truth for the wire format; if a vector looks wrong, that's a design question for the ADR/plan, not a local edit.
- `captured_at` in `ingest.py` uses this process's own wall clock (`time.time()`) minus the frame's `age_ms` — the phone's clock is never trusted (design §3).

### Testing Requirements

```bash
python -m pytest src/site/overhead/test -q
```
