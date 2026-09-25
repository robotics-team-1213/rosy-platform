<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-20 | Updated: 2026-09-20 -->

# site

## Purpose

Fleet/site layer. One package today: `fleet` — formation geometry (FOR-001), slot assignment (FOR-002), the reference-stream relay (D-31), the FOR-004 session, the CLI, and the Fleet console v1 (D-59 SiteHub gather/scatter). No ROS imports anywhere in the package.

## Key Files

None at this level. See `fleet/AGENTS.md`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `fleet/` | Formation/relay/session/CLI + `fleet console` server and 관제 UI; depends on `core_common` schemas only (see `fleet/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- `fleet` consumes the robot contract; it never modifies `core`. Missing contract pieces are an API-ref cycle, not a local patch.
- Tests run without ROS: `conftest.py` puts `src/site/fleet`, `src/contracts/foundation`, and `src/runtime/services` on `sys.path`.

### Testing Requirements

```bash
# from src/ (or repo root)
python3 -m pytest site/fleet/test -v
```

## Dependencies

### Internal

- `core_common.protocol.schemas` (D-18); colcon build order via `exec_depend` (D-126).

### External

- fastapi, uvicorn, httpx, websockets ≥ 14, PyYAML, pydantic

<!-- MANUAL: -->
