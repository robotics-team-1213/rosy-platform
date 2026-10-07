# registry

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Offline policy metadata registry. Registering a run copies verified bytes into the ledger. A later stage flag is not an execution grant.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `policy/` | SQLite ledger, hash chain, and assess/promote CLI (see `policy/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- The ledger root belongs on X:, not in the git repo.
- Promotion checks a PromotionRecord and a real report JSON. It does not start a robot.

### Testing Requirements

See `policy/AGENTS.md`. Tests must not point at a lab robot.

### Common Patterns

CLI is `python learning/registry/policy/registry.py --root <registry-on-X> ...`.

## Dependencies

### Internal

- Artifacts produced by `learning/training/omx/` and dataset manifests from curation.

### External

- Python standard library plus the contract wheel the policy package imports. No ROS.

## Manual Notes
