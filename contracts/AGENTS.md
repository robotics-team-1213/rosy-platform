# contracts

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Shared ROS-free contracts and the ROS IDL package. Wheel folders carry `COLCON_IGNORE` and are not colcon packages. Folder notes here are not the contract; the schemas and ADRs are.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `foundation/` | `core_common`, default YAML, and protocol schemas (see `foundation/AGENTS.md`) |
| `learning/` | Wheel `rosy-contracts-learning`: Episode, DatasetManifest, PolicyArtifact, PromotionRecord (see `learning/AGENTS.md`) |
| `motion/` | Wheel `rosy-contracts-motion`: semantic Motion Intent and DeviceControlPort types (see `motion/AGENTS.md`) |
| `ros_idl/` | ROS interface package (see `ros_idl/AGENTS.md`) |
| `skill/` | Wheel `rosy-contracts-skill`: Skill invocation and receipt identity (see `skill/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- External clients do not speak ROS. Shapes that cross the CORE boundary stay aligned with `docs/reference/ROSY API & Protocol Reference.md` and `foundation/core_common/protocol/schemas.py`.
- A wheel's `pyproject.toml` description is the package name to import. Do not add a `package.xml` so colcon builds it.

### Testing Requirements

Each child names its own pytest. Host pytest for the wheels does not need rclpy.

### Common Patterns

`COLCON_IGNORE` marks a wheel. `package-dir = {"" = "src"}` with a namespace package under `src/`.

## Dependencies

### Internal

- Consumed by `middleware/core/gateway`, Fleet, and the learning tools.

### External

- Python 3.12 for the wheels. ROS IDL uses the Jazzy interface generator.

## Manual Notes
