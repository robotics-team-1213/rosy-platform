---
name: rosy-land-on-main
description: Use when starting, committing, submitting or merging work in rosy-platform while other agent sessions share the checkout — creating a branch or worktree, staging files, picking an ADR number, submitting a PR with pr_land.py, watching or leaving the GitHub merge queue, a PR going DIRTY, or when git status shows files you did not touch or a test fails and you cannot tell whether your change caused it. The full record is docs/reference/shared-checkout.md section 「같이 하는 깃」; AGENTS.md keeps its safety summary.
---

# Working and merging in a shared checkout (PR path, D-1055)

## Overview

The full record is `docs/reference/shared-checkout.md` section 「같이 하는 깃」 (item 6 is the PR path).
`AGENTS.md` section 「같이 하는 깃」 is the safety summary every session reads.
This file only collects the commands. A rule change edits `docs/reference/shared-checkout.md`, and the summary in `AGENTS.md` only when its wording changes.
One `.git/index` serves the shared `main` checkout. A path you did not write belongs to another session.
The shared `main` checkout stays on `main`: never `checkout`, `switch`, commit or run `pr_land` there.

## Before you start

Slot budget: `docs/reference/shared-checkout.md` section 「워크트리 한도와 슬롯 운영」 (15 with main, the tool refuses at 14 under `.worktrees/`, D-886).

```bash
cd <umbrella>/rosy-platform        # the shared main checkout: read-only git here
git status --short --branch; git worktree list
git fetch origin
python tools/worktrees.py new <short-name> <type>/<topic> --from origin/main   # not a bare `git worktree add`
python tools/worktrees.py adopt <short-name> <type>/<topic>   # re-attach an existing branch (D-1070)
python tools/worktrees.py status                              # every worktree with a verdict
```

- `<type>` is `feat`, `fix`, `refactor`, `docs` or `uiux`. One concern per branch; split before 15 files (`pr_land` refuses 30, D-1067).
- A clean worktree is removed by `prune --apply` after 6 h, mergeable or not; the branch stays and `adopt` brings it back (D-1070).
- `landed-dirty`, `stale-history`, `--snapshot`, `--force-over-cap`: read the record first.
- After `cd <worktree>`, run git writes with `&&` or `git -C <worktree>`, never after `;`.
- Scratch files go to `$ROSY_SCRATCH`.

## Committing

- `git add <path> ...` with **only** your paths from `git status --short`. Never `git add -A`, `git add .`, or a directory.
- Before committing: `git diff --cached --name-only` must equal your list.
- Never `--amend`, `rebase`, `reset --hard`, or `stash`. Leave paths you did not write.

## Tests: yours or pre-existing?

Never run pytest on the laptop (D-584). Commit first; the remote run tests the committed HEAD:

```bash
python tools/remote/remote_pytest.py --log-dir $ROSY_SCRATCH/<name> -- <paths>
python test/known_failures.py $ROSY_SCRATCH/<name>/run-1.txt     # exit 1 = a NEW failure
python tools/harness/size_range.py origin/main HEAD
python tools/harness/rosy_harness.py lint
```

A `NEW` line is yours until proven otherwise. No reachable test PC means "not verified": do not submit.

## ADR numbers

```bash
python tools/harness/adr_reserve.py next "<topic>"                    # right before writing the file
python tools/harness/adr_reserve.py release D-nnn --reason "<topic>"
python tools/harness/api_reserve.py next "<topic>"                    # API reference versions
```

Do not add the ADR Log row in a PR: the records bot writes it (D-1061). Unused numbers go into `tools/harness/adr_gaps.txt`.

## Submitting (only when the user says so)

```bash
python tools/pr_land.py --dry-run                         # plan, lab_required count, cutover state
python tools/pr_land.py --evidence --body "Replaces: #N (why)"   # preflight, lab evidence, push, PR, auto-merge
python tools/pr_evidence.py HEAD --solo                   # evidence failed under load: rerun alone
```

`pr_land` returns at once; the GitHub merge queue (`HEADGREEN`, groups of up to 4, merge commit) does the merge.

## Watching and leaving the queue

```bash
python tools/merge_queue.py list
python tools/merge_queue.py status <PR>                         # state, queue position and the one next step (DIRTY: merge origin/main; BEHIND: leave it)
python tools/merge_queue.py dequeue <PR> --reason "<why>"    # gh pr merge --disable-auto cannot remove a queued PR
```

| PR state | Do |
|---|---|
| `DIRTY` or `CONFLICTING` | In the branch worktree: `git fetch origin && git merge origin/main`, resolve with the `resolve-merge-conflicts` skill (hunk by hunk, D-1067), commit, then `python tools/pr_land.py --evidence` again: the tree changed, so evidence reruns |
| `BEHIND` | Nothing. The queue tests on top of main |
| In the queue | Wait |
| `BLOCKED` with a failed check | Fix that check on the branch |

## Red flags — stop

- "I'll switch the shared main checkout to my branch for a minute."
- "Merging origin/main now keeps the branch fresh" — only when DIRTY; every merge reruns evidence.
- "I'll take their side of the file with `--ours`" — resolve hunks, name dropped work in `Replaces: #N` (D-1067).
- "I'll just `git add -A`" / "The failing test is unrelated" without `known_failures.py` / "Amend is quicker".
- Retired (D-1055): `land.py`, `land_async.py`, local-main-first landing and `publish/main-*` publishing.
