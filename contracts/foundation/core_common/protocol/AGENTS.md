<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# protocol

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Single source of pydantic schemas for REST snapshots and Fleet WS envelope (D-10, D-18). Additive changes only; bump `PROTOCOL_VERSION` MINOR (PRT-006).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `schemas.py` | Enums (`RobotMode`, `PowerMode`, `BatteryLevel`, …), `StateSnapshot`, envelope, events. D-400: `SafetyPolicyStatus` on `StateSnapshot.safety_policy` (v1.71; `mode`/verdict are lowercase plain strings, an exception to the enum rule) |
| `trip_lease.py` | D-541 `TripLeaseStatus`, `TripLeaseEnded`, `TripLeaseFields` (base of `StateSnapshot`; the two keys are absent, not null, when unset) |
| `localization.py` | D-395 wire models: `LocalizationStatus` (state + `map\|odom` frame flag, on `StateSnapshot.localization`), `CandidateReport`, `LocalizationDecision` (candidate index or direct pose, source, `cues`, `ttl_s` from receipt), D-494 `OdomPose` (on `StateSnapshot.odom_pose`, stamp = UTC epoch s) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- This file is the machine contract. Update `docs/reference/ROSY API & Protocol Reference.md` in the same change.
- Do not break existing field names. New optional fields are OK.

### Testing Requirements

```bash
python3 -m pytest middleware/core/gateway/test/test_protocol_schemas.py -v
```

### Common Patterns

ISO-8601 UTC via `utc_now_iso()`; UUID `msg_id`.

## Dependencies

### Internal

- Imported across state, API, power, docking, fleet

### External

- pydantic

<!-- MANUAL: -->
