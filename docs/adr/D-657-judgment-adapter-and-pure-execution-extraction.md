## D-657 모델 도구 Fleet 어댑터와 순수 목표·진척 규칙 분리

**Status:** Accepted (2026-10-11). 사용자의 후속 진행 요청으로 D-648 단계 2 및 단계 3의 첫 계산 단위를 수용한다. 소스·설치 책임만 분리하며 운영 활성화·배포·현장 수용을 뜻하지 않는다.

### 결정

`rosy.decision.tool_dispatch` 구현을 `fleet.server.model_feedback_dispatch`로 이전한다. 기존 catalog·provider-neutral 도구 계약·후보는 Decision에 유지하고 Fleet store 예외, journal, trusted scope, stop/generation/watermark 검사는 같은 dispatcher 코드에 남긴다. 실제 Python 호출자를 함께 변경하며 옛 module shim은 만들지 않는다.

Fleet의 순수 `goal_evidence.py` 구현은 `rosy.execution.site.goal_evidence`로 이전한다. predicate·증거 타입·frame provenance·문자열 및 시각 검증과 exception identity는 보존한다. `mission_progress.py`의 시각 해석·신선도·Mission 상태에서 step 상태로의 투영만 `rosy.execution.site.workflow`로 추출한다. DB 상태 전이, goal producer 인증, 새 post-action frame/attempt 확인, claim, stop/fence, transport와 실제 recovery는 Fleet의 기존 transaction/서비스에 유지한다. 상태 투영은 권고나 실행 허가가 아니다.

Fleet는 기존 `rosy-execution==0.1.0` wheel을 dependency로 사용한다. Fleet wheel에 execution 파일을 중복 설치하지 않는다. 소스 checkout과 site source image의 경로·COPY/allowlist를 실제 소비자와 함께 갱신한다. Fleet sdist의 외부 dependency는 기존 execution wheel로 공급한다. execution의 pure 두 모듈은 Fleet·DB·HTTP·ROS 없이 import/호출 가능해야 한다.

### 기존 계약과의 관계

| ADR | 관계 |
|---|---|
| D-427 | 기존 operations holder와 manifest root를 유지하며 설치 소비를 함께 검증한다. |
| D-429 | Decision 후보와 원장 결속 어댑터를 구별한다. 내부 Python 소비자를 일괄 갱신하며 옛 namespace shim은 추가하지 않는다. |
| D-430 | CORE/OMX writer와 Safety 책임을 유지한다. 선택한 이동 파일은 현재 safety tag/anchor가 아니다. tagged 경로까지 변경이 필요해지면 독립 리뷰/trailer 관문을 먼저 통과한다. |
| D-648 | 단계 2와 단계 3의 위 첫 단위만 수용한다. 전체 순수 workflow 상태 전이·복구 추출과 단계 4는 후속이다. |
| D-649·D-652 | Drive/CORE 권한과 내부 shadow assessment의 최소 설치 3파일 및 ABSTAIN 조건을 보존한다. |

### 검증

committed HEAD 원격 RED→GREEN, 기존 dispatcher/journal/fence/late result 및 goal/mission/progress 회귀, Decision→Fleet 의존 금지, pure execution 독립 import, checkout 밖 wheel/sdist의 동일 GoalEvidence 타입, source image closure와 ROS-free 구조 검사를 수행한다. 원격 결과·known_failures·local main 착지를 별도 기록하고 FULL CI·실제 Docker build·배포·물리 정확도를 통과로 집계하지 않는다.

파일별 순서는 [계획](../plans/2026-10-11-judgment-adapter-extraction.md)을 따른다.

### 후속 전체 progress 계산 분리

사용자가 책임 분리 구현 세션의 추가 추출과 이 세션의 import 경계 보완을 처리하도록 요청했다. 기존 전체 progress 계산도 `project_progress(data, now)`로 이전하되 `mission_step_state`, timestamp/freshness, 외부 wire 결과를 보존한다. Fleet는 snapshot transaction·clock·인증·원장/claim/fence를 계속 소유한다. wire schema는 projection 호출 시 불러오고 기존 foundation wheel을 명시 dependency로 선언한다. 순수 helper 단독 import에는 Fleet·DB·HTTP·ROS·wire schema package가 필요하지 않는다. 전체 상태 전이/복구와 D-660~D-662 기능의 구현·착지·활성화는 별도다. [후속 계획](../plans/2026-10-11-pure-progress-projection.md)에 설치와 검증 경계를 기록한다.
