safety: none
# ralph task: cut CI jobs for small changes without dropping needed tests

Worktree: this directory (branch feat/affected-scope-loop). Goal: the check prints jobs<=170 (baseline 234 over 60 fixed commits) with broken=0.

Change ONLY the CI selector: tools/harness/affected_ci.py, affected_narrow.py, affected_tests.py, affected_capsules.py, affected_pack.py and tools/harness/platform_parts.yaml ownership data if needed. Ideas in priority:
1. Use the owning app from tools/harness/platform_parts.yaml: a change inside one app selects that app's tests plus the tests that reference the changed files, not whole neighbouring tiers.
2. Pack selected test files into fewer shards (affected_pack.py) when the total measured seconds are small (tools/harness/fleet_test_seconds.json or existing timing data): small changes should be 1-3 jobs, not one job per tier.
3. Docs/records-only already drop build-smoke; also drop guard jobs that cannot read the changed files.
Hard rules: unknown paths still escalate to FULL; safety capsules, guard set, runner tools, required IDs and ROSY_FULL_LEGACY keep their behaviour; never edit existing tests (they are protected); you may add tests for new rules. Do not touch .github/workflows, land*.py, or anything outside tools/harness. Do not run pytest locally (repo rule D-584); the check runs the selector only.
