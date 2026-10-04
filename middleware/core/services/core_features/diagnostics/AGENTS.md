<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# diagnostics

## Purpose

DIAG-001/002 + OBS-101 health rollup. Providers return `HealthState`; collector takes the worst.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `collector.py` | `DiagnosticsCollector`, CPU/mem/disk providers, `topic_freshness_provider`, `worst()` |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- System providers read `/proc` (or `ROSY_HOST_ROOT`). No psutil.
- Topic freshness is registered from the bridge with last-message timestamps.

### Testing Requirements

Covered indirectly by host runtime / graph tests; add unit tests here if you change `worst()` order.

### Common Patterns

1 Hz collection; UNKNOWN < OK < WARNING < ERROR severity order in `_ORDER` (UNKNOWN is 1, OK is 0 — OK is best).

## Dependencies

### Internal

- `protocol.schemas.HealthState`
- Instantiated from `ros_bridge.py`

### External

None.

<!-- MANUAL: -->
