<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# Perception registry

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-11

## Purpose

The artifact and provenance store plus the model half of the D-356 learned-perception loop: export a trained model to ONNX, verify a returned model against the intake gate, and deliver it to a robot's shadow slot (with rollback). The delivered model runs shadow-only; activating it for driving is a separate decision.

`intake_dataset.py` holds immutable dataset and training-source bindings; `intake.py` re-exports the existing helpers and EvalSetError. `store.read_fixed_manifest` refuses links and verifies manifest bytes against the content version. D-666 offline paired fitness shares these bindings without entering model delivery.

## Key Files

| File | Description |
|------|-------------|
| `store.py` | Shared content-addressed datasets, evalsets, models and READY inbox storage; physical relocation preserves its paths and signatures |
| `model_lineage.py` | Read-only private CLI: exact model/files, fixed dataset/eval content and intake/journal links; missing source, human review and training proofs stay missing. No admission or delivery authority. See `docs/plans/2026-10-21-model-lineage-design.md` |
| `export_onnx.py` | TorchScript to ONNX (opset 17, 1x3x240x320) with a fixed-seed parity check; writes the model folder and manifest |
| `intake.py` | Shadow-deployment eligibility report for a model folder, `store-inbox:<folder>` (taken only when its READY marker matches its content) or `hf:org/repo@<40-hex sha>`; thresholds come from `intake_gate.yaml` |
| `drivable_versions.py` / `drivable_versions.yaml` | D-558 ledger of `v13-drivable` model versions (`v<major>.<minor>.<NN>`, one revision each, status candidate/shadow/rejected/retired); intake refuses a missing, malformed, off-lineage or taken version; CLI `show`/`add`/`set-status` |
| `intake_gate.yaml` | Gate values: p50 host latency, NaN frames, minimum visible-lane fraction, replay sources and frame cap; D-379 eval set keys (`eval_set`, `eval_max_frames`, `min_eval_miou`, `max_eval_miou_drop`, `min_lane_marking_iou`; `eval_set: null` = no eval; gated mIoU leaves out background). Eligibility only, not the D-205 selection gate |
| `deliver.py` | `push`, `rollback`, `release-hold`, `status` against a robot over ssh (default root `/var/lib/rosy/models`); refuses a model whose intake failed; lane_seg `--slot paint` moves the D-408 paint pointer (`paint`, `paint.previous`, `paint.hold`) and leaves shadow and the watcher alone; nothing reads `paint` unless `/etc/rosy/line_observer_overrides.yaml` sets `learned_lane_pointer: /var/lib/rosy/models/paint` (`host_lane_perception.py` still reads shadow), and `paint.hold` is a record only (the watcher never pushes paint) |
| `promote_readback.py` | D-773 A3: after a successful push/rollback/promote, `deliver.py` appends one line to `<journal-dir>/pointer-changes/pointer_changes.jsonl` (no extra network step). `--readback` reads latched status for `lane_seg` shadow/`object_det` active; paint reads the next volatile `line/keep_debug` consumed revision and rechecks its pointer. Records `match`/`mismatch`/`unavailable`/`no_node` without changing delivery exit. Paint signature remains unknown. Evidence only, not device acceptance; live robot readback is unverified |
| `watch.py` | Site-host watcher (D-373): intake plus shadow push for each READY inbox folder (or each new HF commit with `backend: hf`); reads `/etc/rosy/model-watch.yaml` |
| `watch_core.py` | Pure state transitions of the watcher (no I/O, no clock), split out for the 600-line budget; `watch.py` re-exports the names |

## For AI Agents

### Working In This Directory

- Delivery refuses a model whose intake failed; never add a force path around it.
- `v13-drivable` intake and push are refused (final fail, not a retriable HOLD) unless the manifest carries D-554 lineage: `parent_lane_model` (lane-seg revision, ONNX sha256), a 64-hex dataset revision and `dataset.annotation_origin: derived_from_reviewed_lanes` with `dataset.adr: D-554`, plus a `camera_provenance` mark (accepted or provisional, D-554 item 7) (`intake_eval_gate.v13_lineage_error`). Push goes only to the lane_seg shadow slot; lane_seg has no promote.
- HF revisions must be 40-hex commit hashes, not tags. The store folder is the source of truth.
- Robot writes use the operator SSH options in `../../../tools/perception/operator_ssh.py` (user `rosy`, key plus pinned known_hosts, BatchMode, `sudo -n`).
- Model weights never go in `src/` or git.
- The eval champion is the best passing `<out>/*/intake_report.json` on the same eval set content sha, compared over shared classes; a missing or empty eval set is a transient setup error, never a model verdict. Train/eval session overlap (store dataset resolvable) is a model fail; unresolvable is `disjoint: "unverified"`.
- Keep `watch_core.py` free of I/O so its transitions stay unit-testable; callers use `watch.<name>`.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/learning-perception" -- test/learning/perception/test_model_intake.py test/learning/perception/test_model_intake_eval.py test/learning/perception/test_model_deliver.py test/learning/perception/test_model_watch.py test/learning/perception/test_model_watch_host.py test/learning/perception/test_model_watch_inbox.py -q -p no:cacheprovider
```

Needs `onnxruntime`, `torch` and `mcap`; tests skip cleanly where one is missing.

### Common Patterns

- Reports and the intake verdict are files in `data/perception/models/`; a rejected model is moved, not deleted.

## Dependencies

### Internal

- `learning/registry/perception/store.py`, `../../../tools/perception/operator_ssh.py`, `tools/perception/rosy_ml.py` (operator CLI that wraps these), `middleware/perception/front_camera/perception/learned/manifest.py`

### External

- `onnxruntime`, `torch`, `numpy`, `PyYAML`; `ssh`/`scp`; optional `huggingface_hub` for the HF backend

<!-- MANUAL: -->

## Owner evidence

See [progress.md](progress.md), [logs.md](logs.md), and [index.md](index.md). The folder split in D-637 preserves bare import identities and the shared artifact/provenance store. Remote host tests do not admit learning or activate robot behavior.
