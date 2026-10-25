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

Status: focused source verification complete. Independent final review, official landing/FULL selection, publication/CI and deployment remain separate checks.
