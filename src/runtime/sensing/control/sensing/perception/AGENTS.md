<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-09-25 -->

# perception

## Purpose

Camera and lane evidence (D-209, D-228). This folder answers what is visible. It does not publish `cmd_vel`. Lidar, body geometry, and dock tags stay in the parent `sensing/` package.

## Key Files

| File | Description |
|------|-------------|
| `camera.py` | Floor, void, and obstacle classification |
| `lane.py` | Line centre and error |
| `road.py` | Road observation |
| `scene_context.py` | Closed scene profiles |
| `image_frame.py` | Shared `sensor_msgs/Image` to ndarray decode, used by `line_observer_node` and the learned node |
| `paint_hypothesis.py` | D-395 `paint_score`: how well a pose hypothesis explains the camera's paint points (same distance score as `paint_localizer`); `camera_paint_points`: base_link paint points from one frame (keep mode front end: `floor_white_mask` on the `BirdsEye` grid) |
| `reference_square.py` | D-395 reference square (red ring, blue core): `SquareObservation(bearing_rad, range_m, confidence)` contract, `SquareDetector` protocol, `HsvSquareDetector` rule backend |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `learned/` | D-356 learned lane backend, shadow only: `manifest.py` (model manifest contract, sha256 and shape checks), `lane_mask.py` (segmentation logits to lane evidence), `runner.py` (ONNX runner, keep-previous hot swap), `shadow.py` (`perception/learned/shadow` payload, no command fields). `onnxruntime` is imported lazily; it is not in the device image yet |

## For AI Agents

### Working In This Directory

- Do not import ROS. Observation nodes live above this folder and publish facts.
- Do not import `core` or emit a twist.
- The learned backend (`learned/`) is shadow-only (D-356): it publishes `perception/learned/shadow` and never feeds control. Model weights never live in `src/`; they arrive through `tools/perception/model/deliver.py`. It returns `perception/evidence` and stays behind `perception.backend=rule` until the D-205 replay gate passes.

### Testing Requirements

`src/runtime/sensing/test/test_lane.py`, `test_camera.py`, `test_road_perception.py`, `test_perception_folder.py`, `test_learned_manifest.py`, `test_learned_lane_mask.py`, `test_learned_runner.py`, `test_learned_shadow.py`

## Dependencies

### Internal

Sibling modules in this folder only.

### External

None.

<!-- MANUAL: -->
