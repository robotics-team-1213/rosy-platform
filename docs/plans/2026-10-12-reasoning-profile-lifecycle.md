# 판정 프로파일 승인·승격·복귀 Implementation Plan

**Goal:** 독립 평가 근거와 판정 모델 프로파일을 결속해 새 사건부터 승인 revision을 적용하고, 진행 중 사건의 프로파일·예산·원장을 보존하면서 복귀한다.

**Status:** Planned; implementation and operational acceptance are incomplete.

## 실제 소스 감사 결과

2026-10-12 `6a73839f03`에서 root와 독립 읽기 검토가 확인했다. `select_calibrated`의 호출자는 보정 시험뿐이며 production worker에는 호출이 없다. `approved_artifacts`는 외부 dict 포트로 남아 있다. `install_incident_runtime`은 Python config를 직접 주입하는 factory이며 영속 후보/현재/이전 프로파일 loader는 없다. worker의 `current_profiles` 불일치는 기존 사건을 PROFILE_CHANGED/HOLD로 종료하므로, 다음 사건만 새 revision을 적용하는 전환이 아니다.

기존 `learning/registry/policy/registry.py`는 immutable snapshot·hash chain·trusted receipt/HMAC·CAS 기법의 재사용 대상이다. 하지만 `contracts.learning.artifacts.validate_policy`는 OMX/Pinky behavior artifact만 허용한다. 기존 promote는 해당 정책의 metadata 단계 상승이며 reasoning ModelProfile·calibration artifact·current/previous pointer·rollback을 지원하지 않는다. perception model delivery도 vision slot의 별도 경로다. 이 경로들을 판정 모델 승격 완료로 사용하지 않는다.

## 구현 순서와 책임

| 순서 | 책임과 최소 변경 | 완료 조건 |
|---|---|---|
| 1 | 기존 registry 소유자에서 reasoning profile·보정·운영 평가 근거의 내부 계약을 ADR로 확정 | 전체 profile SHA와 역할/domain/modality·calibration revision·검수 자료 hash·평가 근거가 결속되고, 기존 behavior artifact와 혼용하지 않음 |
| 2 | 같은 소유자에서 후보·수용·현재·이전 revision과 전환 원장을 구현 | snapshot/hash chain·동시 CAS·신뢰된 승인 receipt 검증을 재사용하고 회귀/누락/HOLD를 승인하지 않음. metadata 변경만으로 운영 authority를 생성하지 않음 |
| 3 | 기존 Fleet factory의 profiles/providers/admission/current_profiles와 승인 hash 포트에 연결 | 동일 전체 profile과 calibration artifact를 `select_calibrated`에 실제 전달하고 승인 폐기·변조·도메인 변경·낮은 신뢰도/대안 차이를 거절함 |
| 4 | 사건 소유 revision에 따라 기존 worker를 연결 | 새 사건만 현재 revision으로 생성, 진행 중 사건은 원래 프로파일/예산/시도를 유지. 다른 revision worker가 같은 DB의 사건을 PROFILE_CHANGED로 닫거나 같은 요청을 중복 실행하지 않음 |
| 5 | 복귀와 운영 readback을 연결 | 새 사건은 이전 승인 revision을 쓰며 위험으로 폐기된 profile의 admission은 중단. UNKNOWN은 재제출하지 않고 E-stop/사람 인수를 해제하지 않음. registry·설정 readback·실제 사건의 활성 revision을 별도 기록 |

새 학습/운영 서비스나 CORE writer를 만들지 않는다. 기존 worker의 `active_scopes`·`pending_handoffs`는 공유 DB를 읽으므로 여러 revision을 구성할 때 소유 scope별 filtering이 필요하다. 단순히 worker 두 개에 전체 snapshot을 공급하거나 global current_profiles를 바꿔 구현 완료로 표시하지 않는다.

## 검증

1. root가 관리하는 신뢰 포트 밖의 자기 승인·위조 HMAC·다른 profile/domain·잘린 평가/lineage·운영 비교 HOLD를 거절하는 RED를 작성한다. 실제 승인을 만들거나 기존 trust key를 읽지 않는다.
2. 두 경쟁 전환 중 하나만 CAS로 성공하고, restart 후 후보/현재/이전과 감사 원장이 재검증되는지 확인한다. payload/파일/원장 변조와 잘못된 이전 revision에서 복귀를 거절한다.
3. 실제 factory→worker 경로에서 production 보정 gate를 호출하는지 확인한다. 기존 read-only 미수용 동작·최종 인수·source와 운영 권한의 분리를 유지한다.
4. A profile의 진행 사건과 B profile의 새 사건을 같은 DB에서 실행해 상대 사건 종료·예산 초기화·중복 호출이 0회인지 확인한다. 승인 폐기/복귀·사람 claim·취소·UNKNOWN·재시작을 포함한다.
5. 커밋 HEAD의 remote regression·known-failures·lint와 독립 검토 후 승인된 local landing을 한다. 실제 profile 자료·runtime 설치·독립 품질·새 사건 readback과 현장 수용은 별도다.

## 후속 범위

현재 worker는 line_follow와 get_incident_status 읽기만 처리한다. 물리 candidate dispatch·domain별 처리/성공 확인과 door/arm backend는 아직 구현되지 않았다. 정상 불필요 개입·전체 명령/모델 호출/재발/청구 coverage, 검수 label 수용·자동 실패 분류·training-improvement 작업도 필요하다. 이 계획이나 기존 source 시험으로 전체 목표를 완료하지 않는다. 실제 GLM 관리자 준비와 첫 provider 시험, 팀 검수 자료·한계와 현장 수용도 미완료다.
