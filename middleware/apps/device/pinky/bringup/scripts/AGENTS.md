<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# scripts

## Purpose

Per-robot environment isolation for physical devices. Repo-root `env.sh` is for development; this script is for on-robot domain/namespace.

## Key Files

| File | Description |
|------|-------------|
| `rosy_env.sh` | Source with a robot index; sets isolated ROS env |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

```bash
source $(ros2 pkg prefix bringup)/share/bringup/scripts/rosy_env.sh 1
```

Do not replace this with `source env.sh` on a real robot (comment in root `env.sh`). Sets `ROS_DOMAIN_ID=40+N`, `ROSY_NAMESPACE=rosy_%02d` (D-33 — 도메인만 나누면 토픽 이름이 겹친다) and localhost CycloneDDS — **do not source this for `gz_multi`**.

### Testing Requirements

None.

### Common Patterns

Bash; argument is robot index.

## Dependencies

### Internal

- Installed via package share

### External

- ROS 2 setup.bash

<!-- MANUAL: -->
