<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-09-25 -->

# runtime

## Purpose

실행 패키지. 이름은 그대로다. 최종 `cmd_vel`은 `core`만 낸다.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `gateway/` | package `core`. Final `cmd_vel` (see `gateway/AGENTS.md`) |
| `events/` | package `core_events` |
| `services/` | package `core_features`, managers and `decision/` |
| `api_web/` | package `core_api_web`. HTTP only; screens are `src/hmi/dashboard` |
| `sensing/` | package `control`. Perception, calibration, local safety policy |
| `navigation/` | Nav2/SLAM launch |

<!-- MANUAL: -->
