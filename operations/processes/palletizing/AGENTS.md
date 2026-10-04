# Palletizing Process

## Purpose

Own the ROS-free recipe, taught-cell, placement, stack, ordering, and Job compilation rules for palletizing and depalletizing. `plan_bundle.py` converts the canonical Job into one versioned `pallet.transfer` Skill invocation per adjacent pick/place pair and keeps `pallet_done` as site-ledger metadata.

## Boundaries

- This module does not import Fleet, `rosy_cell`, OMX, ROS, or device integrations.
- A PlanBundle is a proposal for admission. It carries no approval, grant, dispatch, or device authority.
- Keep D-18 wire schemas unchanged here. Fleet owns the `pallet_done` ledger and execution sequencing.
- `operations/processes/cell/rosy_cell` is a one-way compatibility facade. Do not restore process algorithms there.
- Before mapping a Job, `compile_plan_bundle` recompiles from the supplied Recipe and Cell and rejects changed steps, carry height, or source hashes.

## Validation

The installed wheel is required by both the compatibility test and the legacy Cell suite:

```bash
python -m pytest test/test_platform_palletizing_compat.py -q
python -m pytest operations/processes/cell/test -q
```

Read [progress.md](progress.md) for current gates and append results to [logs.md](logs.md). Regenerate the module index and repository STATUS with `python tools/harness/rosy_harness.py generate`.
