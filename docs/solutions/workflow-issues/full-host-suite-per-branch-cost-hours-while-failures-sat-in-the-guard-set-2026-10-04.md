---
title: Running the full host suite locally for every branch cost hours, but every merge-caused failure was in the guard set
date: 2026-10-04
category: workflow-issues
module: tools/harness (affected tier), tools/hooks/pre-push, .github/workflows/ci.yml (D-436)
problem_type: workflow_issue
component: development_workflow
severity: medium
root_cause: missing_tooling
resolution_type: tooling_addition
symptoms:
  - "each full host run on the Windows operator PC took 40-60 min (1 h 46 min with two branches running at once)"
  - "the D-418 landing spent about an hour on full runs before review even started"
  - "every failure the merges caused was a guard test: secret scan, size verdicts, platform_parts root, version pins, robot literals"
  - "pre-push (about 4 min) lost the race to peers pushing origin/main: cannot lock ref, rebase, retry, three attempts"
applies_when:
  - "an agent wants to know whether a branch is safe to merge or push in rosy-platform"
  - "several sessions share origin/main and push minutes apart"
  - "a change touches only a few modules, tools, or docs"
tags: [ci, pytest, test-selection, affected-tier, github-actions, matrix, pre-push, guard-set, d-436]
---

# Running the full host suite locally for every branch cost hours, but every merge-caused failure was in the guard set

## Context
On 2026-10-03 two branches, D-418 (SSH access) and D-433 (rosy-face), were being landed. The agents
ran the whole host suite, about 8,400 tests, on the Windows operator PC after every merge or fix.

- **Cost:** one run took 40-60 min; with two branches running at once it took 1 h 46 min.
- **Review order:** independent review waited for those runs to finish instead of running beside them.
- **What actually broke:** every failure the merges introduced was caught by a cheap cross-cutting
  guard test, not by the module suites:
  - `test_release_boundary_guards` (secret scan, 23 findings)
  - `test/architecture/test_module_structure.py` (size verdicts and the 1000-line hard tier)
  - `test_platform_parts` (`tools/ssh` needed its own root)
  - the API version pins
  - `test_robot_literals`
- **Push race:** the pre-push fast gate takes about 4 min. Peers pushed `origin/main` in that window,
  and the push failed with `cannot lock ref` until it was rebased and tried a third time.
- **Re-review gate:** a subagent's `git push` was refused by the auto-mode permission check as a merge
  without review. The commits it fixed after review had not been re-reviewed.

The user's direction: choose tests by the scope of the change, run the full suite on GitHub runners,
and record this lesson.

## Guidance
The fix is D-436, `docs/adr/D-436-change-scoped-test-tiers.md`, landed as commit 458e8291c.

**Locally and in pre-push, run the affected tier only:**

```bash
python tools/harness/rosy_harness.py affected --base origin/main --print   # what and why
python tools/harness/rosy_harness.py affected --base origin/main --run     # run it
```

The affected tier selects:
- the owning module's `tests` (module map in `tools/harness/harness.yaml`)
- direct reverse dependents (one hop)
- test files that name the changed path (including by path parts)
- the guard set, always

It falls back to FULL when the change hits a shared foundation:
- `src/contracts/foundation/**`, `src/contracts/interfaces/**`
- `tools/harness/**`, `.github/workflows/**`
- `conftest.py`, packaging and requirement files
- `deploy/**/compose*.yaml` and the native image or unit files

It also falls back to FULL when a changed file maps to nothing. Unknown means everything, never
nothing.

A local run of a FULL selection still runs only the guards plus the suites mapped from the changed
files. The rest is left to GitHub.

**Leave the full suite to GitHub runners.**
- `ci.yml` runs a `scope` job, then one parallel `test` job per matrix entry.
- Every push to main, every nightly run, every `workflow_dispatch` and every escalated PR runs the full
  matrix.
- A stable `ci-result` job aggregates them; point branch protection at that job.
- Read the results; do not re-run them locally:

```bash
gh run watch <run-id> --exit-status
gh run view <run-id> --log-failed
```

**Order the landing work for speed:**
1. Start independent review in parallel with the scoped tests.
2. Run a short re-review of any fix commits made after review before pushing.
3. Right before pushing, fetch and rebase onto `origin/main`.

## Why This Matters
**Measured on the first matrix run** (run 37133929658, branch `feat/ci-affected-tests`):
- The full matrix on GitHub took 6 min 45 s.
- The last serial `ci.yml` run took 10 min 10 s.
- The same suite on the operator PC took over an hour, longer when agents ran in parallel.

**Selector cost:** the selector takes about 1 s for a normal diff. A tools/ssh-only change selects the
6 guards plus 2 test files.

**Where the risk sits:** in this repo merge risk concentrates in shared contracts and guard tests. The
affected tier always runs the guards, so it catches the same failures the hour-long run caught.

## When to Apply
- **Every branch iteration and pre-push in rosy-platform:** use `affected`. Use `--full` locally only
  when the GitHub run cannot be used.
- **Before a release build:** rely on the full GitHub run of the pushed commit.

## Examples
**Before.** For D-418:
1. Full local run.
2. Merge main.
3. Full local run again.
4. Review only after that.

**After.** For the overlay branch:
1. Targeted sensing tests plus guards, a few minutes.
2. Review in parallel.
3. Push.
4. GitHub runs the full matrix.

**Follow-up from the first matrix run.** The `sensing` job had never run in CI. It is non-gating
(`continue-on-error`) until it goes green, and it failed 6 tests:
- the container's older `cv2.aruco` API has no `generateImageMarker` or `ArucoDetector` (4 tests)
- an entry-point list mismatch (1 test)
- one dock-tag pose tolerance (1 test)

`ci-result` still passed, which confirms that the non-gating entry does not fail the aggregate.

## Related
- `docs/adr/D-436-change-scoped-test-tiers.md`
- `docs/solutions/workflow-issues/card-readback-slows-under-parallel-cpu-load-2026-09-25.md`: parallel
  agent work competing for the operator PC's CPU.
- `docs/solutions/workflow-issues/adr-numbers-collide-between-concurrent-sessions-2026-09-25.md`:
  concurrent sessions on a shared main.
