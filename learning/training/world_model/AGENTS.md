# world_model

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-17 · **Updated:** 2026-10-17 (D-782)

## Purpose

D-782 M1 training. `m1_job.py` fits a bootstrap ridge ensemble that maps the current normalized OMX joint/gripper state and the next `horizon` controller references to the next `horizon` states. Member disagreement is the uncertainty. Input is a dataset built by `learning/curation/omx/world_model_dataset.py`; output is a digest-bound `rosy.world-model-artifact.v1`. Training is not promotion, shadow or deployment.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | CLI and what a run proves |
| `m1_job.py` | Train split only, train-only normalization, deterministic seed, new output directory |
| `test/` | Synthetic-dynamics checks |

## For AI Agents

### Working In This Directory

- The evaluation rule is `rosy.contracts.learning.prediction.forward`. Do not add a second forward pass here; training, evaluation and the operations checker must compute the same thing.
- The artifact cites the exact dataset bytes. Do not rewrite an artifact after training; train again into a new directory.
- M2 (object result) and M3 (pretrained video/latent models) are later D-782 stages and need their own decision.

### Testing Requirements

`python tools/remote/remote_pytest.py --log-dir <dir> -- learning/training/world_model/test`, then `test/known_failures.py`. Needs numpy.

## Dependencies

### Internal

- `contracts/learning/src/rosy/contracts/learning/prediction.py`
- `learning/curation/omx/world_model_dataset.py`

### External

- Python 3.12, numpy.
