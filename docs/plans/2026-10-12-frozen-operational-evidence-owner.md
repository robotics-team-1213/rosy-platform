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
