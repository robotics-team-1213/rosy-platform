# Push5 corrections independent review

- Reviewed baseline: 69779adb524e, plus the five owned uncommitted paths. Repository source and HEAD were not edited by the reviewer.
- Verdict: APPROVE source/host correction slice; no safety blocker found. Final candidate-SHA enforced gate has not been rerun and is not claimed passing. ARM64/SD/Docker build/DEVICE/FIELD remain separate.

## Scope and findings

1. `middleware/core/gateway/test/test_operational_journey.py`: simulated future select_output(now+0.6) proves a future zero output but does not advance the actual monotonic watchdog used by MANUAL admission. The added authenticated IDLE HTTP request explicitly releases the still-live manual session before navigation. Production default 500 ms, U1 guard, stop/release roles, and goal/result assertions are unchanged. This is an explicit operator-release journey; actual timeout recovery remains covered in the separate manual ownership tests.
2. `operations/fleet/fleet/server/web/signals.js`: six local Korean intent labels affect stale-card text only. Missing/null/empty values display none; wrong scalar/object/future/prototype names display explicit unknown through typeof plus Object.hasOwn. Command/presence/supervision behavior is unchanged. Render uses textContent and invokes no transport.
3. `operations/fleet/test/web/signal-presence.test.mjs`: checks all six labels, missing/unknown/prototype values, actual createSignals render against FakeDOM, translated stale text, and no command/log/refresh calls. Global document is restored in finally.
4. `shared/web/test/test_operator_copy.py`: adds a mutation tuple on the actual signals source, keeping the allowlist unchanged. Reverting translated interpolation to raw intent makes the existing copy linter fail. No waiver is added. Parent baseline comparison reports 44 existing shared-parser flake findings and zero new findings; this review does not claim that legacy file is fully flake-clean.
5. `test/test_core_image_closure.py`: keeps exact required ROS closure (10 packages) and source whitelist. ROS copies must enter /opt/rosy_ws/src; the only non-ROS source copies are exact skill/motion wheel sources, with COLCON_IGNORE and no package.xml, at their exact non-colcon destination. Wheel omission, ROS omission, or wheel placement in colcon source fails; no generic extra-source allowance was introduced. Actual wheel install/helper delivery remains protected by the separate delivery checks.

## Independent verification

- Installed-motion dependency provided from the existing X wheel-site; independent operational journey + core image closure + shared operator-copy pytest: **22 passed in 2.10 s**. Cache disabled; all basetemp residue under X:/DevTemp/rosy-d427/resume/review/push5-independent.
- Independent Node signal-presence suite: **3 passed**, no skipped/cancelled tests; actual render test and no-command assertion passed.
- Budget measurement with actual architecture helper: Fleet 29276 versus recorded baseline 29264 (+12, below +150 allowance); signals.js 161 lines, below 800. No baseline relaxation is needed.
- Parent raw mutation evidence inspected: missing ROS package, missing motion wheel, and wheel under colcon each produce a closure assertion failure (three logs show 1 failed); raw signal interpolation mutation causes actual-render expectation failure. Original bytes are restored in the reviewed final diff.
- git diff --check passes. No known-failure/backlog waiver or operator-copy allowlist changes. Current product diff contains only the requested five paths.

## Qualified approval

The fixes repair actual test assumptions and operator text without relaxing manual admission, adding output authority, replaying signal intent, broadening source closure, or changing module budgets. Commit/freeze this bounded slice only after normal checks; the next enforced push gate must run on its committed clean SHA. Prior push5 main/perception results are historical failed-gate evidence, not a successful gate for these changes.
