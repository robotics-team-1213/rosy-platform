<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# training

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

The trainer-side contract of the D-356/D-373 learned loop. Training itself runs outside this repository (Colab or any GPU PC); what lives here is the input/output agreement: export a model folder with a manifest, check it, and hand it to the store inbox. The store folder, not Hugging Face, is the source of truth (HF is optional).

## Key Files

| File | Description |
|------|-------------|
| `README.md` | The training contract: store layout, model folder and manifest rules (Korean) |
| `COLAB.md` | Manual, step-by-step Colab procedure for people using their own notebook. Hand-written; keep it in step with the notebook. States that the notebook has only been run as a local stub, not on a real Colab runtime |
| `rosy_lane_training.ipynb` | Ready-to-run Colab notebook: baseline model training, export, check, hand-over. Generated, do not edit by hand |
| `gen_notebook.py` | Source of the notebook: edit here, then `python gen_notebook.py`; `test_training_notebook.py` fails if they differ |
| `rosy_lane_model.py` | Baseline trainer (`LaneUNet`, same structure as the deployed 0930 model). Imports torch at module level; `train(on_epoch=...)` feeds an optional tracker, never imports wandb |
| `run_log.py` | Default experiment record (D-356 addendum 2026-10-03): `RunLog(run_dir)` writes `config.json` (secret-looking keys dropped), `history.json` (per epoch, atomic), `summary.json` and optional TensorBoard events; `chain()` joins `on_epoch` hooks. Logging errors never stop training. No torch import at module level |
| `export_cell.py` | Trainer-side export of `model.onnx` plus `model_manifest.json` (`rosy.perception.model/1`). Copy into a notebook or import it; torch is imported lazily and `write_manifest()` needs none. `experiment=` stores a `wandb` or `local` run link as `metrics.experiment` (known keys per tracker only) |
| `check_manifest.py` | `check_manifest.py <model_folder>`: load the manifest, verify files, open the model if `onnxruntime` is importable; prints `OK <model_revision>` or the error, exit 1 on failure |
| `handover.py` | `package()` drops a model folder into `<store>/models/inbox/<model_revision>__<utc>/` with `READY` written last; `package_zip()` makes a downloadable zip. Only `model_manifest.json` and the files it names are handed over |

## For AI Agents

### Working In This Directory

- Edit `gen_notebook.py`, never the `.ipynb`; regenerate and commit both.
- `export_cell.py` must stay torch-free at import time; only `rosy_lane_model.py` may import torch at module level.
- The manifest contract is defined on the robot side in `middleware/perception/control/sensing/perception/learned/manifest.py`; change both sides together.
- Do not commit weights, datasets or Colab outputs. Do not put tokens or Drive paths in the notebook.
- Local run records + TensorBoard are the default tracking (D-356 addendum 2026-10-03); keep `run_log.py` torch-free at import and never write secret-looking config keys.
- W&B is optional (D-356 addendum 2026-10-03): the key comes only from Colab Secrets / env `WANDB_API_KEY`, is never printed or written (no `wandb.login`, which writes `~/.netrc`); site and robot tools never depend on wandb.
- Class lists and measured Pi numbers are open items; do not invent them in the docs.

### Testing Requirements

```bash
python -m pytest learning/training/perception/test/test_training_contract.py learning/training/perception/test/test_training_handover.py learning/training/perception/test/test_training_model.py learning/training/perception/test/test_training_notebook.py learning/training/perception/test/test_training_run_log.py -q -p no:cacheprovider
```

Needs `torch` and `onnxruntime`; tests skip where missing.

### Common Patterns

- `READY` is written last, so an inbox folder without a matching `READY` is never taken (`../store.py`).
- Hand-over is a copy into the store inbox; intake and delivery happen later in `../model/`.

## Dependencies

### Internal

- `../store.py`, `../model/` (intake, deliver, watch), `middleware/perception/control/sensing/perception/learned/manifest.py`

### External

- `torch`, `onnxruntime`, `numpy`; Colab for the notebook

<!-- MANUAL: -->
