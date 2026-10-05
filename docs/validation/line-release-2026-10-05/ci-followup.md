# Release gate follow-up — 2026-10-05

Two additional inherited integration issues were corrected before activation.

- Origin CI `37276307702`, source `8b00650772bd12d6fe9f7d3bdc314919b7100b78`, failed the site image source/trigger coverage contract for `contracts/learning/src`. Fleet's Dockerfile copies this directory. The workflow now includes `contracts/learning/src/**`; 14 existing workflow contracts pass. Independent reviewer `keep_review` found no merge blocker.
- The normal push hook passed 490 fast contracts, then stopped after 3,388 passed / 167 skipped / 2 collection errors: Fleet cell app API/browser imports could not find `rosy.processes`. Isolated collection of those two files reproduced the errors on shared main and on the release worktree. `test_cell_compiler.py` previously supplied the palletizing source path too late. Fleet's common test bootstrap now supplies that required production dependency before collection. No production code, test exclusion, or import exemption changes.
- Fresh Fleet API, actual local Chromium browser, and compiler regressions: 30 PASS, known_failures 0 NEW. Private logs: `X:/DevTemp/line-remote-20261005/shared-main-cell-collection.txt`, `release-before-cell-collection.txt`, `cell-green.txt`. The original failed normal push is preserved in `push-integrated.txt`.

These are host release gate results. Candidate CI, native ARM64 build and signed device activation remain separate evidence. Automatic lane driving is NOT_RUN; FIELD acceptance remains HOLD.

## Python annotation semantics follow-up

Source `840570637289b43644f8bc41b6241b9a94020dc1` passed the normal push gate (490 fast tests; 3,660 affected tests, followed by 2,790 on the concurrent-ref retry). ARM64 build `37280335400` succeeded. Payload 041 was signed and both devices matched 314 shared ROS package versions, but it was not activated: CI `37280340298` failed 16 Fleet receiver cases through the HOST runtime extractor's missing postponed-annotation compiler flag. Every other CI matrix entry passed.

The real production runtime has `from __future__ import annotations`. Its extracted test class lost that setting: Python 3.12 evaluated `TrajectoryCommand` eagerly, while Python 3.14 concealed the issue until annotations were inspected. `annotations-red.txt` reproduces the same NameError on the host. The independently landed peer fix `df5359613` explicitly preserves the production compiler flag and disables caller flag inheritance; it is reused without duplicate production changes. A new isolated regression verifies the extracted method's original string annotations. Related runtime/parent/episode/receiver regressions: 108 PASS, 1 SKIP, 0 NEW (`annotations-green.txt`).

Payload 041 and its failed exact-source CI remain historical evidence. Deployment will use a fresh exact-source CI and ARM64 build; no red CI result is reported as release acceptance.
