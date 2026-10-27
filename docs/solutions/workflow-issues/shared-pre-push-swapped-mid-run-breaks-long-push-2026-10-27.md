---
title: A landing that reinstalls the shared pre-push breaks a long push already running
date: 2026-10-27
category: workflow-issues
module: tools/publish_main.py
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "a git push runs the pre-push gate for a long time (publish of thousands of commits)"
  - "other sessions land on the shared checkout while that push runs"
tags: [pre-push, publish, d-868, bash, shared-checkout]
---

# A landing that reinstalls the shared pre-push breaks a long push already running

## Symptom

A D-868 publish push (`origin/main..SHA` about 3,200 commits) failed twice with no gate message:

- once `exit=127` right after `[pre-push] size rule per commit on origin/main..<sha>`;
- once `.git/hooks/pre-push: line 152: syntax error near unexpected token ';;'` after the size rule passed.

The size rule alone at the same SHA passed (`3235 commit(s) checked`, rc 0, 105 minutes), and `bash -n` on
the installed hook was clean.

## Cause

Every worktree shares `<git-common-dir>/hooks/pre-push`. Another session landed a hook change and reinstalled
it (file mtime 14:19) while the push was still inside the size rule. Bash reads a script as it executes, so
the running gate continued from its old byte offset inside the new file and hit a fragment that is not a
command. The installed hook also stopped matching the pushed SHA's `tools/hooks/pre-push`, so a plain retry
of that SHA would be refused anyway.

## Fix

`tools/publish_main.py --apply` writes the publish SHA's own `tools/hooks/pre-push` (CR stripped, as
`tools/hooks/install.sh` does) to `<git-common-dir>/rosy-publish/<branch>-hooks/` and pushes with
`git -c core.hooksPath=<that dir>`. The gate content is the same one the installed hook must match; it is
just not a file another landing can rewrite. The copy is removed with the temporary worktree.
`test/test_publish_main.py::test_apply_pushes_the_chosen_sha_from_a_temporary_worktree_and_opens_a_pr`
installs a failing shared hook and checks the push still goes through the SHA's own hook.

## Next time

- A manual long push (outside `publish_main.py`): copy the pushed SHA's hook to a private directory and push
  with `-c core.hooksPath=<dir>`; never `--no-verify`.
- A pre-push that dies with `exit=127` or a syntax error but no gate message: compare the installed hook's
  mtime with the push start before retrying, and re-run the failing gate step alone at the same SHA.
- The size rule over thousands of commits takes about 105 minutes on this laptop, so each failed publish
  costs two hours; publish before the lag grows.
