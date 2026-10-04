# Independent Windows SSH timeout cleanup implementation review

Verdict: APPROVE this isolated source/host correction. No blocking finding remains. This is not approval of the still-running old PUSH7 candidate, integration, a rerun push gate, CI, robot access or physical acceptance.

Reviewed worktree .worktrees/d427-timeout, fix/d427-ssh-timeout, base/HEAD e29dfc8c549f, with exactly the two owned modified PowerShell helpers and one new owned regression test. No worktree file was changed by review. Peer main, list.txt and the frozen d427-final candidate were untouched.

## Independent verification

Ran python -m pytest test/test_windows_ssh_timeout_cleanup.py test/test_pinky_user_validation.py -q -p no:cacheprovider --basetemp X:/DevTemp/rosy-d427/resume/review/validator-independent-temp.

Result: 22 passed in 33.54s, exit 0. This includes six native cleanup cases (three per helper) and the full original stationary validator module. Windows PowerShell 5.1 is available on this host; pwsh is not. git diff --check also returned no error. The owner's final-format log independently reports 22 passed in 31.94s; this review did not substitute that result for its own run.

## Source and race findings

Both source diffs wrap only the existing Windows native taskkill tree-kill statement, plus its result check. The exact tracked PID and /T /F remain. A native terminating error is ignored only after the same root process HasExited; if it remains live the original error is rethrown. A silent native nonzero result is explicitly rejected while the root remains live, closing the shell case identified in diagnosis. If the process exits between that result check and catch, retaining timeout classification is consistent with the deadline already being exceeded.

The wait deadline, output/ExitCode shape, success path, HOLD mapping, no-replay behavior and finally Dispose/temp-output cleanup are unchanged. No already-exited result is interpreted as successful SSH, and no catch converts a live cleanup failure to a TimedOut response. There is no known-failure waiver, secret material, real device target or new command authority.

The tests parse each actual production function AST, require exactly one helper and one native kill call, then instrument only that kill call. The already-exited case first terminates its known local tree, waits for that root exit and invokes real native taskkill again; it exercises actual already-dead stderr/exception behavior rather than a mocked success. The live case makes native taskkill reject an invalid PID while the real fixture child remains alive; the silent case executes an exit-1 cmd while that real child remains alive. Both must throw and return no result. Fixtures record their owned root PID, terminate only their own tree in finally, assert root exit and exactly one child launch. The timeout response requires true/null/empty values, and original integration tests retain SSH_COMMAND_TIMEOUT and HOLD.

One evidence qualification: deterministic already-exited proof uses fixture-driven tree termination, not naturally timed child completion. The same production branch and native already-dead error are exercised; the earlier six-second scratch natural-exit diagnostic separately demonstrates the natural-exit mechanism. No repeated timing coincidence is required for this new regression.

## Residual boundaries and gate attribution

The success-path taskkill exit 0 is still followed by the pre-existing unbounded WaitForExit(). This patch does not change that assumption: a successful native tree kill finishes the tracked process. It now rejects the observed/known nonzero-live failure before reaching that wait. No new guarantee that all detached descendants are gone, or that cleanup itself has an independently bounded deadline, is asserted. The non-Windows Process.Kill race is unchanged and outside this native Windows correction.

Parent now reports the terminal PUSH7 MAIN trace confirms the exact test failure VERIFY_UNEXPECTED instead of SSH_COMMAND_TIMEOUT (1 failed, 12559 passed, 527 skipped). Independently inspected G0 evidence confirms that mismatch, and the scratch native race diagnostic confirms a matching reproduced mechanism. The terminal trace itself was not reread during this narrow implementation review; full causation attribution remains dependent on that parent evidence. This correction has independently passing source/host tests; it cannot retroactively change the old failed candidate's gate result.

Apply only after the old gate finishes, through the owner's isolated commit/cherry-pick without merging peer ancestry, then rerun the integrated candidate checks and required enforced push gate. Actual native SSH/robot/device acceptance remains NOT_RUN.

## Reviewed content fingerprints

- deploy/robot/pinky_pro/verify/verify-from-windows.ps1: SHA256 2fb3d2c54119149c6954fd60b1560268490bdc05935d5df9f342850dee117e60
- deploy/robot/pinky_pro/verify/validate-pinky-from-windows.ps1: SHA256 058113dd70035a4b9e7fe96d922e7edfe76b9c3c9bafded83c92b23ab5cf7dd2
- test/test_windows_ssh_timeout_cleanup.py: SHA256 9c39f21b9f25049b372f9524932861233af095ac347646071e17226f6fca4357
