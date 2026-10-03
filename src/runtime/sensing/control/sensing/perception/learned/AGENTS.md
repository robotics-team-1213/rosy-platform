<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# learned

## Purpose

Learned (ONNX) lane-perception backend, D-356 / D-373. ROS-free pre/post-processing and runtime plumbing behind a fixed contract: a model manifest in, lane evidence out, same shape as the rule-based `lane.py`. Rule-based stays the default (`perception.backend=rule`); this backend is shadow evidence plus an optional paint mask for the lane keeper. It never emits a twist or `cmd_vel`; only CORE publishes the final command.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package docstring: model contract, pre/post-processing, runner; weights never live in `src/` |
| `manifest.py` | `rosy.perception.model/1` manifest: schema, roles, sha256 and shape checks, fail-closed `ManifestError` |
| `lane_mask.py` | `preprocess` (frame to NCHW) and `lane_evidence` (logits to visible/error/confidence), near-field band, `wall` never a target |
| `runner.py` | `LaneSegModel` (lazy `onnxruntime`, warm-up check) and `ModelSlot` (pointer-file hot swap; failed swap keeps previous model) |
| `shadow.py` | `perception/learned/shadow` payload pairing learned and rule error; no command fields |
| `status.py` | `perception/learned/status` payload: counters, latency, "no shadow model loaded" |
| `paint_worker.py` | `LearnedPaintWorker`: one thread infers on the latest frame; keeper takes the newest mask within `stale_s` or falls back (D-408) |

## For AI Agents

### Working In This Directory

- Do not import ROS, `core`, or emit commands. The ROS node is `learned_lane_node.py` one level up in `sensing/`.
- Weights arrive via `tools/perception/model/deliver.py`, never committed under `src/`. `onnxruntime` is imported lazily and is not in the base device image.
- Keep the output contract (evidence fields, `LaneObservation` sign convention, wire schemas) stable so backends stay swappable. Anything failing validation must be refused, not guessed.
- Promotion beyond shadow is gated by the D-205 replay gate.

### Testing Requirements

Tests are in `src/runtime/sensing/test/`; most run without rclpy. Run the sensing suite on its own line:

```bash
python3 -m pytest src/runtime/sensing/test/test_learned_manifest.py src/runtime/sensing/test/test_learned_lane_mask.py src/runtime/sensing/test/test_learned_runner.py src/runtime/sensing/test/test_learned_shadow.py src/runtime/sensing/test/test_learned_status.py -q
```

### Common Patterns

- Wire schemas are versioned strings (`rosy.perception.learned_shadow/1`, `rosy.perception.learned_status/1`).
- Time-dependent code takes injectable `clock`/`warn` callables for tests.

## Dependencies

### Internal

`..` perception siblings (`lane.py` convention); `sensing/learned_lane_node.py` consumes this package.

### External

`numpy`, `cv2`; `onnxruntime` (lazy, device-side prefix)
