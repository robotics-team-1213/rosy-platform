## D-156 ROS 2 Namespace Strict Segregation (Runtime Guard)

**Date:** 2026-09-21
**Status:** Proposed
**Context:** Static imports can be clean while ROS 2 topics remain global. An
application node could still publish an operational command beside CORE.
**Decision:** `core/control` nodes may publish evidence and sensor topics only.
CORE alone owns operational state, intent, and final `cmd_vel`. This decision
remains Proposed until a launch/graph check verifies the actual publishers.
