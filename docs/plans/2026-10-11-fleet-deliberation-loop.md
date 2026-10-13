# Fleet Deliberation Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** World/목표 기반 문제를 규칙·사례·전문 모델·복수 모델 숙고로 라우팅하고 비실행 후보와 실제 결과를 독립 평가·지속 개선으로 연결한다.

**Architecture:** 기존 `rosy.decision`에 유한 숙고 런을 추가하고 Fleet 사건/후보/feedback 원장과 연결한다. CLI adapter는 제한된 추론만 수행하고 Fleet admission과 CORE/OMX writer는 기존 소유자에 남는다. 첫 연결은 출력 미적용 보고/후보 전용이다.

**Tech Stack:** 기존 Python, httpx/pydantic, Fleet 저장소, 기존 remote pytest; Claude Code/OpenCode의 설치된 CLI/구조화 프로토콜은 별도 adapter 스모크로 고정.

**Status:** D-640 Accepted (2026-10-12), 후보 전용 source 구현. [실제 파일·책임·검증 상태](2026-10-12-decision-deliberation-boundary.md)를 우선한다. 실제 provider/배포/FIELD는 HOLD다. 아래 원래 작업 순서의 단일 파일 예정명은 `deliberation/{__init__,cli}.py` 하위 패키지로 구체화했다.

**사용자 추가 지시:** Discord 제외 나머지 소스를 먼저 진행한다. Task 1/2 source와 Task 3 fixed translator, Task 4 advisory journal, Task 5 offline 비교는 구현했다. 실제 launcher 격리/CLI smoke, 운영 사건 연결·독립 현장 정답과 실제 모델 비교는 미완료다. 원래 현장 receipt 관문은 활성화·승격에 유지한다.

**선행 조건 (2026-10-11 사용자 추가 지시):** [Fleet 중앙 판단 단계 계획](2026-10-11-fleet-central-judgment-stages.md)의 D-647에서 공통 판단 책임·초기 배포를 먼저 결정한 뒤 D-642~D-646을 수행한다. 근거/현재 상태, 개입·비개입·판단 보류, 중앙 조치/결과, 외부 알림·사람 처리, 독립 수용 receipt가 준비될 때 이 계획의 모델 라우팅/토론 구현 관문을 연다. 정상/비개입도 평가 분모에 포함한다. 선행 문서 계약 통과는 런타임 수용 완료가 아니다.

## 1. 내부 런 계약과 의미 검증

**구조 관문:** [D-648 분리 계획](2026-10-11-shared-judgment-structure.md)의 수용 결과를 먼저 반영한다. Situation 필요성 평가와 기존 도메인 owner의 빠른 규칙/사례를 재구현하지 않는다. 아래 Decision supervisor는 미해결/불확실 문제의 모델 선택·유한 토론을 맡으며 원장 도구 중재는 Fleet site 어댑터다.

Create: `operations/decision/src/rosy/decision/deliberation.py`.
Test: `operations/fleet/test/test_deliberation.py`.
Reuse: `candidate.py`, `decision_pipeline.py`, `model_tool_contract.py`, D-619 `core_common.protocol.situation` validator.

먼저 문 장애·암 대상 누락의 유효/무효 fixture와 허위 verified/알 수 없는 근거/새 실행 명령/다른 사건 binding 거절 시험을 쓴다. 테스트 커밋을 원격으로 보내 실패를 확인한 뒤 최소 frozen 런/의견 타입과 validator만 구현한다. identifier를 새 device grant로 사용하지 않는 단언을 넣고 구현 커밋을 원격 재검증한다. 공개 wire를 변경하는 경우에만 API Reference와 공통 schema를 같은 커밋으로 고친다.

## 2. 유한 supervisor와 결정론적 종료

Modify: `operations/decision/src/rosy/decision/deliberation.py`.
Test: `operations/fleet/test/test_deliberation.py`.

fake clock/adapter로 공통 목표/관측/제약 입력, 익숙한 문제의 규칙/검수 사례, 전문 모델 선택, 미지/불확실 문제의 숙고 라우팅을 먼저 시험한다. 두 독립 초기 의견, 한 번 반론 반영, 최대 세 호출, 문제당 활성 런 하나, timeout/기권/상충/stop/세대 변경 거절 시험을 커밋·원격 실행한다. 모델 다수결 없는 결정론 선택과 HOLD/fallback을 구현한다. 큐 한계·불명 provider 결과·SDK retry 예산·과부하 거절·취소 자식 프로세스·재시작 조정 시험을 추가한다. 전역 시간을 호출별로 초기화하지 않는다.

## 3. 제한된 provider 실행기

Create: `operations/decision/src/rosy/decision/cli_deliberation.py`.
Test: `operations/fleet/test/test_cli_deliberation.py`.
Read: `operations/decision/src/rosy/decision/er2_standard.py`, `model_tool_contract.py`, `model_tool_catalog.py`, `deploy/site/AGENTS.md`와 실제 서비스 설치 스크립트.

고정 argv와 stdin/구조화 stdout adapter를 프로세스 fake로 먼저 시험한다. shell 문자열 실행, workspace/model 출력으로 argv 확장, 자동 provider fallback은 사용하지 않는다. 설치된 실행기의 help/version과 인증 방법을 확인한 뒤 Claude Code와 OpenCode 각각 최소 adapter를 구현한다. JSON schema만으로 semantic 검증을 대체하지 않는다. 비정상 exit/부분 출력/oversize/실패 JSON/비용 불명/취소/권한 prompt 대기를 거절한다.

provider 프로파일 미설정은 호출 불가다. 셸/쓰기/MCP/배포/장치 호출 금지와 사용자 설정·hooks·메모리 비상속을 전용 계정에서 확인한다. OS 파일·네트워크 격리와 Fleet 자원 reserve를 배포에 적용할 때 해당 실제 설치 파일과 테스트를 확정한다. 외부 전송은 승인된 최소 자료로만 제한한다. 실제 GLM provider/model ID는 이 단계에서 조회하며 후보명을 API ID로 추정하지 않는다.

## 4. Fleet 사건과 비실행 후보/결과 연결

Read/extend: `operations/situation/rosy_situation/incidents/context.py`, `operations/fleet/fleet/server/model_feedback_dispatch.py`와 기존 Fleet incident/Mission turn journal 소비자.
Test: `operations/fleet/test/test_deliberation_journal.py` (new), 기존 `test_mission_feedback_loop.py`, `test_model_tool_call_journal.py`, `test_mission_model_turn_store.py`.

먼저 기존 서비스 호출자를 `rg`로 찾아 연결 위치를 확정한다. durable 시작/의견/최종 후보/거절/종료를 기존 사건과 연결하고 중복·내용 변경·원장 장애·재시작을 시험한다. 모델 출력은 새로운 임의 tool 호출을 만들지 않으며 첫 버전은 출력 미적용이다. 후보 접수·Action terminal·goal evidence를 따로 기록한다. 실제 장치 재개 연결은 기존 정책·Safety 리뷰·장치 관문이 준비된 후속 변경이다.

## 5. 사건 정답과 비교 평가

Reuse: `learning/curation/perception/incident_feedback.py`, `tools/decision_replay.py`, D-527 모델 PC 평가 절차.
Create only if existing replay cannot express bounded transcripts: `learning/evaluation/decision/deliberation_replay.py`; 해당 holder 등록은 구현 전에 D-427 매니페스트와 child 지침으로 확인한다.
Test: `operations/fleet/test/test_deliberation_replay.py` (new, ROS/GPU-free fixture only).

exact incident/녹화 lineage, 사람 검토 상태, 학습/평가 세션 분리와 동일 사건 세트 hash를 확인한다. 규칙/단일 모델/숙고 비교의 위험 후보·기권·오류·p95·비용 분모 시험을 먼저 쓴다. 모델 PC 실제 정답 재생에서 후보별 결과 receipt를 낸다. 문제 유형별 모델 선택과 검수 사례 재사용 전제, 새로운 문제의 개선과 과거 문제 회귀를 평가한다. 사건 원인이 지도/보정/구동이면 해당 소유자 교정으로 보낸다. 평가 한계·건수·독립 정답 미확정은 승격 HOLD다.

## 검증 및 인수

각 테스트 추가/구현 단계는 소유 파일만 커밋한 HEAD를 원격으로 보낸다. 문서와 코드가 실제로 달라진 뒤에 필요한 시험만 수행한다.

```powershell
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<session>/logs/contracts -- operations/fleet/test/test_deliberation.py operations/fleet/test/test_cli_deliberation.py operations/fleet/test/test_deliberation_journal.py operations/fleet/test/test_deliberation_replay.py operations/fleet/test/test_mission_feedback_loop.py operations/fleet/test/test_model_tool_call_journal.py operations/fleet/test/test_mission_model_turn_store.py
python test/known_failures.py X:/DevTemp/<session>/logs/contracts/run-1.txt
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

위 새 테스트는 작성되기 전 실행 가능한 suite가 아니다. 동일 basename suite는 별도 invocation으로 둔다. notebook pytest는 금지다. 시험 PC가 없으면 원격 runner의 대기/실패 결과를 보고하며 착지·push하지 않는다.

SOURCE/원격 계약, 실제 CLI 제한 스모크, 모델 PC 독립 품질, Fleet 설치/출력 미적용 readback, 장치 정지·복구·목표 증거, FIELD 재발 확인을 각각 기록한다. 런타임 허용 한계 위반 시 숙고 admission을 중단하고 이전 승인 프로파일/규칙/사람으로 복귀한다. main 착지·push는 별도 사용자 지시 뒤 수행한다.
