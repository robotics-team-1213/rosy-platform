# Release gate follow-up — 2026-10-05

Two additional inherited integration issues were corrected before activation.

- Origin CI `37276307702`, source `8b00650772bd12d6fe9f7d3bdc314919b7100b78`, failed the site image source/trigger coverage contract for `contracts/learning/src`. Fleet's Dockerfile copies this directory. The workflow now includes `contracts/learning/src/**`; 14 existing workflow contracts pass. Independent reviewer `keep_review` found no merge blocker.
- The normal push hook passed 490 fast contracts, then stopped after 3,388 passed / 167 skipped / 2 collection errors: Fleet cell app API/browser imports could not find `rosy.processes`. Isolated collection of those two files reproduced the errors on shared main and on the release worktree. `test_cell_compiler.py` previously supplied the palletizing source path too late. Fleet's common test bootstrap now supplies that required production dependency before collection. No production code, test exclusion, or import exemption changes.
- Fresh Fleet API, actual local Chromium browser, and compiler regressions: 30 PASS, known_failures 0 NEW. Private logs: `X:/DevTemp/line-remote-20261005/shared-main-cell-collection.txt`, `release-before-cell-collection.txt`, `cell-green.txt`. The original failed normal push is preserved in `push-integrated.txt`.

These are host release gate results. Candidate CI, native ARM64 build and signed device activation remain separate evidence. Automatic lane driving is NOT_RUN; FIELD acceptance remains HOLD.
