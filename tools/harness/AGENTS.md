<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# harness

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

The D-61 module harness: a registry of modules, each of which keeps `progress.md` (gate states with evidence) and `logs.md` (append-only change log), and a generator/linter that turns them into per-module `index.md` and the root `STATUS.md`. Design: `docs/plans/2026-09-15-module-harness-design.md`. ROS-free; standard library plus PyYAML.

## Key Files

| File | Description |
|------|-------------|
| `harness.yaml` | Registry: `adr_log`, `status`, `stale_after_commits`, and `modules` (`name`, `path`, `tests`, `functional_kind`, `functional`). Edit it when a package is added, moved or removed |
| `adr_gaps.txt` | D-510: ADR numbers deliberately absent, one `D-nnn reason` line each; `merge=union`, duplicates are deduped by number. A local `refs/adr/D-nnn` reservation is never a gap; `lint` warns about one not on the branch |
| `adr_reserve.py` | D-510: `next "<topic>"` claims the next ADR number as a create-only `refs/adr/D-nnn` ref and prints it (scans branches, remotes, worktrees; ignores numbers >20 above main's highest); `list`, `release D-nnn --reason <topic>` or `--force`. Stdlib only. Tests: `test/test_harness_contracts.py` |
| `api_reserve.py` | D-510 for API reference versions: `next "<topic>"` claims `refs/api/v1.NNN` with the `adr_reserve.py` helpers (scans the Version header and `### v1.NNN` rows on branches, remotes, worktrees); `list`, `release v1.NNN`, `bump v1.NNN` rewrites only live-version pins. Stdlib only. Tests: `test/test_api_reserve.py` |
| `rosy_harness.py` | `generate` rewrites every module `index.md` and `STATUS.md`; `lint` validates and exits 1 on errors (staleness is only a warning) |
| `sim2real_gaps.yaml` | sim2real gap registry (`id` G-NN, `gap`, `evidence` list of ADR ids / repo paths with optional `:lines` / `{path, branch}`, `tier` list of M R D infra, `owner`, `status` OPEN IN-PROGRESS CLOSED HOLD, `next`, `validated_by` for CLOSED). `sim2real.py` validates and renders it; `lint` runs it (`harness.yaml` `sim2real_gaps`); `generate` writes `docs/reference/sim2real-gaps.md`. Tests: `test/test_sim2real_gaps.py` |
| `perception_gaps.yaml` | Perception blind-spot registry (`id` P-NN, `kind` miss or candidate, `spot`, `born` recording id / `device:YYYY-MM-DD` / in-repo `.md`, `evidence` as sim2real, `replay` repo path or `unbuilt`, `owner`, `status`, `next`, `validated_by` for CLOSED). A candidate is only HOLD or CLOSED. CLOSED forbids `unbuilt`. `perception_gaps.py` validates and renders it; `lint` runs it (`harness.yaml` `perception_gaps`); `generate` writes `docs/reference/perception-gaps.md`. Tests: `test/test_perception_gaps.py` |
| `platform_parts.yaml` | D-427 part manifest: every root's part, immutable ownership ID `d427_target`, wave and D-429/D-430 `concern`; optional `layout_target` is the later physical destination (D-626), otherwise it defaults to `d427_target`. `safety_modules` and `safety_anchors` follow D-430 §1. Checked by `test/architecture/test_platform_parts.py` and `test_safety_separation.py` |
| `safety_review.py` | D-430 §5 (exemptions: `safety_review_exempt.json`, `[{commit, reason}]`, loaded at import; missing or malformed exits 1): `python tools/harness/safety_review.py BASE HEAD [--warn-only]` fails when a non-merge commit after its `BASELINE` touches (or untags) a safety-tagged path without a `Safety-Review:` trailer. CI runs it on the PR/push range; `tools/land.py` (commits the landing adds) and the pre-push hook (`origin/main..` the pushed sha) refuse on it (D-762 stage 0) |
| `size_limits.py` | D-766 size rule: limits, `measure()` (files, units, packages; same count as before D-766), ratchet and unit parsers and checks. `STANDALONE` (pyproject/Gradle roots counted like packages), `OPS_ROOTS` (file limit only), `COVERAGE_ROWS` (the one-time rows of the coverage addendum). Used by `test/architecture/test_module_structure.py` and `size_range.py` |
| `size_range.py` | D-766 2: `python tools/harness/size_range.py BASE HEAD` measures each commit of the range through git and fails on a commit that does not pass the size rule on its own. Run by `tools/hooks/pre-push` and CI beside `safety_review.py`; not by `tools/land.py` |
| `structure_report.py` | D-773: read-only `python tools/harness/structure_report.py [--json \| --issue \| --picks-json] [--top N]`. Same counter as the size gate (`test_module_structure._measure`): units over 10,000 lines with split candidates (files the unit still owns, grouped by folder and file-name prefix), files over their limit, and the entry counts of the shrink-only lists (`KNOWN_VIOLATIONS`, `KNOWN_SAFETY_VIOLATIONS`, Fleet `KNOWN_WRITERS`; a list not on the branch is shown as such). `--issue`/`--picks-json` feed `.github/workflows/structure-report.yml` |
| `structure_jira.py` | D-773: `python tools/harness/structure_jira.py PICKS_JSON ISSUE_URL` turns `structure_report.py --picks-json` picks into unassigned Jira tasks under the path's Epic (KAN-19..22; none: `[Epic 미정]`), comments on an open task for the same group, and skips a group whose task a person closed. Needs `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`; without them it exits 0 and skips |
| `split_check.py` | D-766 3: `python tools/harness/split_check.py BASE HEAD` compares the changed `.py` files: definitions in order, string constants by name (paths may change), imports by target (new modules only from the moved set); any changed non-`.py` file is impure; exit 0 = pure move |
| `affected_tests.py` | D-436 `affected` tier, wired as `rosy_harness.py affected [--base main] [--print\|--run] [--json]`: maps `base...HEAD` plus working-tree changes to owning modules, reverse dependents (`platform_parts.yaml` `import_prefix` imports), tests naming the changed path and the guard set (`GUARD_SET`); `FULL_TRIGGERS` (including the landing/test gate tools, design 0.7 rule 8) and unmapped files escalate to full; with `--head` the files are read at that commit; invocations are packed so no two test files share a basename; every suite prints why. Tests: `test/test_affected_tests.py` |
| `affected_ci.py` | The GitHub full-run matrix for `affected_tests.py`, split from it (pure move): `FULL_SUITES`, `CI_FULL_MATRIX`, `ROOT_SHARDS`, `SUITE_SHARDS`, `CI_FULL_EXCLUDED`, Fleet shard weights and `ci_matrix` (`--ci-matrix`); `affected_tests` re-exports every name. Tests: `test/test_affected_tests.py` |
| `affected_repo.py` | The static repository facts for `affected_tests.py`, split from it (pure move, D-766 2): `Repo` (registry, import owners, tracked tests, file texts), `TEST_FILE`, `IMPORT`, `_match`, `_under`, `_git`; `affected_tests` re-exports every name. Tests: `test/test_affected_tests.py` |
| `affected_narrow.py` | D-762 stage 0 narrowing for `affected_tests.py`: foundation modules may select known test readers; unresolved runtime consumers, config and workflows retain FULL. `registry_readers`: a change under a tree listed in `shared/web/surfaces.yaml` selects every test importing `surface_registry` (the D-792 page landed red without them, 2026-10-18). Design 0.7 rules: a `test/architecture` change runs that directory (6); a `test/known_failures.txt` edit runs the files of the ids it adds or removes, FULL when an added id's test is also changed on the branch, safety-tagged or missing (7, `flaky_quarantine.txt` stays FULL as a safety root). Tests: `test/test_affected_tests.py` |
| `run_functional.py` | Runs each module's `functional` pytest surface in isolation (`--module NAME` for one) |
| `structure_report.py` | D-773 read-only size report and at most three safe split picks, using the size gate counter. `--issue` renders a GitHub task body; `--picks-json` feeds the optional publisher. |
| `structure_jira.py` | Manually configured Jira publisher for selected picks; absent configuration skips it. Repository workflows do not provide Jira secrets. Do not invoke its publishing CLI without a user request to publish. |

## For AI Agents

### Working In This Directory

- What `lint` enforces: `progress.md` front matter has `module`, `owner`, `last_verified` (quoted commit or `uncommitted`, plus date) and `gates`; gates are `SOURCE LOCAL ROS-SIM ARTIFACT DEVICE FIELD` with state `GO HOLD PARKED N/A`, and `HOLD` needs a `blocker`; ADR ids exist in the ADR log; each `logs.md` entry has date, change, evidence, gate change in order, no duplicate entry, and committed entries are never edited (append-only, checked against git history); no conflict markers or mojibake; ADR index rows and body sections match, and gaps are declared in `adr_gaps.txt` (local `refs/adr` reservations only warn).
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
