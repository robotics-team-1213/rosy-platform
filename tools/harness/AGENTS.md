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
| `affected_tests.py` | D-436 `affected` tier, wired as `rosy_harness.py affected [--base main] [--print\|--run] [--json]`: maps `base...HEAD` plus working-tree changes to owning modules, reverse dependents (`platform_parts.yaml` `import_prefix` imports), tests naming the changed path and the guard set (`GUARD_SET`); `FULL_TRIGGERS` and unmapped files escalate to full; invocations are packed so no two test files share a basename; every suite prints why. Tests: `test/test_affected_tests.py` |
| `run_functional.py` | Runs each module's `functional` pytest surface in isolation (`--module NAME` for one) |

## For AI Agents

### Working In This Directory

- What `lint` enforces: `progress.md` front matter has `module`, `owner`, `last_verified` (quoted commit or `uncommitted`, plus date) and `gates`; gates are `SOURCE LOCAL ROS-SIM ARTIFACT DEVICE FIELD` with state `GO HOLD PARKED N/A`, and `HOLD` needs a `blocker`; ADR ids exist in the ADR log; each `logs.md` entry has date, change, evidence, gate change in order, no duplicate entry, and committed entries are never edited (append-only, checked against git history); no conflict markers or mojibake; ADR index rows and body sections match, and gaps are declared in `adr_gaps`.
- After editing any `progress.md` or `logs.md`: `generate`, then `lint`, and commit the regenerated `index.md`/`STATUS.md` (the pre-push hook refuses to push them uncommitted).
- `progress.md/logs.md/index.md` may exist only at paths registered here (`test/architecture/test_folder_layout.py`), and every ROS package must be registered (`test_module_structure.py`).
- D-430 §5: a commit that changes a safety-tagged path (`concern: safety` roots, `safety_modules`) or removes a safety root, module or `safety_anchors` entry needs a `Safety-Review:` trailer. A `git mv` of a safety root or module touches both paths, so D-427 wave 3 and wave 4 moves need the trailer (3b firmware, 3c `console.py` and the other Fleet stop files, 4c OMX stop files, 4d `core_features/safety` and the CORE safety modules). `safety_review.py` checks it in CI.
- D-430 §4 approval record: a robot config with `safety.fleet_loss_policy` other than STOP/HOLD carries `safety.fleet_loss_policy_approval {robot, approver, evidence}`. `test_safety_separation.py` validates tracked YAML only; the runtime PUT `/api/v1/safety/limits` and on-device overlays are not covered.
- Run it with `python`, as the docs and the script header do. On Windows `python3` is often the Store stub without PyYAML; `tools/hooks/pre-push` copes by trying `python3` then `python` and picking the first that imports `yaml`. The code itself does not enforce the name.
- D-436: iterate with `python tools/harness/rosy_harness.py affected --run`. The full suite runs only on GitHub Actions runners (main push, escalated PRs, nightly, `workflow_dispatch`, before a release build); `--run` on a FULL selection runs the guards plus the suites mapped from the changed files (owning module, direct reverse dependents, referencing tests) and stops there (escalated paths are still mapped). Contract tests that build paths from components are found by the basename + parent-directory token match; files reached only through path constants (deploy compose and image/native manifests) are `FULL_TRIGGERS`, `--full` forces it locally. `--ci-matrix` emits the GitHub job matrix (`CI_FULL_MATRIX` + `ROOT_SHARDS` root `test/` shards + `build-smoke`, or one entry per affected invocation); add a new whole suite to `CI_FULL_MATRIX` with its `ros` level (`none`, `base`, `overlay`). Read CI with `gh run watch <id> --exit-status` and `gh run view <id> --log-failed` instead of re-running locally. The selector is only as accurate as `harness.yaml` paths and `platform_parts.yaml` `import_prefix`: a file outside every module escalates to full, so register new packages here instead of adding `affected` special cases. Editing `affected_tests.py`, `harness.yaml` or any file here escalates the selector itself to full.
- `run_functional.py` builds its `PYTHONPATH` from `src/rosy_core`, a pre-regroup path that no longer exists; check before relying on it.

### Testing Requirements

```bash
python tools/harness/rosy_harness.py lint
python -m pytest test/test_harness_contracts.py test/test_affected_tests.py -q
python tools/harness/rosy_harness.py affected --base main        # what the branch would run, and why
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
