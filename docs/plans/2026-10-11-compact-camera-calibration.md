# Compact camera calibration implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Small partial AprilGrid observations produce measured lens candidates and reviewable corrected/plane images, with map coverage and bounded AI advice.

**Architecture:** Rosy Cam owns raw capture, Vision owns measurement and display transforms, Fleet owns approved map/calibration identity, Console preserves the reference map when observations vanish. Offline measured candidates do not overwrite approved operational calibration. AI reviews evidence and proposes recapture or review steps; it cannot synthesize accepted geometry or robot poses.

**Tech Stack:** Existing OpenCV contrib, NumPy, Python standard library, Console ES modules. No new service or dependency.

### Task 1: Measured workshop

Create `operations/vision/rosy_vision/camera_calibration.py`, CLI entry in setup.py and tests `test_camera_calibration.py`. Generate exact-metre AprilTag 36h11 grids and SVG/PNG with measured board manifest. Detect complete tags from partial grids; reject duplicate IDs, inconsistent dimensions and degenerate views. Fit pinhole and fisheye on training views, evaluate independent validation frames and report coverage/conditioning limits. Keep source/geometry identity and hashes in candidates.

### Task 2: Corrected and map previews

The workshop consumes its lens candidate to remap raw pixels, write a valid-pixel mask and corrected preview. A separately measured, explicitly undistorted-pixel floor registration can compose a single inverse remap to map metres; raw-pixel homographies cannot be silently reused. Keep reference-map data independent of camera visibility.

### Task 3: AI assistance

Emit a bounded, credential/path-free review request from measured reports. Accept only allowed recapture/review recommendations and an explanation; ignore neither unknown fields nor invented geometry. AI output remains advisory. No background provider, new robot command or direct model-selected URL is introduced.

### Task 4: Existing plane coverage

Fix `rectify.py` horizon/off-frame sampling and carry a same-plane valid mask and observed fraction. Add the documented coverage header to ingest and Console parsing/status. Keep legacy frame compatibility, approved source/map/lens/revision/freshness and no-inline-style rules. Known 2D maps persist outside measured camera coverage.

### Task 5: Verification and evidence

Commit failing tests, run only remote pytest and compare known_failures. Use synthetic projected partial-grid poses for numerical checks and actual rendered tag detection for target generation. Verify wrong identity, raw/undistorted mismatch, missing validation, insufficient coverage and unauthorized AI geometry proposals are rejected. Run relevant Vision/Fleet contracts, Node and Chromium, record evidence and practical collection steps. Deployment requires the repository's explicit landing/push instruction; physical accuracy requires actual target captures and surveyed check points.
