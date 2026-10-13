---
title: A stale ros2 daemon makes ros2 topic list show a partial graph
date: 2026-10-10
category: workflow-issues
module: robot ros2 diagnostics
problem_type: workflow_issue
component: development_workflow
symptoms:
  - "ros2 topic list on 8kcn showed only 2 topics"
root_cause: environment
resolution_type: workflow_improvement
severity: medium
tags: [ros2, daemon, diagnostics]
---

# A stale ros2 daemon makes ros2 topic list show a partial graph

## Problem

`ros2 topic list` on 8kcn listed 2 topics while the stack was running; the daemon's cached graph was stale.

## Rule

- Use `ros2 topic list --no-daemon`, or `ros2 daemon stop` first.
- Pass the message type to `ros2 topic echo` so it does not depend on discovery.

## Evidence

Project skill `rosy-device-access`.
