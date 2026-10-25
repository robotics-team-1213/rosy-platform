# Site updater runtime extraction

## 2026-10-26 source preparation

Base commit3733f72b5d; branch refactor/site-updater-runtime in the existing secondary slot. D766 requires a split before adding work to the590-line updater (95% floor570 of600). Move exactly _compose_files, _compose, _verify, healthy, _containers_reason and _restart into owner-local site_update_runtime.SiteRuntimeIO; SiteUpdater retains constructor, switch, rollback and control ordering. New counts: updater516, runtime helper110.

Static AST proof preserves all23 original methods including constructor/defaults, six relocated methods and the17 remaining methods. All original public imports remain, and every relocated global resolves through the same stdlib, existing I/O or verifier import targets. I/O, verifier and builder content is unchanged. Existing tests retain their function/class AST except adding the required runtime file to the positive administrator-copy fixture. The separately added negative closure guard proves an incomplete reviewed install must refuse, without borrowing checkout/candidate code.

Tests-only commitd50e67e208 remote RED:1failed,0skipped,0.21s, official/outerexit1, knownNEW1/known0/flaky0. The existing CLI returned0/help with only the old four files, failing the newly required runtime dependency assertion; no import/collection failure is counted. External logs/proof: %LOCALAPPDATA%/Temp/rosy-site-updater-runtime/{red-closure/run-1.txt,red-closure/run-1-known.txt,red-closure-runner.txt,source-preservation.json}.

README administrator installation now copies allfive reviewed host Python files from the same commit; missing helpers remain refusal. These files remain outside candidate authority. No new ADR/API is needed for this same-owner method relocation under existing D301/D441/D766; signature, Compose/runtime checks, error handling and service sets are unchanged. Legacy/current three/four-image compatibility remains in the pending separate migration unit, which must wait for this split to land.

Actual independent source review, committed regression GREEN and official dry-run remain pending. No site access, install, migration/rollback, publication, device motion or field acceptance. Existing lessons about whole configuration and external-installer delivery/real exit status were read; CE: no new lesson for routine extraction and explicit installer-copy regression.


## 2026-10-26 reviewed source and committed regression GREEN

Source commit 9816e56bd9 matches independently approved tree 5df4af6143. The review preserves all six relocated method bodies, the original constructor/default/global bindings, public callers and switch/rollback boundaries. The reviewer disclosed one git write-tree call returning the supplied tree: object/cache metadata may be written, with source, staged content and refs unchanged. This is not a zero-Git-writes claim; the disclosure is retained in workspace-records/2026-10-26/site-updater-runtime-review-evidence.md.

Qualified-lab committed invocation of test_site_autoupdate, test_site_candidate, test_site_candidate_verifier, test_site_candidate_signing, test_site_candidate_workflow and test_site_candidate_fetch: 178 passed, 0 skipped in 2.07s. Official runner and outer cmd both exit 0; the complete raw report compares NEW0/known0/flaky0. It includes complete installed five-file CLI loading, missing runtime/IO refusal, and existing verification/runtime/health/rollback behavior. Fresh disk qualification before launch: model 100.172 GiB available /77.23% used; AI 142.923 GiB /67.78%. No site/laptop fallback or actual site commands.

Generate/lint/diff and Python AST checks pass; lint has 0 errors /35 legacy warnings. The staged complete-size decision and actual two-commit D766 range from base 3733f72b5d to source 9816e56bd9 pass, without threshold/ratchet changes. Official read-only dry-run exits 0 against observed main f943e98896, planning a conflict-free merge and one affected invocation, with no FULL escalation. This did not merge or test that later main, run official land or install helpers.

External source-bound proof: %LOCALAPPDATA%/Temp/rosy-site-updater-runtime/{source-preservation.json,staged-size.json,size-range.txt,dry-run.txt}; green-regression/{run-1.txt,run-1-known.txt} and sibling runner log. Original closure RED remains preserved. This split must land before the dependent migration feature; legacy3/current4 compatibility and retired Postgres cleanup are still unimplemented here. Installed helper delivery and operational migration/rollback acceptance remain separate. CE: no new lesson; the move is behavior-preserving and the copy-closure reasoning is explicit in tests/README and existing lessons.
