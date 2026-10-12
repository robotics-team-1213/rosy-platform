# 판정 프로파일 승인·승격·복귀 Implementation Plan

**Goal:** 독립 평가 근거와 판정 모델 프로파일을 결속해 새 사건부터 승인 revision을 적용하고, 진행 중 사건의 프로파일·예산·원장을 보존하면서 복귀한다.

**Status:** Planned; implementation and operational acceptance are incomplete.

## D-706 구현 checkpoint

### D-715 보존 사건 population 결속 checkpoint

`871591c3e6`에서 root `tools/incident_case_inventory.py`의 읽기 전용 Fleet DB 트랜잭션과 기존 독립 비교/CLI의 `compare_with_inventory`를 연결했다. 지정한 owner/policy/전체 profile tuple·시작 시간 창의 ACTIVE/HOLD/NOT_NEEDED 사건 행을 모두 목록화한다. caller가 누락한 실제 실패 사건, scope/예산/상태/카운터 변경과 별도 고정 digest 불일치를 거절한다. 독립 검토에서 같은 사건의 유효 이전·후속 export를 여러 전략에 넣으면 마지막 snapshot만 검증되는 결함을 실제 RED 1 NEW로 확인했다. inventory 모드에서 중복 키를 덮어쓰기 전에 거절하며 기존 비교 모드는 유지한다. LF를 고정해 최종 파일도 consumer의 1 MiB 제한 이내로 맞췄다.

관련 5개 파일의 적격 AI PC 원격 회귀는 terminal exit 0/NEW 0이며 로그는 세션 `logs/incident-inventory-final/run-1.txt`다. 실제 생산/비교 CLI와 exclusive output·read-only source를 포함한다. `9baec27cfb`의 추가 population 회귀 12개는 terminal exit 0/NEW 0이며 다른 owner/policy/profile 제외, end-exclusive 창, 재고정된 잘못된 metadata 거절, 1,001건 초과의 전체 거절을 확인했다. 로그는 `logs/incident-inventory-population/run-1.txt`다. 독립 source 재검토에서 중요한 잔여 blocker는 없었다.

이 inventory는 `retained_case_rows_only`, UNREVIEWED, field_accepted=false다. source 수집 누락·정상 무명령·전체 모델 호출·재발·청구·정답·독립 한계와 runtime/현장 수용을 입증하지 않으며 비교/승격은 HOLD를 유지한다. 다음은 이 실제 population과 완전한 관측/명령/결과 창을 결속하고 독립 검수·수용 한계를 공급하는 것이다. source 목록의 digest는 출처 인증을 대신하지 않는다.

### D-714 로컬 통합 착지

`feat/incident-installation-binding`는 `e78eca89e3`로 로컬 main에 착지했다. 처음 통합에서 문서의 Git SHA가 high-entropy token으로 분류되는 NEW 1을 확인해 문서만 식별 가능한 짧은 revision으로 고쳤으며 secret scanner를 변경하지 않았다. 해당 원격 회귀 80개 통과 후 실제 main 통합은 378 passed/skipped 0/terminal exit 0/NEW 0과 lint를 통과했다. 고정 로그는 세션 `logs/incident-manifest-land-4e2598.txt`다. FULL CI, push·배포·모델·현장 수용과는 구분한다.

### D-714 고정 설치 명세 결속 checkpoint

`feat/incident-installation-binding`의 `4301911968`에서 root composition `tools/incident_reasoning.py`에 `load_incident_profile_config`를 추가했다. 별도 설치 설정의 파일 SHA256과 최대 64 KiB 원본을 확인하고 내부 `rosy.incident.profiles/1` 명세의 전체 ModelProfile set을 이미 구성된 provider/config에 결속한다. 명세는 schema/profile_sets만 허용하며 set은 최대 8개, 각 set의 primary/reviewer는 1~2개다. 제공자 전체 profile·adapter identity/범위와 비교하고 중복 set·미설치 ID/revision/예산·변조·clock 재정의를 거절한다. 원래 admission/current_profiles/budget/enabled/보정 포트는 보존한다. 파일에서 제공자·주소·명령어·credential을 만들거나 호출하지 않는다.

초기 missing loader RED 13 NEW 이후 실제 create_app→dispatcher→선택된 stub 경로와 재로드를 확인했다. 추가 원본 JSON 시험에서 큰 정수의 내부 OverflowError 노출을 RED 1 NEW로 재현했고, RecursionError/OverflowError도 같은 redacted ValueError from None으로 변환했다. 깊은 JSON과 중복 key는 거절 회귀로만 확인했으며 별도 RecursionError 재현을 주장하지 않는다. `4301911968`의 실제 원격 6개 파일 회귀는 terminal exit 0/NEW 0, 로그는 기존 세션 `logs/incident-manifest-final/run-1.txt`다. 원격 시험·독립 source 검토에 중요한 잔여 blocker는 없으며 설치·구조 회귀도 포함한다. 실제 모델·trust/호스트 설치는 수행하지 않았다.

기존 root 구성 호출자는 다음 순서로 연결한다. `installed_configs`는 이미 구성된 기존 provider와 명시적 admission/budget 설정이며 clock을 포함하지 않는다. `installed_file_sha256`은 신뢰된 설치 구성의 별도 값이다. 로더가 파일 자체에서 예상 hash를 계산해 수용하지 않는다.

```python
from tools.incident_reasoning import load_incident_profile_config, registry_calibration_config

config = load_incident_profile_config(profile_file,
    expected_sha256=installed_file_sha256, installed=installed_configs, clock=clock)
config = registry_calibration_config(config, registry, domain='line_follow')
# Existing create_app(..., incident_model_config=config); selection remains explicit CAS.
```

이 source 결속은 실제 고정 명세 배포·실행 성공이나 signed 운영 품질 수용이 아니다. 다음은 운영 coverage와 독립 수용 receipt의 결속, 실제 설치 readback·provider 결과·현장 처리/성공 확인이다. 파일과 callables의 구성을 신뢰하는 기존 root 경계는 계속 필요하다.

### D-706~D-713 로컬 통합 착지

통합 브랜치 `feat/reasoning-artifact`는 `3a9f812bd222`로 로컬 main에 착지했다. 기존 main 병합에서 도착한 D-692의 stale gap 표시만 제거한 뒤 lint와 적격 AI PC/Model PC의 두 통합 그룹을 통과했다. 각각 5,860 passed/292 skipped와 452 passed/3 skipped, terminal exit 0/NEW 0이다. 고정 로그는 세션 `logs/reasoning-land-91be5f.txt`, `logs/reasoning-land-f24797.txt`다. 선택기가 FULL로 승격했으므로 전체 CI tier는 여전히 필요하며 local landing은 push·CI·배포·모델/현장 수용을 대신하지 않는다. D-714는 별도 worktree에서 개발해 진행 중 착지의 검증 HEAD를 변경하지 않았다.

### D-713 기존 runtime의 pinned dispatcher checkpoint

`b5648d15a6`에서 기존 Fleet factory/loop/outbox의 단일 worker 슬롯에 opt-in `profile_workers` 구성을 연결했다. 같은 store·board·관측·clock을 공유하는 고정 profile worker 최대 8개를 만들고, active/최종 인수 대기 사건의 원 profile과 새 사건의 현재 선택에 로봇의 공개 CORE 상태만 분배한다. 기존 사건과 같은 case가 고정돼 있으면 current worker에 중복 전달하지 않는다. case가 바뀌면 이전 사건 정리와 새 사건 생성은 각 worker가 맡으며 최종 생성 선택 검증은 D-712의 동일 DB 트랜잭션이다. outbox receipt는 같은 트랜잭션에서 원 scope 또는 현재 선택의 worker 하나에만 연결한다.

독립 검토에서 한 worker 종료 오류가 다른 worker 정리보다 먼저 dispatcher를 종료하는 결함을 RED 1 NEW로 재현했다. 모든 worker의 cleanup terminal을 기다린 뒤 오류를 그대로 보고하도록 수정했다. 정상 0호출·미설치 current 0호출·기존 예산과 assignment 보존·복귀·UNKNOWN 재제출 금지·in-flight 취소·중복/unrouted 거절을 실제 원장과 create_app 경로에서 확인했다. `b5648d15a6`의 관련 8개 파일 원격 회귀는 terminal exit 0이며 로그는 세션 `logs/incident-dispatch-final/run-1.txt`다. source-less wheel/sdist와 구조 검사도 포함한다. 독립 source 검토에서 중요한 잔여 blocker는 없었고 실측은 Fleet 55,472/automation 331/execution 343/ledger 492로 기존 기준을 유지했다.

`799587b251`의 root `registry_calibration_config`는 같은 opt-in profile_workers 각각에 기존 엄격한 보정 승인 읽기 포트를 구성한다. top clock과 기존 providers/admission/current/budget/enabled를 보존하고 nested workers·variant clock·소유된 포트 재정의를 거절한다. 실제 SQLite 승인→root 구성→create_app→dispatcher에서 primary만 호출하고, 폐기 후 새 사건은 동일 입력의 primary+reviewer로 제한되는 흐름을 확인했다. 관련 원격 회귀는 terminal exit 0/NEW 0, 로그는 `logs/incident-dispatch-registry-green/run-1.txt`다. `deb4429b44`의 구성 경계 추가 시험은 15개 통과/terminal exit 0/NEW 0, 로그는 `logs/incident-dispatch-composition/run-1.txt`다. 실제 모델·운영 trust 설치를 사용하지 않았다.

내부 구성에서 `profile_a`와 `profile_b`는 기존 worker 설정이며 clock을 포함하지 않는다. flat 설정은 계속 단일 worker를 만들고 기본 미활성 동작을 유지한다.

```python
configured = registry_calibration_config(
    {'clock': clock, 'profile_workers': (profile_a, profile_b)},
    registry, domain='line_follow')
# Existing create_app(..., incident_model_config=configured) owns installation.
# Profile selection still requires the existing Fleet journal and explicit CAS.
```

선택 목록·보정의 PASS_OFFLINE_ONLY는 운영 품질 승격이 아니다. 다음은 signed 운영 수용·실제 설치 loader/readback과 운영 coverage 결속이다. 실제 모델 결과·독립 품질·현장 수용, 물리 처리/door/arm·실패 분류/training도 여전히 남아 있다. D-706 이후 통합 착지는 lint에서 이미 도착한 D-692의 stale gap 표시 때문에 중단됐으며 실제 ADR/Log 확인 후 `92edcab97`로 표시만 제거했다. 기존 실행은 terminal로 종료됐고 수정 후 새 통합 실행을 한다.

### D-712 영속 선택·원자적 사건 배정 checkpoint

`d0541c3b27`에서 기존 Fleet 사건 DB에 owner/policy별 current/previous profile tuple SHA·증가 revision과 사건별 assignment revision을 기록한다. 새 사건은 선택 일치 확인·생성·assignment 기록을 같은 BEGIN IMMEDIATE 또는 기존 outbox 트랜잭션에서 수행한다. 기존 사건의 scope·예산·시도·assignment는 변경하지 않는다. 선택이 없거나 다른 profile/owner/policy면 routed 새 사건을 거절한다. 선택·복귀는 revision CAS로 경쟁 전환과 ABA를 거절하며 재시작 후 읽어 확인한다.

책임 경계는 기존 `automation/routing.py`의 `IncidentProfileRoutes(store)`가 current/previous 선택·CAS·복귀를 맡고, `ledger/store.py`가 같은 트랜잭션의 사건 생성·배정만 맡는 것이다. 초기 구현에서 ledger 532 > 기존 370+150을 실제 원격 구조 시험으로 확인했으며 이 책임 추출로 해결했다. 새 SIZE_UNITS나 허용량 증액은 없다. 실제 두 경쟁 선택, case 트랜잭션 중 선택 차단, 잘못된 revision/hash·이전 선택 부재, receipt/poll와 실제 create_app opt-in 연결을 확인했다. 원격 회귀는 적격 Model PC에서 terminal exit 0/NEW 0이며 로그는 세션 `logs/incident-routing-owner-green/run-1.txt`다. source-less 설치 import와 구조 검사도 포함한다.

내부 구성 예시는 다음과 같다. worker의 `routed=True`는 명시적 opt-in이고 기본값 false를 유지한다. 아래 선택은 모델 수용·활성화·물리 authority가 아니며 기존 admission/current_profiles/보정 gate를 우회하지 않는다. signed 운영 수용과 설치 loader, 여러 pinned worker dispatcher, 실제 전환·복귀 readback과 현장 수용은 남아 있다.

```python
from fleet.incidents.automation.routing import IncidentProfileRoutes
from rosy_situation.snapshot_assessment import POLICY

routes = IncidentProfileRoutes(worker.store)
selected = routes.select_profile('core', POLICY.revision, worker.profile_sha256,
                                 expected_revision=0)
# A later profile selection must use the readback revision; rollback requires previous.
current = routes.profile_route('core', POLICY.revision)
assignment_revision = worker.store.assignment(case_scope)
```

다음은 기존 factory/loop/outbox의 단일 worker 소유자에서 pinned worker dispatcher를 구성하는 것이다. 새 사건은 현재 선택의 설치된 worker에만 배정하고 기존 사건은 원래 worker에 전달한다. 설치되지 않은 current, 폐기된 admission, 사람 claim·UNKNOWN·취소·재시작을 fail-closed로 확인한다. 후보의 offline PASS를 운영 수용으로 올리지 않는다.

독립 source 재검토에서 중요한 잔여 blocker는 없었다. 동일 필터의 실측은 Fleet 55,471, automation 224, execution 343, ledger 492행이며 각 기존 기준·허용량 이내다. lint는 0 errors/28 기존 검증 기록 경고였다. 원격 GREEN 확인과 읽기 전용 검토를 실제 운영 수용으로 대신하지 않는다.

### D-711 새 사건 생성 허가 분리 checkpoint

`31f2cbbe8f`에서 기존 worker의 선택적 `new_case_admission(scope)`를 새 사건 생성 두 경로에 연결했다. 기존 outbox receipt 트랜잭션과 poll에서 사건이 없을 때만 exact true를 요구한다. false·None·숫자·문자열·일반 오류는 생성과 모델 호출을 막는다. 이미 맡은 사건은 기존 프로파일·예산으로 이어가며 기존 안전 admission과 UNKNOWN·사람 소유권 검증을 유지한다.

실제 SQLite receipt/poll 거절과 두 프로파일·두 로봇의 기존 사건 보존을 RED 6 NEW로 재현한 뒤 수정했다. 적격 AI PC 원격 회귀 112 passed/terminal exit 0/NEW 0이며 로그는 세션 `logs/incident-new-case-green/run-1.txt`다. 독립 source 검토에서 중요한 blocker는 없었다. D-711은 빠른 local 생성 fence이며 mutable current 선택과 begin_case의 원자성을 제공하지 않는다. 영속 전환·원자적 배정·pinned dispatcher와 실제 운영 수용을 이어 구현해야 한다.

### D-710 사건 소유권 분리 checkpoint

`e9a5adab14`에서 worker의 active/최종 인수 대기 조회와 `_process`·`_finish`를 자신의 전체 profile tuple SHA 및 CORE owner로 제한했다. 실제 공유 DB 두 worker가 다른 profile 사건을 PROFILE_CHANGED로 닫거나 인수를 대신 큐에 넣는 RED 3 NEW를 재현한 뒤 수정했다. 상태·원래 예산·시도/호출 수를 그대로 보존하고 원 worker만 최종 인수를 처리한다. 같은 profile의 다른 실행 owner도 종료하지 않는다.

적격 Model PC 원격 회귀 135 passed/terminal exit 0/NEW 0을 확인했다. 기존 자기 profile 변경 HOLD·UNKNOWN/재시작·원장·보정/실제 factory·source-less wheel/sdist·구조를 포함한다. 로그는 세션 `logs/incident-profile-scope-green/run-1.txt`다. 독립 source 검토에서 중요한 blocker는 없었다. DB/CaseScope/public API와 기존 안전 fence를 바꾸지 않았다. pinned old/new worker의 새 사건 배정·영속 current/previous·복귀 dispatcher는 여전히 구현해야 한다.

같은 시점의 모델 무호출 AI PC readback은 `/opt/rosy-deliberation/review-cfcba82ddf` missing, 기존 V2 확인 venv Python present, GLM 시험 표식 unreadable이다. 존재/실행 여부를 추정하거나 표식을 변경하지 않았다. runtime_admitted=false이며 실제 GLM 준비·현재 source 설치·첫 실제 모델 결과/독립 품질/현장 수용은 미완료다.

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

새 학습/운영 서비스나 CORE writer를 만들지 않는다. D-710의 worker는 공유 DB에서 자신의 profile SHA·CORE owner scope만 처리한다. 실제 전환 dispatcher는 진행 사건의 pinned profile과 새 사건 배정 권한도 분리해야 한다. 단순히 worker 두 개에 전체 snapshot을 공급하거나 global current_profiles를 바꿔 구현 완료로 표시하지 않는다.

## 검증

1. root가 관리하는 신뢰 포트 밖의 자기 승인·위조 HMAC·다른 profile/domain·잘린 평가/lineage·운영 비교 HOLD를 거절하는 RED를 작성한다. 실제 승인을 만들거나 기존 trust key를 읽지 않는다.
2. 두 경쟁 전환 중 하나만 CAS로 성공하고, restart 후 후보/현재/이전과 감사 원장이 재검증되는지 확인한다. payload/파일/원장 변조와 잘못된 이전 revision에서 복귀를 거절한다.
3. 실제 factory→worker 경로에서 production 보정 gate를 호출하는지 확인한다. 기존 read-only 미수용 동작·최종 인수·source와 운영 권한의 분리를 유지한다.
4. A profile의 진행 사건과 B profile의 새 사건을 같은 DB에서 실행해 상대 사건 종료·예산 초기화·중복 호출이 0회인지 확인한다. 승인 폐기/복귀·사람 claim·취소·UNKNOWN·재시작을 포함한다.
5. 커밋 HEAD의 remote regression·known-failures·lint와 독립 검토 후 승인된 local landing을 한다. 실제 profile 자료·runtime 설치·독립 품질·새 사건 readback과 현장 수용은 별도다.

## 후속 범위

현재 worker는 line_follow와 get_incident_status 읽기만 처리한다. 물리 candidate dispatch·domain별 처리/성공 확인과 door/arm backend는 아직 구현되지 않았다. 정상 불필요 개입·전체 명령/모델 호출/재발/청구 coverage, 검수 label 수용·자동 실패 분류·training-improvement 작업도 필요하다. 이 계획이나 기존 source 시험으로 전체 목표를 완료하지 않는다. 실제 GLM 관리자 준비와 첫 provider 시험, 팀 검수 자료·한계와 현장 수용도 미완료다.
