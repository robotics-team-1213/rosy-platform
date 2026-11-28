
# Perception registry

**Parent context:** `../AGENTS.md`

## Purpose

The artifact and provenance store (`store.py`) plus the model half of the D-356 learned-perception loop: export to ONNX, verify a model against the intake gate (`intake_gate.yaml`), deliver it to a robot's shadow slot (with rollback). The delivered model runs shadow-only; activating it for driving is separate.

`intake_dataset.py` holds immutable dataset and training-source bindings; D-666 offline paired fitness shares them without entering delivery.

## For AI Agents

### Working In This Directory

- Delivery refuses a model whose intake failed; never add a force path around it.
- `v13-drivable` intake and push are refused (final fail, not a retriable HOLD) unless the manifest carries D-554 lineage (`parent_lane_model`, 64-hex dataset revision, `dataset.annotation_origin: derived_from_reviewed_lanes`, `dataset.adr: D-554`, `camera_provenance`).
- Push goes only to the lane_seg shadow slot; lane_seg has no promote.
- `drivable_versions.yaml` (D-558) is the ledger of `v13-drivable` versions; intake refuses a missing, malformed, off-lineage or taken version.
- HF revisions must be 40-hex commit hashes, not tags. The store folder is the source of truth; `store-inbox:` is taken only when its READY marker matches its content.
- `deliver.py` robot writes use `../../../tools/perception/operator_ssh.py` (user `rosy`, pinned known_hosts, BatchMode, `sudo -n`). `--slot paint` moves only the D-408 paint pointer; the watcher never pushes paint.
- `promote_readback.py` (D-773 A3) journals every pointer change; `--readback` is evidence only, not device acceptance, and never changes delivery exit.
- `model_lineage.py` is read-only: no admission or delivery authority; missing proofs stay missing.
- Model weights never go in `src/` or git. A rejected model is moved, not deleted.
- The eval champion is the best passing `intake_report.json` on the same eval set content sha; a missing or empty eval set is a transient setup error, never a model verdict. Train/eval session overlap is a model fail; unresolvable is `disjoint: "unverified"`.
- Keep `watch_core.py` free of I/O; callers use `watch.<name>`.
- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- D-637 split keeps bare import identities and the shared store. Remote host tests do not admit learning or activate robot behavior.

### Testing Requirements

`python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/learning-perception" -- test/learning/perception/test_model_intake.py test/learning/perception/test_model_intake_eval.py test/learning/perception/test_model_deliver.py test/learning/perception/test_model_watch.py test/learning/perception/test_model_watch_host.py test/learning/perception/test_model_watch_inbox.py -q -p no:cacheprovider` (needs `onnxruntime`, `torch`, `mcap`; skips when missing).
