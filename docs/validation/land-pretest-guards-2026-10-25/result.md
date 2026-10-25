# Queued FULL pretest guards

Source: commit `f7357ca121`, based on main commit `6abf6a8a7e`.

`land.pretest()` now runs the existing structural guards before its queued FULL tier. Guard logs use `gpre`; FULL logs retain `pre`. A candidate HEAD change during the guards stops before the long suite and before saving FULL evidence. The existing post-FULL HEAD check, original main base, FIFO and cache behavior remain in place.

| Check | Committed source | Actual result |
|---|---|---|
| Queued success, guard failure, HEAD-change regressions before fix | `c0449396f7` | 3 failures: the old path entered `pre` without `gpre` |
| Land, queue and landing-record regressions after fix | `f7357ca121` | 98 passed, no skips; remote runner exit 0 |
| Known-failure comparison | `f7357ca121` | NEW 0, known 0, flaky 0 |

The success case retains real FULL evidence in its isolated repository. Failure cases verify no long suite, no FULL save, unchanged main, release of the caller's ticket and preservation of the peer ticket. Existing FULL reuse and moving-HEAD tests also run.

The first GREEN attempt selected an absent `test/test_land_guards.py` and ended exit 4 without executing tests. It is excluded from the pass evidence. The corrected command selects `test/test_land.py`, `test/test_land_queue.py` and `test/test_land_record.py`.

Raw evidence is retained outside Git under `rosy-land-pretest-guards/{red,green-final}/`, with separate runner logs and known-failure output. Tests execute on the approved remote test PCs using throwaway Git repositories; no device or operating service is involved.

## Canonical records during main merges

A clean Git merge can combine two valid indexes into a stale index. Source `18c09b384e` renders the merged inputs before creating the original two-parent merge commit, stages only declared generated outputs, and leaves fast-forward/up-to-date merges unchanged. The checkout's own harness validates every target before writing; targets outside the checkout, under `.git`, or resolving to non-files are rejected. Record I/O moved to `tools/harness/generated_records.py`; the harness size ratchet fell from 858 to 843 lines.

| Check | Committed source | Actual result |
|---|---|---|
| Clean-merge normalization and unsafe-target reproduction | `622da9c6aa` | 6 failed, 2 passed |
| First implementation | `0d1f4e40c1` | 203 passed, 3 failed: two incomplete harness fixtures and refused merge abort |
| Truthful abort-refusal reproduction, including partial tracked output | `73241f046a` | 2 failed, 1 passed, 91 deselected |
| Land, queue, record and harness contracts after correction | `18c09b384e` | 207 passed, no skips; remote runner exit 0; NEW 0, known 0, flaky 0 |

Independent source review approved source commit `18c09b384ecebea9e6c30acdc872db4799c1f7dc`. If Git refuses to abort after a generator changes tracked output, the tool stops and explicitly preserves the pending merge, index and worktree for manual recovery. It never forces a reset or stages unexpected source. The regressions verify original branch/main heads, retained merge parent, staged incoming changes and partial output. Pre-existing untracked files are preserved and are not attributed to the generator.

Raw remote logs and known-failure comparisons are retained in `rosy-land-pretest-guards/{merge-red,merge-green,abort-red,merge-green-final}/`. No local laptop pytest or device execution was used. FULL restore, cache and receipt code are unchanged. The earlier FULL on `835f96d4aa` passed its suites but stopped after a later main merge left an index stale; it does not verify this newer implementation.

The fresh official FULL on commit `fba21722f2` passed the 276-test preguard, but its root invocation reported 2 failed, 10,168 passed and 1,146 skipped. The release secret scanner rejected the exact review SHA in this document without the contextual word `commit`; that failure reproduced alone. The process-group timeout test passed alone (1 passed), and both tests passed on main commit `46f7a88240` (2 passed). The landing correctly stopped. Logs are preserved separately under `rosy-comm-landing/tool-full-failed-fba/`; this failed round is not successful FULL evidence. The wording correction identifies the value as a source commit and changes no scanner rules or exemptions.

Status: focused verification and independent source review complete. Corrected-document verification, fresh official FULL, landing, publication/CI and deployment remain separate checks.
