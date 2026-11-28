
# control.control (import and installation compatibility)

**Parent context:** `../AGENTS.md`

## Purpose
This directory holds `__init__.py` and this guide. The initializer preserves the existing `control.control` exports and adds the four source roots declared by `control/_source_layout.py` to its package path. After D-630 the pure algorithm files are owned by Drive (`middleware/drive/{motion_limits,tracking,recovery,calibration}`) and installed once under unchanged `control.control.*` identities. Planning/grid, tracking/wander and safety/adapter keep `control.planning`, `control.wander`, `control.safety`. See the [platform folder guide](../../../../docs/reference/platform-folder-responsibilities.md) and [composition guide](../AGENTS.md).

## For AI Agents

### Working In This Directory
- Edit pure logic in its Drive source holder. Keep ROS imports out of those algorithms; pass node state through their existing inputs.
- Keep this initializer's exports and the narrow source package path. `setup.py` collects the 50 flat modules into one installed `control.control` package; duplicate source names are rejected. The sdist snapshots those roots for an isolated rebuild.
- `ControlPolicyProducer` is the one in-process boundary that may hold an `Observations` source and a `CommandPolicy`; call it from the sensor producer's serialized callback/timer group.
- It carries receive/source deadlines plus candidate-specific translation/tracking evidence and never publishes motor commands.
- `hazard_action` (`recover.py`) is the only cliff/tilt decision home: **do not re-branch on `self.cliff`/`self.tilt` in FSM code**, call the policy.
- The label list lives once in `modes.MODES` (`WANDER_TO_MODE` maps FSM states to labels). New labels keep the taxonomy hazard > action > contact > idle; subjects do not overlap.
- Thresholds are module constants with hardware rationale comments (`US_NOSE_MAX_M = 0.80`: beyond ~0.8 m a US-016 echo is noise). Float handling is NaN/None-safe (no echo = no opinion).
- This initializer adds no runtime or motion authority.

### Testing Requirements
- Run `middleware/perception/test/` through the committed-HEAD remote pytest runner (D-584). Source holder, installed identity, sdist/wheel and map-byte checks are in `middleware/perception/test/test_responsibility_layout.py`.
