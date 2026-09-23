## D-150 web_node는 control 디버그 서피스로 잔류하고 맵의 단일 홈은 navigation/map이다

**Status:** Accepted (2026-09-21).

**Context:** `web_node`(포트 28161/28162 + `web/dashboard.html`)는 CORE 대시보드(D-23)와 병존하는 2번째 웹 서피스다. 카메라 JPEG, 실시간 scan, wander 세션 릴레이를 보여 주는 관측 뷰지만 `POST /teleop` 같은 명령 릴레이도 있어 운영 서피스로 오인될 여지가 있다. 또한 맵 번들이 `control/map`과 `navigation/map`에 이중 소재다.

**Decision:**

1. **web_node는 control 개발·디버그 전용 서피스로 잔류한다.** 운영 launch·deploy 구성에 포함되지 않는다. 외부 클라이언트 계약은 D-23의 CORE 대시보드가 유일하다.
2. **병존 규칙: web_node는 control 노드 관측과 수동 조작(`cmd_vel_raw`)만 다룬다.** 프로토콜·인증·이벤트 계약의 소스가 되지 않으며 CORE API를 대체하지 않는다.
3. **운영 맵의 단일 홈은 `navigation/map`이다.** `control/map`의 Gazebo/검증 자산은 캘리브레이션 기준 자산으로 명시적으로 격하한다 — 이동이 필요하면 별도 커밋에서 한다.

**Alternatives:** core_api_web 흡수 후 삭제 — 카메라 JPEG/실시간 scan 뷰는 CORE 계약 밖 기능이라 흡수 비용이 서비스보다 크다. 현상 유지 — 운영 서피스 오인 위험이 남는다.

**Consequences:** 외부 서피스 소유는 D-23 그대로 단일하다. web_node 문서·포트·launch는 디버그 용도로 명시된다. 맵 이중 소재 해소의 근거가 생긴다.

**Validation / Transition:** deploy 구성(compose/설치 스크립트)에 28161/28162 포트 부재 검사는 후속 커밋. `robot.launch.py`의 web 브랜치는 디버그 launch 안에만 존재한다.

**References:** D-23 (FastAPI 내장 대시보드), D-38, 결합도 평가 §4 (2026-09-19).

---

**Update 2026-09-23:** `web_node` 기본 포트를 28161/28162에서 **28181(페이지)/28182(API)**로 바꿨다(사용자 요청). deploy 부재 가드(`test/test_control_launch_boundary.py`)도 새 포트를 검사한다.
