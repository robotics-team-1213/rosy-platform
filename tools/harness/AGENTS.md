<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# harness

## Purpose

The D-61 module harness: a registry of modules, each of which keeps `progress.md` (gate states with evidence) and `logs.md` (append-only change log), and a generator/linter that turns them into per-module `index.md` and the root `STATUS.md`. Design: `docs/plans/2026-09-15-module-harness-design.md`. ROS-free; standard library plus PyYAML.

## Key Files

| File | Description |
|------|-------------|
| `harness.yaml` | Registry: `adr_log`, `adr_gaps` (ADR numbers deliberately absent, with reason), `status`, `stale_after_commits`, and `modules` (`name`, `path`, `tests`, `functional_kind`, `functional`). Edit it when a package is added, moved or removed |
| `rosy_harness.py` | `generate` rewrites every module `index.md` and `STATUS.md`; `lint` validates and exits 1 on errors (staleness is only a warning) |
| `platform_parts.yaml` | D-427 part manifest: every root's part, `d427_target`, wave and D-429/D-430 `concern`; `safety_modules` and `safety_anchors` (D-430 §1). Checked by `test/architecture/test_platform_parts.py` and `test_safety_separation.py` |
| `safety_review.py` | D-430 §5: `python tools/harness/safety_review.py BASE HEAD [--warn-only]` fails when a non-merge commit after its `BASELINE` touches (or untags) a safety-tagged path without a `Safety-Review:` trailer. CI runs it on the PR/push range; the pre-push hook runs it as a warning |
| `run_functional.py` | Runs each module's `functional` pytest surface in isolation (`--module NAME` for one) |

## For AI Agents

### Working In This Directory

- What `lint` enforces: `progress.md` front matter has `module`, `owner`, `last_verified` (quoted commit or `uncommitted`, plus date) and `gates`; gates are `SOURCE LOCAL ROS-SIM ARTIFACT DEVICE FIELD` with state `GO HOLD PARKED N/A`, and `HOLD` needs a `blocker`; ADR ids exist in the ADR log; each `logs.md` entry has date, change, evidence, gate change in order, no duplicate entry, and committed entries are never edited (append-only, checked against git history); no conflict markers or mojibake; ADR index rows and body sections match, and gaps are declared in `adr_gaps`.
- After editing any `progress.md` or `logs.md`: `generate`, then `lint`, and commit the regenerated `index.md`/`STATUS.md` (the pre-push hook refuses to push them uncommitted).
- `progress.md/logs.md/index.md` may exist only at paths registered here (`test/architecture/test_folder_layout.py`), and every ROS package must be registered (`test_module_structure.py`).
- Run it with `python`, as the docs and the script header do. On Windows `python3` is often the Store stub without PyYAML; `tools/hooks/pre-push` copes by trying `python3` then `python` and picking the first that imports `yaml`. The code itself does not enforce the name.
- `run_functional.py` builds its `PYTHONPATH` from `src/rosy_core`, a pre-regroup path that no longer exists; check before relying on it.

### Testing Requirements

```bash
python tools/harness/rosy_harness.py lint
python -m pytest test/test_harness_contracts.py -q
```

### Common Patterns

- Run from the repository root; the config path `tools/harness/harness.yaml` is relative to it.
- Korean log field names (`변경`, `증거`, `gate 변화`) have English aliases (Change, Evidence, Gate).

## Dependencies

### Internal

- Every registered module's `progress.md` and `logs.md`, `docs/reference/ROSY ADR Log.md`, `STATUS.md`

### External

- PyYAML; `git` for the append-only and staleness checks

<!-- MANUAL: -->
