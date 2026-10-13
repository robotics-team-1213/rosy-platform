<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->
# hub

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

D-59 SiteHub: hello/heartbeat/event gather, REST scatter. No rclpy, no cmd_vel, no Image.

## Key Files

| File | Description |
|---|---|
| `registry.py` | Online snapshot and event seq |
| `hub.py` | Envelope handle + scatter_estop |

## Testing Requirements

`operations/fleet/test/test_hub.py`, `test_boundaries.py`
