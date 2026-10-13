## D-648 공통 상황평가·Decision·작업 실행·Fleet 목표 소스 구조

**Status:** Proposed (2026-10-11). 사용자의 구조 구체화 요청에 따른 목표 책임·이행 제안이다. 실제 코드 이동, 새 판단 구현, 설치·서비스 분리·배포·장치 수용은 수행하지 않았다.

### Context
D-637의 소스 이동은 완료됐지만 `rosy.decision.tool_dispatch`는 Fleet proposal store 예외와 Mission 서비스를 참조한다. 현재 `rosy.execution.site`는 submission·authority projection과 item-pose 검증을 제공하며 전체 Mission 운영 원장이나 실행기를 소유하지 않는다. World는 관측 참조·현재 MapPose projection이고 미래 행동 예측기는 없다. Situation의 `stuck_scene`은 사실과 제한된 기존 stuck 제안을 별도 출력하므로 모든 Situation 출력이 사실이라고 요약해서는 안 된다.

D-647의 잠정 B안을 구체화한다. 공통 판단은 Fleet DB나 로봇에 직접 접근하지 않아야 하지만 작업·자원 수락에는 기존 소유자의 판단과 transaction이 필요하다. 단일 암 셀·단일 로봇·다중 로봇·Mission 없는 관측에 같은 평가 의미를 적용하되 모든 사례에 Fleet coordination을 강제하지 않는다.

### 제안
1. **World는 상태, Situation은 상황평가, Decision은 대안 후보를 맡는다.** 공통 개입 필요성·비개입·보류 평가의 목표 holder는 `operations/situation/rosy_situation/assessment.py`다. 신선한 상태·목표 진척 근거·제약·clock/정책 버전에서 근거를 가진 권고만 반환하는 ROS-free 순수 모듈로 시작한다. 기존 service/incident/analyzer는 I/O와 도메인 근거 생산자로 유지한다. 공개 facts envelope에 권고를 끼워 넣지 않는다.
2. **작업 오케스트레이션의 공통 의미는 기존 execution/site를 확장하는 방향으로 제안한다.** 목표 holder는 `operations/execution/src/rosy/execution/site/workflow.py`이며 상태 전이·진척/복구 선택의 순수 규칙부터 추출한다. 실제 Mission/Job/claim 저장소, HTTP/auth, generation fence와 device transport는 현재 Fleet 서비스의 Work Orchestration 어댑터에 유지한다. 소스 holder를 바꾼다고 원장 소유·DB·실행 권한을 옮기지 않는다. 두 번째 범용 Orchestration 서비스나 Mission 실행기는 만들지 않는다.
3. **Fleet coordination은 로봇 집합에 필요한 배정·교통·협업 판단을 맡는다.** 기존 `formation`, `swarm`, `traffic`, `routing`과 robot roster 소비를 유지한다. `fleet.server`의 이름은 현재 설치·serving 경계이며 그 안의 Mission/Job 업무를 모두 Fleet coordination 의미로 부르지 않는다. 셀·문·컨베이어 자원을 자동으로 로봇 교통 자원에 합치지 않는다.
4. **저장소를 쓰는 모델 도구 중재는 site 어댑터다.** `rosy.decision.tool_dispatch`의 목표 위치는 `operations/fleet/fleet/server/model_feedback_dispatch.py`다. 이미 존재하는 provider-neutral tool 계약·catalog와 Decision 후보는 재사용한다. Fleet store 예외·claim·stop/fence 검사는 어댑터에 남기고 Decision 핵심의 Fleet import를 제거한다. 이 이동은 D-637 다음의 책임 보완 제안이며 수용·회귀 검증 전 현재 namespace를 바꾸지 않는다.
5. **배포는 우선 현재 경계를 유지한다.** 공통 assessment 설치/가용성은 기존 Situation 전체 서비스의 설치와 별도로 검증하며 Fleet 소비자에 필요한 source closure만 제공한다. Decision은 Fleet 배포에 유지하고 execution의 기존 wheel을 재사용한다. AI PC service·Fleet PC 모델 runner·모델 PC 학습/평가는 호스트 역할대로 유지한다. 별도 소비자·자원 경합·장애 격리의 실증과 지연 예산이 있을 때만 독립 서비스 계약을 연다.
6. **비개입·알림·학습을 같은 사건/결과 경계에 연결한다.** 권고만으로 조치나 알림이 생성되지 않는다. 현재 owner가 최신 상태·권한을 재검사한 뒤 기록·조치·알림 outbox를 기존 transaction에 연결한다. 정상 비개입은 추가 장치 요청/신규 문제 알림 zero-send, 근거 부족은 보류·재관측·필요한 담당자 상승으로 구별한다. Discord/Slack/Telegram은 같은 사건의 인증된 사람 처리 진입점이며 장치 writer가 아니다. 실제 결과와 독립 정답을 learning에 전달하고 모델 합의·ACK로 완료 또는 정책 승격을 판정하지 않는다.

### 의존과 이행 관문
World·공통 assessment·Decision 핵심·순수 workflow/검증은 `fleet`, `core`, `rclpy`, DB, HTTP service와 device transport를 import하거나 변경하지 않는다. 실행에 필요한 I/O 어댑터는 이러한 핵심을 소비하는 방향이다. provider/영상 I/O는 기존 어댑터 파일에서 수행하며 모든 Decision 파일을 무조건 pure로 분류하지 않는다. 각 모듈의 참조 형식과 import/설치 closure는 producer/consumer와 함께 검증한다.

단일 셀·로봇·다중 로봇·Mission 없는 관측의 사례표, 순수 평가/원장 어댑터 의존 검사, 비개입 zero-call·stale/상충·경쟁/늦은 결과, 기존 API·SQLite·설치 호환을 단계별로 검증한다. 미래 World rollout·학습 가중치·범용 ResourceManager·새 외부 API를 이번 구조 작업에 추가하지 않는다. 정상 작업과 장치 정지 경로가 모델 토론을 기다리게 하지 않는다.

### 기존 계약과의 관계

| ADR | 관계 |
|---|---|
| D-427 | operations/middleware/learning 분류와 frozen ownership identity를 유지한다. 실제 이전 시 manifest layout·소비자·설치 입력을 함께 갱신한다. |
| D-429 | deliberative 후보와 조정·장치 실행 권한을 구별한다. 공통 assessment를 deliberative Decision으로 확대하지 않는다. |
| D-430 | CORE/OMX writer와 독립 Safety 검토를 유지한다. 코드의 safety-tagged 경계를 옮기거나 바꾸는 단계는 별도 독립 리뷰가 선행한다. |
| D-435 | 아직 Proposed인 목표 역할 구분을 구체화하는 보완이다. 현재 Accepted 실행 계약을 이 문서만으로 대체하지 않는다. |
| D-630·D-637 | 수용된 현재 폴더/설치 상태는 유지한다. tool dispatcher의 어댑터 재분류는 후속 Proposed 변경이며 소스 이동 완료를 취소하지 않는다. |
| D-647·D-642~D-646·D-640 | 0단계의 holder 후보·의존·사례를 구체화한다. 중앙 판단의 근거·비개입·원장·알림·수용이 모델 토론/개선의 선행 관문이다. |

목표 트리·사례·현재/목표 대응은 [설계](../plans/2026-10-11-shared-judgment-structure-design.md), 실제 파일별 분리 순서는 [계획](../plans/2026-10-11-shared-judgment-structure.md)을 따른다. Proposed 수용과 구현·설치·배포 증거는 각각 기록한다.

### 후속 제한 수용 기록 (2026-10-11)

D-652는 단계 0/1 내부 shadow만, [D-657](D-657-judgment-adapter-and-pure-execution-extraction.md)은 단계 2와 단계 3 첫 계산 단위만 수용한다. D-657의 dispatcher·목표 검증·진척 투영 분리와 기존 원장/권한 보존은 별도 [검증 기록](../validation/judgment-adapter-extraction-2026-10-11.md)을 따른다. 이 ADR의 전체 목표를 구현·배포 완료 또는 현장 수용으로 승격하지 않는다.
