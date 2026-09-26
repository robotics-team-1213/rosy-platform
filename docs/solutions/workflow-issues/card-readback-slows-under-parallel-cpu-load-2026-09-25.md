---
title: The card readback took 18 minutes instead of 7 because parallel agent work competed for the CPU
date: 2026-09-25
category: workflow-issues
module: deploy/sd (verify-media-readback.py, release 2026.09.25-011 on rosy-pinky-e4us)
problem_type: performance_issue
component: development_workflow
symptoms:
  - "readback progressed at about 7 MB/s instead of the 19-20 MB/s the preflight measured"
  - "release 011 readback took 18 min on the same card and reader where 010 took 7.2 min"
  - "three background agents were running pytest suites and a git worktree checkout during the readback"
root_cause: concurrency
resolution_type: workflow_improvement
severity: low
tags: [sd-writer, readback, xz, cpu-contention, parallel-agents, operator-pc]
---

# The card readback took 18 minutes instead of 7 because parallel agent work competed for the CPU

## Problem
The readback for release 2026.09.25-011 on `rosy-pinky-e4us` ran at roughly a third of the expected speed.
The write before it finished at normal speed. The card still verified (8,574,867,968 bytes), but the card
step took about 11 minutes longer than it needed to.

## Symptoms
- Progress heartbeats in `write-2026.09.25-011-rosy-pinky-e4us-20260925T034608.log.progress.jsonl` show
  6,534,725,632 bytes read after 16 minutes of readback.
- The same USB 2.0 reader read at 19.1 MB/s in preflight minutes earlier.

## What Didn't Work
- Nothing was tried during the run; the readback was left to finish rather than restarted.

## Solution
Do not start heavy parallel work (pytest suites, worktree checkouts, builds) on the operator PC while a card
write's readback is running. Launch that work before the write starts or after the receipt is written.

## Why This Works
The write is bound by the card reader. The readback also decompresses the `.img.xz` stream in Python
(`verify-media-readback.py` hashes the compressed stream and compares the decompressed bytes with the
device in the same pass), which is single-threaded and CPU bound. At USB 2.0 speed the decompressor has
headroom only while the CPU is idle. Under load from parallel agents it becomes the bottleneck. The
2026-09-25 speed analysis measured single-threaded lzma decompress-and-scan at about 41.6 MB/s on an
idle machine, so the headroom is only about 2x.

## Prevention
- Treat the readback as a CPU-sensitive step: schedule parallel agent work around it.
- After a faster (USB 3) reader is in place (ADR D-225 3.1), decompression becomes the limit even when
  idle, so the same rule matters more, and a multithreaded or zstd decompressor becomes worth it.

## Related Issues
- ADR D-225 (update without reflash, faster card writes)
- `docs/solutions/workflow-issues/long-elevated-card-write-needs-liveness-and-one-verify-2026-09-23.md`
