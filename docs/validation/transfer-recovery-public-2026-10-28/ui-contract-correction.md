# Public recovery UI contract correction

This supplements the earlier frozen records. The shared contract landed on local main as commit 73e2f7c650; public HTTP/console integration is still awaiting its final official landing. No push, deployment, observation-producer installation, device movement or VLA training is accepted by these results.

## Failures and correction

- Native public candidate commit d01fe54215 passed 299 common guards and several selected browser groups, but its collect-alone guard failed two wrapper IDs. The dialog inventory still counted one confirmation instead of admission plus recovery approval. The shared controls guard rejected comma-separated helper-button bindings and a disabled approval without its own reason. Both wrapper IDs failed their isolated reruns.
- That native command was deliberately interrupted after the owned failures. Its remaining selections and main comparison are unverified. The native PID/ticket were gone before edits; logs were preserved outside Git in system TEMP under `rosy-recovery-public-d01-owned-ui-failures/`.
- Commit 16538e6929 declares each button and kind explicitly, supplies disabled reasons, and changes only this surface's exact confirmation count from one to two. Its shared UI/dialog checks passed 37 cases. A review caught an over-specific new browser reason expectation; test-only commit 724f2fb2d4 checks nonempty reasons across both write/requery branches.
- Actual browsers on commit 724f2fb2d4 failed all 14 cases, including unchanged legacy cases. The reason expression had eagerly read the role callback during construction, before Console initializes its captured authentication state. Commit af1b7ac467 restores the original short-circuit order and adds an early captured-pageerror assertion. Both actual browsers and the shared contracts then passed. Independent rereview traced initial construction and found no supported remaining regression; the earlier review had missed evaluation order.
- In those actual final captures, generic disabled reasons could imply another recovery remained available after a child existed. Production commit b948a232049c05b4e207d9bc4197a8c3e8cfb616 prioritizes the consumed-budget explanation for known children. The existing maximum-one-recovery eligibility stays closed. Browser assertions require this reason on both controls.

## Committed-revision verification

| Source and selection | Actual result |
|---|---|
| commit af1b7ac467, shared dialog/control contracts | 37 passed, 0 skipped, 20.59 seconds |
| commit af1b7ac467, real HTTP/Chromium recovery plus existing ARM console | 14 passed, 0 skipped, 51.50 seconds |
| commit b948a23204, same real HTTP/Chromium selection plus final consumed-budget reasons | 14 passed, 0 skipped, 51.43 seconds |

All three runners exited 0; their saved-log classifiers reported NEW0/known0/flaky0. These are focused source results, not final native landing acceptance. External system-TEMP logs: `rosy-recovery-ui-initialization-contracts/`, `rosy-recovery-ui-initialization-green/`, and `rosy-recovery-ui-budget-reason-final/`. JavaScript syntax and the existing pure admission Node case passed before the budget-text-only adjustment.

## Actual final captures

The six remote PNGs from commit b948a23204 were fetched byte-for-byte and checked against the SHA-256 values printed by the committed browser test. Their external system-TEMP folder is `rosy-recovery-public-screenshots/b948a23204/`. They show final confirmed-child states; intermediate lost-response and child-read failures are established by browser assertions, not these final images.

| Case | Integrity |
|---|---|
| 320px normal / lost | SHA-256 `c60b2c89f438ec9bfdf23ca99f6940d7bab8a0ff96decb09265655fbfafbd8ed` |
| 390px normal / lost | SHA-256 `3adad3954d89665992caa715e8e7ca3bf846167630b260a41eaa96696ff1bec2` |
| 1920px normal | SHA-256 `0620374b5c29d1dab1099bea5cecafa025e30f4f9a99e0beb90e80097e0edcda` |
| 1920px lost | SHA-256 `1ca1c5efd38d8614167964272d56baec50fa45d2b0a8480e1f979345a1df842a` |

Independent final visual rereview inspected all six captures: disposition ship, no material findings. Both disabled controls visibly explain the consumed budget; original failure, simulation label, separate child result and long-identifier wrapping remain intact. No durable DESIGN.md change is needed. No tokens, styles, assets, dependencies, design-system concepts or instruction files changed. The existing clipping lesson remains this task's new CE record; these corrections are explained by the final code, startup comment, contracts and actual browser regressions, so no additional lesson is added.
