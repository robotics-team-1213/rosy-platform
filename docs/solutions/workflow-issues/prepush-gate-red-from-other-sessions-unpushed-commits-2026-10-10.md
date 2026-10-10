---
title: A red pre-push gate can come from other sessions' unpushed commits on shared main
date: 2026-10-10
category: workflow-issues
module: pre-push gate, shared checkout
problem_type: workflow_issue
component: development_workflow
symptoms:
  - "pre-push gate fails on commits that are not ours"
root_cause: environment
resolution_type: workflow_improvement
severity: medium
tags: [pre-push, known_failures, shared-main]
---

# A red pre-push gate can come from other sessions' unpushed commits

## Problem

Shared local `main` carries other sessions' unpushed commits, so the pre-push gate can fail for a change you did not make.

## Rule

- Find the introducing commit (`git log` on the failing path).
- Verify on a clean `origin/main` snapshot to confirm it is not ours or origin's.
- Fix the real cause. Do not add it to `test/known_failures.txt`.

## Evidence

Project skill `rosy-land-on-main`; AGENTS.md section on the shared git.
