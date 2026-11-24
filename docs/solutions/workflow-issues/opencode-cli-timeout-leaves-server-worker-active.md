---
title: OpenCode CLI timeout can leave a workspace writer active
date: 2026-11-23
category: workflow-issues
module: development workflow
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "reassigning a shared worktree after a delegated OpenCode command times out"
symptoms:
  - "a timed-out OpenCode client exits and its server continues modifying task files"
root_cause: missing_validation
resolution_type: workflow_improvement
tags:
  - opencode
  - worktree
  - timeout
---

## Problem

During the `rosy-world` implementation, four task-owned OpenCode clients timed out without a completed report. Their work appeared after client exit. The server then overwrote edits while replacement workers were integrating the same files.

## Cause and recovery

The timeout stopped the client process tree. The shared OpenCode server still owned the sessions. A process listing of the clients could show no writers even while the server accepted file edits.

Identify sessions by the assigned worktree and dispatch time. Interrupt only the sessions created for that task using `opencode api POST /api/session/<session-id>/interrupt`. Wait until the sessions report an interrupted idle outcome. Review the remaining diff and recover approved work from an existing source copy or bundle. Run the integration checks against the recovered source. [OpenCode session interrupt](https://opencode.ai/docs/api)

## Evidence and prevention

The server returned `interrupted: true` for all four task sessions. Each recorded an `interrupted` idle outcome on the same timestamp. The shared server remained running. No other session was interrupted. Check server-side completion before handing a timed-out worker's paths to another writer.
