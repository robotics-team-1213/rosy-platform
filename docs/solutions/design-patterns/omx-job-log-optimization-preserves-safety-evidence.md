---
title: OMX job log optimization preserves safety evidence
date: 2026-11-25
category: design-patterns
problem_type: design_pattern
component: service_layer
severity: high
applies_when:
  - "Limiting reads of OMX peer status JSONL used in arm admission"
  - "Evicting completed OMX jobs that can be replayed by idempotency key"
  - "Reading the tail of a log while its writer can append"
tags:
  - omx
  - safety-invariant
  - idempotency
  - process-audit
---

# OMX job log optimization preserves safety evidence

## Context

An independent D-430 review of the Wave 3 performance candidate found two safety regressions in optimizations that passed the initial OMX tests. The reviewer reproduced both by running the candidate functions in memory.

## Guidance

- **Keep the admission evidence window complete.** The peer-fold guard can proceed with no telemetry for an unlocked and unleased peer. The existing JSONL reader looks at the last 25 lines. A fixed 64 KiB byte window discarded the only unfolded state when its row crossed the window boundary. A future bounded reader needs a fallback that preserves the original window or an explicit refusal when it cannot establish that evidence.
- **Audit completion before eviction.** Polling processes in an audit pass and again in a pruning pass creates a gap. A process can finish between passes. The second poll can then make it eligible for eviction before the completion audit and state-generation update. Base eviction on recorded completion. A replayable job ID also needs a readable result for as long as its key can be replayed. Exercise POST replay and result GET together when changing retention.
- **Cap diagnostic reads at the sampled file size.** Seeking to the expected start and then reading to EOF can include bytes appended after that seek. The retained job-log change computes the read size from the measured end and passes that size to the read. The regression test in `test/test_omx_pr2_safety_and_auth.py` appends during the seek to verify the cap.

The reviewed follow-up kept the prior peer-status, audit, and replay paths and limited its I/O changes to diagnostic log reads and HTTP socket inactivity. The remote OMX checks verified the code paths. Physical-motion evidence requires a separate device observation.
