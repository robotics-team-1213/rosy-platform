# D-427 push3 gate corrections — 2026-10-04

Failed gate candidate d7409e996: main affected suite 3 failed, 12381 passed, 527 skipped (2340.23 s); separate perception suite 2836 passed, 112 skipped (453.47 s); face lint 3 existing skips. Enforced push rejected; no remote source migration landing occurred.

Two failures came from D-441 site candidate workflow source triggers introduced by the latest remote rebase. Map its seven old source references to the moved roots; preserve all automatic candidate feature, concurrency and release controls. Existing coverage and moved-root scans then pass.

The JPEG recorder host test failed with FAILED () when startup process visibility briefly failed but the immediate diagnostic probes both succeeded; isolated original suite reproduced a different startup case, 1 failed/13 passed. A deterministic regression runs the actual startup block with transient versus permanent disappearance: transient case was RED. The startup loop now confirms suspected disappearance after 200ms and records the confirmed reason. Its initial fixed deadline, early confirmed failure, zombie/identity predicates, cleanup and metadata remain. Legacy tail options become portable -n arguments.

Final related recorder/workflow/manifest tests **48 passed**, 52.13 s; known failures NEW0. X:/DevTemp/rosy-d427/resume/push3-corrections.txt and rec-start-probe-red.txt. Independent reviewer /root/d427_safety_review **APPROVE source/host corrections**: workflow/moved roots **20 passed**, startup regressions **2 passed**, Bash syntax exit0. Final candidate enforced push gate and full CI remain required; no prior failed gate is relabeled green.
