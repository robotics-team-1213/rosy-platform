---
title: Classify the failure cause before turning failure frames into labels; a local VLM is one fact, not the judge
date: 2026-10-10
category: workflow-issues
module: failure loop D-578, perception review
problem_type: workflow_issue
component: development_workflow
symptoms:
  - "'lane not visible' on the real robot looked like a model miss"
  - "D-578 classified 6 of 10 9dfk losses as pose_off_lane and 0 as model_miss"
  - "local VLM (qwen3-vl 8b) answered 'along' for a robot facing a wall across the lane and counted 4 lines on a dark canary"
root_cause: missing_validation
resolution_type: workflow_improvement
severity: high
tags: [failure-loop, labels, vlm, canary, pose, lidar, keep_debug, d-578]
---

# Classify the failure cause before turning failure frames into labels

## Problem

"Lane not visible" was the robot's pose (facing a wall across the lane), not the model. The model segmented the wall and the line correctly. Labeling such frames as model failures would have taught the model wrong things.

## Rule

- Classify the cause first (pose_off_lane, model_miss, ...), then label only the model_miss frames.
- A local VLM is unreliable as a judge. Use it as one fact, fused with LiDAR and `keep_debug` by an auditable rule.
- For review, use Claude with hidden canaries. Never leak a canary's answer in a refusal or rejection message.

## Evidence

D-578 failure-loop classification; VLM background in D-492.
