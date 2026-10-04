# Windows SSH timeout cleanup correction

2026-10-04, SOURCE / LOCAL Windows PowerShell 5.1. No real SSH command or robot write was issued by these regression fixtures.

PUSH7 at `f1e908c7f363` terminated unsuccessfully: main 1 failed, 12559 passed, 527 skipped (2063.84s); perception 2836 passed, 112 skipped (363.81s); face 3 skipped. The failed stationary validator test expected SSH_COMMAND_TIMEOUT but received VERIFY_UNEXPECTED. The existing handler continues to HOLD. A separately reproduced natural process-exit race yields a matching native taskkill exception; the gate trace alone does not prove its internal exception cause.

Both Windows verification helpers now tolerate a taskkill exception only when their tracked process has exited. They reject silent nonzero taskkill results while it remains live. The deadline, PID/tree target, timeout response, no replay and HOLD behavior are preserved. A live cleanup error is rethrown. The existing successful-kill WaitForExit assumption is unchanged; this does not establish an independently bounded cleanup deadline or detached descendant elimination.

The new test parses each actual helper AST and instruments only the native kill point. It proves already-exited native error retains timeout, native live cleanup error throws, and silent nonzero/live cleanup throws. It kills only its own benign local fixture tree, checks root exit and one launch. Both helpers are covered. Linux skips this Windows-native boundary; pwsh was unavailable and was not verified.

Original stationary validator tests plus the six new cases: 22 passed in 31.94s; independent rerun 22 passed in 33.54s. The scratch RED run against original code had 4 failures and 2 passes, and corrected scratch run had 6 passes. Flake8 and diff checks passed. No known-failure entry or waiver was added.

[Independent review](windows-ssh-timeout-cleanup-review-2026-10-04.md): APPROVE isolated source/host correction. Integrated push gate, GitHub CI, ARM64/SD, DEVICE and FIELD acceptance remain pending. The old failed candidate was not retroactively accepted.
