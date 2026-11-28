
# Perception training

**Parent context:** `../AGENTS.md`

## Purpose

The trainer-side contract of the D-356/D-373 learned loop. Training runs outside this repository (Colab or any GPU PC); here live the input/output agreement: export a model folder with a manifest, check it, hand it to the store inbox.

The store folder, not Hugging Face, is the source of truth. Contract details: [README.md](README.md); Colab steps: [docs/COLAB.md](docs/COLAB.md) (keep in step with the notebook; only run as a local stub, not on a real Colab runtime).

## For AI Agents

### Working In This Directory

- Edit `gen_notebook.py`, never `rosy_lane_training.ipynb`; run `python gen_notebook.py` and commit both (`test_training_notebook.py` fails if they differ).
- `export_cell.py` and `run_log.py` stay torch-free at import; only `rosy_lane_model.py` imports torch at module level.
- `drivable_head.py` direct CLI export is held until the library is called under D-464 `IndexedReview`; this script cannot mint a `v13-drivable` artifact directly.
- The manifest contract is defined robot-side in `integrations/perception/perception_runtime/perception/learned/manifest.py`; change both sides together.
- Do not commit weights, datasets or Colab outputs. Do not put tokens or Drive paths in the notebook.
- Local run records + TensorBoard are the default tracking (D-356 addendum 2026-10-03); never write secret-looking config keys.
- W&B is optional: the key comes only from Colab Secrets / env `WANDB_API_KEY`, is never printed or written (no `wandb.login`, which writes `~/.netrc`); site and robot tools never depend on wandb.
- Class lists and measured Pi numbers are open items; do not invent them in the docs.
- `READY` is written last, so an inbox folder without a matching `READY` is never taken (`learning/registry/perception/store.py`). Hand-over is a copy into the store inbox; intake and delivery happen later in the registry.
- Review transport and sealed evidence helpers live in `learning/curation/perception/`; this holder keeps `review_admission.py` and `review_pipeline.py`. Training source proofs must pin the implementation files in their actual holders.
- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- D-637 split keeps bare import identities and the shared store. Remote host tests do not admit learning or activate robot behavior.

### Testing Requirements

`python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/learning-perception" -- test/learning/perception/test_training_contract.py test/learning/perception/test_training_handover.py test/learning/perception/test_training_model.py test/learning/perception/test_training_notebook.py test/learning/perception/test_training_run_log.py test/learning/perception/test_drivable_head.py test/learning/perception/test_drivable_cli_admission.py -q -p no:cacheprovider` (needs `torch`, `onnxruntime`; skips when missing).
