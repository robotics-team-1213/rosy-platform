---
title: The Isaac run supervisor stopped runs on a file the task was deleting (nlink 0), not on a link
date: 2026-10-31
category: runtime-errors
module: learning/envs/isaac (run_worker.py)
problem_type: runtime_error
component: simulation
symptoms:
  - "a long Isaac run ends FAILED with reason unsafe_output and exit code -15 partway through, with a valid video so far"
  - "sdk.log ends with `SUPERVISOR unsafe_output plan-request-<n>.json mode 0o100600 nlink 0`"
root_cause: link_count_check_treated_nlink_zero_as_a_hard_link
resolution_type: code_fix
severity: medium
tags: [isaac, supervisor, run-worker, race, unsafe-output]
applies_when: "a run's output directory is scanned while the task creates and deletes exchange files in it"
---

# The Isaac run supervisor stopped runs on a file being deleted

## Problem

Nine-container run f3eb (2026-10-31, rl3, seed 43) placed six containers and was then killed with
`unsafe_output`. Earlier runs a4e9 and one on 2026-10-30 08:06 ended the same way, and the entry was gone before
anyone looked, so it was read as a real unsafe file.

## Cause

`run_worker._budget` walks the output directory every 50 ms and refuses symlinks, special files and regular files
whose link count is not 1 (a hard link could expose a file outside the run). The task writes and then deletes
`plan-request-<n>.json` exchange files in that directory. When `lstat` lands between the unlink and the directory
entry disappearing, the file is still listed with `st_nlink == 0`. `!= 1` treated that as a hard link.

The supervisor log line that names the entry and its link count (added on 2026-10-30) is what showed this: before it,
the run only said `unsafe_output`.

## Fix

A regular file with `st_nlink == 0` is skipped as being deleted. Symlinks, special files and `st_nlink > 1` are still
refused. Regression test: `test_a_file_being_deleted_is_not_unsafe_output` in `test/test_run_worker.py`.

## Verification

Same input as f3eb (`nominal-bc-v0-rl3`, seed 43) on the fixed commit: run 1038 SUCCEEDED, 9/9, row gaps
2.65–4.82 mm, `reason: process_exited`.

## Next time

If a run ends `unsafe_output`, read the `SUPERVISOR unsafe_output` line in the run's `sdk.log` on the model PC
(`~/.cache/rosy-isaac/runs/runs/<run_id>/sdk.log`; it is not in the fetched snapshot) before changing the task. An
`nlink 0` entry on a file the task deletes is this race; `nlink 2` or a symlink is a real refusal.
