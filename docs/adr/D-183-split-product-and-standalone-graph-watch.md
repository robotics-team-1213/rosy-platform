## D-183 그래프 감시는 제품 그래프와 control 단독 그래프를 나눈다

**Status:** Accepted (2026-09-24). `inspect(..., mode='product'|'standalone')`가
표 하나를 고른다. `watch_node`의 `graph_mode` 기본값은 `standalone`이다.

**Context:** D-2와 D-38은 제품 런타임에서 최종 `/cmd_vel`의 발행자가 CORE
하나라고 정한다. D-149는 control만 단독으로 띄울 때 레거시 safety 게이트가
그 토픽을 가질 수 있다고 정한다. `control/watch.py`는 그 둘을 한 표에 둔다.
`REQUIRED`는 `sllidar_node`, `wander_node`, `safety_node`, `camera_detect_node`
를 제품 스택처럼 요구하고, `EXCLUSIVE['/cmd_vel']`은 `core`와 `safety_node`를
함께 적는다. 제품 그래프를 이 표로 보면 없는 레거시 노드가 경보가 되고,
단독 control 그래프를 제품 표로 보면 CORE가 빠져도 조용할 수 있다.

**Decision:**

1. 감시 표는 둘이다. 제품 표와 control 단독 표는 한 dict를 공유하지 않는다.
2. 제품 표의 `/cmd_vel` 허용 소유자는 `core` 하나다. 필수 노드도 그 런타임에
   실제로 뜨는 노드만 적는다. `safety_node`, `wander_node`, `sllidar_node`,
   `camera_detect_node`는 제품 표에 넣지 않는다.
3. control 단독 표는 D-149가 허용한 그래프만 적는다. 이 표는 제품 런타임
   감시에 쓰이지 않는다.
4. 한 프로세스가 두 표를 동시에 적용하지 않는다. 모드가 표를 고른다.

**Alternatives:** 지금의 한 표에 모드 주석만 달기 — 오탐의 원인이 표에 남는다.
제품 감시가 레거시 노드를 OPTIONAL로 내리기 — 없어도 되는 노드와 있으면
안 되는 발행자가 같은 목록에 남는다.

**Consequences:** 제품 대시보드나 진단이 그래프 이상을 읽을 때 제품 표만
본다. control 단독 모드는 자기 표를 본다. 표를 나누기 전에는 감시 결과가
제품 그래프의 증거가 아니다.

**Validation:** `src/core/control/test/test_watch.py`.
