---
title: The intake reserved-eval check fails closed for datasets built before capture_group existed
date: 2026-10-10
category: workflow-issues
module: model intake (reserved-eval check, dataset bundles)
problem_type: workflow_issue
component: development_workflow
symptoms:
  - "reserved-eval check fails on datasets built before capture_group existed"
  - "even the accepted champion fails the check today"
root_cause: missing_workflow_step
resolution_type: workflow_improvement
severity: medium
tags: [intake, reserved-eval, capture_group, dataset, gate, provenance]
---

# The intake reserved-eval check fails closed for datasets built before capture_group existed

## Problem

The check needs `capture_group` to prove the reserved eval frames are disjoint from training. Older datasets lack it, so the check fails closed, including for the accepted champion.

## Rule

- Do not relax the gate. Failing closed is correct when the evidence is missing.
- Supply the evidence honestly: rebuild the dataset, or publish an annotated revision (metadata-only revision, frames byte-identical, operator assertion recorded).
- Chosen by the user: annotated revision; new bundles name that revision.
- When adding a gate field, plan the back-fill for existing artifacts in the same change, or the champion becomes un-promotable.

## Evidence

Intake tooling under `learning/`; the annotated revision is recorded next to the dataset manifest.
