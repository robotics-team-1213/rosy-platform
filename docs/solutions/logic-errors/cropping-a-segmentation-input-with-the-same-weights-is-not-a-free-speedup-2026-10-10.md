---
title: Cropping the top of a segmentation model's input with the same weights is not a free speedup
date: 2026-10-10
category: logic-errors
module: learning/training/perception lane segmentation (input crop experiment)
problem_type: performance_issue
component: tooling
symptoms:
  - "argmax parity with the uncropped model only 57%"
  - "lane pixels become wall 60+ rows deep"
  - "input height 130 rejected by the network"
root_cause: wrong_api
resolution_type: workflow_improvement
severity: medium
tags: [segmentation, crop, position-prior, latency, fine-tune, lane]
---

# Cropping the top of a segmentation model's input with the same weights is not a free speedup

## Problem

To cut latency, the top rows of the input were cropped while reusing the trained weights. The model had learned a position prior (top edge = wall), so removing the top shifted that prior and labels flipped.

## Symptoms

- Argmax parity vs the full-frame model: 57%.
- Lane pixels turned into wall up to 60+ rows deep.
- Height must be a multiple of the downsampling factor (x16); 130 is invalid.

## Rule

- A crop changes the input distribution; it needs a crop-aware fine-tune.
- Even after fine-tuning, compare against the champion on the same rows (0.758 vs 0.800 here). Comparing the cropped model on its own crop against the champion on the full frame hides the loss.
- Choose heights as multiples of 16.

## Evidence

Eval harness under `learning/training/perception`; promotion comparison rules in the model intake ADRs.
