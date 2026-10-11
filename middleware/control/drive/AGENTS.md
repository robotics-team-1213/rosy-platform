# drive

**Parent context:** `../AGENTS.md`

Base-control backends: `planning/{nav2,grid}`, `tracking/wander`, `safety/adapter`, and the flat modules in `safety/`, `tracking/`, `recovery/`, `calibration/`. The 50 flat modules keep their installed `control.control.*` identities; grid, wander and adapter retain `control.planning`, `control.wander`, `control.safety`. Static source mappings in `middleware/perception/setup.py` build them into the existing `control` distribution once.

ROS node composition remains in `middleware/perception/control`. Sensor evidence lives in `middleware/perception/sensors/sensing`, vision in `middleware/perception/vision/perception`. CORE feature managers and final command arbitration stay in `middleware/core/services`; CORE-specific Drive composition lives in `middleware/core/gateway/core/drive`. See [the current folder responsibilities](../../../docs/reference/platform-folder-responsibilities.md).

Every backend submits a candidate to CORE. No operational final publisher, new mode or automatic recovery activation belongs in this holder. Curvature, clearance, pivot/reverse and bounded recovery must retain their own behavioral evidence.
