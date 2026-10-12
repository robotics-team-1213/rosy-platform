# 모델 주도 제한 복구와 실제 결과 연결 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 모델의 수용된 제한 복구 후보를 기존 Fleet dispatch 한 곳으로 보내고, 원래 사건·예산을 유지하며 실제 결과와 최종 인수를 확인한다.

**Architecture:** Decision은 고정 JSON 후보, Fleet 사건 owner는 durable 후보/시도/결과, 기존 StuckResolverLoop는 단일 실제 제출, CORE는 기존 D-407 안전/최종 base 출력, Model PC는 독립 평가·수용 근거를 담당한다. 첫 backend는 기존 BACK_AND_RETRY 하나이며 door/arm은 해당 owner의 계약을 수용한 뒤 확대한다.

**Tech Stack:** 기존 ModelProfile/catalog/judgment, SQLite 사건/outbox·StuckResolverLoop·RobotClient, ros-free SDK receipt, 기존 원격 pytest/MCAP 검증과 독립 평가.

**Status:** Planned; source, runtime, model quality and field acceptance are incomplete. D-716 is Proposed for review; it grants no physical admission.

## 먼저 확인한 실제 빈칸

`deliberation.__init__.CHOICES`에는 물리 복구 선택이 없고 worker의 `_problem`은 reobserve/human만 공급한다. incident catalog에는 읽기 도구 하나만 있다. `_process`는 get_incident_status 외의 단계에서 NO_ADMITTED_READ_OR_REVIEW로 끝난다. StuckResolverLoop._answer는 이미 rule/AI 법칙·token·불명 결과를 다루지만 worker와 같은 물리 ownership을 공유하지 않는다. worker에서 직접 호출하는 빠른 연결은 rule/model 동시 전송 경쟁을 만들므로 사용하지 않는다.

## Task 1: 실제 후보·제출 소유권을 원장에 고정

Read/modify: `operations/fleet/fleet/incidents/automation/ledger/store.py`, `automation/execution/worker.py`, `automation/runtime.py`, `fleet/stuck/loop.py`, `fleet/stuck/pipeline.py`. 필요 시 동일 책임의 작은 helper를 기존 automation/execution owner에 둔다. 새 service와 크기 허용량은 만들지 않는다.

1. 같은 case/input/generation의 두 후보, rule/model 동시 소비, owner/profile/policy 변경, 취소·재시작 SUBMITTING을 실제 SQLite RED로 재현한다.
2. worker는 후보만 기록한다. 사건당 물리 신규 제출 1회와 원자적 단일 소비·최종 상태를 원장에 결속하고, loop 한 곳이 rule/model 중 하나를 제출한다. 알려지지 않은 시도는 재제출하지 않는다.
3. 현재 원장이 저장한 profile/budget와 generation을 사용하며 새 관측·프로파일 선택/복귀가 물리 한계를 초기화하지 않는지 확인한다. 기존 generic case/모델/관측 예산을 action으로 가장하지 않는다.
4. 사람 claim·stale·정상 상태·CORE 이미 복구 중·다른 사건에서는 후보 소비/제출을 거절한다. default runtime에는 새 제출 경로가 열리지 않는다.

## Task 2: 실제 공통 JSON 후보와 운영 수용 결속

Read/modify: `operations/decision/src/rosy/decision/model_tool_catalog.py`, `deliberation/__init__.py`, `deliberation/contracts/judgment.py`, 관련 profiles/schema/CLI codecs, `contracts/learning/src/rosy/contracts/learning/incident_model.py`, `learning/registry/policy/reasoning_registry.py`, root `tools/incident_reasoning.py`.

1. 현행 tools/choices로 물리 후보를 표현할 수 없는 RED와 속도/거리/주소/토큰/다른 사건의 입력 거절을 작성한다.
2. 첫 후보는 기존 BACK_AND_RETRY 하나에 해당하는 닫힌 choice/tool 계약이다. 모델 파라미터가 physical 거리·속도나 endpoint를 결정하지 않는다. 현재 사건의 trusted 근거와 generation/input을 결속한다.
3. 동일 profile의 검수 정답·보정과 signed 운영 수용이 모두 필요한 admission을 구성한다. 없음/폐기/자료 누락은 읽기·제한 reviewer 또는 최종 인수로 남기며 자기 확률·합의로 허가하지 않는다.
4. 공통 receipt 확장 시 `contracts/learning/pyproject.toml`, `operations/fleet/setup.py`, `.github/workflows/ci.yml`, `middleware/execution/local/pyproject.toml`과 원장 exporter/독립 소비자를 같은 SDK revision으로 맞춘다. 실제 설치 artifact 및 source-less import를 검증한다.

## Task 3: 기존 실제 제출·응답·성공 확인

Read/modify: 기존 `fleet/stuck/loop.py::_answer`, `lane_lost.py`, `closed_loop.py`, `automation/closure.py`, `tools/incident_model_feedback.py`와 사건/규칙 inventory·독립 비교. 기존 API reference의 `/api/v1/line-follow/stuck/decision`과 D-407 안전 계약을 사용한다.

1. fresh token/owner/사건·법칙·예산을 await 전후 검증하고 현장 gate가 거절할 때 모델 합의로 완화하지 않는 시험을 추가한다.
2. 후보 기록·제출 시작·CORE back ACK·후속 정상 관측을 별도 receipt로 기록한다. ACK·read-only 관측은 실제 model action 성공이 아니다.
3. timeout/cancel/disconnect/restart UNKNOWN에서 재전송 없이 최종 인수와 요약을 연결한다. 재시작 후 owner가 바뀐 사건에 stop/취소를 보내지 않는다.
4. 정상 상태의 0후보/0제출/0모델 호출, 다른 사건의 조치 0건, 관측 부족·위험 누락 0건을 수용 세트에서 확인한다. 원본 final cmd_vel의 여섯 축 검증과 actor/case/generation·수집 창의 연속성은 별도로 결속한다.

## Task 4: 독립 검증·병합·실제 수용

1. 커밋 HEAD를 기존 `tools/remote/remote_pytest.py`로 적격 PC에 보내고 고정 로그에 남긴다. `python test/known_failures.py <log>`에서 NEW를 해결한다. 노트북 pytest는 사용하지 않는다.
2. 독립 review와 실제 source-less wheel/sdist·CORE 경계/legacy resolver 회귀 후 승인된 local landing을 한다. FULL CI와 push·배포는 별도 증거다.
3. 실제 운영 receipt·고정 profile/모델·설치 trust와 runtime readback을 확보한다. 기존 실제 모델 시험 소비 표식은 유지하며 허용된 1건/1회·1024 출력 토큰/30초/무재시도 밖의 호출을 하지 않는다.
4. 팀이 정답/한계를 검수하고 Pinky 현장 관측→후보→CORE 응답→최종 출력→새 정상 근거까지 확인한다. E-stop을 해제하거나 motion으로 guard를 억지로 통과시키지 않는다. Discord는 담당 세션의 기존 최종 인수 인터페이스를 사용한다.

## 완료 기준과 후속

첫 backend의 source·시험·runtime·현장 증거를 분리한다. 현장 확인이 없으면 코드가 통과해도 전체 목표는 ACTIVE다. door/arm backend, 자동 실패 분류·검수 label 수용·training/새 후보 독립 비교·승격/복귀도 전체 목표에 남아 있다. 이 계획은 완료나 runtime activation이 아니다.
