# map_260905_update_v2 Live Gazebo SLAM Implementation Plan

**Goal:** Produce and retain a passing fresh Gazebo/SLAM/CORE/Fleet evidence run for the exact v2 world.

**Architecture:** Install and resolve the source map bundle, run namespaced Gazebo sensors and `slam_toolbox`, route all final motion through CORE, execute an adaptive centerline coverage route with clearance-derived recovery, then save and audit one run-ID-bound artifact set.

**Tech stack:** ROS 2 Jazzy, Gazebo Harmonic, ros_gz_bridge, slam_toolbox, Nav2, Python/pytest, CORE FastAPI, Fleet client.

## Task 1: Pin Linux execution and exact-world contracts

**Files:** `.gitattributes`, `src/sim/gz_sim/test/`, `src/core/control/setup.py`, `src/sim/gz_sim/config/worlds.yaml`, `src/sim/gz_sim/launch/world_profiles.py`

1. Keep the reproduced executable-shebang and missing-v2-profile tests red.
2. Pin executable Python files to LF.
3. Install the map bundle and resolve its world through the package index.
4. Verify host contracts and installed-file layout.

## Task 2: Prove the current Gazebo bridge and collision path

**Files:** only confirmed launch/URDF defects plus focused tests.

1. Build the relevant packages in the pinned Jazzy/Harmonic container.
2. Launch the exact world headless with one robot.
3. Bound checks for `/clock`, namespaced scan/odom/TF, primitive simulation collision, and a non-empty SLAM map.
4. For each failure, add a focused red test before the smallest fix.

## Task 3: Add adaptive v2 traversal through CORE

**Files:** a reusable ROS-free route/recovery policy, its tests, and a thin ROS runner.

1. Test centerline waypoints against footprint clearance and connected-space topology.
2. Test continuous clearance/curvature speed caps and clearance-derived reverse recovery.
3. Test stale-evidence stop, finite retry, and zero final command.
4. Publish only `nav_cmd_vel`; arm navigation through CORE and verify CORE is the sole final publisher.

## Task 4: Make evidence namespaced and run-bound

**Files:** v2 run monitor/audit/report tools and tests.

1. Parameterize namespace, domain, evidence directory, and run ID.
2. Save OccupancyGrid, trajectory, topic/publisher samples, CORE/Fleet snapshots, and contact/clearance audit.
3. Fail unless all map-quality and same-run gates in the design pass.
4. Render a final map/trajectory comparison PNG.

## Task 5: Execute to completion and integrate

1. Run the exact live traversal repeatedly, changing only evidenced logic/parameters.
2. Preserve failed run artifacts for diagnosis; designate only the first fully passing run as accepted.
3. Run focused and full regression suites, harness generation/lint, and `git diff --check`.
4. Commit coherent units, refresh against `main`, integrate without touching unrelated work, and report commit IDs plus the evidence paths.

