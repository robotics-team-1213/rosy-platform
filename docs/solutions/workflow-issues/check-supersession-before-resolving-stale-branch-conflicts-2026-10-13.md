---
title: A stale branch that conflicts with main is usually already on main — check before resolving
date: 2026-10-13
category: workflow-issues
module: git workflow (shared main checkout, tools/land.py)
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "Collecting many old topic branches into main"
  - "A branch conflicts with main and its commits were cut before a folder move or a re-port"
  - "Deciding whether an unmerged branch can be deleted"
tags: [git, merge-conflict, stale-branches, supersession, land-tool, branch-cleanup]
---

# A stale branch that conflicts with main is usually already on main — check before resolving

## Context

On 2026-10-13 one session landed the unmerged topic branches of `rosy-platform` onto local `main`.
161 branches were not ancestors of `main`. The first pass ran `tools/land.py --tests auto` on the 35
most recent ones: 13 landed, 18 stopped on merge conflicts. The conflicts looked like work to do.
They mostly were not. Of 16 recent conflicting branches, 8 added nothing to `main` once the conflicts
were taken from `main`; of 81 older ones, 53 were the same work already on `main` under other
commits (re-ported after the D-427 folder move, squashed, or re-implemented). Resolving those
conflicts by hand would have re-applied old file contents over newer code.

## Guidance

Before resolving a conflict on a branch you did not just write, measure what the branch still adds.
Both checks are read-only and write nothing to any worktree:

```bash
# commits whose patch is not on main ("+" lines); 0 means every commit was cherry-picked or re-ported
git cherry main <branch> | grep -c '^+'

# what the branch would add if every conflict took main's side; empty output = nothing left to land
git diff --stat main "$(git merge-tree --write-tree -X theirs <branch> main | head -1)"
```

Read the result this way:

- **Empty residue** — the branch is superseded. Do not merge it. If it is to be deleted, tag it first
  (`archive/<YYYY-MM-DD>/<branch>`, D-172) so the commits stay reachable.
- **A few lines of residue** — look at them. On this run they were stale `adr_gaps.txt` rows, a
  duplicated ADR Log row from the union merge, or a file `main` had moved. None was real work.
- **Real residue** — resolve in the branch's own worktree, keeping `main`'s newer logic and
  re-applying the branch's idea on top. When `main` moved the code to another file, the branch's hunk
  goes to the new location, not back into the old one.

`git cherry` alone is not enough: a re-port changes the patch, so it reports `+` for work that is on
`main`. A symbol grep alone is not enough either: one branch triaged as "missing on main" was a draft
the owner had discarded the same day, and the module `logs.md` said so. Read the module log and the
ADR before porting anything older than the last restructure.

Three guards stop a landing for reasons that are not the branch's logic. Expect them:

- The secret scan (`test_no_secrets_in_tracked_files` in `test/test_release_boundary_guards.py`) flags a
  bare 40-character commit hash in a document and a test variable named `secret`. Cite short hashes.
- The size guards in `test/architecture/test_module_structure.py` need an independent re-judge or an
  extraction when a file passes 600 lines or a unit passes its allowance. Do not raise the number.
- `tools/land.py` and `tools/remote/remote_pytest.py` do not run browser tests; they are skipped
  without a message. A UI branch that lands green has not been checked in a browser.

## Why This Matters

A conflict is evidence that two sides changed the same lines, not that the branch holds missing work.
Treating it as a to-do list costs hours and, worse, can put superseded code back. On this run the
check turned 99 conflicting branches into about 20 that needed a decision, and the independent
reviews of the ported ones found real defects each time — which is where the effort belonged.

## When to Apply

- Any time more than a handful of old branches are merged, ported or deleted in one pass.
- Before deleting an unmerged branch: an empty residue plus an archive tag makes the deletion safe.
- Not needed for a branch written in the current session against current `main`.
