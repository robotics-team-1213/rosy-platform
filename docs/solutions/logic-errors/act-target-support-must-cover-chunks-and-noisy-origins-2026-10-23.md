---
title: Bounded ACT training must cover every future target from the same source
date: 2026-10-23
module: learning/training/omx ACT training and SIM demonstration intake
problem_type: logic_error
component: tooling
severity: high
symptoms:
  - "Offline training and model reload complete, but native object trials still fail."
  - "Selected original action chunks exceed the bounded model head's reachable delta."
root_cause: missing_validation
resolution_type: code_fix
applies_when:
  - "Training a source-relative bounded action chunk from recorded absolute targets."
  - "Perturbing source states while preserving absolute demonstration labels."
tags: [act, lerobot, training, chunk, bounded-action, provenance]
---

# Check label support before training or adding state noise

## Problem and verified scope

Stored OMX ACT models passed training/reload checks yet failed separate native object trials. A source-data audit of one actual training selection found 3,843 of 12,444 selected chunks contained a label outside the model head's support. This is a verified training-input validation defect. It is not proof that this defect alone caused every controller, camera or task failure.

The source fix landed on local main at commit `d54c33a8da`; it has not been installed on a physical robot. See the [verification record](../../validation/learning-execution-2026-10-23/result.md) for source revisions and the actual test environments.

## Why the previous checks missed it

`training_sample_indices()` used the current row's target to select a frame, with a wider allowance for the gripper. ACT's bounded action head applies a 0.035rad delta bound to every joint in four future actions, all relative to the chunk's original state. A valid current target therefore did not imply a valid future chunk. Some entire commands had no source frame that could express their original targets with that head.

Gaussian noise also moved the synthetic source without checking whether all unchanged absolute targets remained expressible. This can create impossible labels even when the original source was valid. Restricting runtime commands or obtaining a successful teacher receipt does not validate the learner's output support.

## Resolution

- [The trainer](../../../learning/training/omx/act_job.py) checks every original future target, including the gripper, against the same source and the head bound. It preserves command coverage and refuses an incompatible command instead of silently dropping it. `all_frames` refuses unsupported chunks.
- Synthetic state noise is limited to the feasible origin interval for the full original chunk: `lower = max(targets) - bound`, `upper = min(targets) + bound`. Only the synthetic input changes; the absolute targets, images and original chronology remain intact.
- The changed input distribution is recorded as `gaussian_state_noise_clamped_to_chunk_support_v1` in normalization/augmentation metadata and its existing provenance hashes. Unbounded relative training retains its Gaussian input distribution.
- The [research guide](../../../learning/training/omx/README.md) records that old incompatible demonstrations must be recollected. Refusal is not evidence that the new teacher or learned policy succeeds.

## Verification and recovery

Remote regressions first failed on the missing checks, then passed. The model PC's actual LeRobot environment also exercised training, five independent validation episodes, reload and replay in all six integration parameterizations, with no skips. These are synthetic integration fixtures, not object-task success evidence.

The corrected selection refused all 25 original episodes in the audited cohort because some commands could not be represented. Preserve those originals and their previous model revisions. Do not shrink action labels, remove hard commands, widen the owner limit or relabel a failed trial to admit the data. Collect a compatible new cohort and run the same original-data support audit before training. Existing failure receipts remain valid evidence of those failed trials.

Prevention: validate the full action horizon against the model's actual output parameterization before spending a long training run. Repeat after any input augmentation; low loss and successful weight reload do not establish output support or closed-loop task success.
