# registry

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Existing artifact and provenance registries. The perception store holds content-addressed datasets, evalsets, READY inbox handovers and model provenance; model export, intake, delivery and watcher tooling use those unchanged shared paths. The policy ledger copies verified run bytes and records metadata. Neither a ledger stage nor an intake result grants operational execution authority.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `perception/` | Shared artifact/provenance `store.py`, model export/intake/delivery, version ledger and watcher (see `perception/AGENTS.md`) |
| `policy/` | SQLite ledger, hash chain, and assess/promote CLI (see `policy/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- The ledger root belongs on $ROSY_SCRATCH, not in the git repo.
- Promotion checks a PromotionRecord and a real report JSON. It does not start a robot.

### Testing Requirements

See `policy/AGENTS.md` and `perception/AGENTS.md`; perception uses the unified `test/learning/perception/` suite. Run committed HEAD through `tools/remote/remote_pytest.py` and compare with `test/known_failures.py`; never run laptop pytest (D-584). Tests must not point at a lab robot.

### Common Patterns

CLI is `python learning/registry/policy/registry.py --root <registry-on-X> ...`.

## Dependencies

### Internal

- Artifacts produced by `learning/training/` and dataset/evaluation manifests from `learning/curation/`.
- Contract source imports use `contracts/learning/src`; perception consumers also use the existing middleware and foundation contracts declared in their child guide.
- `tools/perception/` supplies the cross-owner CLI and pinned operator SSH options.

### External

- Policy uses the Python standard library and learning contracts. Perception export/intake tools require the optional model dependencies listed in `perception/AGENTS.md`; its `store.py` remains standard-library-only.

## Manual Notes
