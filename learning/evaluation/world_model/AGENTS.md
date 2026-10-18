# world_model

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-17 · **Updated:** 2026-10-17 (D-782)

## Purpose

D-782 §6 offline acceptance for M1 artifacts. `m1_eval.py` scores held-out sessions and passes an artifact only when it beats both the hold baseline (state does not move) and the reach baseline (state equals the driving controller reference) at every horizon step. It reports 2-sigma coverage of the ensemble spread. A pass is offline evidence, not promotion, shadow or live acceptance.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | CLI and report fields |
| `m1_eval.py` | Baselines, per-step MAE, coverage, verdict |
| `test/` | Synthetic pass and reject cases |

## For AI Agents

### Working In This Directory

- Evaluate on `eval`; use `test` once for a final report. `train` is refused.
- The artifact must cite the evaluated dataset's exact bytes and share its horizon, rig and calibration revisions.
- Do not weaken the both-baselines rule to make a model pass. Record the reject.

### Testing Requirements

`python tools/remote/remote_pytest.py --log-dir <dir> -- learning/evaluation/world_model/test`, then `test/known_failures.py`.

## Dependencies

### Internal

- `contracts/learning/src/rosy/contracts/learning/prediction.py`
- `learning/curation/omx/world_model_dataset.py`, `learning/training/world_model/` (tests)

### External

- Python 3.12; numpy for the training step the tests run.
