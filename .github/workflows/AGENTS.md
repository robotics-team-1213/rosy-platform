<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-10-03 -->

# workflows

## Purpose

CI job definitions for this repository.

## Key Files

| File | Description |
|------|-------------|
| `ci.yml` | `ci` workflow (D-436: `scope` + parallel `test` matrix; the step list below now lives in `CI_FULL_MATRIX`): colcon build (domain-tree paths), flake8 (max 120, non-gating), pytest the core-domain suites (`runtime/gateway/test`, `runtime/events/test`, `runtime/services/test`, `hmi/web_common/test`, `contracts/foundation/test`) and `products/pinky_pro/test` (D-196), `operations/fleet/test`, `operations/vision/test` (own invocation), `integrations/simulation/gazebo/test`, repo `test/`, `core` boot smoke, slam_toolbox SaveMap type guard. D-134 rehearsal workflows re-run the same procedure on other runners |
| `android.yml` | `android-unit`: Rosy Cam (ceiling camera phone app) JVM unit tests (`./gradlew testDebugUnitTest`, Temurin 17), only when `operations/ui/cam/**` changes |
| `build-arm64-payload.yml` | Manual native arm64 build of the unsigned core/io OCI payload; uploads a checksum-bound artifact for offline signing, never a release |
| `build-pinky-image.yml` | Manual native arm64 `.img.xz` build; uploads an unsigned image handoff for offline signing |
| `build-site-candidate.yml` | D-437: manual amd64 site candidate build (syft SBOM). A pre-job fails fast if `site-<sha12>` exists; the build job (repo read-only) prints the `release.json` SHA-256 in the job summary; a small `attest-provenance` job (the only one with `id-token`/`attestations` write) attests `release.json`/`SHA256SUMS`; a separate `contents: write` job publishes the UNSIGNED prerelease (tar split into `.partNN` + `SHA256SUMS`, `release.json` as its own asset) and prunes older `site-*` releases to 3. Actions pinned by commit SHA. Signing stays offline (`sign_candidate.py --manifest-only`) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Triggers: push to `main`, all pull requests, nightly `schedule` (03:00 KST), `workflow_dispatch`.
- D-436 tiers and parallel matrix: job `scope` (full-history checkout, D-430 Safety-Review, `rosy_harness.py affected --ci-matrix`) emits `mode` and `matrix`; job `test` runs one runner per entry (`fail-fast: false`, `continue-on-error` for `gating: false`). Pull requests get one entry per affected pytest invocation unless the selector escalates; every other event gets the full matrix (`CI_FULL_MATRIX` in `tools/harness/affected_tests.py`: core-domain, sensing (non-gating until first green), fleet, site-vision-cell, gz-sim, hardware-safety, root `test/` in 3 shards) plus `build-smoke` (colcon build, flake8, boot smoke, SaveMap guard). Each entry repeats the container/apt/pip setup (~70 s); colcon builds only for `ros: overlay` entries and build-smoke. Add suites in `CI_FULL_MATRIX`, not as new steps. Serial job before D-436: ~10 min; parallel estimate ~5 min wall.
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

- `src/`, `src/runtime/gateway/test/`, `src/runtime/events/test/`, `src/runtime/services/test/`, `shared/web/test/`, `operations/fleet/test/`, `integrations/simulation/gazebo/test/`, `test/`

### External

- `ros:jazzy-ros-base`, apt colcon + openssl

<!-- MANUAL: -->
