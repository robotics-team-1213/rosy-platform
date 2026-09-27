<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-09-28 -->

# hmi

## Purpose

Human-facing screens and shared browser assets. These source locations do not identify a separate server process or deployment host. The CORE dashboard is served in-process by core_api_web; web_common assets are shared by browser surfaces.

## Subdirectories

| Directory | ROS package / purpose |
|-----------|-----------------------|
| dashboard/ | Operator screens served by the CORE FastAPI process (core_api_web); static screens, not a Node server |
| face/ | ROS package emotion; Pinky LCD face and status surfaces |
| web/ | ROS package web_common; shared browser tokens and controls |

## For AI Agents

- Keep the physical source directory distinct from the ROS package name (web/ is web_common).
- The browser workstation may differ from the host running Fleet or CORE. Follow D-275 and deployment configuration.
- Do not infer final command authority from an HMI asset or screen.

<!-- MANUAL: -->
