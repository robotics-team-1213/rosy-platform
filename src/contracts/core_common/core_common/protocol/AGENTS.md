<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# protocol

## Purpose

Single source of pydantic schemas for REST snapshots and Fleet WS envelope (D-10, D-18). Additive changes only; bump `PROTOCOL_VERSION` MINOR (PRT-006).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `schemas.py` | Enums (`RobotMode`, `PowerMode`, `BatteryLevel`, …), `StateSnapshot`, envelope, events |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- This file is the machine contract. Update `docs/reference/ROSY API & Protocol Reference.md` in the same change.
- Do not break existing field names. New optional fields are OK.

### Testing Requirements

```bash
python3 -m pytest src/core/core/test/test_protocol_schemas.py -v
```

### Common Patterns

ISO-8601 UTC via `utc_now_iso()`; UUID `msg_id`.

## Dependencies

### Internal

- Imported across state, API, power, docking, fleet

### External

- pydantic

<!-- MANUAL: -->
