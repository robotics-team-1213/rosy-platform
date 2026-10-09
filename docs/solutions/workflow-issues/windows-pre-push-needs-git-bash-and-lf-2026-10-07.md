---
title: Windows pre-push checks need Git Bash and LF input
date: 2026-10-07
category: workflow-issues
module: tools/hooks/pre-push
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "running the ROSY pre-push gate from Windows PowerShell"
tags: [windows, git-bash, wsl, crlf, pre-push]
---

# Windows pre-push checks need Git Bash and LF input

## Context

On this Windows host, bare `bash` resolved to WSL. Running the checked-out
`tools/hooks/pre-push` there failed immediately at `set -euo pipefail` because
the worktree file had CRLF line endings (`pipefail\r`). Piping the committed
script to bare `bash` avoided CRLF but sent the whole gate through WSL on the
Windows drive; lint spent minutes without a result.

## Guidance

Invoke Git Bash explicitly and feed it the committed LF blob:

```powershell
& 'C:\Program Files\Git\bin\bash.exe' -c 'git show HEAD:tools/hooks/pre-push | bash'
```

From a clean, isolated worktree this reached lint, the Safety-Review warning,
and the fast contract suite. The suite exposed real repository failures; its
nonzero result must remain a failed pre-push gate. Check the selected Bash and
Python before treating a silent or slow run as a product result.

## Why This Matters

The shell and file bytes are part of the verification path. A failed or
unfinished invocation gives no evidence that the candidate passed the gate.
