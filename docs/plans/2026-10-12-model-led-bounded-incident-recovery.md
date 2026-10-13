# 모델 주도 제한 복구와 실제 결과 연결 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 모델의 수용된 제한 복구 후보를 기존 Fleet dispatch 한 곳으로 보내고, 원래 사건·예산을 유지하며 실제 결과와 최종 인수를 확인한다.

**Architecture:** Decision은 고정 JSON 후보, Fleet 사건 owner는 durable 후보/시도/결과, 기존 StuckResolverLoop는 단일 실제 제출, CORE는 기존 D-407 안전/최종 base 출력, Model PC는 독립 평가·수용 근거를 담당한다. 첫 backend는 기존 BACK_AND_RETRY 하나이며 door/arm은 해당 owner의 계약을 수용한 뒤 확대한다.

**Tech Stack:** 기존 ModelProfile/catalog/judgment, SQLite 사건/outbox·StuckResolverLoop·RobotClient, ros-free SDK receipt, 기존 원격 pytest/MCAP 검증과 독립 평가.

**Status:** Planned; source, runtime, model quality and field acceptance are incomplete. D-716 is Proposed for review; it grants no physical admission.

## 먼저 확인한 실제 빈칸

2026-10-12 D-718 선행 CORE/설치 경계는 `f7221c12e6`로 로컬 main에 착지했다. 마지막 원격 통합은 18,671 passed/822 skipped/NEW 0 및 lint이며 세션 `logs/stuck-condition-land-f7221c12e6-{1,2,3}.txt`에 원본을 보존했다. FULL CI·push·배포·실제 모델·현장 수용은 별도다. 이 선행 완료는 아래 모델 후보 생산·단일 소비·운영 receipt·결과 확인의 완료가 아니다.

`deliberation.__init__.CHOICES`에는 물리 복구 선택이 없고 worker의 `_problem`은 reobserve/human만 공급한다. incident catalog에는 읽기 도구 하나만 있다. `_process`는 get_incident_status 외의 단계에서 NO_ADMITTED_READ_OR_REVIEW로 끝난다. StuckResolverLoop._answer는 이미 rule/AI 법칙·token·불명 결과를 다루지만 worker와 같은 물리 ownership을 공유하지 않는다. worker에서 직접 호출하는 빠른 연결은 rule/model 동시 전송 경쟁을 만들므로 사용하지 않는다.

## Task 1: 실제 후보·제출 소유권을 원장에 고정

2026-10-12 선행 CORE source checkpoint: D-717은 `40fdfec111` 로컬 main 및 원격 통합 5,706 passed/40 skipped/NEW 0으로 확인했다. D-718은 동일 막힘의 ASKING/attempts 조건과 HTTP 처리기·제어기의 동시 지원을 검증하고 구형 SDK 의존성을 거절하는 설치 묶음을 구현했다. 독립 SOURCE 안전 재검토를 승인받았고, native installer pin 수정 뒤 실제 wheel/sdist·CI closure 21개 원격 회귀는 terminal exit 0/NEW 0이다. 기존 모델 호출 예산·소비 표식과 설치 runtime은 바꾸지 않았다. 아래 후보 원장·규칙/모델 단일 소비·운영 수용·실제 결과 연결은 여전히 다음 구현이다.

Read/modify: `operations/fleet/fleet/incidents/automation/ledger/store.py`, `automation/execution/worker.py`, `automation/runtime.py`, `fleet/stuck/loop.py`, `fleet/stuck/pipeline.py`. 필요 시 동일 책임의 작은 helper를 기존 automation/execution owner에 둔다. 새 service와 크기 허용량은 만들지 않는다.

1. 같은 case/input/generation의 두 후보, rule/model 동시 소비, owner/profile/policy 변경, 취소·재시작 SUBMITTING을 실제 SQLite RED로 재현한다.
2. worker는 후보만 기록한다. 사건당 물리 신규 제출 1회와 원자적 단일 소비·최종 상태를 원장에 결속하고, loop 한 곳이 rule/model 중 하나를 제출한다. 알려지지 않은 시도는 재제출하지 않는다.
3. 현재 원장이 저장한 profile/budget와 generation을 사용하며 새 관측·프로파일 선택/복귀가 물리 한계를 초기화하지 않는지 확인한다. 기존 generic case/모델/관측 예산을 action으로 가장하지 않는다.
4. 사람 claim·stale·정상 상태·CORE 이미 복구 중·다른 사건에서는 후보 소비/제출을 거절한다. default runtime에는 새 제출 경로가 열리지 않는다.
5. loop가 ready/inflight/missing/rejected/stale를 구분하는 시험을 먼저 만든다. 적격 inflight에만 CORE 남은 ASKING 시간보다 짧은 고정 대기 상한을 적용하고 만료·누락·거절은 기존 규칙으로 처리한다. 기존 `pipeline.ai_hold`는 유지하며 typed 모델 후보는 별도 명시적 검증 seam을 통과한다. legacy PENDING/UNKNOWN과 사람 WAITING_CONSOLE 처리를 회귀에 포함한다.

### 선행 CORE 수정과 실제 적용 경계

Modify: `middleware/control/drive/behaviors/line_follow/recovery/stuck/stuck_recovery.py`, `stuck_wiring.py`; Test: `middleware/core/services/test/test_line_stuck_recovery.py`, `middleware/core/gateway/test/test_line_follow_stuck_api.py`; Contract: D-407 및 API reference.

먼저 BACKING/SETTLING 중 늦은 BACK_AND_RETRY가 시도 수와 타이머를 다시 시작하는 RED를 console/ask_timeout 두 출처에서 재현하고 거절한다. 이어 모델의 expected phase/episode를 기존 API 경계와 manager lock 안에 결속한다. Fleet의 조회 후 CORE가 local fallback을 시작하는 실제 경쟁을 재현하고 모델 제출을 거절한다. 기존 사람 WAIT/ABORT와 수동 답의 호환성을 유지하며 새 필드가 필요하면 API reference·schema·소비자를 같은 변경에서 갱신한다.

## Task 2: 실제 공통 JSON 후보와 운영 수용 결속

Read/modify: `operations/decision/src/rosy/decision/model_tool_catalog.py`, `deliberation/__init__.py`, `deliberation/contracts/judgment.py`, 관련 profiles/schema/CLI codecs, `learning/registry/policy/reasoning_registry.py`, root `tools/incident_reasoning.py`. 기존 receipt 구현은 `operations/fleet/fleet/incidents/automation/ledger/receipt.py`, SDK 사건 계약은 `contracts/learning/src/rosy/contracts/learning/incident_rule.py`, `incident_profiles.py`, `incident_handoff.py`다. `incident_model.py`는 현재 없으며 공통 계약이 필요하면 Create 경로로 명시한다.

1. 현행 tools/choices로 물리 후보를 표현할 수 없는 RED와 속도/거리/주소/토큰/다른 사건의 입력 거절을 작성한다.
2. 첫 후보는 기존 BACK_AND_RETRY 하나에 해당하는 닫힌 choice/tool 계약이다. 모델 파라미터가 physical 거리·속도나 endpoint를 결정하지 않는다. 현재 사건의 trusted 근거와 generation/input을 결속한다.
3. 동일 profile의 검수 정답·보정과 signed 운영 수용이 모두 필요한 admission을 구성한다. 없음/폐기/자료 누락은 읽기·제한 reviewer 또는 최종 인수로 남기며 자기 확률·합의로 허가하지 않는다.
4. 공통 receipt 확장 시 `contracts/learning/pyproject.toml`, `operations/fleet/setup.py`, `.github/workflows/ci.yml`, `middleware/execution/local/pyproject.toml`과 원장 exporter/독립 소비자를 같은 SDK revision으로 맞춘다. 실제 설치 artifact 및 source-less import를 검증한다.
5. 새 운영 receipt kind를 기존 reasoning_calibration과 분리한다. trusted 검수 principal·full profile/model/domain·calibration digest·action/policy revision·site installation identity·독립 품질/coverage를 정확히 결속한다. 미서명·폐기·다른 설치·PASS_OFFLINE_ONLY로는 물리 후보를 수용하지 않는 RED를 추가한다.

## Task 3: 기존 실제 제출·응답·성공 확인

D-724의 전달 경계는 `fleet/swarm/transport.py::line_stuck_decision`의 선택적 async `before_submit`이다. 조건부 BACK의 지원 확인 GET이 성공한 뒤, POST 입구 직전에 호출한다. 기존 단일 loop의 최종 검증·durable claim을 이 포트에 연결하고, False/오류/취소·미지원 CORE는 POST하지 않는다. 포트 자체는 운영 수용이나 물리 claim 구현이 아니다. signed 운영 receipt → 동일 DB의 사건 단일 claim → pinned dispatcher/ready·inflight·missing·rejected·stale 선택 → 이 제출 포트 → ACK/UNKNOWN/실제 결과 순서로 연결한다. current self probability나 항상 HOLD인 operational_comparison을 수용으로 바꾸지 않는다.

Read/modify: 기존 `fleet/stuck/loop.py::_answer`, `lane_lost.py`, `closed_loop.py`, `automation/closure.py`, `tools/incident_model_feedback.py`와 사건/규칙 inventory·독립 비교. 기존 API reference의 `/api/v1/line-follow/stuck/decision`과 D-407 안전 계약을 사용한다.

1. fresh token/owner/사건·법칙·예산을 await 전후 검증하고 현장 gate가 거절할 때 모델 합의로 완화하지 않는 시험을 추가한다.
2. 후보 기록·제출 시작·CORE back ACK·후속 정상 관측을 별도 receipt로 기록한다. ACK·read-only 관측은 실제 model action 성공이 아니다.
3. timeout/cancel/disconnect/restart UNKNOWN에서 재전송 없이 최종 인수와 요약을 연결한다. 재시작 후 owner가 바뀐 사건에 stop/취소를 보내지 않는다.
4. 정상 상태의 0후보/0제출/0모델 호출, 다른 사건의 조치 0건, 관측 부족·위험 누락 0건을 수용 세트에서 확인한다. 원본 final cmd_vel의 여섯 축 검증과 actor/case/generation·수집 창의 연속성은 별도로 결속한다.
5. await 이후 durable physical claim 직전에 운영 수용·보정·현재 trust를 재검증한다. 승인 revision/epoch와 claim을 원자적으로 결속하고, 제어된 이벤트로 폐기가 claim보다 먼저/나중인 두 순서를 시험한다. 선행 폐기는 거절하고 이미 제출 중인 시도는 UNKNOWN을 유지한다. 설치 변경·재시작·human claim에도 재제출하지 않는다.

## Task 4: 독립 검증·병합·실제 수용

1. 커밋 HEAD를 기존 `tools/remote/remote_pytest.py`로 적격 PC에 보내고 고정 로그에 남긴다. `python test/known_failures.py <log>`에서 NEW를 해결한다. 노트북 pytest는 사용하지 않는다.
2. 독립 review와 실제 source-less wheel/sdist·CORE 경계/legacy resolver 회귀 후 승인된 local landing을 한다. FULL CI와 push·배포는 별도 증거다.
3. 실제 운영 receipt·고정 profile/모델·설치 trust와 runtime readback을 확보한다. 기존 실제 모델 시험 소비 표식은 유지하며 허용된 1건/1회·1024 출력 토큰/30초/무재시도 밖의 호출을 하지 않는다.
4. 팀이 정답/한계를 검수하고 Pinky 현장 관측→후보→CORE 응답→최종 출력→새 정상 근거까지 확인한다. E-stop을 해제하거나 motion으로 guard를 억지로 통과시키지 않는다. Discord는 담당 세션의 기존 최종 인수 인터페이스를 사용한다.

## 완료 기준과 후속

첫 backend의 source·시험·runtime·현장 증거를 분리한다. 현장 확인이 없으면 코드가 통과해도 전체 목표는 ACTIVE다. door/arm backend, 자동 실패 분류·검수 label 수용·training/새 후보 독립 비교·승격/복귀도 전체 목표에 남아 있다. 이 계획은 완료나 runtime activation이 아니다.
