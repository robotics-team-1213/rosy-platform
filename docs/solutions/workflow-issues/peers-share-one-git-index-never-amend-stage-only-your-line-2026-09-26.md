---
title: "Concurrent sessions share one git index: never amend, and stage only your line"
date: 2026-09-26
category: workflow-issues
module: .git/index, docs/reference/ROSY ADR Log.md, docs/logs.md
problem_type: workflow_issue
component: development_workflow
root_cause: concurrency
resolution_type: workflow_improvement
severity: medium
applies_when:
  - "more than one agent session commits in the same Rosy OS checkout"
  - "the working tree holds a peer's uncommitted rows in an append-only shared file (ADR log, logs.md)"
  - "before any history-rewriting command: amend, rebase, reset --hard"
tags: [concurrent-sessions, git-index, amend, staging, append-only, shared-checkout]
---

# Concurrent sessions share one git index: never amend, and stage only your line

## Context
On 2026-09-26 three sessions committed into one checkout within minutes of each other. Two
commands that are safe in a solo repo produced near-misses:

1. `git commit --amend --no-edit` was run to fold a regenerated `docs/index.md` into the session's
   own commit. Between that commit and the amend, a peer had committed — so HEAD was *their*
   commit, and the amend rewrote it: `ca58b9f8` carries the peer's message and their two D-255
   files plus this session's one-line index change. No content was lost (unpushed, message and
   files intact), but a peer's commit identity was rewritten by someone else.
2. The ADR log held a peer's uncommitted `| D-255 |` row while this session had to add its own
   `| D-256 |` row. `git add` on the file stages the whole working tree — including the peer's
   row — and `git commit -- <path>` is worse: with a pathspec, git records the *working-tree*
   contents of those paths and ignores the index, so the peer's row (whose ADR file was still
   untracked) would have been pushed as an index row with no body, turning CI red.

A peer also demonstrated the third failure mode by committing half a pair: `374fcc81` added the
D-258 ADR *file* without its ADR-log *row* (D-257 was still fully uncommitted), and HEAD lint went
to 2 errors (`D-258: body section missing from index`, `D-257: missing and not declared in adr_gaps`)
for every session sharing the tree.

## Guidance
1. **Never amend, rebase, or `reset --hard` in a shared checkout.** HEAD can become a peer's
   commit between your commit and your rewrite. If an amend is unavoidable, run
   `git log --format='%h %an %s' -1` immediately before and require it to be your own commit —
   otherwise make a new commit instead.
2. **Treat `git diff --cached` as global state.** One `.git/index` serves all sessions: before any
   pathspec-less `git commit`, assert the staged set is exactly yours:
   `git diff --cached --name-only` must equal your file list, nothing else.
3. **In append-only shared files, stage only your line.** Build a patch from the `HEAD:` content
   anchored on the last committed line and apply it to the index alone:
   `git apply --cached --unidiff-zero your-row.patch` (equivalent to the
   `git update-index --cacheinfo` blob recipe in the ADR-number-collision note). Then verify both
   sides: `git diff --cached -- <file>` must show only your line and `git diff -- <file>` only the
   peer's.
4. **Never use `git commit -- <path>` on a shared file.** The pathspec form takes working-tree
   contents, not the staged index — it sweeps every peer edit in that file into your commit.
5. **Commit file and row as one pair.** A half-paired commit (ADR body without log row, or a row
   without its body) reds the harness lint for all sessions and blocks everyone's push until the
   peer completes the pair. Verify HEAD in a scratch worktree (`git worktree add --detach <dir> HEAD`
   → `rosy_harness.py lint`) before pushing someone else's in-flight pairing.

## Why This Matters
The shared index makes solo-repo reflexes actively dangerous: an amend rewrites a peer's commit, and
a pathspec commit silently publishes a peer's half-finished rows to origin. Both failures are
invisible in `git status` afterwards — they only surface as someone else's red CI or a rewritten
SHA nobody expected.

## When to Apply
- Before every commit while other sessions are active in the same checkout (`git status` showing
  files you did not touch is the tell).
- Whenever `docs/reference/ROSY ADR Log.md` or `docs/logs.md` shows unstaged lines you did not write.

## Examples
- Staging one row out of a two-row working tree (2026-09-26): patch hunk
  `@@ -257,0 +258,1 @@` inserting `| D-256 | ... | Accepted |` after HEAD's D-247 row, applied with
  `git apply --cached --unidiff-zero`; verification showed staged = D-256 only, unstaged = the
  peer's D-255 row only; plain `git commit` (no pathspec) then shipped exactly 5 owned paths.
- The amend near-miss: session commit `ba2e5237` → peer commit → `git commit --amend --no-edit`
  produced `ca58b9f8` (peer's message, peer's files, one extra index line).

## Related
- `docs/solutions/workflow-issues/adr-numbers-collide-between-concurrent-sessions-2026-09-25.md`
  (the numbering half of the same shared-tree problem; its guidance 4 is the row-staging recipe)
- `docs/solutions/workflow-issues/card-readback-slows-under-parallel-cpu-load-2026-09-25.md`
  (contention on the same shared machine, different resource)
