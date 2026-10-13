# D-649 independent source Safety review

Reviewer: `/root/safety_structure_review`, 2026-10-11.

**Verdict: APPROVE source scope before implementation commit.**

- Seven intact Base behavior packages move into Drive; four legacy ROS entry modules retain `control.*` installation.
- All 80 renamed files retain normalized text; all 76 Python files retain identical AST. Four tagged Safety bodies and dotted public anchors remain unchanged. Initial move receipts compared raw bytes immediately after moving; subsequent checkout normalization is not an algorithm change.
- CORE final Command/Safety and bridge remain authoritative; no mode, writer, activation, device configuration or persistent map/model/data is added.
- CORE generic calibration session and camera-fault eligibility remain admission policy. Perception localization observation/pose evidence remains Perception; CORE Drive composition is explicitly separate from behavior implementations.
- Reviewed fixed source mapping, isolated source archive mapping, flattened Docker behavior snapshot, legacy runtime build/sdist, development overlay and duplicate detection.
- Reviewer identified missing CI lint and affected-test owner coverage. Final review verified behaviors lint, core_features external source ownership/full CORE suites, control runtime ownership and longest matching source owner. Executor/event/advice source scanners include the moved implementations.

Remote regressions, isolated wheel/source archive execution, ROS graph, ARM64 installation and device/field acceptance remain separate evidence; this review does not claim them. The model-code runtime allowlist is a source-closure follow-up preserving the existing signed release validation, not new model or runtime authority.

## Follow-up source review

Same independent reviewer, commit `33125bf1c`: **APPROVE, no material findings.** Explicit `.dockerignore` admissions cover both moved holders; exact image dependency closure and package selection remain asserted. The import fixture registers its package as a normal loader would, with monkeypatch cleanup. No algorithms, command/Safety authority, activation defaults or installed identities changed. The existing D-649 source approval remains valid. Remote 45-pass evidence is separately recorded; actual image/ROS/device proof is separate.
