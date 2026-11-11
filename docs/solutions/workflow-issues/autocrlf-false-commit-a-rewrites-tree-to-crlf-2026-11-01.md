---
title: "`git -c core.autocrlf=false commit -a` in a Windows worktree rewrites the tree to CRLF"
date: 2026-11-01
category: workflow-issues
module: git worktrees on Windows
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "committing from a Windows worktree of rosy-platform"
  - "tempted to add -c core.autocrlf=false to silence the LF/CRLF warning"
tags: [windows, crlf, autocrlf, gitattributes, worktree, landing]
---

# `git -c core.autocrlf=false commit -a` rewrites the tree to CRLF

## Context

The repo runs with `core.autocrlf=true`, so every Windows checkout (main, gateway
worktrees, plain `git worktree add`) has CRLF working files. `.gitattributes`
pins `eol=lf` only for `*.sh` and a few named paths; most files carry no `text`
attribute and rely on `autocrlf` to convert back to LF when staged.

On 2026-11-01 a two-file fix was committed with
`git -c core.autocrlf=false commit -am ...` to quiet the "LF will be replaced by
CRLF" warning. With the conversion turned off, `-a` restaged every
attribute-less file with its CRLF bytes: the commit touched 3,128 files. The
landing stopped only because the change happened to reach safety-tagged files
and the Safety-Review trailer check refused it.

## Guidance

- Commit with plain `git commit` (or `git add <paths>`). Never pass
  `-c core.autocrlf=false` or `core.autocrlf=input` for a commit from a Windows
  worktree; the warning is harmless.
- Before landing, check the size of the diff: `git diff --shortstat main...HEAD`.
  A file count far beyond what you edited means line endings, not your change.
- Recovery: keep the bad branch under a `backup/` name, open a fresh worktree via
  `python tools/worktrees.py new ...`, cherry-pick only the clean commits, re-apply
  the remaining edits there, verify `--shortstat`, then delete the backup.

## Evidence

Reproduced in a scratch repo with this repo's `.gitattributes` and
`core.autocrlf=true` after a fresh checkout:

- `git commit -a` reports "nothing to commit".
- `git -c core.autocrlf=false commit -a` commits `x.py` changed; `git ls-files --eol`
  shows `i/crlf` for `x.py` and `i/lf` for `y.sh` (protected by `*.sh text eol=lf`).

The rebuilt branch (5 files, +23/-1) landed on local main as 093ef30c2b.

## Not done

A repo-wide `* text=auto eol=lf` would make this impossible, but needs a
renormalization commit across the tree and a check against byte-compared
fixtures; it is a separate decision.

## Update 2026-11-09: one CRLF blob stays CRLF, then conflicts as a whole file

`tools/land_mainred.py` and `test/test_land_mainred_flow.py` were born CRLF in
their creation commit (a555e421fe -> fd9019f795, 2026-10-27): every file that
commit added was CRLF, every file it modified was LF, which fits a commit made
with `core.autocrlf` off (the path above). The reflog is gone, so the exact
command is not proven.

Nothing noticed for two weeks because git's "safer autocrlf" never normalizes a
blob that is already CRLF in the index: with `core.autocrlf=true` (or
`text=auto`) every later edit (c0390e7ba5, 7ee8cf0ffa, ...) kept the file CRLF.
On 2026-11-09 two branches stored it LF; each then differed from main on every
line and the landing stopped with "not in the auto-resolvable set".

- Guard: `land_precheck.crlf_added` refuses a branch whose changed text files
  gain CRLF lines the merge base did not have (`-text` files excluded) and
  prints `git add --renormalize -- <paths>`.
- Merge: `land.py` (merge and preview), `land_prepare` (wait preview) and
  `land_full` (FULL-reuse check) merge with `-X renormalize`, so a
  line-ending-only difference no longer conflicts.
- `* text=auto` in `.gitattributes` (separate branch, it is a product path)
  normalizes on commit even with `autocrlf` off. Measured scope on main
  488dab2970: `git add --renormalize .` changed only the two files above.
- Check: `git ls-files --eol | grep i/crlf` lists the CRLF blobs; anything not
  `attr/-text` is a bug.
