# 판정 프로파일 승인·승격·복귀 Implementation Plan

**Goal:** 독립 평가 근거와 판정 모델 프로파일을 결속해 새 사건부터 승인 revision을 적용하고, 진행 중 사건의 프로파일·예산·원장을 보존하면서 복귀한다.

**Status:** Planned; implementation and operational acceptance are incomplete.

## D-706 구현 checkpoint

### D-709 Fleet 판단 포트 연결 checkpoint

기존 registry의 `approved_candidate(profile_json, domain)`가 현재 승인 상태·신뢰와 정확한 전체 profile/domain을 검증한다. root composition `tools/incident_reasoning.py`의 `registry_calibration_config`가 이 결과와 현재 승인 map을 기존 create_app→install_incident_runtime→IncidentCaseWorker로 공급한다. Fleet에서 learning을 import하지 않으며 기존 admission/provider/profile/current/budget/enabled와 이미 지정한 보정 포트의 소유권을 유지한다.

독립 검토에서 동기 원장 조회의 event-loop 정지를 실제 RED 1 NEW로 재현했다. `880ef2ff33`에서 조회·재계산을 off-loop로 옮기고 기존 case deadline 잔여 시간만 기다리며 완료 후 사람 소유권과 freshness를 재검증했다. 적격 Model PC의 factory·worker·registry·구조·source-less wheel/sdist 회귀는 229 passed/terminal exit 0, `1247cd22df`의 만료/취소와 늦은 결과 차단 회귀는 54 passed/terminal exit 0, 각각 NEW 0이다. 동일 입력의 reviewer, 정상 0호출, 승인 폐기와 두 조회 사이 폐기, 읽기 중 사람 인수를 실제 원장/app factory로 확인했다. 로그는 세션의 `logs/reasoning-fleet-offloop/run-1.txt`, `logs/reasoning-fleet-stop/run-1.txt`다.

독립 source 재검토에서 중요한 잔여 blocker는 없었다. 별도 보정 승인 전달·실제 설치 trust·운영 current/previous와 기존 사건 revision 보존·새 사건 적용·복귀, 실제 provider/품질/현장 수용은 미완료다. 원장/보정 판정이 물리 authority를 만들지 않으며 전체 목표는 ACTIVE다.

### D-707 영속 보정 승인 checkpoint

`8c0ca46af0`에서 같은 registry 소유자의 immutable 후보 snapshot·별도 reasoning tables/chain과 signed 보정 승인·폐기를 구현했다. 기존 Registry의 드라이브/trust/FULL BEGIN IMMEDIATE를 재사용하고 Decision validator는 명시적 포트로만 주입한다. 후보와 보정 원본을 매 읽기 재검증하고 candidate/full-profile/domain/calibration digest/kind/expected-head/verdict를 HMAC receipt에 결속한다. head CAS·승인 revision 충돌·폐기 map 제거를 확인한다. 운영 current/previous·action admission은 추가하지 않았다.

적격 AI PC의 관련 registry·구조·source-less wheel/sdist·실제 incident calibration worker 원격 회귀는 `86522505c4`에서 148 passed/terminal exit 0이다. 독립 검토 후 현재 key/kind 제거·변경과 resealed 과거 receipt signature 변조를 추가했고 `6b2e526694`의 실제 재시작 회귀 21 passed/terminal exit 0을 확인했다. 로그는 기존 세션의 `logs/reasoning-registry-boundary/run-1.txt`, `logs/reasoning-registry-restart/run-1.txt`다. 전체 승인 원장과 worker를 연결한 실제 흐름·설치 trust·운영 전환·현장 수용은 아직 남아 있다.

`feat/reasoning-artifact`의 `d94447edea`에서 내부 후보 계산·재검증과 기존 Model PC 도구의 실제 생산 경로를 구현했다. 계산 소유자는 `operations/decision/src/rosy/decision/deliberation/evaluation/reasoning_candidate.py`다. learning registry는 운영 Decision을 직접 import하지 않는다. 전체 ModelProfile·domain과 fit/evaluation/training/reviewed_profile 원본·재계산 보정 결과를 seal하며 입력과 후보는 각각 2 MiB 이내다. 기존 모델 invocation 16 KiB 제한은 유지한다.

`python tools/decision_calibration.py --candidate <input>`의 입력은 `{profile, calibration_input}`이다. `--from-feedback`을 함께 쓰면 실제 원장 export와 검수 입력을 기존 D-703 경계에서 먼저 결속한다. offline PASS만 exit 0이고 HOLD·FAIL도 후보 자료를 보존하며 exit 1이다. 기존 `--compare`와는 배타적이다. 결과의 `field_accepted`는 false이며 후보 생성이 승인·운영 current 설정은 아니다.

적격 AI PC 9GB에서 기존 registry·보정·비교·피드백 CLI·구조와 source-less wheel/sdist 설치 import 회귀 195 passed, terminal exit 0을 확인했다. 실제 SQLite 원장→별도 검수→후보 CLI와 receipt 변조 거절을 포함한다. 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/logs/reasoning-candidate-feedback/run-1.txt`다. 로컬 main 착지와 전체 통합 검증은 아직 완료하지 않았다.

다음 구현은 같은 registry 소유자의 immutable candidate snapshot, 범위가 제한된 신뢰 receipt 검증, CAS와 감사 원장이다. 후보의 self-reported PASS/검수 이름/hash만으로 승인하지 않는다. 이후 Fleet의 명시적 승인 포트 공급, 기존 사건 소유 revision 보존·새 사건 전환·복귀를 연결한다. 운영 성과 비교 HOLD와 부족한 coverage를 수용으로 바꾸지 않는다.

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
