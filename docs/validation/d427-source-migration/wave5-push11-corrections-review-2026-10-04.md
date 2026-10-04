# Wave5 PUSH11 test-correction independent review

Verdict: APPROVE the two owned test-file changes on candidate/base 1792877e72da. No blocker found. This is SOURCE/LOCAL test correctness, not approval of the failed PUSH11 gate or the next integrated SHA/push/CI/artifact/device result.

Read-only .worktrees/d427-w5 / refactor/d427-wave5-final. Git diff/status show only test/test_control_absorption_package.py and test/test_pinky_release_impact.py modified. Production classifier, manifest, runtime and wheel source bytes are untouched. No repository file or live build/gate process was mutated by review.

## Independent verification

Ran actual two test files: 14 passed in 2.02s, exit0. Invocation used python -B, PYTHONDONTWRITEBYTECODE=1, no pytest cache and basetemp X:/DevTemp/rosy-d427/resume/review/push11-corrections-independent. git diff --check passed.

The absorption ownership test now loads the authoritative actual platform_parts.yaml and requires exactly one middleware/perception root, middleware ownership and control import prefix. This is stronger than searching for the literal control name in a deleted guide: absence, duplicate root, wrong owner or missing import prefix fails. Existing package/import/device-guide and sole CORE writer assertions remain.

The release-impact Git fixture still proves real merge-base changed-path selection, returned base/head/path and native-payload classification. It now creates the current middleware/perception/control/node.py family rather than a retired unknown src path. Existing CLI review exit3 test remains. New mixed retired-src/current-native regression proves src/node.py is review, the current runtime is native-payload and aggregate review takes precedence. It does not silently reclassify legacy src as deliverable or change production policy.

Production artifact_impact.py reads the manifest colcon roots from its own checkout and explicitly ranks review above other impacts. With src removed from that manifest, old arbitrary src fixture correctly became unknown/review. No production bug fix, exception or classifier relaxation is hidden in this correction. The canonical current fixture and explicit retired-root guard retain fail-closed strength.

## Other evidence and pending stages

PUSH11 failure stays failed: these local results do not retroactively accept its two failures. Owner reports 2 failed / 3664 passed / 151 skipped and exit1; final integrated evidence/log additions and the next actual-SHA gate remain subsequent work.

Independently checked the full legacy perception evidence record against its private log SHA256 and terminal footer: 2588 passed, 107 skipped, 2755.26s; terminal exit0 is the owner's completed-process record. Its explicit start-on-WIP/source-content correspondence and ROS-none/synthetic scope are retained. This reviewer did not rerun that full suite or imply remote CI/ARM64/DEVICE/FIELD acceptance. The separate WSL colcon build is still running and is not accepted based on this test review.

No new failure waiver, unknown-path allowlist, safety relaxation, peer file edit, robot command or installed-directory mutation occurred. Meaningful additional mutation was unnecessary: the new two-item regression directly exercises the actual unchanged classifier and its review-precedence branch, while the real Git fixture retains end-to-end selection evidence.

## Reviewed worktree fingerprints

- test/test_control_absorption_package.py: SHA256 521300c7771c26ad1b83b124e95db4d01033664209560a019d33da0156c52b59
- test/test_pinky_release_impact.py: SHA256 9d8e1e76afe3f654585c44e02dda1c2d7e4924f7915c0599941ad829d2391ed0
