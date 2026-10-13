# D-657 원장 모델 어댑터와 순수 실행 규칙 분리 검증

시작 `063676cbcb`, branch `refactor/judgment-adapter-extraction`. [D-657](../adr/D-657-judgment-adapter-and-pure-execution-extraction.md)은 D-648 단계 2와 단계 3 첫 계산 단위만 수용한다. 공유 main의 후속 D-656 책임·권한 계약과도 같은 경계다. 다른 workflow 상태 전이/복구 추출과 단계 4는 미구현 후속이다.

## 소스와 소비자

| 변경 | 실제 범위와 보존 조건 |
|---|---|
| `rosy.decision.tool_dispatch` → `fleet.server.model_feedback_dispatch` | 423줄 모듈 byte 동일 Git rename 100%. trusted scope·journal·egress·최신 frame·stop/generation/watermark·동일 proposal transaction 보존 |
| `fleet.server.goal_evidence` → `rosy.execution.site.goal_evidence` | 181줄 모듈 byte 동일 Git rename 100%. GoalPredicate/GoalEvidence/exception·검증 함수 보존. producer 인증·새 post-action frame/attempt·원장 재검사는 기존 Fleet service/store에 유지 |
| `rosy.execution.site.workflow` | 기존 `_timestamp`, `_freshness` AST 동일; 15초/2초 상수와 step-state mapping 동일. ACTION_SUCCEEDED는 AWAITING_GOAL_EVIDENCE이며 GOAL_CONFIRMED만 COMPLETED. store 전이/claim/transport 없음 |
| 실제 소비 | mission_service/store, goal_evidence_service, mission_progress, dispatcher/goal/provenance/service/replay 시험과 두 conftest 갱신. 기존 Python module shim 없이 canonical import 사용 |
| 설치 | Fleet metadata는 기존 `rosy-execution==0.1.0` dependency. execution은 자체 wheel로만 제공; Fleet wheel의 `rosy/execution/` 중복 설치 금지. Fleet sdist 외부 dependency도 같은 execution wheel을 사용 |
| source image | 기존 execution source COPY/allowlist와 별도 source bootstrap을 동반 갱신. packaged SOURCE_ROOTS/빌드 helper는 execution을 추가 포장하지 않음. 기존 assessment 3파일 closure 유지 |

독립 reviewer `safety_structure_review`가 시작 SHA→`fb2e5e07d3`의 실제 Git blob·AST·호출자를 읽고 소스 검토를 승인했다. 기존 MissionProgressService 호출을 원래 mapping으로 복원하면 class AST가 동일하고 세 Fleet 목표 소비자는 import만 바뀐 것을 대조했다. 현재 선택한 경로는 Safety tag/anchor가 아니며 CORE/OMX writer·Safety-tagged 경로를 변경하지 않았다. 크기 기준/예외/known_failures 목록도 확대하지 않았다.

## 원격 실행

- RED `b7cef606ee`: 새 canonical module·순수 규칙·wheel/sdist/source image 누락으로 **14 failed**. known_failures도 **14 NEW**로 보고했으며 예상 TDD 실패를 기존 실패로 분류하지 않았다.
- GREEN `fb2e5e07d3`: **212 passed, NEW 0**, terminal exit 0. 순수 import·상태/시각 경계, 기존 dispatcher·model tool journal·provider conformance·Mission 후보/feedback·goal/service/store·Mission service/progress/provenance/store·cell replay와 wheel/sdist/source image·모듈 크기·Safety 분리 시험을 함께 실행했다.
- harness lint: **0 errors, 23 warnings**. warning은 기존 last_verified 등의 gate 기록이며 새로운 수용 증거가 아니다.

원시 로그는 X 관리 세션 `2026-10-11--200411--judgment-adapter-extraction--baf49d`의 `logs/red/run-1.txt`, `logs/green/run-1.txt`에 보존한다. 시험 host는 remote runner가 자원 floor를 확인해 선택했고, 노트북 pytest는 실행하지 않았다. source image 결과는 Docker COPY fixture에서 실제 생산 import와 동일 클래스 소비를 검증한 것이며 실제 Docker build 성공으로 집계하지 않는다.

## 착지와 남은 gate

최신 main 통합 후 `tools/land.py --tests auto`의 원격 terminal 결과와 actual main/land record는 별도 후속 receipt로 기록한다. 초기 GREEN을 최신 main 검사나 FULL CI로 집계하지 않는다. push, 배포, 운영 판단/모델 routing 활성화, 실제 로봇·Arm·문 동작 및 현장 정확도는 이번 변경의 수행/수용 범위에 포함하지 않는다.
