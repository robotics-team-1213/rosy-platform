<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# Perception training

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-11

## Purpose

The trainer-side contract of the D-356/D-373 learned loop. Training itself runs outside this repository (Colab or any GPU PC); what lives here is the input/output agreement: export a model folder with a manifest, check it, and hand it to the store inbox. The store folder, not Hugging Face, is the source of truth (HF is optional).

## Key Files

| File | Description |
|------|-------------|
| `README.md` | The training contract: store layout, model folder and manifest rules (Korean) |
| `docs/COLAB.md` | Manual, step-by-step Colab procedure for people using their own notebook. Hand-written; keep it in step with the notebook. States that the notebook has only been run as a local stub, not on a real Colab runtime |
| `rosy_lane_training.ipynb` | Ready-to-run Colab notebook: baseline model training, export, check, hand-over. Generated, do not edit by hand |
| `gen_notebook.py` | Source of the notebook: edit here, then `python gen_notebook.py`; `test_training_notebook.py` fails if they differ |
| `rosy_lane_model.py` | Baseline trainer (`LaneUNet`, same structure as the deployed 0930 model). Imports torch at module level; `train(on_epoch=...)` feeds an optional tracker, never imports wandb |
| `drivable_head.py` | Frozen delivered lane model (TorchScript, e.g. now2466 v11) + drivable head library (user decision 2026-10-07). Rebuilds the lane model as `LaneUNet` (key renames, output parity checked) and trains only the head. Direct CLI export is held until this library is called under D-464 `IndexedReview`; this script cannot mint a `v13-drivable` artifact directly. |
| `run_log.py` | Default experiment record (D-356 addendum 2026-10-03): `RunLog(run_dir)` writes `config.json` (secret-looking keys dropped), `history.json` (per epoch, atomic), `summary.json` and optional TensorBoard events; `chain()` joins `on_epoch` hooks. Logging errors never stop training. No torch import at module level |
| `export_cell.py` | Trainer-side export of `model.onnx` plus `model_manifest.json` (`rosy.perception.model/1`). Copy into a notebook or import it; torch is imported lazily and `write_manifest()` needs none. `experiment=` stores a `wandb` or `local` run link as `metrics.experiment` (known keys per tracker only) |
| `check_manifest.py` | `check_manifest.py <model_folder>`: load the manifest, verify files, open the model if `onnxruntime` is importable; prints `OK <model_revision>` or the error, exit 1 on failure |
| `handover.py` | `package()` drops a model folder into `<store>/models/inbox/<model_revision>__<utc>/` with `READY` written last; `package_zip()` makes a downloadable zip. Only `model_manifest.json` and the files it names are handed over |

## For AI Agents

### Working In This Directory

- Edit `gen_notebook.py`, never the `.ipynb`; regenerate and commit both.
- `export_cell.py` must stay torch-free at import time; only `rosy_lane_model.py` may import torch at module level.
- The manifest contract is defined on the robot side in `middleware/perception/front_camera/perception/learned/manifest.py`; change both sides together.
- Do not commit weights, datasets or Colab outputs. Do not put tokens or Drive paths in the notebook.
- Local run records + TensorBoard are the default tracking (D-356 addendum 2026-10-03); keep `run_log.py` torch-free at import and never write secret-looking config keys.
- W&B is optional (D-356 addendum 2026-10-03): the key comes only from Colab Secrets / env `WANDB_API_KEY`, is never printed or written (no `wandb.login`, which writes `~/.netrc`); site and robot tools never depend on wandb.
- Class lists and measured Pi numbers are open items; do not invent them in the docs.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/learning-perception" -- test/learning/perception/test_training_contract.py test/learning/perception/test_training_handover.py test/learning/perception/test_training_model.py test/learning/perception/test_training_notebook.py test/learning/perception/test_training_run_log.py test/learning/perception/test_drivable_head.py test/learning/perception/test_drivable_cli_admission.py -q -p no:cacheprovider
```

Needs `torch` and `onnxruntime`; tests skip where missing.

### Common Patterns

- `READY` is written last, so an inbox folder without a matching `READY` is never taken (`learning/registry/perception/store.py`).
- Hand-over is a copy into the store inbox; intake and delivery happen later in `learning/registry/perception/`.

## Dependencies

### Internal

- `learning/registry/perception/store.py`, `learning/registry/perception/` (intake, deliver, watch), `middleware/perception/front_camera/perception/learned/manifest.py`

### External

- `torch`, `onnxruntime`, `numpy`; Colab for the notebook

<!-- MANUAL: -->

## Owner evidence

See [progress.md](progress.md), [logs.md](logs.md), and [index.md](index.md). The folder split in D-637 preserves bare import identities and the shared artifact/provenance store. Remote host tests do not admit learning or activate robot behavior.

Review transport, indexed dataset preparation and sealed evidence helpers live in `learning/curation/perception/`. This holder retains `review_admission.py` and `review_pipeline.py`; training source proofs must pin the implementation files in their actual holders.
