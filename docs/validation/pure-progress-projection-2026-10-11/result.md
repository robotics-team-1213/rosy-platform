# D-657 전체 progress 계산과 단독 import 보완 검증

변경 유형: 소스 책임 분리 및 설치 의존성 보완. 증거 수준: SOURCE, committed HEAD 원격 계약/설치 검증. 검토 대상 소스 `4ed2975f3`, branch `refactor/pure-progress-projection`; 시작 main `342a72f479`.

## 변경과 보존 경계

책임 분리 세션 `d942b265bf`의 전체 `project_progress` 계산·Fleet adapter·기존 foundation pin만 가져왔다. D-660~D-662 기능과 동료의 미커밋 schema는 가져오지 않았다. workflow의 schema import만 계산 호출 내부로 이동해 stdlib helper 단독 import를 보존한다. `mission_step_state`를 재사용하며 상태 mapping을 중복하지 않는다.

독립 reviewer `safety_structure_review`는 기존 Fleet snapshot 계산과 새 project_progress 본문을 AST로 대조했다. 이동한 import 외 계산은 동일하며 timestamp/freshness/step helper와 Fleet의 init/events/model_context도 동일하다. snapshot은 한 번의 store 조회와 주입 clock 한 번을 유지하며 missing mission에서는 clock을 호출하지 않는다. GoalEvidence·dispatcher·공유 schema Git blob은 그대로다. producer 인증·원장/claim/fence·transport·CORE/OMX writer는 유지하며 `stop.physical_state=UNKNOWN`을 보존한다. Safety-tagged/anchor 경로는 변경하지 않았다.

## 원격 실행

- 설치 준비에서 기존 execution dependency의 `core-common` 누락을 원격 `pip check`로 확인했다. CI wheel build 목록에 기존 foundation을 포함했고 remote runner의 같은 CI 입력 wheel 설치와 `pip check`가 성공한 뒤 시험을 실행했다. GitHub CI를 실행했다는 뜻은 아니다.
- RED `0a54ef6f8`: 기존 격리 시험 **1 failed / 1 NEW**, `pure execution imported core_common`로 eager import 문제를 재현했다. known_failures에 추가하지 않았다.
- GREEN `4ed2975f3`: **97 passed / NEW 0**, terminal exit 0. 단독 import·시각/step 경계, 실제 wheel/self-contained Fleet sdist에서 Fleet 없이 먼저 import한 후 전체 projection 호출, 동일 GoalEvidence identity·별도 execution 배포·source-image COPY closure, Mission progress/provenance/OMX phase와 모듈 크기/Safety 분리를 함께 검증했다.
- harness lint: **0 errors / 23 warnings**. 기존 warning은 별도 검증 기록의 상태이며 새 FIELD 증거가 아니다.

원시 로그는 X 관리 세션 `2026-10-11--223323--pure-progress-import--c132e2`의 `logs/red-import/run-1.txt`, `logs/green/run-1.txt`에 보존한다. 노트북 pytest는 실행하지 않았다. source-image 검증은 COPY fixture의 생산 import 확인이며 실제 Docker build 증거가 아니다.

## 남은 관문

최신 main 착지의 최종 후보 SHA·원격 terminal 결과·실제 main/land record는 관리 세션의 별도 export receipt로 기록한다. FULL CI, 실제 Docker build, push·배포, 팀 채널 수신/인수, 독립 현장 정답/한계, provider 활성화와 장치/FIELD 수용은 이번 수행 범위에 포함하지 않는다. 배포 시 Fleet와 갱신된 execution/foundation wheel을 함께 공급해야 한다.
