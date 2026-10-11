## D-649 Drive behavior source ownership and compatibility identities

**Status:** Accepted
**Date:** 2026-10-11

## Context

D-630/D-637 moved source holders while preserving installed identities. This did not finish responsibility extraction: `core_features` still physically contains Base-specific behavior engines, and Perception still physically contains legacy motion-node entry modules. Repeated `core`, `control` and `fleet` names also include ROS/Python distribution identities; their repetition alone is not evidence of duplicate implementation.

## Decision

Move the existing `core_features.{line_follow,docking,navigation,localization,swarm,road_behaviour,traffic_policy}` implementations to `middleware/control/drive/behaviors/<existing-name>`. They remain ROS-free, installed by the existing `core_features` distribution and imported under exactly the same names. A single source-only package search-path mapping and standard setuptools package mappings preserve class, module and monkeypatch identity. Self-contained source archives include these declared holders; installed wheels contain one implementation per identity.

Move `control_node.py`, `goal_node.py`, `wander_node.py` and `safety_node.py` from `middleware/perception/control` to `middleware/control/drive/runtime`. They retain `control.*` identities and existing ROS entry points through the distribution's existing holder build mechanism. This does not activate the legacy final writer beside CORE.

Keep CORE common command arbitration, Safety Guard, identity, state, power, diagnostics and Fleet attachment in CORE. `core/drive` is CORE composition, not another algorithm implementation. General calibration-session leases also fence camera/IMU/IR calibration and remain CORE. `core_features.recovery.camera_fault` computes operator-action eligibility, not escape motion, and remains CORE admission policy. Perception localization nodes produce observation/readiness and pose-injection evidence and remain Perception. Current World state projection and action-conditioned prediction planning remain distinct; this change does not implement prediction.

| Previous ADR | Relationship |
|---|---|
| D-427 | Keep parts, import directions, colcon roots and installed package identities; declare every new physical owner |
| D-429 | Drive concerns remain device control; no training or deliberative decision dependency |
| D-430 | Move all affected Safety tags with their files; require independent review and commit trailer |
| D-625–D-630 | Complete Base behavior ownership without replacing existing backend/source mappings |
| D-637 | Preserve Fleet/Decision/Console/Learning holders and installed closure |

## Naming and authority

`behaviors` owns Base state machines, bounded recovery/curvature and observation-to-candidate logic. `tracking`, `planning`, `recovery`, `calibration` and `safety/adapter` retain the historical control algorithms. `runtime` owns legacy ROS adapters. CORE composition creates and binds these features; CORE Command/Safety and its bridge retain the only operational final `/cmd_vel` authority. Arm joint/action and stop/rearm ownership remain OMX.

Compatibility package directories contain initializers only, never algorithm copies. Namespace/distribution repetition is documented rather than arbitrarily renamed. `middleware/execution` is device-local execution; `operations/execution` is site orchestration. `operations/apps/fleet` is an application gateway, while `operations/fleet` owns Fleet transactions. Their distinct authority does not justify merging them.

## Verification and rollback

Run remote CORE services/gateway, Perception and architecture checks separately; assert non-empty source scans and unchanged size/coupling coverage. Build an isolated sdist, then its wheel outside the repository, and verify representative old imports, one implementation, resources and package metadata. Compare all failures with the known-failure registry. Review safety independently before committing the move. A folder/source proof does not prove ROS graph, ARM64 installation, physical acceptance or deployment. Roll back through a normal reviewed reversal commit; do not change persistent data, map/model lineage or device identity.
