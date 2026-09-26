## D-126 완전 모듈 분리 — CORE는 슬라이스 코드를 import하지 않는다

**Status:** Accepted (2026-09-19). 분리 계약(가드 5개 + 영향 스위트)이 초록이다.
수용 범위: `test/test_module_separation.py` 5 passed, 어댑터 23·api/host/rmw/criteria 159 중
158 passed(1건은 Level-3 잔재 `rosy_default.yaml` 경로, D-126 미접촉), control 996 passed(환경성 2건은
패키지 디렉터리 실행 시 PASS 확인), fleet 312·omx 10·games 101·gz_sim 14 passed.
core 스위트의 나머지 실패(dashboard/web 자산·swarm 경로·triage/palette 등)는 9b77daa 구조
개편의 잔재로 D-126 미접촉 파일의 구 경로 참조이며, 별도 백로그로 수용을 막지 않는다.

**Context:** 2026-09-19 작업 트리 결합도 실측에서 이음새 5곳이 나왔다.
S1 `core → control` 미선언 import 3건(`control_sensor_adapter.py:118,140,213`, `package.xml`에는 `control` 없음),
S2 `control`의 최종 `cmd_vel` 구독 잔재 2곳(`web_node.py:431`, `wander/node.py:36`),
S3 `fleet` 선언 과다(`exec_depend: core`이나 생산 코드는 `core_common.protocol.schemas`만),
S4 `gz_sim/swarm_bench.py`의 `fleet.swarm.*` 직접 import,
S5 `core_api_web/api/v1/*` 12개 모듈의 `core_features` 하위 7개 영역 직접 참조.
게다가 D-64 가드(`test_runtime_slices.py`)는 구 경로(`src/rosy_core`)를 가리켜 신 구조에서 검사하지 않는다.

**Decision:**

- 런타임 단일 프로세스(D-1) 유지. 새 ROS 패키지 없음.
- S0 가드 재건이 먼저다: `test/test_module_separation.py`에 가드 5개(CORE의 슬라이스 import 금지,
  control의 최종 토픽 문자열 금지, `package.xml` ⊇ 코드 import, `cmd_vel` 발행 1곳, fleet 생산 코드는
  `core_common`만). 가드는 mutation-prove한다.
- S1은 provider 역전으로 닫는다 (D-63의 "토픽 경계" 예고를 이 메커니즘으로 이행): 어댑터가
  `control.*`를 정적으로 import하지 않고, worker/policy/calibration loader를
  `rosy.sensor_provider` 엔트리포인트(`control.sensor_provider:PROVIDER`) 또는 생성자
  주입으로 받는다. 검증(프로파일 revision·sensor-only·명령권 deny-list·보정 바인딩·측정
  파라미터 allow-list)은 CORE에 남아 덕타입 데이터에 동작하므로 provider 부재·변형은
  fail-closed. worker 생성은 스트림이 아니라 조립이라 토픽 경계로 바꿀 수 없고, 이 방식이
  D-1 단일 프로세스·무복사 handoff·호스트 테스트 가능성을 모두 보존한다. D-64의 `ALLOWED` 집합은 비운다.
- S2는 토픽명 개명·삭제(핀된 레거시 발행자 선언 1곳은 parity 계약으로 유지),
  S3은 `exec_depend: core_common`(+ 시험용 `test_depend: core_features`),
  S4는 시뮬→함대/내비 하향 의존 선언으로 고정,
  S5는 `CoreServicesLike` Protocol + `rmw.py→core_common`·`host_agent_client.py→api` 이동으로
  `core` 역참조만 제거한다. `core_features.*` 직접 참조는 선언 범위 안이라 유지한다 (X5).
- `core_features` 추가 분할과 멀티 프로세스화는 하지 않는다. 전자는 B1~B3 미충족, 후자는 D-125에서 보류한 Option B다.

**Alternatives:** 미선언 import를 선언으로 덮기(`package.xml`에 `control` 추가하고 끝내기) —
싸고 거짓말을 없애지만 D-63 끝 상태(토픽 경계)에서 멀어지므로 S1의 중간 단계로도 채택하지 않는다.

**Consequences:** S1·S5는 동작 불변 리팩토링이며 각 단계마다 기존 어댑터·api 시험이 PASS해야 한다.
Accepted 조건은 가드 5+1 초록과 관련 회귀 전체 PASS다. SOURCE/LOCAL 증거만 만들며
ARTIFACT/DEVICE/FIELD gate는 변하지 않는다.

**Validation / Transition:** `test/test_module_separation.py`, `src/core/core/test`,
`src/core/control/test`, `src/site/fleet/test`, `src/sim/gz_sim/test`.

**References:** D-1, D-2, D-38, D-62, D-63, D-64, D-125.
설계: `docs/plans/2026-09-19-full-module-separation-design.md`,
실행: `docs/plans/2026-09-19-full-module-separation.md`.

---
