
# wander/ (the autonomy FSM)

**Parent context:** `../AGENTS.md`

## Purpose
The wander autonomy: a 20 ms FSM (`wait forward pause look calc recon wall backup turn escape stop`) over subject mixins. Publishes semantic velocity (positive x = nose-forward) to `/cmd_vel_raw`, never `/cmd_vel`.

## For AI Agents

### Working In This Directory
- Cliff/tilt decisions go through `control/recover.hazard_action` — do not re-branch on `self.cliff`/`self.tilt` in tick handlers.
- State and mode are always published together (`_announce`/`_publish_mode`); the fused label comes from `control/modes.pick_mode`. `/safety/mode` is a deprecated same-value alias line — keep it single-site. Shutdown never leaves a stale label.
- Cliff only counts after the first forward drive (`seen_forward` gate lives inside `hazard_action`); raw `self.cliff` remains only where the comment says so (backup persistence, forward interrupt).
- Enter states via the shared helpers; the only forward entry is `_resume_forward`.

### Testing Requirements
- The FSM is hardware-coupled (not unit-tested); keep new decisions in `control/recover.py`/`control/modes.py` where they are.
- After FSM changes, on-robot smoke: echo `/wander/state` + `/robot/mode` through drive → wall → cliff → estop → pickup; Ctrl+C must leave `STOP`.

### Common Patterns
- One concern per mixin, `"""Subject: …"""` docstrings; transitions via `_enter` (logs + per-state resets).

## Dependencies

### Internal
- `control/modes.pick_mode`, `control/recover.*`, `sensing/lidar.wrap_pi`.

### External
- `rclpy.qos` (latched `/estop/state` subscription — label only; safety owns the e-stop decision).
