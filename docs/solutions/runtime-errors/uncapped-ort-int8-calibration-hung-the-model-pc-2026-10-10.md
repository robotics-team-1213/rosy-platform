---
title: Uncapped ONNX Runtime static INT8 calibration keeps every activation in RAM and hung the model PC for an hour
date: 2026-10-10
category: runtime-errors
module: learning/training/perception export (ONNX Runtime static quantization)
problem_type: runtime_error
component: tooling
symptoms:
  - "model PC unresponsive for about 1 h during static INT8 calibration"
  - "ORT 1.26 raises an error when the calibration frame count is a multiple of CalibMaxIntermediateOutputs"
root_cause: wrong_api
resolution_type: config_change
severity: high
tags: [onnxruntime, int8, quantization, calibration, memory, model-pc, systemd-run]
---

# Uncapped ONNX Runtime static INT8 calibration hung the model PC for an hour

## Problem

Static INT8 calibration with default settings keeps all activations of all calibration frames in RAM. On the model PC this swapped the machine out for about an hour. Same class as `docs/solutions/runtime-errors/sam3-tracker-loads-the-whole-frame-folder-and-hung-the-model-pc-2026-10-07.md`.

## Rule

- Set `CalibMaxIntermediateOutputs` to 7 and use 120 calibration frames. ORT 1.26 errors when the frame count is a multiple of that value; 120 is not a multiple of 7, 119 and 126 are.
- Run it under a memory cap: `systemd-run --user --scope -p MemoryMax=3G <command>`.
- Any model-PC job that loads a dataset-sized object needs a cap before the first run, not after the first hang.

## Result worth keeping

`int8-hf` (first conv and head conv kept fp32, rest INT8) matches fp32 accuracy at 0.6x the Pi latency. All-INT8 hurts the drivable class.

## Evidence

Lane branch `lane-int8-hf` worktree; model-PC notes under `docs/reference/`.
