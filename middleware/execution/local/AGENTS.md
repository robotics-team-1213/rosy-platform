# local

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel `rosy-execution-local`. Verifies an installed policy artifact against a caller-supplied `InstallBinding` (pinned revision, device and camera profile, normalization hash, owner, controller, envelope, action order, ranges, timing). `InstalledPolicy.recheck()` notices a replaced manifest or a corrupt referenced file. No inference model is deserialized.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Binding rules, the OMX session, and what this wheel does not authorize |
| `pyproject.toml` | Wheel metadata and the contract pins |
| `test/` | Install, journal, parent-fence, and OMX session tests |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `test/` | Host pytest. `native_parent_chain.py` supports the fence tests |

## For AI Agents

### Working In This Directory

- Bindings come from the accepted installed release. Deriving them from the policy being inspected is not a check.
- `OwnerPolicySession` defaults disabled and accepts only a bound SIM identity. Faults latch HOLD and cancel that session's own active command. Do not add automatic rearm or a final publisher.
- The installation loader imports no registry, inference framework, ROS node, device driver, or network client.

### Testing Requirements

`python -m pytest middleware/execution/local/test -q`

### Common Patterns

Metadata returned to callers is a fresh copy. Bool and numeric aliases do not satisfy camera equality.

## Dependencies

### Internal

- Skill contract 0.1.0 and learning contract, as pinned in the README.
- OMX `ArmCommandOwner` and `LocalStopController` only on the optional `omx_policy` path.

### External

- None on the loader import path beyond the contract wheels.

## Manual Notes
