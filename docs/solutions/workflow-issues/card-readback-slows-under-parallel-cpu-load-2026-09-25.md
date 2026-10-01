---
title: The card readback took 18 minutes instead of 7 because parallel agent work competed for the CPU
date: 2026-09-25
category: workflow-issues
module: deploy/robot/pinky_pro/sd (verify-media-readback.py, release 2026.09.25-011 on rosy-pinky-e4us)
problem_type: performance_issue
component: development_workflow
symptoms:
  - "readback progressed at about 7 MB/s instead of the 19-20 MB/s the preflight measured"
  - "release 011 readback took 18 min on the same card and reader where 010 took 7.2 min"
  - "three background agents were running pytest suites and a git worktree checkout during the readback"
root_cause: concurrency
resolution_type: workflow_improvement
severity: low
tags: [sd-writer, readback, xz, cpu-contention, parallel-agents, operator-pc, emergency-card-write]
last_updated: 2026-10-01
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

## Recurrence 2026-10-01 (release 2026.09.30-009, rosy-pinky-9dfk)
This happened again, worse, although this doc existed. The session that wrote the card had two background executor agents running host test suites. WSL (a Gazebo sim from another session, about 3 cores) and opencode were also busy. The readback ran at 0.2-4 MB/s, against 88 MB/s at preflight. The ETA was about 1.5 h for 12.9 GB. The operator needed the card at once.

- **How to diagnose it in 10 s:** `\PhysicalDisk(<card>)\Current Disk Queue Length` averaged **0** while `\Processor(_Total)\% Processor Time` was **100**. The card sat idle and the verifier was starved of CPU. Per-process `% Processor Time` counters show elevated and protected processes (vmmemwsl, MsMpEng) that `Get-Process` CPU deltas hide.
- **What helped:** stopping the session's own background agents roughly doubled the rate.
  - Raising the verifier's priority needs an **elevated** shell. The readback python runs elevated and its command line is not visible unelevated:
    `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? CommandLine -match 'verify-media-readback' | % { (Get-Process -Id $_.ProcessId).PriorityClass='High' }`
  - `wsl --shutdown` frees the most CPU, but it kills other sessions' sims, so it needs the operator's approval.
- **Emergency path used:** the operator accepted the risk. A local, uncommitted copy of `prepare-rosy-sd.ps1` without the readback block ran with `-ResumeAfterWrite`, which skips the write. The signature, serial, plan and bundle steps were unchanged, and the receipt records `media_readback.verified=false`. The card was then checked on the device instead: all 2152 release files matched `SHA256SUMS`, `dpkg --verify` was clean, and no systemd unit had failed. A first-class `-Emergency` mode with a mandatory reason is being built on `fix/card-write-confirm-and-artifact-download`.

**Stronger rule:** the writing session must not have any background agent running from the confirm stage until the receipt is written. Before launching `write-card.ps1`, check `ListAgents` and the session's own task list.

## Related Issues
- ADR D-225 (update without reflash, faster card writes)
- `docs/solutions/workflow-issues/long-elevated-card-write-needs-liveness-and-one-verify-2026-09-23.md`
