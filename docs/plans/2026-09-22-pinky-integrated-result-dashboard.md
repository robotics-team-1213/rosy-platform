# Pinky Integrated Result Dashboard Implementation Plan

**Goal:** Preserve and display the actual run path and camera evidence for one
integrated Pinky Gazebo acceptance result.

**Architecture:** Extend the command-inert collector with bounded visual
evidence, then render an offline self-contained dashboard from the authoritative
JSON. Do not change control authority, geometry, walls, or acceptance gates.

**Tech stack:** ROS 2 Jazzy, Gazebo Harmonic, rclpy, Python standard library,
HTML/CSS/SVG/JavaScript, pytest, Playwright Chromium.

## Task 1: Freeze evidence helper contracts

Files:

- Modify `src/sim/gz_sim/launch/pinky_acceptance_policy.py`
- Modify `src/sim/gz_sim/test/test_pinky_acceptance.py`

1. Add failing tests for bounded spatial trajectory sampling.
2. Add failing tests for RGB/BGR/mono ROS-image to BMP conversion.
3. Implement pure helpers and run the focused tests green.

## Task 2: Extend the collector

Files:

- Modify `src/sim/gz_sim/scripts/pinky_acceptance.py`
- Modify `src/sim/gz_sim/test/test_pinky_acceptance.py`

1. Store a bounded trajectory independent of the high-rate clearance poses.
2. Retain one representative camera frame and write it atomically beside JSON.
3. Serialize reference walls, visual trajectory, and camera evidence metadata.
4. Preserve every existing acceptance gate and command-inert property.

## Task 3: Add the offline renderer

Files:

- Create `src/sim/gz_sim/scripts/pinky_acceptance_dashboard.py`
- Create `src/sim/gz_sim/web/pinky_acceptance_dashboard.html`
- Create `src/sim/gz_sim/test/test_pinky_acceptance_dashboard.py`
- Modify `src/sim/gz_sim/CMakeLists.txt`

1. Add failing validation and rendering tests.
2. Implement schema validation and atomic self-contained HTML generation.
3. Render the scaled wall/path SVG and every acceptance boundary.
4. Install the renderer and template through CMake.

## Task 4: Run Gazebo and preserve evidence

1. Build the updated `gz_sim` package in the existing isolated WSL overlay.
2. Execute a fresh run ID with the measured world and accepted Pinky envelope.
3. Render `dashboard.html` from its terminal JSON.
4. Copy the exact JSON, BMP, dashboard, and browser screenshot into the dated
   validation directory.

## Task 5: Verify and deliver

1. Run the complete `gz_sim` test suite and WSL colcon build.
2. Run Playwright against a local static server and assert visible values.
3. Capture desktop and narrow screenshots and check console errors.
4. Update validation README, progress/logs, and improvement priorities.
5. Run `git diff --check`, commit coherent units, and reconcile with local main
   without touching unrelated user work.
