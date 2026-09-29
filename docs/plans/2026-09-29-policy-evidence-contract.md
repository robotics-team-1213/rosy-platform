# 정책 적격 증거 계약 실행 계획

작성일: 2026-09-29
상태: 실행 계획([설계](2026-09-29-policy-evidence-contract-design.md) 참조). TDD — 각 작업은 시험 먼저.

근거: [설계](2026-09-29-policy-evidence-contract-design.md), [D-268](../adr/D-268-policy-eligible-vision-evidence-for-fleet-tasks.md), [처분 기록](2026-09-29-d268-policy-evidence-disposition.md), [D-330](../adr/D-330-fleet-action-admission-stop-and-recovery.md), [D-332](../adr/D-332-human-confirmation-placement.md), [API Ref §10](../reference/ROSY%20API%20%26%20Protocol%20Reference.md).

범위: 정책 적격 증거의 schema·제출·보관·발의 binding과 API Ref v1.48. **비범위: 밸브 개방 없음(`POLICY_DISPATCH_ENABLED = False` 불변), 자동 실행 없음, sighting 무변경, 목표 증거(D-328) 무변경, 실물 배치 없음.**

| 작업 | 내용 | Files | Test |
|---|---|---|---|
| T1 | `PolicyEvidencePayload` schema — 필드 규칙, 금지 필드(`source`·`source_id`·`token`·`policy`·`satisfied`), bool 거부·유한수, closed set(asset/task) | `src/contracts/foundation/core_common/protocol/policy_evidence.py`, `protocol/__init__.` 재수출 없이 sightings 방식 유지 | `src/contracts/foundation/test/test_policy_evidence.py` (신규) |
| T2 | 출처 설정 로더 — YAML(비밀 아님) + `token_env` 환경 조회, 허용 종류·revision·폐기 플래그, 빈 목록 거절 | `src/site/fleet/fleet/server/policy_evidence_config.py` | `test_policy_evidence_config.py` (신규) |
| T3 | 증거 저장·제출 검증 — SQLite `fleet_policy_evidence`(evidence_id 유니크, received_at 서버 스탬프), 멱등(같은 내용=같은 레코드, 다른 내용=`EVIDENCE_REPLAY`), transit 300 ms, 등록부·revision 검증, 거절 사유 enum 상수 | `src/site/fleet/fleet/server/policy_evidence.py` | `test_policy_evidence_store.py` (신규) |
| T4 | 발의 binding — `submit_navigation(source="policy")`에 `evidence_id` 필수, 저장 증거 대조(출처·task_kind·asset·revision·age), 통과 시에도 `HOLD(POLICY_NOT_ACCEPTED)` 유지, operator 경로 무변경 | `src/site/fleet/fleet/server/task_service.py` | `test_task_api.py`·`test_task_service_policy_evidence.py` (신규) — **밸브 False 단언 포함** |
| T5 | 경로·인증 — `POST /api/fleet/policy-evidence`(source token), `GET /api/fleet/policy-evidence/latest`(operator), 401/403/409 매핑 | `src/site/fleet/fleet/server/app.py` | `test_server_app.py` 확장 |
| T6 | API Ref v1.48(additive) — 신규 섹션·변경 로그·policy 발의 binding 서술; 거절 사유 enum 정렬 단언 | `docs/reference/ROSY API & Protocol Reference.md`, `src/site/fleet/test/test_task_contract_docs.py` | `test_task_contract_docs.py` 확장 |
| T7 | harness 기록·정리 — `core_common`·`fleet` logs/progress, flake8 120 | 각 `logs.md`·`progress.md` | `python tools/harness/rosy_harness.py lint` |

순서: T1→T2→T3→T4→T5→T6→T7. T4는 T3 저장이 있어야 하고, T6은 T1~T5의 최종 모양을 문서에 확정한다.

## 회수 조건(게이트)

- **SOURCE/LOCAL만.** ROS 불필요(전부 ROS-free 경로), 네트워크 없음(testclient·가짜 토큰).
- 통과 기준: `python -m pytest src/contracts/foundation/test src/site/fleet/test -q` 녹색, 계약 시험 4종 녹색, flake8 120.
- **불변 단언(어긋나면 이 계획 실패):** (1) `POLICY_DISPATCH_ENABLED is False`, (2) v1 관측 등록부 비어 있어 모든 제출이 검증 거절, (3) `max_age_s` 미설정 시 admission 거절, (4) sighting 경로·payload 무변경.
- ARTIFACT/DEVICE/FIELD: 이 계획이 다루지 않는다. 증거의 실측·수용은 [처분 기록](2026-09-29-d268-policy-evidence-disposition.md) 사다리 3~5단계.

## 리스크와 대응

- **동시 세션 충돌:** `fleet/server`는 지금 활발하다(21 commits 미검증). T4·T5 시작 전 `git status`·최신 커밋 재확인, `task_service.py` 충돌 시 rebase 후 재시험.
- **문서 정합 시험 경직:** `test_task_contract_docs.py`는 ADR·API Ref·schema를 함께 검사한다 — T6은 T1 결과물 확정 후 마지막에.
- **멱등 의미:** 재전송이 조용히 새 레코드를 만들면 안 된다. 같은 `evidence_id`+다른 내용은 감사 남기고 거절.
