# 정책 적격 증거 계약 설계 (D-268 승격 사다리 1단계)

작성일: 2026-09-29
상태: 설계. 구현은 [실행 계획](2026-09-29-policy-evidence-contract.md)이 따른다. 자동 실행·밸브 개방이 아니다.

관련: [D-268](../adr/D-268-policy-eligible-vision-evidence-for-fleet-tasks.md)·[처분 기록](2026-09-29-d268-policy-evidence-disposition.md)·[D-332](../adr/D-332-human-confirmation-placement.md)·[D-328](../adr/D-328-model-proposed-missions-and-independent-goal-evidence.md)·[D-330](../adr/D-330-fleet-action-admission-stop-and-recovery.md)·[D-18](../adr/D-18-rosy-core.md)

## 목표와 비범위

D-268 Decision 2·3이 요구하는 **정책 적격 증거 계약**의 필드·제출 표면·자격 증명·검증 규칙을 정한다. 이것은 처분 기록 승격 사다리의 1단계이며, API Reference v1.49(additive)과 `core_common.protocol` 공유 schema를 한 변경 단위로 개정한다(D-18).

비범위: 밸브 개방(`POLICY_DISPATCH_ENABLED`는 False 유지), 자동 실행, 모델/LLM 관여(ER 2 provider는 제안 전용 그대로), sighting 용도 변경, 목표 성공 증거(D-328 `GoalEvidence`)의 재설계, 수치 기준 발명(D-268 Decision 5 — 최대 age·오탐·표본은 수용 계획이 정한다).

## 확인 사항: 제출 기반의 공유 여부

처분 기록이 남긴 질문 — "제출·검증 기반을 목표 판정과 공유하는가" — 에 대한 이 설계의 확정:

- **공유하는 것(제출 기반):** 자격 증명에서 서버가 결정하는 출처 identity, 필드 어휘(`evidence_id`·`evidence_source`·`evidence_revision`·`captured_at`/`observed_at`), 신선도·revision 검증 원칙, 감사 기록 형식. sighting source-token 패턴(D-257/D-269)을 계승한다.
- **나누는 것(소비):** payload 타입과 소비자. `PolicyEvidencePayload`는 **발의 승인**(task admission)용, `GoalEvidence`는 **목표 판정**(mission confirm)용. 어느 하나가 다른 하나를 대신하지 않는다.
- **지금 통합하지 않는 것:** `GoalEvidence`의 제출 표면. D-328 착지분을 이 계약에서 재설계하지 않는다. 대신 코어 필드 어휘를 맞춘다(`observed_at`↔`captured_at`, `evidence_revision`↔revision 삼종) — 통합은 필요가 측정되면 별도 리팩터링으로.

## 계약 설계

### 1. 제출 표면과 자격 증명

- `POST /api/fleet/policy-evidence` — `Authorization: Bearer <정책 증거 source token>`. 서버가 토큰에서 출처를 결정하고 클라이언트가 제출한 출처 식별자는 신뢰하지 않는다(D-268 Decision 3).
- `GET /api/fleet/policy-evidence/latest` — operator readback(최근 증거·거절 사유, sighting readback 패턴).
- 설정은 사이트 비밀 아닌 YAML + 환경 변수 토큰(`sightings_config.py` 규칙 그대로): 출처별 `source_id`, `token_env`, 허용 `asset_kind`·`task_kind`, `map_id`, `calibration_revision`, 허용 `model_revision` 목록, `revoked`. 비밀 값을 YAML에 두지 않는다.
- 폐기·만료 자격 증명은 `EVIDENCE_SOURCE_UNKNOWN` 거절. 재생은 `evidence_id` 멱등으로 막는다 — 같은 내용 재전송은 같은 레코드 반환, 다른 내용 재사용은 `EVIDENCE_REPLAY` 거절.

### 2. `PolicyEvidencePayload` (`core_common/protocol/policy_evidence.py`)

sighting schema와 같은 규율(extra 금지·frozen·bool 거부·유한 수). 클라이언트가 `source`·`source_id`·`token`·`policy`·`satisfied` 필드를 보내면 거부한다(`satisfied`는 목표 판정 전용 어휘가 증거 발의에 섞이는 것을 막는다).

| 필드 | 형태 | 규칙 |
|---|---|---|
| `evidence_id` | str ≤160 | 식별자 규칙, 멱등 키 |
| `asset_kind` | enum | `robot`·`workcell`·`object` — dispatch admission의 자원 종류와 동일 어휘(D-330) |
| `asset_id` | str ≤128 | 식별자 규칙 |
| `task_kind` | str | v1 닫힌 집합 `navigate`(task service 유일 종류) — 서버 등록부 대조 |
| `captured_at` | float | 유한·양수 아님 허용(에포크), bool 거부 |
| `map_id` | str ≤160 | 공백 불가 |
| `calibration_revision` | str ≤128 | 공백 불가 |
| `model_revision` | str ≤128 | 공백 불가 — 검출/추론 모델 산출물 revision |
| `observation` | 객체 | `kind`는 **서버 등록부 대조, v1 등록부는 비어 있다** — v1에는 어떤 관측 종류도 등록되지 않으므로 모든 제출이 검증 단계에서 거절된다(fail-closed). 첫 종류는 실 사용 사례와 함께 자체 시험을 붙여 등록한다 |

### 3. 서버 검증(제출 시)과 거절 사유

제출 시: 출처(자격 증명) → transit(`received_at - captured_at ≤ 300 ms`, D-268 Decision 4의 기존 계약 수치) → 필드/등록부 → 저장(SQLite `fleet_policy_evidence`, `received_at` 서버 스탬프). 수용·거절 모두 감사 기록에 출처·`evidence_id`·사유를 남긴다.

거절 사유 enum(감사·readback에 노출): `EVIDENCE_SOURCE_UNKNOWN`·`EVIDENCE_REPLAY`·`EVIDENCE_TRANSIT_LATE`·`EVIDENCE_REVISION_MISMATCH`·`EVIDENCE_TASK_KIND_NOT_REGISTERED`·`EVIDENCE_ASSET_NOT_PERMITTED`·`EVIDENCE_OBSERVATION_KIND_UNKNOWN`.

### 4. 소비 — 발의 승인 binding (task admission)

`submit_navigation(source="policy")`는 `evidence`에 `{"evidence_id": ...}` 참조를 **필수**로 요구한다(operator 발의는 무변경). 서버가 저장된 증거를 읽어 binding을 검증한다: 출처 등록·폐기, `task_kind` 일치, `asset_id == robot_id`, revision 삼종이 사이트 현재값과 일치, 제출 시각 기준 age ≤ `max_age_s`(설정값 — **미설정 시 거절**, 수치는 수용 계획이 정한다), 관측 종류 등록부. 검증 통과는 **수용**일 뿐 발행이 아니다: `POLICY_DISPATCH_ENABLED = False`가 그대로면 작업은 `HOLD(POLICY_NOT_ACCEPTED)`에 머문다. 이 계약의 어떤 부분도 밸브를 열지 않는다.

### 5. API Reference 개정 예고 (v1.49 additive)

새 섹션: 정책 증거 제출·readback 경로, payload 필드, 거절 사유, policy 발의의 `evidence_id` binding. 변경 로그 초안: *Additive(D-268 사다리 1단계): 정책 적격 증거 제출·보관 계약 — source token 출처 결정, `evidence_id` 멱등, transit 300 ms, 발의 binding·거절 사유. `POLICY_DISPATCH_ENABLED` 유지, 자동 실행 불변*. PRT `protocol_version` 1.0 유지(기존 필드 변경 없음).

## 불변식 (구현·리뷰가 강제하는 것)

1. 밸브: `POLICY_DISPATCH_ENABLED`가 True가 되는 변경은 이 계획 어디에도 없다. 계약 시험은 이 플래그가 False임을 단언한다.
2. fail-closed: 관측 등록부 비어 있음(모든 제출 거절), `max_age_s` 미설정 거절, 폐기 출처 거절.
3. 수치 비발명: 이 설계가 새로 만든 수치는 없다. transit 300 ms는 D-268 기존값이다.
4. 생산자·소비자 함께 시험: schema 시험(생산자 관점) + 제출·admission 시험(소비자 관점)이 같은 계획에 있다.
5. sighting 무변경: `POST /api/fleet/sightings`·`SiteSightingPayload`·표시 전용 규칙은 그대로.

## 테스트 전략

- schema: 필드 규칙·금지 필드·bool/유한수·closed set(`src/contracts/foundation/test/`).
- 제출: 가짜 토큰·재생·transest 초과·revision 불일치·등록부 빈 거절(`src/site/fleet/test/`, 네트워크 없음).
- admission: `evidence_id` 없는 policy 발의 거절, binding 통과 후 HOLD 유지, operator 경로 무변경.
- 문서 정합: `test_task_contract_docs.py` 확장 — API Ref v1.49·schema·거절 사유 enum 정렬 단언.

## 열어두는 것

- 첫 관측 종류(`observation.kind`)의 시맨틱 — 실 사용 사례(예: 구역 관측 기반 사전 등록 작업 시작) 제안 시 별도 추가.
- `GoalEvidence` 제출 표면과의 통합 — 필요가 측정되면 어휘 매핑을 따라 리팩터링.
- 사이트 revision "현재값" 원장(map·calibration·model의 정본 위치) — 첫 실물 배치 때 확정. 그 전에는 출처 설정값과의 일치 검사로 대체한다.
