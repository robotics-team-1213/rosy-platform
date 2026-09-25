<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# launch

## Purpose

Launch file for the `core` node.

## Key Files

| File | Description |
|------|-------------|
| `core.launch.py` | Declares `config` and `mode` (`nav`/`slam`); runs executable `core` |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

```bash
ros2 launch core core.launch.py
```

On Pi, compose runs `ros2 run core core` with `__ns` instead of this launch. Keep both equivalent regarding node name.

### Testing Requirements

CI boot smoke uses `ros2 run`, not this launch.

### Common Patterns

`get_package_share_directory("core")` for default YAML.

## Dependencies

### Internal

- `core.main:main`

### External

- launch, launch_ros

<!-- MANUAL: -->
