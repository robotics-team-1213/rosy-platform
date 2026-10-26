# Landing selection extraction - source evidence

2026-10-26. Task0 only of the independently approved explicit-FULL plan. This unit separates existing selection; it adds no FULL mode, JSON forcing, prepared coverage rule, receipt format or browser registry change. Root owns subsequent official landing and feature work.

## Source and ownership

Base commit 353d847f00383956ef642d88e046337712ea5283; source commit b82af1ec31c9492e673892f01e49c2e0be1aee79. Independent admission_arch_v1 review approved source tree c0f27b3c403d8fce3106c060866501445d11aef5. The three source/test paths are tools/land.py, new tools/land_selection.py and new test/test_land_selection.py. Both new paths were absent before this unit. These concern:other changes require no Safety attestation; none is invented.

Only select/browser_tier moved. Existing public signatures/defaults remain as thin wrappers passing sys.modules[__name__], as the existing land_prepare pattern does. The caller still supplies Stop, subprocess/environment, fallback mapping, packing, browser targets/chunks and monkeypatch seams. Inverse-qualification AST comparison proves both moved bodies equal the base; all other land functions/classes are AST-identical. The caller's Stop remains the caught class when land runs as __main__. No CLI or default auto/none/custom behavior changes.

Physical sizes: land.py581 ->548 (<570, the95% threshold of600); new helper53 lines. No limit or ratchet was raised. The standalone behavior tests exercise affected/FULL outputs, main's harness-only delta, failure/malformed JSON, fallback, subprocess argv/environment, browser chunk/ALONE order and public wrapper delegation.

## Committed remote evidence

| Phase | Source | Actual result | Official/outer | Known |
|---|---|---|---|---|
| RED | commit b41cbae635844880f50d7173c767de0a980bfced | 11 failures at explicit missing-leaf assertions in test bodies | 1 / 1 | NEW11 / known0 / flaky0 |
| GREEN | commit b82af1ec31c9492e673892f01e49c2e0be1aee79 | 152 progress-row passes,0 skips | 0 / 0 | NEW0 / known0 / flaky0 |

The first tests-only commit1637b18006 was followed by tests-onlyb41cbae635 before any RED run, moving the missing-leaf assertion into each test body. Actual RED has no import, collection or fixture-setup errors. It reports one Python regex SyntaxWarning; the production checkpoint adds only the raw-string prefix to that regex, without changing its meaning.

GREEN ran test/test_land_selection.py, test/test_land.py, test/test_land_browser.py, test/test_land_record.py and test/test_land_queue.py. The existing prepare/FULL/default-mode cases reside in test_land.py. Every produced run log was classified. One existing unrelated theme browser ID is listed but not failing, not new coverage. Quiet -qq output omits a numeric summary: the152 count is from complete pytest progress rows. Browser chunk algorithm tests ran; no Chromium opt-in or actual whole FULL tier ran.

Each remote job used the approved qualified-labs wrapper with fresh >=30GiB/<90% preflight and only lab hosts, never laptop/site. GREEN observations: model97.458GiB/77.82%, AI192.652GiB/56.56%. The raw GREEN log lists20 pip-* entries in its capped /tmp warning; attribution is unknown, and no cleanup or unrelated host action occurred. No rerun/LOAD-FLAKY or skipped success is claimed.

Evidence root: %LOCALAPPDATA%/Temp/rosy-land-selection/. red/ and green/ each retain runner.txt, run-1.txt and run-1-known.txt. source-preservation.json records AST, exact tree and sizes; frozen-source.patch and verification-summary.json preserve scope/results/hashes. The external progress.md records the bounded plan and live-policy rulings. Prior C2/prelude evidence is not reused as this source's pass.

Source D766 checked all3 commits from the pinned base and passed. After the final docs commit, run the full range D766, generate/lint/diff and official dry-run; bind their actual results and final HEAD/clean status in the external handoff. These final steps are pending at this record's creation. An official dry-run is a plan, not FULL/landing evidence. No worker land/push/site/device/robot action occurred; explicit FULL implementation and final publication remain separate pending work.

CE: not applicable. This pure extraction is explained by its passed-caller seam, preserved bodies and behavior regressions. Existing size-before-feature and scoped-selection lessons were applied with the current remote policy; no newly solved operational issue warrants another solution document.
