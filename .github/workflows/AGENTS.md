<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-10-03 -->

# workflows

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

CI job definitions for this repository.

## Key Files

| File | Description |
|------|-------------|
| `ci.yml` | `ci` workflow (D-436: `scope` + parallel `test` matrix; the step list below now lives in `CI_FULL_MATRIX`): colcon build (domain-tree paths), flake8 (max 120, non-gating), pytest the core-domain suites (`runtime/gateway/test`, `runtime/events/test`, `runtime/services/test`, `hmi/web_common/test`, `contracts/foundation/test`) and `products/pinky_pro/test` (D-196), `operations/fleet/test`, `operations/overhead/test` (own invocation), `integrations/simulation/gazebo/test`, repo `test/`, `core` boot smoke, slam_toolbox SaveMap type guard. D-134 rehearsal workflows re-run the same procedure on other runners |
| `structure-report.yml` | D-773: Monday 09:00 KST (and manual). Runs `tools/harness/structure_report.py --issue` and posts it as a GitHub issue `주간 구조 리포트 <date>` (a comment when one is still open), then `structure_jira.py` for up to three split picks when the Jira secrets exist. `issues: write` only; never gating, no model, no code change |
| `android.yml` | `android-unit`: Rosy Cam (ceiling camera phone app) JVM unit tests (`./gradlew testDebugUnitTest`, Temurin 17), only when `operations/site_ui/cam/**` changes |
| `structure-report.yml` | D-773 weekly/manual structure report; GitHub issue/comment with the job token only. Optional Jira publication remains a separately configured manual CLI. |
| `build-arm64-payload.yml` | Manual native arm64 build of the unsigned core/io OCI payload; uploads a checksum-bound artifact for offline signing, never a release |
| `build-native-payload.yml` | D-225 manual native arm64 payload build, unsigned; since D-553 addendum 3 it runs in the payload-builder image (`builder_image` input, digest only), writes `source-ref.txt` (the dispatch branch) into the signed payload, and any branch may be dispatched (bench builds; only main reaches D-412) |
| `build-payload-builder.yml` | D-553 addendum 3: builds `ghcr.io/<owner>/rosy-payload-builder:<sha>` (Ubuntu 24.04 by digest + `install-ros-build-prereqs.sh` + rosdep apt packages) on push to its inputs or dispatch, prints the digest; `packages: write` with the job token only |
| `build-pinky-image.yml` | Manual native arm64 `.img.xz` build; uploads an unsigned image handoff for offline signing |
| `build-site-candidate.yml` | D-437: manual amd64 site candidate build (syft SBOM). A pre-job fails fast if `site-<sha12>` exists; the build job (repo read-only) prints the `release.json` SHA-256 in the job summary; a small `attest-provenance` job (the only one with `id-token`/`attestations` write) attests `release.json`/`SHA256SUMS`; a separate `contents: write` job publishes the UNSIGNED prerelease (tar split into `.partNN` + `SHA256SUMS`, `release.json` as its own asset) and prunes older `site-*` releases to 3. Actions pinned by commit SHA. Signing stays offline (`sign_candidate.py --manifest-only`) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Triggers: push to `main`, all pull requests, `merge_group` (D-762 stage 1: full tier; Safety-Review and `HARNESS_BASE_REF` use `merge_group.base_sha`; inert until the merge queue is turned on in stage 3), nightly `schedule` (03:00 KST), `workflow_dispatch`. No `concurrency:` group: it could cancel a merge-group or `main` push run and hide its failure.
- D-436 tiers and parallel matrix: job `scope` (full-history checkout, D-430 Safety-Review, `rosy_harness.py affected --ci-matrix`) emits `mode` and `matrix`; job `test` runs one runner per entry (`fail-fast: false`, `continue-on-error` for `gating: false`). Pull requests get one entry per affected pytest invocation unless the selector escalates; every other event gets the full matrix (`CI_FULL_MATRIX` in `tools/harness/affected_tests.py`: core-domain, sensing (non-gating until first green), fleet, site-vision-cell, gz-sim, hardware-safety, root `test/` in 3 shards, then `modules`: every other registered module suite, derived from `harness.yaml`, non-gating until its first green run; `CI_FULL_EXCLUDED` lists the only skipped files, pinned by `test/test_affected_tests.py`) plus `build-smoke` (colcon build, flake8, boot smoke, SaveMap guard). Each entry repeats the container/apt/pip setup (~70 s); colcon builds only for `ros: overlay` entries and build-smoke. Add suites in `CI_FULL_MATRIX`, not as new steps. Every pytest call passes `-pno:launch_testing -pno:launch_ros` (`test/known_failures.py` `NO_ROS_LAUNCH_PLUGINS`): ROS's launch_testing hook imports each module while collecting, and one module-level `importorskip` then skipped the whole root session from 2026-10-11 to 10-16 ("collected 0 items / 1 skipped", exit 0). An invocation of several paths that collects 0 items is now red. Fleet shards are weighed by `tools/harness/fleet_test_seconds.json` (mean of measured runs). The container's pytest is apt 7.4, which still calls a module-level plain `setup()` as nose setup; `test/test_ci_dependencies.py` refuses one. Serial job before D-436: ~10 min; parallel estimate ~5 min wall.
- D-762 stage 1 flaky quarantine: when every failure of an invocation is listed in `test/flaky_quarantine.txt`, the test step reruns those ids once (`-rA`); all passing turns the invocation green with a `FLAKY` warning. Unlisted failures are never rerun.
- `ci-result` (needs `scope` + `test`, `if: always()`) is the one stable check for branch protection: it fails unless `scope` and every gating matrix entry succeeded (cancelled or skipped counts as failure). Point protection rules at `ci-result`, never at a `test (<entry>)` name, which changes with the selection.
- The full suite runs here, not on developer machines. Read results with `gh run watch <id> --exit-status` and `gh run view <id> --log-failed`.
- Boot smoke: `timeout 60 ros2 run core core`; must log `core up` **and** `slam_toolbox unavailable`.
- SaveMap guard unpacks the slam_toolbox deb and asserts `SaveMap.Request.name` is `std_msgs/String` and `RESULT_SUCCESS == 0`.
- pip installs: flake8, pydantic, fastapi, uvicorn, httpx, websockets, pyyaml, jsonschema, ext4 (pure-Python ext4 reader for `test/test_card_diagnostics.py`; the test skips without it).
- D-145: the ARM64 payload workflow must stay manual, native, read-only, and unsigned. Never add a private key or publication step to it.
- D-437: builds run on GitHub-hosted runners, signing never does. No workflow may use a secret other than `GITHUB_TOKEN`; only a dedicated publish job gets `contents: write`. Contracts: `test/test_site_candidate_workflow.py`.

### Testing Requirements

Edit `ci.yml` only with a matching local command. Do not drop the root `test/` step.

### Common Patterns

`set -eo pipefail` after sourcing ROS setup (setup.sh is not `-u` safe).

## Dependencies

### Internal

- `src/`, `middleware/core/gateway/test/`, `middleware/core/events/test/`, `middleware/core/services/test/`, `shared/web/test/`, `operations/fleet/test/`, `integrations/simulation/gazebo/test/`, `test/`

### External

- `ros:jazzy-ros-base`, apt colcon + openssl

<!-- MANUAL: -->
