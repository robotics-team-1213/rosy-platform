# Semantic Road Perception and Control Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a semantic road scene on `map_260905_update_v2`, recognize it from simulated camera frames, enforce traffic rules in CORE, and expose evidence and policy controls in the dashboard.

**Architecture:** Preserve the measured occupancy world and generate a derived traffic world from a versioned semantic YAML. Control publishes camera evidence only; a ROS-free CORE policy gates line-follow candidates before the existing sole Command Manager publisher. Dashboard APIs expose versioned readback and stopped-only policy edits.

**Tech Stack:** Python 3, PyYAML, OpenCV, Pydantic/FastAPI, vanilla dashboard JavaScript, Gazebo Harmonic SDF, pytest.

---

### Task 1: Semantic road scene contract and derived world

**Files:**
- Create: `src/core/control/map/map_260905_update_v2/semantic/road_scene.yaml`
- Create: `src/core/control/map/map_260905_update_v2/scripts/build_road_scene.py`
- Create: `src/core/control/map/map_260905_update_v2/tests/test_road_scene.py`
- Generate: `src/core/control/map/map_260905_update_v2/worlds/map_260905_traffic.world`
- Generate: `src/core/control/map/map_260905_update_v2/review/map_260905_traffic.png`

1. Write failing schema, source-hash, geometry, and deterministic-output tests.
2. Run `python -m pytest .../tests/test_road_scene.py -q` and verify the missing-file failure.
3. Add the minimal semantic YAML and generator.
4. Generate the derived world and preview; rerun the test green.
5. Run all bundle tests and `validate_bundle.py`.

### Task 2: Camera road perception

**Files:**
- Create: `src/core/control/control/sensing/road.py`
- Create: `src/core/control/test/test_road_perception.py`
- Create: `src/core/control/control/road_observer_node.py`
- Modify: `src/core/control/setup.py`
- Modify: `src/core/control/launch/line_follow.launch.py`

1. Write failing synthetic-frame tests for lane, stop line, crosswalk, red/yellow/green, conflicts, and blank frames.
2. Verify failure because the detector module is absent.
3. Implement immutable observations and OpenCV detectors without ROS imports.
4. Add payload validation tests, then the sensing-only ROS observer.
5. Run focused Control tests and flake8.

### Task 3: Fail-closed traffic policy

**Files:**
- Create: `src/core/core_features/core_features/traffic_policy/__init__.py`
- Create: `src/core/core_features/core_features/traffic_policy/manager.py`
- Create: `src/core/core/test/test_traffic_policy.py`
- Modify: `src/core/core_common/core_common/protocol/schemas.py`
- Modify: `src/core/core/core/services.py`

1. Write failing tests for state transitions and candidate gating.
2. Verify red, yellow, stale, conflict, wrong map, and policy revision failures.
3. Implement config, observation, decision, manager, and status schemas.
4. Wire a service instance and E-stop reset while preserving sole publisher ownership.
5. Run focused CORE tests.

### Task 4: ROS bridge and command integration

**Files:**
- Modify: `src/core/core/core/bridge/ros_bridge.py`
- Modify: `src/core/core/test/test_line_follow.py`
- Create: `src/core/core/test/test_traffic_policy_bridge_contract.py`

1. Write a failing test proving a line-follow Twist cannot bypass a red/stale policy.
2. Add road observation subscription and strict JSON decoding.
3. Gate `LineFollowDecision` immediately before `set_nav_twist`.
4. Clear navigation and latch HOLD on invalid road evidence.
5. Run bridge, line-follow, command, and safety suites.

### Task 5: API and dashboard supervision

**Files:**
- Create: `src/core/core_api_web/core_api_web/api/v1/traffic.py`
- Modify: `src/core/core_api_web/core_api_web/api/v1/routes.py`
- Modify: `src/core/core_api_web/core_api_web/api/app.py`
- Modify: `src/core/core_api_web/core_api_web/web/index.html`
- Modify: `src/core/core_api_web/core_api_web/web/app.js`
- Modify: `src/core/core_api_web/core_api_web/web/styles.css`
- Create: `src/core/core/test/test_traffic_api.py`
- Modify: `test/test_dashboard_browser.py`
- Modify: `docs/reference/ROSY API & Protocol Reference.md`

1. Write failing viewer/operator, stopped-only, validation, and audit tests.
2. Implement GET status and operator policy staging/apply endpoints.
3. Add simulation-only signal control behind capability checks.
4. Add dashboard cards for detection, policy state/reason, revision, and controls.
5. Run API, dashboard, and browser tests.

### Task 6: Closed-loop simulation and governance

**Files:**
- Create: `tools/simulate_semantic_road.py`
- Create: `src/core/control/test/test_semantic_road_simulation.py`
- Create: `docs/validation/semantic-road-2026-09-21/README.md`
- Generate: `docs/validation/semantic-road-2026-09-21/result.json`
- Generate: `docs/validation/semantic-road-2026-09-21/semantic_road_simulation.svg`
- Modify: `docs/reference/ROSY ADR Log.md`
- Modify: `src/core/control/logs.md`
- Modify: `src/core/control/progress.md`
- Modify: `src/sim/gz_sim/logs.md`
- Modify: `src/sim/gz_sim/progress.md`

1. Write a failing end-to-end host simulation contract.
2. Implement deterministic approach, red wait, green resume, and stale stop sequence.
3. Record raw samples and create a rendered semantic-map/command plot.
4. Add D-151 for the evidence-policy-command separation.
5. Run focused suites, full host pytest, flake8, harness lint/generate, and `git diff --check`.
6. Commit the verified unit and integrate only after review.
