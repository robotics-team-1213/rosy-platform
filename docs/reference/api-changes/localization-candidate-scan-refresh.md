---
surface: core
kind: additive
slug: localization-candidate-scan-refresh
date: 2026-11-26
title: Stationary localization candidates retain scan provenance
history: Retire a stationary candidate set when fresh scans repeatedly disagree
---
The same `/api/v1/localization/candidates` request retains its `stamp` on transport-only retransmissions. A newer scan supplies a new stamp only when it revalidates the same hypotheses and refreshes their LiDAR evidence. Three recent scans showing disagreement with all candidates can retire the request as `SUSPECT` with reason `candidate_scan_mismatch`, then use the existing bounded search path. A replacement request and any later decision follow the existing localization check.
