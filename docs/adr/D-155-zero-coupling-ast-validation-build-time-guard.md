## D-155 Zero-Coupling AST Validation (Build-time Guard)

**Date:** 2026-09-21
**Status:** Accepted
**Context:** Static code dependencies between modules are currently maintained manually. Python's dynamic nature makes it easy to accidentally introduce cross-domain imports that pass local monolithic tests but break isolated runtime slices.
**Decision:** Extend `test/test_module_separation.py` with an AST-based guard
that fails when `core/control` production code imports CORE packages. The
existing package-dependency and final-publisher guards remain authoritative.

### Refinement (2026-10-02)

Guard 4의 금지 목록에서 `core_common`을 빼고 계약면만 허용한다(선행: D-18의 fleet 규칙).
근거: (1) `core_common`은 계약 기반(contracts/foundation)이지 core 런타임이 아니고,
(2) control의 package.xml이 `core_common`을 exec_depend로 선언해 감지 전용 슬라이스도
함께 배포된다, (3) D-395/D-397이 만든 공유 계약(`core_common.protocol.localization`,
`core_common.calibration_store`)을 bringup·core·fleet가 함께 쓴다. 허용은
`core_common.protocol.*`와 `core_common.calibration_store` 둘뿐이고 런타임 패키지
(core, core_features, core_api_web, core_events)는 여전히 전면 금지다.
