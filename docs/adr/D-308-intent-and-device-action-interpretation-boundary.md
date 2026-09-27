## D-308 의도 해석과 장치별 Action 해석의 책임을 분리한다

**Status:** Accepted (2026-09-27, 의미·소유권·검증 기준에 한정). 새 Mission API, 공통 Device Action wire schema, 통역기 프로세스, OMX·드론 운영 capability 또는 물리 안전 승인을 뜻하지 않는다. D-293 Decision 2의 Fleet interpreter/ledger 적용 범위를 명확히 하고 D-290·D-296·D-305의 경계를 구체화하며 기존 경로의 호환 계약을 변경하지 않는다.

**Context:** 사용자는 화면·음성·대화로 “어디로 이동해 무엇을 하라”는 목표를 말할 수 있다. 장치는 Pinky 주행, 고정 OMX 팔, 장래 드론처럼 실행 방법과 안전 상태가 다르다. `core_common.intent.interpret()`는 현재 고정 동사를 REST 경로로 고르는 공유 문법이다. Fleet `/api/fleet/do`와 CORE `/api/v1/do`가 함께 사용한다. Fleet의 `navigate`는 `task_service`가 구성된 경우에만 durable task service를 경유하고, 그 밖의 경로는 직접 호출한다. `steps` 1~8개는 선검증 뒤 순서대로 호출되며, 앞 단계의 물리 효과를 되돌리거나 각 단계의 최종 완료를 기다리는 Mission/Step 실행기가 아니다. 뒤 단계에서 예외가 나면 앞 단계가 이미 실행됐어도 전체 HTTP 오류로 응답해 앞 단계의 `steps` 결과도 누락될 수 있다. D-293의 “Fleet은 인터프리터이자 작업 원장”을 현행 모든 `do` 호출이 durable Mission이라는 뜻으로 읽으면 접수와 목표 달성을 혼동한다.

**Decision:**

1. **해석을 세 경계로 나눈다.** 화면·음성·AI의 문장 해석은 출처·시각·대상·제약이 붙은 *실행권 없는 Intent 후보*를 만든다. 후보 생성자에게 현재 `/api/fleet/do`를 즉시 실행할 operator credential을 주지 않는다. 사용자 제출 시 서버가 operator principal을 새로 인증하며 후보 텍스트의 actor/source나 모델 confidence를 권한으로 신뢰하지 않는다. 대상·좌표계가 모호하거나 capability가 stale이면 명확화 또는 HOLD로 둔다. 사이트 Fleet의 의미 해석은 인증된 요청의 권한, 대상, capability, 좌표계·단위, 상태와 목표 달성 조건을 검증해 사이트 작업으로 수용할지 판단한다. 장치 로컬의 Action 해석은 승인된 유한 요청을 장치의 기존 API·Local Transaction·ROS/driver 실행 경로로 옮기며 identity, mode, 구성 세대, 상태·증거 신선도와 안전 한계를 다시 검사한다. 후보 해석기나 Fleet은 원시 ROS topic, `cmd_vel`, arm trajectory 또는 비행 actuator 명령의 최종 writer가 아니다. Pinky의 로컬 해석은 현재 CORE API→service 경로에 위치하며 이 결정만으로 새 프로세스를 만들지 않는다. OMX와 드론의 운영 Action 소비자는 각 장치 게이트 전까지 유보한다.

2. **요청을 목표 책임으로 분류한다.** 사이트가 목표 결과의 판정·재조정 책임을 지고 대기·인계·재조회·복구해야 하는 요청은 Fleet Mission/Step 원장을 필요로 한다. Fleet은 목표·순서·할당·성공 판정과 action/attempt 연결을 소유하고, 장치 owner는 수락·거절·실행·최종 결과를 소유한다. 현행 `/api/fleet/do`의 비-navigation 동사와 CORE `/api/v1/do`는 즉시 운영·로컬 제어용 편의 경로로 분류하며 Mission 완료를 주장하지 않는다. 동일한 동사라도 사용 맥락에 따라 목표 작업 또는 직접 조작일 수 있으므로 동사 이름만으로 분류하지 않는다. `task_service`가 구성된 경우의 현행 `navigate` task도 단일 단계에 대한 영속 기록일 뿐 다장치 Mission 엔진의 증거가 아니다. 기존 API와 응답은 별도 계약 변경 전까지 유지한다.

3. **직접 조작과 Mission의 충돌을 명시적으로 중재한다.** 같은 장치에 Mission Action이 진행 중일 때 CORE 직접 `move`·`home`·`cancel` 등이 들어오는 반례를 다룬다. 로컬 owner가 우선순위·mode·lease 또는 동등한 제어권 규칙으로 거절하거나 안전하게 중단하고, 해당 action/attempt의 결과를 Fleet에 연결해 원장을 조정하기 전에는 Mission 완료를 표시하지 않는다. 현재 Fleet→CORE 요청에는 task/action ID가 이어지지 않으므로 직접 조작의 출처·우선순위·중단 결과와 Fleet 재조정이 검증되기 전 **같은 장치의 Mission과 직접 조작 혼합 운용은 HOLD**다. 구체적 중재 규칙과 wire 필드는 별도 구현·검증에서 결정한다. 발행 전 queued cancel, 발행 후 장치 action cancel, 안전 stop/E-stop은 서로 다른 동작이다. 로컬 안전 정지는 AI 해석기나 Fleet Mission scheduler를 기다리지 않아야 하며, 운영 UI는 안전 정지를 `steps`의 뒤 항목이나 AI 후보에 묻지 않고 독립 경로로 요청해야 한다. 현재 사이트 `/api/fleet/estop` 등 `/api/fleet/*` 변경 요청은 D-276의 감사 DB 쓰기가 실패하면 CORE 호출 전에 `503`이 되므로 **사이트 전체 정지의 독립 가용성은 아직 입증되지 않았다**. 이를 해결할 긴급 경로와 감사 내구성은 D-276 변경 및 장치 시험을 거쳐 별도 결정한다.

4. **계약은 공통 의미만 먼저 정한다.** Fleet이 알아야 하는 것은 장치 identity, 등록된 capability와 버전, 목표·제약과 관련 좌표계·단위, 요청·action·attempt의 상관관계, 기한·중복·취소·재조회, 최종 결과 및 증거 출처다. Fleet은 joint trajectory, 모터 속도 제어, 비행 스택 내부 명령, driver 상태기계나 원본 영상을 공통 Action으로 소유하지 않는다. `core_common.intent`는 두 서버가 소비하는 기존 typed grammar·경로 선택 규칙이며 범용 Mission DSL, 장치 공통 실행기 또는 Fleet 전용 패키지가 아니다. Pinky의 `x/y/yaw`와 `RobotMode`를 OMX·드론에 재사용하지 않는다. 실제 두 장치의 생산·소비 표본과 D-18의 API/schema/구현/시험 동시 변경 조건을 통과할 때 최소 wire 계약과 공용 라이브러리 추출을 결정한다.

5. **결과를 네 축으로 표시한다.** Fleet 원장 접수 `QUEUED`와 장치 receipt `ACCEPTED`, 장치 Action/attempt의 권위 있는 최종 결과, 물리 정지·driver readback, Fleet Mission 목표 달성은 별도 사실이다(D-293, D-307). 동일 ID/attempt의 확정적 로컬 실패·중단 결과는 보존하고, 최종 결과가 확인되지 않을 때만 그 Action 결과를 `UNKNOWN`으로 둔다. 장치 Action 성공만으로 인계·집기·배송 같은 사이트 목표를 완료로 승격하지 않고 별도의 목표 증거를 판정한다. `steps` 배열에서 첫 호출 뒤 둘째 호출이 실패할 수 있으므로 반환된 `accepted`나 일부 step의 성공을 전체 작업 완료로 해석하지 않는다. 전체 HTTP 오류에 앞 단계 결과가 빠질 수 있어 응답 누락 뒤 무조건 재요청하지 않는다.

**현재 구현과 목표의 차이:**

| 경계 | 현재 SOURCE 사실 | 운영 전 필요한 증거 |
|---|---|---|
| 입력 후보 | `core_common.intent`는 이미 구조화된 고정 동사를 검사한다. 자연어·음성·AI 후보의 출처와 승인 흐름은 없다. | 후보 preview, 출처·시각·대상·제약, 애매하거나 오래된 후보의 보류, 별도 실행 권한 검증. |
| Fleet 목표 작업 | `task_service` 구성 시 navigation task가 영속화된다. `/api/fleet/do`의 다른 동사와 1~8 `steps`는 순차 직접 호출이다. | Mission/Step·action/attempt ID, 목표 성공 조건, 단계 인계·부분 실패·중복·단절 조정. |
| 장치 로컬 실행 | Pinky CORE는 기존 API와 로컬 서비스·최종 writer를 가진다. OMX 운영 Action과 드론 owner는 미확정이다. | 각 장치의 action 수락·거절·취소·최종 결과와 독립 readback; 배포 package closure 및 DEVICE/FIELD 증거. |

**우선 반례와 게이트:**

- **SOURCE/LOCAL:** `[navigate, dock]`의 첫 호출 접수 뒤 둘째 호출 실패·전체 HTTP 오류로 첫 결과 누락·재요청 중복·늦은 ACK·재시작을 재현해 부분 실행과 Mission 미완료를 구분한다. `steps` 뒤에 둔 `stop`/`estop`의 지연 반례도 검사한다. 음성·AI 후보의 operator credential 오용, 후보가 써 넣은 actor/source, 모호한 좌표계, stale capability를 거절·보류한다. Pinky 단일 작업의 `task_id`→CORE action/attempt→최종 이벤트 연결, 중복·기한·`UNKNOWN`을 닫는다. 현재 `do` 호출을 durable/direct/site/safety로 목록화하고 UI·API 설명에서 receipt를 완료로 표시하지 않는다. 진행 중 Mission과 직접 조작의 우선순위·거절/중단·Fleet 재조정 이벤트를 같은 ID로 검증한다.
- **ROS-SIM/ARTIFACT:** 장치별 단일 writer와 stale·단절·재시작 HOLD를 검증한다. 실제 실행 이미지의 package closure, 서명·digest·설치 목록을 장치별로 판정한다. 소스 폴더 배치만으로 배포·제어권을 추론하지 않는다(D-305).
- **DEVICE/FIELD:** Pinky 정지 요청, 로컬 안전 래치, driver/actuator readback, 물리 정지 및 재개 조건을 분리 검증한다. 사이트 감사 DB 장애 중 사이트 정지 요청과 독립 로컬 정지의 실제 경로를 시험하기 전 사이트 전체 정지 가용성을 주장하지 않는다. OMX 실물 Action 표본, 탑재형 상호 인터록, 독립 드론 비행 스택·링크 단절은 각자의 선행 조건과 별도 게이트를 따른다.

**Alternatives:** 하나의 중앙 범용 통역기가 모든 장치 ROS 명령까지 생성하는 방식은 장치 로컬 safety owner를 침범하므로 채택하지 않는다. 모든 `do` 동사를 즉시 Mission으로 간주하는 방식은 현행 직접 호출·부분 실행과 모순된다. 장치마다 자연어 모델을 두는 방식은 사이트 권한·목표 원장과 실패 의미를 분산한다. `core_common.intent`를 곧바로 Fleet 또는 Pinky 아래로 옮기는 방식은 현재 양쪽 소비자와 배포 경계를 설명하지 못한다.

**Consequences:** D-293의 Fleet interpreter/ledger 원칙은 Fleet이 **Mission으로 수용한 목표**에 적용되는 책임으로 범위를 명확히 하고, 현행 `do` 호환 경로의 미구현 간극을 명시한다. D-305의 Fleet·CORE·OMX 소유권, D-307의 결과 분류, D-276의 감사 선행 계약은 유지한다. 이번 결정은 경계와 검증 기준만 고정하며 새 endpoint·상태 enum·폴더 이동·배포 단위를 추가하지 않는다.

**References:** [D-18](D-18-rosy-core.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-276](D-276-site-fleet-per-principal-api-authorization.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-290](D-290-rosy-platform-naming-and-site-intent-boundaries.md), [D-293](D-293-site-fleet-intent-api-contracts.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-305](D-305-platform-boundary-outcome-invariants-and-independent-gates.md), [D-307](D-307-final-action-outcome-and-stop-readback-evidence.md), [P0 추적](../validation/2026-09-27-platform-p0-task-result-trace.md).
