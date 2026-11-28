
# workflows

**Parent context:** `../AGENTS.md`

CI job definitions. `ci.yml` is the test pipeline (D-436 `scope` + parallel `test` matrix).
`review-gate.yml` is a required check: a non-author approval when a PR overlaps files changed on `main` in 14 days or in another open PR.
`structure-report.yml` (D-773) is weekly, never gating, `issues: write` only. `build-*.yml` are manual native or image builds.

## For AI Agents

### Working In This Directory

- Triggers: push to `main`, all pull requests, `merge_group` (Safety-Review and `HARNESS_BASE_REF` use `merge_group.base_sha`), weekly `schedule`, `workflow_dispatch`. No `concurrency:` group: it could cancel a merge-group or `main` push run and hide its failure.
- Job `scope` (full-history checkout, D-430 Safety-Review, `rosy_harness.py affected --ci-matrix`) emits `mode` and `matrix`; job `test` runs one runner per entry (`fail-fast: false`, `continue-on-error` for `gating: false`).
- PRs get one entry per affected invocation unless the selector escalates; other events get `CI_FULL_MATRIX` (`tools/harness/affected_ci.py`). Add suites there, not as new steps.
- `ci-result` (`if: always()`) is the one stable branch-protection check: it fails unless `scope` and every gating entry succeeded (cancelled or skipped counts as failure). Never protect a `test (<entry>)` name.
- Every pytest call passes `-pno:launch_testing -pno:launch_ros` (`NO_ROS_LAUNCH_PLUGINS` in `test/known_failures.py`): one module-level `importorskip` once skipped the whole root session for five days (exit 0). An invocation of several paths that collects 0 items is red.
- The container's pytest is apt 7.4 and still runs a module-level plain `setup()` as nose setup; `test/test_ci_dependencies.py` refuses one.
- D-762 flaky quarantine: when every failure of an invocation is in `test/flaky_quarantine.txt`, the step reruns those ids once; unlisted failures are never rerun.
- The full suite runs here, not on developer machines: `gh run watch <id> --exit-status`, `gh run view <id> --log-failed`.
- Boot smoke `timeout 60 ros2 run core core` must log `core up` and `slam_toolbox unavailable`; the SaveMap guard asserts `SaveMap.Request.name` is `std_msgs/String` and `RESULT_SUCCESS == 0`.
- `set -eo pipefail` after sourcing ROS setup (setup.sh is not `-u` safe).
- D-145: the ARM64 payload workflow stays manual, native, read-only and unsigned. Never add a private key or publication step to it.
- D-437: builds run on GitHub-hosted runners, signing never does. No workflow uses a secret other than `GITHUB_TOKEN`; only the publish job gets `contents: write`, only the attest job `id-token`. Actions are pinned by commit SHA (`test/test_site_candidate_workflow.py`).
- `build-ci-image.yml`/`build-payload-builder.yml`: `packages: write` with the job token only; the printed digest goes into the `image:` lines of `ci.yml`.

### Testing Requirements

Edit `ci.yml` only with a matching local command. Do not drop the root `test/` step.
