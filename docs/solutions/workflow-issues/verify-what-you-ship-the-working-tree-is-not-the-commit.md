---
title: Verify what you ship - the working tree is not the commit
date: 2026-09-30
category: workflow-issues
module: docs
problem_type: workflow_issue
component: development_workflow
severity: critical
applies_when:
  - "two or more sessions share one checkout and push interleaves"
  - "a pre-push hook or gate runs against the working tree"
  - "you fixed a guard using values you read from the working tree"
  - "git add sweeps a file another session is also editing"
symptoms:
  - "CI is red on a push whose local gate was green minutes earlier"
  - "a size verdict or adr_gaps entry is 'missing' or 'stale' only on CI"
  - "your commit diff is far larger than the change you made"
  - "generated records (STATUS.md, docs/index.md) are stale only on origin"
root_cause: shared_state_conflation
resolution_type: workflow_improvement
related_components:
  - testing_framework
  - infrastructure
  - release_gates
tags:
  - shared-checkout
  - pre-push-gate
  - committed-state
  - concurrent-sessions
  - git-hygiene
  - false-green-local
---

# Verify what you ship - the working tree is not the commit

> **Track: knowledge.** On 2026-09-30 two sessions sharing one checkout each
> shipped red CI from a locally green tree, three hours apart, in opposite
> directions. The durable rule is one sentence: gates that matter must run
> against the commit you are about to push, not against the tree you happen
> to be standing in.

## The shape

A shared checkout holds three different truths at once:

1. **origin's committed state** - what CI runs,
2. **local HEAD** - what your push actually ships,
3. **the working tree** - your edits mixed with every other session's
   uncommitted files.

The pre-push hook and `pytest` both read (3). CI reads (1) after your push
turns (2) into (1). When another session holds uncommitted edits that
*contradict* their committed state - a file shrunk by an in-flight refactor,
an ADR row added in an unsaved log edit - any guard you "fix" using the
working tree encodes state origin has never seen.

## The two failures, one shape

- Session A landed `styles.css` at 1119 lines with no size verdict because
  their working tree already contained the verdict-table edit - uncommitted.
- Session B (this author) then "fixed" the verdict table for the working
  tree's app.js (692 lines) and staged the file - sweeping A's uncommitted
  table edits into the same commit. Origin received a table matching
  nobody's committed files. Both pushes were locally green; both were
  CI-red.

## The procedure

1. **Measure the commit, not the tree.** Before pushing contested guards,
   check a clean worktree out at your HEAD and run the gate suite there:

   ```
   git worktree add X:/DevTemp/verify-head HEAD
   cd X:/DevTemp/verify-head && python -m pytest <gate suite> -q
   ```

2. **Stage by content, not by file**, when a file carries another session's
   edits: `git add -p` or stage a patch, never the whole file on faith.
   A commit whose diff is bigger than your change is a contaminated commit.

3. **A hook rejection on the shared tree is not always your red.** When the
   working tree contradicts the commit structurally (gap entries, verdicts),
   and the clean-worktree run at your exact SHA is green, a documented
   `git push --no-verify` ships a *verified* commit instead of blocking on
   another session's unsaved state. Say so in the commit and the report.

4. **Write guards for the committed state.** If a verdict/gap describes a
   state that exists only uncommitted, say that inside the entry ("the
   in-flight extraction shrinks it in an uncommitted tree; when that lands,
   this entry goes with it") so the next reader knows which truth it serves.

## Related

- D-346 (the pre-push fast gate - correct design, shared-tree blind spot),
  D-362 (the zero-allowance tier whose verdicts triggered this), the
  2026-09-30 red-CI chain (`026dc3a` contaminated, `eca5a0b0`/`17cf030e`
  restored, verified in a clean worktree, shipped `--no-verify` with that
  evidence).
