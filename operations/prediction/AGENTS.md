# prediction

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-17 · **Updated:** 2026-10-17 (D-782)

## Purpose

Action-conditioned prediction consumers (D-625 §6, D-782). Predictions are separate from World State: World holds observed facts, this folder holds estimates of what a candidate action would do. Nothing here has command, lease, admission or device authority.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `world_model/` | OMX pre-execution checker and shadow recording (see `world_model/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- A prediction may support REJECT or HOLD only. It never permits a candidate (D-782 §1).
- Do not import Fleet, owner or ROS code here. Wiring into an admission or owner recheck is D-782 W4 and needs user approval and a D-430 Safety review.
