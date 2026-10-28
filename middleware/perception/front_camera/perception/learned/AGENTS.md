<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# learned

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-11

## Purpose

Learned (ONNX) lane-perception backend, D-356 / D-373. ROS-free pre/post-processing and runtime plumbing behind a fixed contract: a model manifest in, lane evidence out, same shape as the rule-based `lane.py`. Rule-based stays the default (`perception.backend=rule`); this backend is shadow evidence plus an optional paint mask for the lane keeper. It never emits a twist or `cmd_vel`; only CORE publishes the final command.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package docstring: model contract, pre/post-processing, runner; weights never live in `src/` |
| `manifest.py` | `rosy.perception.model/1` manifest: schema, roles, sha256 and shape checks, optional `input.crop` (D-597), fail-closed `ManifestError` |
| `lane_mask.py` | `preprocess` (frame to NCHW) and `lane_evidence` (logits to visible/error/confidence), near-field band, `wall` never a target |
| `road_region.py` | D-665 road_surface/1 masks and camera-local region from explicit projected anchors; no centre fallback, branch policy or hole filling; offline paired evaluation only |
| `road_observation.py` | D-670 truth-free internal road/region observations with D-667 input validity and loaded model/preprocess binding; always HOLD, no transport or operational consumer |
| `runner.py` | `LaneSegModel` (lazy `onnxruntime`, warm-up check); D-663 legacy postprocessing refuses road_surface/trajectory semantics before inference. `ModelSlot` refuses those lane candidates and keeps the previous model; offline raw sessions remain readable |
| `shadow.py` | `perception/learned/shadow` payload pairing learned and rule error; no command fields |
| `status.py` | `perception/learned/status` payload: counters, latency, "no shadow model loaded" |
| `paint_worker.py` | `LearnedPaintWorker`: one thread infers on the latest frame; keeper takes the newest mask within `stale_s` or falls back (D-408) |
| `drivable_paint.py` | D-597: the drivable way for keep mode (`learned_paint_target: drivable`): D-566 region without the row-growth clamp, rightmost branch at a split (D-384), too little near = none; `boundary_paint` draws a line-wide strip just outside each side so the keeper's inner paint edge is the drivable edge. Pure numpy, no ROS |
| `paint_motion.py` | D-570: `OdomHistory` (pose at a frame stamp), ground-plane homography that moves an older paint mask to the current frame by odometry, bounded by age/dxy/dyaw; no odom or too much motion = fallback |

## For AI Agents

### Working In This Directory

- Do not import ROS, `core`, or emit commands. ROS composition source is `middleware/perception/nodes/learned_lane_node.py`; this implementation retains the `control.sensing.perception.learned` import identity.
- Weights arrive via `learning/registry/perception/deliver.py`, never committed under `src/`. `onnxruntime` is imported lazily and is not in the base device image.
- Keep the output contract (evidence fields, `LaneObservation` sign convention, wire schemas) stable so backends stay swappable. Anything failing validation must be refused, not guessed.
- Promotion beyond shadow is gated by the D-205 replay gate.

### Testing Requirements

Tests are in `middleware/perception/test/`; most run without rclpy. D-584: run the committed-HEAD sensing suite in a separate remote invocation and keep logs in the X session:

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<name>/learned" -- middleware/perception/test/test_learned_manifest.py middleware/perception/test/test_learned_lane_mask.py middleware/perception/test/test_learned_runner.py middleware/perception/test/test_learned_shadow.py middleware/perception/test/test_learned_status.py -q
```

### Common Patterns

- Wire schemas are versioned strings (`rosy.perception.learned_shadow/1`, `rosy.perception.learned_status/1`).
- Time-dependent code takes injectable `clock`/`warn` callables for tests.

## Dependencies

### Internal

`..` perception siblings (`lane.py` convention); `middleware/perception/nodes/learned_lane_node.py` consumes this package.

### External

`numpy`, `cv2`; `onnxruntime` (lazy, device-side prefix)
