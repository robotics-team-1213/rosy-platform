<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

# workflows

## Purpose

CI job definitions for this repository.

## Key Files

| File | Description |
|------|-------------|
| `ci.yml` | `ci` workflow: colcon build (domain-tree paths), flake8 (max 120, non-gating), pytest the core-domain suites (`core/core/test`, `core/core_events/test`, `core/core_features/test`, `core/web_common/test`, `core/core_common/test`) and `products/pinky_pro/test` (D-196), `src/site/fleet/test`, `src/sim/gz_sim/test`, repo `test/`, `core` boot smoke, slam_toolbox SaveMap type guard. D-134 rehearsal workflows re-run the same procedure on other runners |
| `build-arm64-payload.yml` | Manual native arm64 build of the unsigned core/io OCI payload; uploads a checksum-bound artifact for offline signing, never a release |
| `build-pinky-image.yml` | Manual native arm64 `.img.xz` build; uploads an unsigned image handoff for offline signing |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Triggers: push to `main`, all pull requests.
- Boot smoke: `timeout 60 ros2 run core core`; must log `core up` **and** `slam_toolbox unavailable`.
- SaveMap guard unpacks the slam_toolbox deb and asserts `SaveMap.Request.name` is `std_msgs/String` and `RESULT_SUCCESS == 0`.
- pip installs: flake8, pydantic, fastapi, uvicorn, httpx, websockets, pyyaml, jsonschema, ext4 (pure-Python ext4 reader for `test/test_card_diagnostics.py`; the test skips without it).
- D-145: the ARM64 payload workflow must stay manual, native, read-only, and unsigned. Never add a private key or publication step to it.

### Testing Requirements

Edit `ci.yml` only with a matching local command. Do not drop the root `test/` step.

### Common Patterns

`set -eo pipefail` after sourcing ROS setup (setup.sh is not `-u` safe).

## Dependencies

### Internal

- `src/`, `src/core/core/test/`, `src/core/core_events/test/`, `src/core/core_features/test/`, `src/core/web_common/test/`, `src/site/fleet/test/`, `src/sim/gz_sim/test/`, `test/`

### External

- `ros:jazzy-ros-base`, apt colcon + openssl

<!-- MANUAL: -->
