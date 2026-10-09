---
title: Remote ops gotchas - pkill -f kills its own ssh shell, a stale ros2 daemon hides topics, pre-push fails on other sessions' commits
date: 2026-10-10
category: workflow-issues
module: robot ssh operations, pre-push gate
problem_type: workflow_issue
component: development_workflow
symptoms:
  - "ssh command with pkill -f <pattern> ends with the connection dropping and no output"
  - "ros2 topic list on 8kcn shows only 2 topics"
  - "pre-push gate fails on commits that are not ours"
root_cause: environment
resolution_type: workflow_improvement
severity: medium
tags: [ssh, pkill, ros2, daemon, pre-push, known_failures]
---

# Remote ops gotchas

## 1. `pkill -f` over ssh kills its own shell

`pkill -f <pattern>` matches the `bash -c '...'` that ssh runs when the pattern text appears in the command line. Use the bracket trick (`[x]yz`) AND keep the literal pattern out of every other argument of the same command line.

## 2. A stale ros2 daemon shows a partial graph

`ros2 topic list` on 8kcn showed 2 topics. Use `ros2 topic list --no-daemon` or `ros2 daemon stop`, and pass the message type to `ros2 topic echo`.

## 3. Pre-push fails on other sessions' unpushed commits

Shared local `main` carries other sessions' commits. Find the introducing commit (`git log` on the failing path), verify on a clean `origin/main` snapshot, and fix the real cause. Do not add the failure to `test/known_failures.txt`.

## Evidence

Project skills `rosy-device-access` and `rosy-land-on-main`; print a date or nonce before claiming remote state is live.
