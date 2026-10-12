# Frozen operational evidence owner implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 운영 fake PASS 입력을 받지 않고 원본 검수·coverage·현재 설치에서 D-727 기대 binding을 계산하는 SOURCE 경계를 만든다.

**Architecture:** Model PC의 기존 learning/evaluation 소유자는 pure compiler를 소유한다. ROOT 도구가 bounded file loading·raw verification·current installation·승인 보정 읽기를 구성하며 Fleet 기존 OperationalState.apply를 재사용한다. 기존 comparison HOLD·codecs·default off·단일 writer/DB를 유지한다.

**Tech Stack:** Python standard library, existing ROS-free contracts/calibration/export validators, SQLite owner port; raw MCAP 검증은 기존 별도 환경.

## Scope and safety

작업 브랜치 `feat/operational-evidence-owner`, 등록 worktree `.worktrees/wt-op-evidence-006abc`. 기존 main·다른 worktree는 수정하지 않는다. private key와 실제 검수/현장 자료를 읽거나 만들지 않는다. 출력과 로그는 기존 X: 세션만 사용한다. 실제 provider·robot·notification·배포·push·착지는 하지 않는다.

### Task 1: 닫힌 계약과 RED

- Create `docs/adr/D-734-frozen-operational-evidence-owner.md` and this plan; append only this ADR to `docs/reference/ROSY ADR Log.md` with BOM/CRLF.
- Create `test/learning/decision/test_operational_evidence.py` and `test/test_incident_operating.py`.
- Tests call the future compiler/ROOT loader and assert flags-only PASS, unreviewed/forged sources, missing windows, changed bytes/installation are rejected or HOLD, never operation proof.
- Commit exact paths. Run strict remote wrapper against these two tests; record expected RED and compare known_failures.

### Task 2: Pure original-evidence compiler

- Create `learning/evaluation/decision/operational_evidence.py` and bounded source/window validators beside it if the responsibility needs a second file.
- Reuse operational_comparison, calibration and model profile codecs. Do not import Fleet or call a provider.
- Validate exact bundle fields and authentic review bindings, independent split/inventory population, full trace window and original recording/source identities. Cross-check physical actor/submission/ACK/UNKNOWN/result/recurrence/cost and keep unknown numbers null.
- Reviewed limits must be explicit and authenticated. A missing original or incomplete collector is HOLD. Return computed report/binding artifacts only, never signing or command authority.
- Commit and run focused remote GREEN plus existing operational_comparison/calibration regressions. Fix NEW instead of adding known failures.

### Task 3: ROOT installation owner and importer

- Create `tools/incident_operating.py`; reuse `tools/incident_reasoning.py` functions without changing ROOT default-off composition.
- Load each original with separate expected SHA and bounded bytes/duplicate-field rejection. Validate installed files from an explicit deployment-owned base, current signed runtime/source evidence, exact profile/model/calibration/policy/action identity and expiry.
- Recompute raw/capture evidence using existing owner validators; do not trust supplied pass flags or raw hashes without original validation.
- Expose callable evidence/trusted ports for caller composition and a narrow importer delegating to an explicitly supplied existing OperationalState.apply. No Fleet imports in evaluation and no automatic config, signer or activation.
- Exercise current getter mutation/restart/expiry, same DB import rejection of HOLD and independently derived binding. Commit exact paths and run remote regressions/known_failures/lint.

### Task 4: Evidence and limits

- Update the evaluation README with the closed schema and separate SOURCE versus actual acceptance.
- Record exact terminal remote evidence and remaining data/producer/runtime work. Actual field labels, reviewer/source trust, full collection and deployment cannot be replaced by fixtures.
- Give root agent the committed branch, changed paths, test logs and integration caveats. No landing/push; goal remains incomplete.

## SOURCE readiness 하위 checkpoint — US-006 전체 미완료

현재 구현은 authenticated review declaration 진단이다. window의 stream payload는 generic dict이며 실제 collector/actor-credit/clock calibration/cost/result/recurrence 상관관계를 수용하지 않는다. 운영 limits는 형식·서명 검증까지이고 측정값 비교는 없다. 지원하는 기존 calibration/cohort/export/inventory 원본을 재검증하고 UNKNOWN·미지원 domain·빈 원본 자료를 HOLD/null로 보존한다. raw/capture loader는 기존 원본 검증기를 직접 호출하며 caller-supplied fake raw pass report를 받지 않는다.

별도 설치 getter는 pinned manifest·실제 artifact bytes·signed owner process/runtime 선언에서 설치 hash를 계산한다. runtime scope는 signed_owner_declaration_only이며 실제 OS probe나 FIELD 증거가 아니다. compiler는 explicit unsupported 때문에 항상 HOLD이므로 OperatingEvidenceOwner의 installation/calibration/binding branch는 준비 코드이고 현재 evidence 호출에서 실행되지 않는다. ROOT factory 기본 off와 기존 comparison HOLD는 그대로다. importer는 flags-only callback을 거절하고 폐기는 기존 DB stored-binding 검증에 맡긴다.

RED checkpoint들은 새 SOURCE 경계를 확인한 것이며 실측 한계·운영 승인·서명·OS probe·실제 모델·로봇·현장 정답을 만들지 않았다. 최신 code regression `7e212f920`은 strict Model PC의 228 tests, terminal exit 0, known-failures NEW 0이다. 로그는 기존 X: 세션 `logs/us006-source-regression/run-1.txt`. 관련 calibration/cohort/원장과 P6/import 경계를 포함한다. 후속 문서/정리 커밋에서 최종 focused 회귀를 다시 기록한다.

통합 전 독립 ROOT 검토가 필요하다. D-734는 Proposed를 유지하며 US-006 전체, 실제 운영 producer·collector·actor/source/cost/result/recurrence·OS probe admission과 door/arm은 미완료다. 다른 세션 D-732/D-733 예약은 임의 gap 처리하지 않고 ROOT가 승인된 main 통합에서 결합한다. 이 worktree는 push/landing하지 않는다.
