<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

# .github

## Purpose

GitHub Actions for colcon build, lint, pytest, and `core` boot smoke on ROS 2 Jazzy.

## Key Files

None at this level.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `workflows/` | CI workflow definitions (see `workflows/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- The runner is `ros:jazzy-ros-base` and **must not** have `slam_toolbox` installed; the boot smoke asserts the log line `slam_toolbox unavailable`.
- Install OpenSSL explicitly in CI — release signing needs OpenSSL 3 Ed25519.

### Testing Requirements

Push/PR to `main` runs the workflow. Reproduce locally with the same pytest commands as in `ci.yml`.

### Common Patterns

Comments in `ci.yml` document why extra steps exist (root `test/` used to be skipped; SaveMap SIGABRT). Keep those comments if you change the job.

## Dependencies

### Internal

- Builds `src/`, tests the runtime suites (`src/runtime/{core,core_events,core_features}/test`, `src/hmi/web/test`) and repo-root `test/`

### External

- GitHub Actions, `ros:jazzy-ros-base` container

<!-- MANUAL: -->
