---
title: Verify what you ship - the working tree is not the commit
date: 2026-09-30
last_updated: 2026-10-25
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
  - "a runtime validator was loaded from a different revision than the deployed artifact"
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

A deployment investigation can involve four different source states:

1. **origin's committed state** - what CI runs,
2. **local HEAD** - what your push actually ships,
3. **the working tree** - your edits mixed with every other session's
   uncommitted files,
4. **the deployed artifact** - the signed revision actually running on the
   target, which can differ from all three.

In the 2026-09-30 failures, the local hook and tests read (3), while CI
read the published commit. When another session holds uncommitted edits that
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

1. **Bind evidence to a committed revision.** Create an authorized task
   worktree through the repository gateway, then run the gate suite through
   the official remote runner with the exact commit:

   ```
   python tools/worktrees.py new <short-name> <type>/<topic>
   python tools/remote/remote_pytest.py --sha <committed-revision> --log-dir <external-log-dir> -- <gate-suite>
   ```

   Follow the current slot, landing and publication rules in the workspace
   and repository instructions. Preserve the runner's source/host binding,
   exit status, skips and comparison with known failures.

2. **Stage by content, not by file**, when a file carries another session's
   edits: `git add -p` or stage a patch, never the whole file on faith.
   A commit whose diff is bigger than your change is a contaminated commit.

3. **Attribute a hook rejection to its source.** Compare the rejected
   working tree and committed revision, preserve peer edits, and follow the
   current approved landing/PR/CI path. A passing remote run alone grants
   no hook-bypass permission. The bypass in the historical incident below
   records what happened in 2026-09-30; it is not a current procedure.

4. **Write guards for the committed state.** If a verdict/gap describes a
   state that exists only uncommitted, say that inside the entry ("the
   in-flight extraction shrinks it in an uncommitted tree; when that lands,
   this entry goes with it") so the next reader knows which truth it serves.

5. **Bind runtime checks to the deployed artifact.** Independently verify
   the signed candidate before inspecting its exact source revision. Pin
   that resolved artifact throughout the check, including its helper
   functions, dependent constants, Compose inputs and container runtime.
   A final mutable-pointer comparison alone cannot exclude an A→B→A swap.
   Compare the new deployed revision with a validator prepared for that
   revision after activation. Preserve the prior signed candidate for rollback.

## Runtime validator follow-up, 2026-10-25

On 2026-10-25, a read-only readiness probe loaded its helper from the
communication working branch while the site was observed running signed
commit `7a4df41b79` (reachable from origin/main; absent from this checkout).
The old helper expected four services and did not recognize the running
candidate's canonical Workcell and Account overlays. It rejected a healthy
three-service deployment before any activation. This was a validator
revision error; changing the operating configuration would have hidden it.

The corrected probe read the helper from the verified candidate's immutable
commit, included its service/project/unit constants, pinned Compose inputs
to the resolved candidate, and targeted the host's local Docker socket.
Signature, overlay content, service counts, healthy image identities and
runtime configuration checks then passed; the candidate pointer remained
unchanged. No image load, restart or activation was performed. This confirms
the existing deployment baseline only, and does not accept the new code.

Apply this extension when an installed artifact and the current checkout can
have different schemas or deployment layouts. A newer helper also needs
revision matching; its age alone does not establish compatibility.

## Related

- D-346 (the pre-push fast gate - correct design, shared-tree blind spot),
  D-362 (the zero-allowance tier whose verdicts triggered this), the
  historical 2026-09-30 red-CI chain (`026dc3a` contaminated,
  `eca5a0b0`/`17cf030e` restored, verified in a clean worktree, shipped
  `--no-verify` with that evidence). These historical commit IDs exist but
  are unreachable from the current HEAD and origin/main; preserve them as
  incident references, not as runnable current baselines.
