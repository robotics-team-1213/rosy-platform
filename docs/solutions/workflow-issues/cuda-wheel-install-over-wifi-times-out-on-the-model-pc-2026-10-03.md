---
title: The CUDA PyTorch install on the model PC timed out over Wi-Fi until uv got a longer HTTP timeout and ran detached
date: 2026-10-03
category: workflow-issues
module: model PC setup (D-434), ~/rosy-ml/.venv via uv, torch cu128
problem_type: performance_issue
component: development_workflow
symptoms:
  - "uv pip install torch --index-url .../whl/cu128 stopped with 'operation timed out' on nvidia-cudnn-cu12 (627 MiB)"
  - "the same multi-hundred-MiB nvidia-* wheels (cublas 567 MiB, nccl 283 MiB) show up 2-4 times as Downloading in the log"
  - "an ssh command that starts the install in the background does not return before the client-side timeout (exit 124)"
root_cause: concurrency
resolution_type: workflow_improvement
severity: low
tags: [model-pc, uv, pytorch, cu128, cuda-wheels, wifi, ssh, background-job, rtx-5080]
---

# The CUDA PyTorch install on the model PC timed out over Wi-Fi until uv got a longer HTTP timeout and ran detached

## Problem
Setting up the model PC (D-434) needs PyTorch built for CUDA 12.8 (`cu128`), because the RTX 5080 Laptop GPU is
Blackwell (sm_120). That install is several GB of `nvidia-*` wheels. The PC had only Wi-Fi (its Ethernet port was
unplugged), and at the same time a 9.2 GB `tar | ssh` copy of the raw recordings (the gitignored `data/perception/raw/` folder, not in the repo) was streaming to the same host.
The first install attempt failed and the second took well over an hour.

## Symptoms
- First run: `uv pip install --python .venv/bin/python torch torchvision --index-url https://download.pytorch.org/whl/cu128`
  ended with `cause: operation timed out` and the hint naming `nvidia-cudnn-cu12 (v9.19.0.56)`.
- Relaunched run: no errors, but `install.log` lists `Downloading nvidia-cublas-cu12 (566.8MiB)` and
  `Downloading nvidia-nccl-cu12 (283.0MiB)` four times each, so slow transfers kept being restarted.
- Starting the job with `ssh host 'cd ~/rosy-ml && nohup sh -c "..." > install.log 2>&1 & echo started'` printed
  `started` but the local `timeout 60 ssh ...` still returned 124. The remote job kept running.

## What Didn't Work
- uv's default HTTP timeout for a 627 MiB wheel on a shared Wi-Fi link: the request timed out mid-download.
- Running the big data copy and the wheel download at the same time on one Wi-Fi interface: both slowed down
  (the raw copy took over an hour for 9.2 GB).
- A wait loop that detected "still running" with `pgrep -f "uv pip"` exited early; checking the log for a
  completion marker plus `pgrep -x uv` was reliable.

## Solution
1. Give uv a longer timeout and fewer parallel downloads, and run it detached from the ssh session, writing a
   completion marker:
   ```bash
   ssh rosy@<model-pc> 'cd ~/rosy-ml && setsid nohup sh -c "export UV_HTTP_TIMEOUT=600 UV_CONCURRENT_DOWNLOADS=4; \
     ~/.local/bin/uv pip install --python .venv/bin/python torch torchvision --index-url https://download.pytorch.org/whl/cu128 \
     && echo INSTALL_DONE" > install.log 2>&1 < /dev/null &'
   ```
   Downloads already finished stay in `~/.cache/uv` (3.6 GB there during this run), so a relaunch does not start
   from zero.
2. Poll for the marker, not for a process name pattern that can match the polling shell itself:
   ```bash
   ssh rosy@<model-pc> 'if grep -q INSTALL_DONE ~/rosy-ml/install.log; then echo DONE; elif pgrep -x uv >/dev/null; then echo RUN; else echo STOP; fi'
   ```
3. Treat a client-side `timeout` exit on the launching ssh as "unknown", and confirm with the poll above before
   relaunching. Relaunching blindly starts a second uv against the same venv.
4. Keep `UV_HTTP_TIMEOUT=600` in the host's `~/rosy-ml/env.sh` so later installs inherit it.

## Why This Works
The failure was a per-request timeout on very large files over a congested link, not a missing package or an
index problem. A longer timeout lets a slow transfer finish, the uv cache keeps finished wheels across attempts,
and running detached means a dropped or timed-out ssh session no longer decides whether the install survives.

## Prevention
- Before a large ML install on a new GPU host, plug in Ethernet or schedule bulk data copies after the install;
  do not run both over one Wi-Fi interface.
- Start every long remote job detached (`setsid nohup ... < /dev/null &`) with a log file and a completion marker,
  and poll the marker.
- Install add-on packages that depend on torch (ultralytics, ncnn/pnnx export tools) only after the cu128 torch
  install has finished, so the resolver does not pull a CPU-only torch from PyPI instead.

## Related Issues
- `docs/adr/D-434-model-pc-and-site-pc-roles.md` (model PC role and setup rules)
- `docs/solutions/workflow-issues/card-readback-slows-under-parallel-cpu-load-2026-09-25.md` (same pattern:
  a long transfer slowed by other work competing for the same resource)
