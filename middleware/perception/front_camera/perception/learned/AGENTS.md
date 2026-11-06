<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# learned

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-11

## Purpose

Learned (ONNX) lane-perception backend, D-356 / D-373. ROS-free pre/post-processing and runtime plumbing behind a fixed contract: a model manifest in, lane evidence out, same shape as the rule-based `lane.py`. Rule-based stays the default (`perception.backend=rule`); this backend is shadow evidence plus an optional paint mask for the lane keeper. It never emits a twist or `cmd_vel`; only CORE publishes the final command.

> 2026-11-03 (D-964): lane fit, bird's-eye view, keeper, camera ground plane, road state and the learned model contract/runners (`manifest`, `runner`, `detector`, `lane_mask`, `signature`, ...) moved to `integrations/perception` (`perception_runtime.perception.*`). Rows below for those files are gone; see `integrations/perception/AGENTS.md`.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package docstring: model contract, pre/post-processing, runner; weights never live in `src/` |
| `shadow.py` | `perception/learned/shadow` payload pairing learned and rule error; no command fields |
| `status.py` | `perception/learned/status` payload: counters, latency, "no shadow model loaded" |
| `paint_worker.py` | `LearnedPaintWorker`: one thread infers on the latest frame; keeper takes the newest mask within `stale_s` or falls back (D-408) |
| `paint_motion.py` | D-570: `OdomHistory` (pose at a frame stamp), ground-plane homography that moves an older paint mask to the current frame by odometry, bounded by age/dxy/dyaw; no odom or too much motion = fallback |

## For AI Agents

### Working In This Directory

- Do not import ROS, `core`, or emit commands. ROS composition source is `middleware/perception/observers/learned_lane_node.py`; this implementation retains the `control.sensing.perception.learned` import identity.
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

`..` perception siblings (`lane.py` convention); `middleware/perception/observers/learned_lane_node.py` consumes this package.

### External

`numpy`, `cv2`; `onnxruntime` (lazy, device-side prefix)
