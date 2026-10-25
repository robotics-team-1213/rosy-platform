# Site updater runtime extraction

## 2026-10-26 source preparation

Base commit3733f72b5d; branch refactor/site-updater-runtime in the existing secondary slot. D766 requires a split before adding work to the590-line updater (95% floor570 of600). Move exactly _compose_files, _compose, _verify, healthy, _containers_reason and _restart into owner-local site_update_runtime.SiteRuntimeIO; SiteUpdater retains constructor, switch, rollback and control ordering. New counts: updater516, runtime helper110.

Static AST proof preserves all23 original methods including constructor/defaults, six relocated methods and the17 remaining methods. All original public imports remain, and every relocated global resolves through the same stdlib, existing I/O or verifier import targets. I/O, verifier and builder content is unchanged. Existing tests retain their function/class AST except adding the required runtime file to the positive administrator-copy fixture. The separately added negative closure guard proves an incomplete reviewed install must refuse, without borrowing checkout/candidate code.

Tests-only commitd50e67e208 remote RED:1failed,0skipped,0.21s, official/outerexit1, knownNEW1/known0/flaky0. The existing CLI returned0/help with only the old four files, failing the newly required runtime dependency assertion; no import/collection failure is counted. External logs/proof: %LOCALAPPDATA%/Temp/rosy-site-updater-runtime/{red-closure/run-1.txt,red-closure/run-1-known.txt,red-closure-runner.txt,source-preservation.json}.

README administrator installation now copies allfive reviewed host Python files from the same commit; missing helpers remain refusal. These files remain outside candidate authority. No new ADR/API is needed for this same-owner method relocation under existing D301/D441/D766; signature, Compose/runtime checks, error handling and service sets are unchanged. Legacy/current three/four-image compatibility remains in the pending separate migration unit, which must wait for this split to land.

Actual independent source review, committed regression GREEN and official dry-run remain pending. No site access, install, migration/rollback, publication, device motion or field acceptance. Existing lessons about whole configuration and external-installer delivery/real exit status were read; CE: no new lesson for routine extraction and explicit installer-copy regression.
