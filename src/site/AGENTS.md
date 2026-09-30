<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-20 | Updated: 2026-09-28 -->

# site

## Purpose

Site-facing and non-robot-hosted source groups. Folder location alone does not identify which physical PC runs a service; deployment is defined by deploy/ and the selected package closure. Fleet owns site mission/task records and its console server, while robot-side final command authority remains with the local owner.

## Key Files

None at this level. See each package AGENTS.md.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| fleet/ | Fleet formation, relay, session, CLI, and console server; consumes shared contracts and does not own robot final commands |
| vision/ | ROS package rosy_vision (Rosy Vision, D-377): receive-only image ingest and sighting derivation; sighting is not a robot command |
| cam/ | Rosy Cam ceiling camera Android app (`io.github.livsbittt.rosy.cam`, D-377); `COLCON_IGNORE`, Gradle only |
| games/ | ROS package games and match host; game coordination is not a cmd_vel writer |

## For AI Agents

### Working In This Directory

- fleet consumes the robot contract; it never modifies CORE. Missing contract pieces require an API reference cycle.
- Keep the overhead sighting stream separate from robot front-camera preview and OMX task cameras (D-275).
- Do not infer server host placement from this source directory. Check deploy/site/ and its current composition.
- Fleet tests run without ROS; do not generalize that property to every package under site/.

### Testing Requirements

    python3 -m pytest src/site/fleet/test/ -v

## Dependencies

### Internal

- Fleet consumes core_common.protocol.schemas (D-18); colcon build order via exec_depend (D-126).
- Rosy Vision and Rosy Cam contracts and deployment are documented in their package-level guidance.

### External

Fleet: fastapi, uvicorn, httpx, websockets >= 14, PyYAML, pydantic. Other packages have their own manifests.

<!-- MANUAL: -->
