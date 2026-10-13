# policy

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

D-449 offline policy ledger. SQLite `BEGIN IMMEDIATE`, `FULL` synchronous, file snapshots, and a canonical event hash chain. `register` re-checks policy, normalization, and eval bytes and copies them in. The same revision registered again does not grow history. A damaged file, stage, or history is rejected on the next read.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | CLI, assess-act, and HMAC promotion rules |
| `registry.py` | Ledger CLI: register, assess-act, show, history |
| `dataset_store.py` | Register a curated dataset directory |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- `assess-act` recomputes research conditions from the offline report tied by hash. It does not accept a reported pass as-is.
- `reject` and `offline_only` are not stage changes. The ledger stays unregistered for those.
- The last stage is a metadata promotion state. It is not the owner's permission to run.
- Promote needs a HMAC-SHA256 receipt from a trusted principal. Keys are injected, at least 32 bytes, and are not stored in this repo.

### Testing Requirements

Run the policy tests beside this folder with a temporary `--root` under X: or a temp directory. Do not use a shared lab registry.

### Common Patterns

Snapshot-then-commit. A failure before commit leaves an orphan snapshot that can be re-verified and registered again.

## Dependencies

### Internal

- `contracts/learning/` artifact shapes.
- Training jobs that emit the ACT run directory.

### External

- SQLite in the Python standard library.

## Manual Notes
