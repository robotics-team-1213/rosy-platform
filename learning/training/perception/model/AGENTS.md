<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# model

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

The model half of the D-356 learned-perception loop: export a trained model to ONNX, verify a returned model against the intake gate, and deliver it to a robot's shadow slot (with rollback). The delivered model runs shadow-only; activating it for driving is a separate decision.

## Key Files

| File | Description |
|------|-------------|
| `export_onnx.py` | TorchScript to ONNX (opset 17, 1x3x240x320) with a fixed-seed parity check; writes the model folder and manifest |
| `intake.py` | Shadow-deployment eligibility report for a model folder, `store-inbox:<folder>` (taken only when its READY marker matches its content) or `hf:org/repo@<40-hex sha>`; thresholds come from `intake_gate.yaml` |
| `intake_gate.yaml` | Gate values: p50 host latency, NaN frames, minimum visible-lane fraction, replay sources and frame cap; D-379 eval set keys (`eval_set`, `eval_max_frames`, `min_eval_miou`, `max_eval_miou_drop`, `min_lane_marking_iou`; `eval_set: null` = no eval; gated mIoU leaves out background). Eligibility only, not the D-205 selection gate |
| `deliver.py` | `push`, `rollback`, `release-hold`, `status` against a robot over ssh (default root `/var/lib/rosy/models`); refuses a model whose intake failed |
| `watch.py` | Site-host watcher (D-373): intake plus shadow push for each READY inbox folder (or each new HF commit with `backend: hf`); reads `/etc/rosy/model-watch.yaml` |
| `watch_core.py` | Pure state transitions of the watcher (no I/O, no clock), split out for the 600-line budget; `watch.py` re-exports the names |

## For AI Agents

### Working In This Directory

- Delivery refuses a model whose intake failed; never add a force path around it.
- HF revisions must be 40-hex commit hashes, not tags. The store folder is the source of truth.
- Robot writes use the operator SSH options in `../operator_ssh.py` (user `rosy`, key plus pinned known_hosts, BatchMode, `sudo -n`).
- Model weights never go in `src/` or git.
- The eval champion is the best passing `<out>/*/intake_report.json` on the same eval set content sha, compared over shared classes; a missing or empty eval set is a transient setup error, never a model verdict. Train/eval session overlap (store dataset resolvable) is a model fail; unresolvable is `disjoint: "unverified"`.
- Keep `watch_core.py` free of I/O so its transitions stay unit-testable; callers use `watch.<name>`.

### Testing Requirements

```bash
python -m pytest learning/training/perception/test/test_model_intake.py learning/training/perception/test/test_model_intake_eval.py learning/training/perception/test/test_model_deliver.py learning/training/perception/test/test_model_watch.py learning/training/perception/test/test_model_watch_host.py learning/training/perception/test/test_model_watch_inbox.py -q -p no:cacheprovider
```

Needs `onnxruntime`, `torch` and `mcap`; tests skip cleanly where one is missing.

### Common Patterns

- Reports and the intake verdict are files in `data/perception/models/`; a rejected model is moved, not deleted.

## Dependencies

### Internal

- `../store.py`, `../operator_ssh.py`, `../rosy_ml.py` (operator CLI that wraps these), `middleware/perception/control/sensing/perception/learned/manifest.py`

### External

- `onnxruntime`, `torch`, `numpy`, `PyYAML`; `ssh`/`scp`; optional `huggingface_hub` for the HF backend

<!-- MANUAL: -->
