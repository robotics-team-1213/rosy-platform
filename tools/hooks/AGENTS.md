<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# hooks

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-08

## Purpose

The D-346 pre-push fast gate (under 2 minutes). Git does not version hooks, so each clone installs it explicitly. It catches the class that landed red on 2026-09-29: ADR body gaps, io closure, version pins, size verdicts.

## Key Files

| File | Description |
|------|-------------|
| `pre-push` | Bash hook. Picks the first of `python3`/`python` that can import `yaml`, then runs: harness `lint`; a check that regenerated `index.md`/`STATUS.md` are committed; pytest on `test/test_harness_contracts.py`, `test/architecture/test_module_structure.py`, `test/test_io_image_closure.py`, `test/test_line_follow_contract_docs.py` and `middleware/core/gateway/test/test_protocol_version_alignment.py` (see the file for the current list); then the D-436 affected tier (`rosy_harness.py affected --json` against the `origin/main` merge base). Both pytest steps go through `tools/remote/remote_pytest.py` on the commit being pushed (first local sha on stdin, else HEAD): model PC, then AI PC, this machine only when neither answers. Lint, the generated-records check and Safety-Review stay local. `--skip` drops the fast suites (one `FAST_SUITES` array) so the guards do not run twice. On a FULL escalation it still runs only the guards plus the suites mapped from the changed files (owning module, direct reverse dependents, referencing tests); the full suite runs on GitHub runners, never in the hook |
| `install.sh` | Copies `pre-push` to `.git/hooks/pre-push` and marks it executable. Uninstall with `rm .git/hooks/pre-push` |

## For AI Agents

### Working In This Directory

- The installed copy in `.git/hooks` does not follow edits here; re-run `install.sh` after changing `pre-push`.
- Keep it fast. A new check belongs here only if it is cheap and has already failed CI; everything else stays in CI.
- Never bypass the hook with `--no-verify`; fix the failure.
- The `Safety-Review:` step (D-430 §5) runs `tools/harness/safety_review.py --warn-only` on the pushed tip for a quick local warning. The CI step in `.github/workflows/ci.yml` checks the complete range and enforces it.

### Testing Requirements

```bash
python -m pytest test/test_pre_push_hook.py -q
```

### Common Patterns

- `set -euo pipefail`, `cd` to the repo top-level first, and a stderr message that says what to do.

## Dependencies

### Internal

- `tools/harness/rosy_harness.py` (`lint`, `generated_targets`), the pytest files listed above

### External

- bash, git, Python with PyYAML and pytest

<!-- MANUAL: -->
