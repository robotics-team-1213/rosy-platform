---
title: Real-cell CPU ACT inference misses chunk 1 deadline mathematically and arm_b mode-averages across the pi wrist-roll split
date: 2026-11-22
category: runtime-errors
module: learning/training/omx (experiment_artifact.py, experiment_cuda_train.py), learning/registry/policy/sim_l1.py, deploy/robot/omx (cell_policy_timing.py, cell_policy_shape.py)
problem_type: runtime_error
component: learning
symptoms:
  - "cell_policy_drive.py --dry-run timed out at chunk 0 with default max_obs_age_s=0.6 (CPU bench 0.611-0.648s; pure forward median 0.4084s at threads=4)"
  - "Even with --max-obs-age-s 1.5, chunk 0 dropped 9/16 frames (observation_age_s=0.641s, remaining=7 frames <=0.467s), guaranteeing chunk 1 misses previous_end=observed+1.067s"
  - "On real arm_b home [0.8, -62.2, 53.1, 51.6, 45.2, 48.8], bdart-cos 7.5k emitted wrist_roll=-12.92..-12.15 (midway between real +45.2 and sim -54.8) and shoulder_lift=-74.41..-73.89 (outside reviewed -65.2..-7.1) for both slot=3 (ship-h1) and slot=9 (tray)"
  - "Dual-GPU training chains crashed in 6-8s with FileExistsError because mkdir -p .../train pre-created output_dir before lerobot_train"
root_cause: cpu_backbone_exceeds_chunk16_overlap_budget_and_pi_wrist_branch_averaging
resolution_type: workflow_and_gate_fix
severity: high
tags: [omx, act, cell-timing, cpu-inference, wrist-roll, sim-real-mix, preflight, sim-l1, bundle]
applies_when: "staging or evaluating an OMX ACT checkpoint for rosy-arm-cell, interpreting real-cell dry-run refusals, or launching CUDA lerobot_train chains"
---

# Real-cell CPU ACT inference deadline and sim-real wrist-roll split

## Problem

On 2026-11-22, the best simulation `arm_b` ACT checkpoint (`bdart-cos 7.5k`, sealed `42/42` lift and `27/42` place: `l0 14/14, l1 13/14, l2 0/14`; 7-frame causal delay spot `n8_d7` `12/18` with `l0/l1 12/12` and `0` collisions) was staged on `rosy-arm-cell` without moving the robot (`~/omx_models/h1-goal-b-bdart-cos-007500`). Non-motion dry-run and isolated CPU diagnostics (`D:/DevTemp/verify-1122/`) surfaced two hard blockers plus a chain-startup failure earlier that morning:

1. **Chunk 0/1 CPU timing impossibility (`cell_policy_timing.py:12-33, 108-157`):**
   - `MAX_OBSERVATION_AGE_S = 0.6` timed out chunk 0 during live-cell heartbeats (`inference_s = 0.611-0.648s`).
   - Raising `--max-obs-age-s 1.5` completed chunk 0 (`inference_s = 0.516s`, `observation_age_s = 0.641s`), dropping `floor(0.641 * 15) = 9` frames of the 16-frame chunk (`action_steps = 7`).
   - Because `len(frames)` is capped at `chunk_size=16` (`16 / 15 = 1.067s`), chunk 1 worker sleeps `2/30s` and sees at most `1.067 - (start - observed) - 0.067 = ~0.400s` before `previous_end`. Any `inference_s > ~0.35s` deterministically hits `next policy chunk missed its playback deadline` at chunk 1 regardless of `max_obs_age_s`.
2. **`wrist_roll` branch averaging & start-pose envelope refusal (`cell-branch-diag-1122.json`):**
   - With `arm_b` at its real home (`[0.8, -62.2, 53.1, 51.6, 45.2, 48.8]`), BOTH `goal_slot=3 (ship-h1)` AND `goal_slot=9 (in-domain tray)` produced `wrist_roll = -12.92` (`-12.15` for tray), sitting dead center between the real branch (`+45.2`) and simulation wait branch (`-54.8`), plus `shoulder_lift = -74.41..-73.89` outside reviewed `-65.2..-7.1` -> `frame 0 shoulder_lift=-66.1 outside reviewed -65.2..-7.1`.
   - Feeding the same real camera frames with `input_wrist_roll` shifted `-100.0` (`-54.8`, sim branch) eliminated `wrist_roll_warning` (`null`) on both `slot=3` (`-54.11`) and `slot=9` (`-54.22`), proving the failure stems from `±180°` branch mixing and start-state mismatch rather than `ship-h1` goal OOD alone.
3. **Training startup crash & deployment tree drift:**
   - Pre-creating `.../train` caused `lerobot_train` (`resume=False`) to fail in 6-8s with `FileExistsError` on both AI PC (`arm_a`) and Model PC (`arm_b`).
   - On `rosy-arm-cell`, `~/rosy-test/omx-tools-current` points to `cell/adaptive-ship` (`3fff92e55d`, lacking `UNITS.json` / `cell_policy_timing.py`, needed for active cell calibration params), separate from `omx-devices/current`.

## CPU Benchmark Evidence on `rosy-arm-cell` (`i7-1165G7`, `torch 2.10.0+cpu`, `D:/DevTemp/verify-1122/cell-cpu-bench-1122.json`)

| Variant (`n=5` warmed, fixed 3x `480x640` obs) | Median `inference_s` | `max_abs_diff` vs `baseline_t4` | Notes |
|---|---|---|---|
| `baseline_t4` (`threads=4, interop=4, FP32 NCHW`) | **`0.4084`** | `0.0` | ResNet18 x3 backbone alone = `0.3512s`; transformer rest = `0.088s` |
| `threads_1` (`OMP=1`) | `1.1628` | `2.4e-7` | `2.8x` slower |
| `threads_2` | `0.5926` | `2.4e-7` | Slower |
| `threads_4` (`explicit`) | `0.4270` | `0.0` | Matches default plateau |
| `threads_8` (SMT hyperthreads) | `1.2614` | `2.4e-7` | Thread thrashing (`max=3.899s`) |
| `channels_last_t4` | `0.6720` | `2.4e-7` | Slower on CPU |
| `bf16_autocast_t4` | `1.9545` | `0.0021` | No fast BF16 ISA on Tiger Lake |
| `dyn_int8_linear_t4` | `0.7005` | `0.0158` | ResNet convs dominate (`0.35s`), Linear quantization adds overhead |

Result: `0.35s` continuous-chunk ceiling cannot be reached on `i7-1165G7` with stock PyTorch `chunk_size=16` ACT without accelerator backend (ONNX/OpenVINO), off-box GPU proposal inference, or larger `chunk_size`.

## Fix / Structural Preventions

- **PR #491 (`experiment_cuda_train.py`, merged `6aad24b7`):** `preflight_cuda()` blocks existing `output_dir` when `resume=False`, verifies `data_gate` receipts (`reject=0, review=0`) and `~/rosy-jobs` GPU locks before spawning `lerobot_train`, reaps crashes immediately instead of polling, and exposes bounded `<=64 KiB` HTTP `bundle-manifest`.
- **PR 2 (`experiment_artifact.py`, `experiment_cuda_train.py`, `sim_l1.py`):**
  - `package_cell_bundle()` atomically converts `rs→top` across `config.json`, pre/postprocessor JSON, and normalizer `.safetensors`, sets `device='cpu'`, emits `UNITS.json` + `VIEW_NAMES.json`, verifies `CELL_CAMERA_ROLES` and zero symlinks, and computes `checkpoint_sha256` (`bundle_manifest()` exposes both `policy_revision` and `checkpoint_sha256`).
  - `sim_l1.py` (`rosy.sim-l1-eval/2`) requires both `nominal` (`delay=0`) and `delayed` (`delay>=1`) profiles plus `per_layer` (`l0/l1/l2`) breakdown and `0` collisions (`neighbour_disturbed == 0` and `arm_link_contacts == 0`).
- **Operational rules (`.claude/skills/rosy-omx-act-training/SKILL.md`):**
  - Never raise `max_obs_age_s` as a "fix" for slow CPU inference without verifying chunk 1 `ready_at <= previous_end`.
  - Never switch `~/rosy-test/omx-tools-current` away from `cell/adaptive-ship` while calibration services depend on it; stage policy dry-runs on an isolated tree/link and pass non-motion `goal_slot` + `wrist_roll` branch checks before live trials.

## 2026-11-23 Slice 0/2 Empirical Update & D-1073 LAN Transport Fix

- **Evidence report:** [omx-act-infer-parity-2026-11-23/result.md](../../validation/omx-act-infer-parity-2026-11-23/result.md).
- **Slice 0 receipt forensics (`arm_s` paced playback):** Physical playback (`37.456 s`) + settled `park` (`30.226 s`) consumed **98.95%** of total `68.398 s` wall time (`load ok` = `0.715 s`, `1.05%`), and Slice 2 JPEG parity confirmed `frames_cell_len = 1140..1174 >> 100` (`timed_rate_ok: false` even with RTX 5080 CUDA warm `infer_only` p50 `12.011 ms` / `inputs_plus_infer` p99 `16.633 ms`). Offloading paced `arm_s` remains **NO-GO**.
- **Cross-LAN mDNS + `HTTP/1.0` tail-latency trap on D-1073 (`PR #556`):** Over real lab LAN (`deadline_s = 0.3 s`, `n = 1,000`), per-request `urllib.request` + fresh `.local` mDNS dropped `16/1,000` (`URLError: 10`, `TimeoutError: 6`, unbiased `p99 = 5,131.632 ms`), which breaches the `0.6 s` `D-1024` / `D-854` observation budget. Switching to persistent `HTTP/1.1` keep-alive + one-shot IP cache (re-resolved on error to preserve `<name>.local` auto-attach) + `TCP_NODELAY` achieved **`1,000/1,000`** (`p50 = 29.693 ms`, `p99 = 43.182 ms`).
- **Structural fix:** `learning/training/omx/act_policy_http_server.py` enables `HTTP/1.1` (`TCP_NODELAY`, `Connection: close` on early/framing 400/401/404/411/413 errors and GET requests carrying a body, clean shutdown socket tracking, `request_id` echo) and `deploy/robot/omx/cell_remote_policy.py` reuses a persistent `http.client.HTTPConnection` with cached IP + `TCP_NODELAY` + fail-closed `request_id` verification alongside PR #554 (`31353316f0`) HOLD/ack hardening.

### 2026-11-23 Remote GPU HTTP Server: OpenCV / PyTorch CPU OpenMP Contention

- **Symptom:** After enabling HTTP/1.1 keep-alive against `rosy-omx-act-http.service` on `<ai-pc-host>`, idle RTX 5080 server inference inside the live HTTP server jumped from `11.4 ms` (standalone before `cv2`) to `server_infer_ms = 45–50 ms`, pushing `rosy-arm-cell` keep-alive RTT to median `83.23 ms` (`arm_a`, `p95 102.6 ms`) and `63.26 ms` (`arm_b`, `p95 91.74 ms`, placeholder wrist) — above the D-1073 `< 50 ms` target.
- **Root cause:** Each `/infer` request decoded 3 JPEGs in `decode_jpeg_rgb()` (`cv2.imdecode`/`cv2.cvtColor`, activating OpenCV's worker thread pool), immediately before `_load_lerobot_arm.predict()` normalized 3x `480x640x3` tensors on **CPU** (`torch.from_numpy(...).permute(2, 0, 1).float().unsqueeze(0) / 255.0` across 24 PyTorch OpenMP threads). Contention between OpenCV's thread pool and PyTorch's CPU OpenMP ops inflated `predict()` 4x from `11.4 ms` to `45–47 ms` even on localhost.
- **Structural fix:** Moved tensor transfer to `target_device` while still `uint8`, performing `.permute(2, 0, 1).unsqueeze(0).to(torch.float32).div_(255.0)` inside `with torch.inference_mode():` alongside `device=target_device` state/goal tensors in `learning/training/omx/act_policy_http_server.py`, with fake-torch ordering coverage in `learning/training/omx/test/test_act_policy_http_server.py`.
- **Verification (`n=20` warmed, `rosy-arm-cell` <-> `<ai-pc-host>` over Tailscale direct/Wi-Fi):** Numerical parity on the `arm_a` 75k checkpoint measured `max_abs_diff = 2.38e-7` (`0.000000238419`). Post-fix `server_infer_ms` dropped to **`12.91–13.02 ms`** (median `12.98 ms`), and client RTT met the `< 50 ms` KPI on both arms: `arm_a` (real wrist) RTT median **`26.8 ms`** / `p95 29.6 ms` (`e2e` median `30.74 ms` / `p95 34.4 ms`); `arm_b` (`arm_b_wrist` HTTP `503` placeholder) RTT median **`22.95 ms`** / `p95 26.81 ms` (`e2e` median `27.0 ms` / `p95 30.4 ms`).
