---
title: Canonical watch must scrub host-path string values and parse hold_gpu.sh multi-token lock PIDs
date: 2026-11-23
category: runtime-errors
module: learning/training/omx (canonical_watch.py, canonical_telemetry.py)
problem_type: runtime_error
component: learning
symptoms:
  - "Live Model PC watch-root scan included replay-s06-*.json with summary.checkpoint=/home/rosy/rosy-scratch/.../pretrained_model unredacted in /api/learning/canonical JSON"
  - "canonical_telemetry.external_gpu_locks() returned [] on both Model PC and AI PC despite active hold_gpu.sh training locks in ~/rosy-jobs/train-*.lock"
root_cause: key_only_path_filtering_and_single_token_lock_Assumption
resolution_type: code_and_regression_test_fix
severity: high
tags: [omx, canonical, path-scrub, privacy, hold_gpu, lock, telemetry]
applies_when: "scanning arbitrary training/eval JSON receipts under scratch watch_roots or reading ~/rosy-jobs/train-*.lock files written by hold_gpu.sh"
---

# Canonical watch value path scrubbing & `hold_gpu.sh` lock parsing

## Symptom

During live 2-PC verification of PR #535 (`8a567ee6ba`) on Model PC and AI PC:

1. `canonical_watch.scan_watch_dir()` read `arm_b_ladder/replay-s06-002500.json` and emitted `"summary": {"checkpoint": "/home/rosy/rosy-scratch/.../pretrained_model"}` in public snapshot JSON.
2. `canonical_telemetry.external_gpu_locks(Path("~/rosy-jobs"))` returned `[]` even while `hold_gpu.sh` held `train-2363676.lock` on Model PC and `train-1368905.lock` / `train-4150158.lock` on AI PC.

## Root Cause

1. `canonical_watch.strip_paths()` only dropped keys matching `_PATH_KEYS` or `_PATH_SUFFIXES`. Real replay summaries store checkpoint paths under key `"checkpoint"`, which is also used elsewhere for step IDs (e.g. `"002500"`), so key-only filtering missed host-path values under arbitrary keys.
2. `hold_gpu.sh` writes `<pid> gpu <x> <y>` (space-separated tokens on line 1, e.g. `2363676 gpu 4 8`), not a bare PID integer, causing `int(line)` in `external_gpu_locks()` to catch `ValueError` and ignore all active training locks.

## Fix & Verification

1. **`learning/training/omx/canonical_watch.py` (`strip_paths`):** Scrub any `str` value matching `_POSIX_PATH_RE` or `_WIN_PATH_RE` through `scrub_text(value, max_chars=256)` while leaving non-path strings untouched.
2. **`learning/training/omx/canonical_telemetry.py` (`external_gpu_locks`):** Parse `lp.read_bytes()[:64].decode("ascii", errors="ignore").split()[0]` as integer PID.
3. **Regression tests:** Added assertions in `learning/training/omx/test/test_canonical_pipeline.py` covering both `<pid> gpu 4 8` lock files and `replay-s06-*.json` `summary.checkpoint` path scrubbing.
4. **Recovery & live check:** After merging the follow-up PR, redeploy both `rosy-canonical-peer.service` (AI PC) and `rosy-edge-review.service` (Model PC) to the merged `main` commit and re-run the read-only 2-PC snapshot check confirming `gpu_lock.busy == True` and zero `/home/` or `/mnt/` host paths in serialized JSON.

## When to Apply

Apply this pattern whenever sanitizing external run artifacts or reading lockfiles created by external shell wrappers (`hold_gpu.sh`): scrub path-shaped values regardless of key name, and test lock/JSON parsers against live host files rather than hand-written unit fixtures alone.
