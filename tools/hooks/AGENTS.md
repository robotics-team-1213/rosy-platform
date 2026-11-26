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
| `pre-push` | Bash hook, the D-346 fast gate: harness `lint`, generated-records check, fast pytest suites, D-436 affected tier. Details in the rules below |
| `reference-transaction` | Guards local `refs/heads/main` (see rules). Test `test/test_main_writer_hook.py` |
| `install.sh` | Copies `pre-push` and `reference-transaction` to `.git/hooks/` and marks them executable. Uninstall with `rm .git/hooks/<name>` |

## For AI Agents

### Working In This Directory

- The installed copy in `.git/hooks` does not follow edits here; re-run `install.sh` after changing `pre-push`.
- pre-push picks the first of `python3`/`python` that imports `yaml`. Pytest runs `test_harness_contracts.py`, `architecture/test_module_structure.py`, `test_io_image_closure.py`, `test_line_follow_contract_docs.py`, `test_protocol_version_alignment.py` (list in the file).
- Both pytest steps run through `tools/remote/remote_pytest.py` on the pushed commit (first local sha on stdin, else HEAD): model, AI or site PC by headroom (D-568), this machine only when none answers. Lint, generated-records check and Safety-Review stay local.
- The D-436 affected tier uses `rosy_harness.py affected --json` against the `origin/main` merge base. `--skip` drops the fast suites (`FAST_SUITES`). A FULL escalation still runs only guards plus mapped suites; the full suite runs on GitHub runners.
- `reference-transaction` refuses any move of local `refs/heads/main` unless `ROSY_MAIN_WRITER` is set (only `tools/land.py`'s fast-forward) or the new tip is `origin/main` (D-868 sync). Reason: 25 hand commits on main stopped every landing for a day (2026-11-13).
- Keep it fast. A new check belongs here only if it is cheap and has already failed CI; everything else stays in CI.
- Never bypass the hook with `--no-verify`; fix the failure.
- The `Safety-Review:` step (D-430 §5) runs `tools/harness/safety_review.py origin/main <pushed sha>` and refuses the push on a missing trailer: the same rule and range CI's `scope` job checks after a push to `main` (D-762 stage 0). `tools/land.py` refuses the landing earlier on the same rule.

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
