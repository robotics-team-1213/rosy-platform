<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-11-03 | Updated: 2026-11-03 -->

# perception_runtime (integrations/perception)

**Parent context:** `../AGENTS.md`
**Updated:** 2026-11-03

## Purpose

ROS-free lane perception and learned-model runtime shared by the robot and the learning tools. It was split out of `control` (`middleware/perception`) on 2026-11-03 so `learning/*/perception` can replay, evaluate, convert and deliver models with the robot's exact code without importing middleware (the four former `learning -> middleware/perception` exceptions in `test/architecture/test_platform_parts.py`). `control` declares `exec_depend perception_runtime` and colcon installs both on the robot; this package never publishes a command or touches ROS.

## Key Files

| File | Description |
|------|-------------|
| `package.xml` / `setup.py` | ament_python library package `perception_runtime` (no nodes, no entry points) |
| `perception_runtime/recording.py` | D-356 recording session format, quota and topic names (was `control.recording`) |
| `perception_runtime/keep_odom_veto.py` | Odometry veto for keep mode (was `control.keep_odom_veto`) |
| `perception_runtime/perception/` | Rule-based lane evidence: camera ground plane, lane fit, bird's-eye view, keeper, road state (was `control.sensing.perception.*`) |
| `perception_runtime/perception/learned/` | Model manifest, signature, pre/post-processing and ONNX/NCNN runners (was `control.sensing.perception.learned.*`) |
| `progress.md` / `logs.md` / `index.md` | Harness records (D-61); `index.md` is generated |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `perception_runtime/` | The Python package |
| `test/` | Pure-logic tests of the moved modules; `conftest.py` puts this folder and `contracts/foundation` on `sys.path` |

## For AI Agents

### Working In This Directory

- Import only `contracts` (`core_common`) and third-party libraries here. Never import `control`, `rclpy` or other middleware: the layer rule allows `middleware` and `learning` to import this part, not the reverse.
- Keep the module tree. Robot nodes in `control` and the learning tools import `perception_runtime.perception.*` by these names.
- A source checkout finds this package through `control/__init__.py` (it appends this folder to `sys.path` when `control` runs from source) or through the explicit `integrations/perception` path entries in learning/tools scripts. Installed robots get it from colcon.
- The manifest is the contract between training and the robot (`perception/learned/manifest.py`); change both sides together.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py integrations/perception/test middleware/perception/test test/learning
```

### Common Patterns

ROS-free, numpy/OpenCV in, plain data out. `ncnn`/`onnxruntime` load lazily inside the runners.

## Dependencies

- `core_common` (contracts/foundation)
- numpy, OpenCV; optional `onnxruntime`, `ncnn`, `mcap` at the call sites that use them
