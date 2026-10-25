# Transitive pytest helper packing restoration

Base main commit `f4d06e4543` replaced the canonical pack delegate with a local basename-only implementation and lacked both `Repo.test_import_names()` and its transitive-helper regression. Earlier baseline commit `7594dfe72201` contains all three. The existing `affected_pack.py` helper remained unchanged and unused.

The correction restores the existing delegate and sibling test-helper traversal. It preserves CI/FULL ordering, path coverage, remote command budgets and exception handling. Exactly two source/test paths change; the helper file is unchanged. The regression keeps separation across different helper owners and coalescing for the same helper source.

| Check | Source commit | Result |
|---|---|---|
| Restored guard before implementation | `7e02ab3ec5` | 1 failed at the grouping assertion; fresh-interpreter fixture import/value check passed first |
| Affected selection, CI dependencies, land/queue/record/harness contracts and architecture | `ce056c8fb4` | 507 passed, no skips, 77.79 seconds; remote runner exit 0 |
| Known-failure comparison | `ce056c8fb4` | NEW0, known0, flaky0; one listed test not failing |
| Independent whole-branch source review | `ce056c8fb4` | Approved against base main; no findings |
| Per-commit size gate | `ce056c8fb4` | Both commits passed |

The historical synthetic fixture contained a circular from-import. The restored fixture uses `VALUE = 2` at its terminal helper and imports the entry module in a fresh Python subprocess before any packing assertion. This verifies a valid example rather than accepting the historical fixture solely by byte identity. Existing budget/no-drop assertions are unchanged; FakeRepo only adopts the canonical interface.

Evidence is outside Git: `rosy-import-pack-restore/{red,green}/run-1.txt`, `known-green.txt`, and separate RED/GREEN runner logs. Pytest ran only on approved remote test PCs. No exemption, quarantine, safety classification, cache or receipt rule changed.

CE: existing [committed-source verification lesson](../../solutions/workflow-issues/verify-what-you-ship-the-working-tree-is-not-the-commit.md) updated with this integration recurrence. Official FULL, landing, publication and deployment remain separate checks. The saved C1 boundary correction is not part of this unit.
