---
title: A rule that only works if everyone follows it is not a gate
date: 2026-10-14
category: workflow-issues
module: git workflow (shared main checkout, tools/land.py, GitHub ruleset)
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "Writing a procedure rule into AGENTS.md or a skill and expecting it to hold across many sessions"
  - "Deciding whether a check is advisory or blocks the action"
  - "Running a destructive batch over branches, tags or worktrees"
  - "Removing a worktree that an agent session used"
tags: [git, gates, land-tool, merge-queue, worktrees, branch-cleanup, destructive-batch]
---

# A rule that only works if everyone follows it is not a gate

## Context

On 2026-10-13 and 2026-10-14 one lab clone held 279 worktrees and 1,246 local branches, local `main`
ran 85–500 commits ahead of `origin/main`, and a folder restructure left `main` failing about 50
tests for hours while every session's landing was blocked. Sorting out what had held and what had
not gave a clean split.

**Held every time — checks a program runs and that stop the action:** `tools/land.py`'s lint,
affected tests and `--ff-only`; the secret scan; the size verdicts. Each one caught real defects
during the clean-up.

**Did not hold — rules written in prose:**

- "Remove your worktree when the branch lands." Nothing removed them; the count only grew.
- "The FULL tier is still owed to CI." `tools/land.py` prints that sentence and lands anyway. The debt
  was paid hours later, on `main`, by everyone.
- "main moves by pull request." The ruleset has no required check and the admin role bypasses it, so
  `origin/main` moved by direct push and pull requests went unused from 2026-10-08.

## Guidance

1. **Ask of every rule: what refuses when someone skips it?** If the answer is "a reviewer would
   notice" or "the document says not to", it is a convention. Either make a tool refuse, or write
   down that it is advisory and do not plan around it. D-762 (main gateway) and the proposed D-761
   (worktree gateway) are that conversion.
2. **A check that prints a debt and continues is a rule, not a gate.** "Owed to CI" must become
   "waits for CI" or it will be owed forever.
3. **A destructive batch parses its plan in Python, not with a shell `read`.** The plan was a
   file of tab-separated rows, read in a shell loop with `read`. Tab is IFS whitespace, so
   consecutive tabs collapse and an empty column shifts every later field left. Six branches the
   plan kept were deleted. Use `csv.reader(...,
   delimiter="\t")` or `line.split("\t")`, assert the column count per row, print the parsed plan and
   read it before applying.
4. **Tag before every delete, one by one.** The six branches came back only because each
   `git branch -D` was preceded by `git tag archive/<date>/<branch>`. A batch that tags everything
   first and deletes afterwards is equally safe; one that deletes without a ref is not recoverable
   after gc.
5. **A clean `git status` does not mean a worktree is empty.** Before `git worktree remove`, also list
   ignored files (`git status --porcelain --ignored`) and look for agent-state folders such as
   `.omc/`. Credentials, collected data and session state are gitignored on purpose and disappear
   with the directory. Caches (`__pycache__`, `node_modules`, colcon `build/ install/ log/`) are the
   only ignored content that is safe to drop unseen.

## Why This Matters

Prose rules fail silently and at scale: each session skips one step once, and the total is 279
worktrees and a red `main`. Programmatic gates fail loudly and locally, at the moment and in the
branch where the problem is. The same holds for the clean-up tools themselves: the one step that
trusted its input without a check deleted six branches, and the one habit that was mechanical (a
tag before each delete) is what brought them back.

## When to Apply

- When adding a step to a shared procedure: decide in the same change which tool enforces it.
- When a tool reports something it cannot check: make that a failure or an explicit, recorded waiver.
- Before any batch that deletes refs or directories, and before removing any worktree you did not
  create in the current session.
