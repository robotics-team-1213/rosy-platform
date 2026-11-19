## D-1043 보기 전용도 Fleet 전체 비상 정지를 누른다

**Status:** Accepted (2026-11-18, 사용자 결정 "보기 전용 사용자에게도 여는건 괜찮아")

잇는 결정: [D-333](D-333-er2-mission-device-action-contract-closure.md) 5항(전용 `/api/fleet/estop`은 인증된 operator의 원격 정지 fanout) · [D-540](D-540-fleet-console-structure-v2.md) 9항(멈춤은 어느 운영자에게나 열림) · DESIGN.md C9(정지는 권한과 무관하게 항상 눌린다).

### Context

CORE `POST /api/v1/safety/stop`은 Viewer 이상 누구나 누른다(SAF-001). Fleet `POST /api/fleet/estop`만 operator 전용이라 보기 전용으로 로그인한 사람에게 머리의 비상 정지가 꺼져 있었고, DESIGN.md C9에 "알려진 예외"로 남아 있었다. 사람이 위험을 보고도 누를 수 없는 정지는 정지의 목적과 맞지 않는다.

### Decision

1. `POST /api/fleet/estop`은 사람 계정의 `fleet.read` 권한(보기 전용·정책 관리자·운영자)이면 받는다. `service` 역할(영상 원천·제안자 같은 기계 토큰)은 전과 같이 403이다. D-333 5항의 "operator"를 이 범위로 넓힌다. 감사 장애 때도 fanout을 계속하는 예외([D-330](D-330-fleet-action-admission-stop-and-recovery.md))는 그대로다.
2. 막는 것은 그대로 막는다. 자격 없음 401, 이웃 관제의 전용 자격(`CONTROL_UNIT_CREDENTIAL_SCOPE_REQUIRED`), AI 관찰자 POST 제한, `service` 역할 403. 이 결정은 D-333 5항·[D-330](D-330-fleet-action-admission-stop-and-recovery.md)의 "operator" 정지 권한을 이 범위로 넓힌다.
3. 정지를 푸는 쪽(래치 해제·발행 재개 `/dispatch/rearm`·재가동·승인)은 바꾸지 않는다. 지금처럼 이름 있는 운영자만 한다.
4. 화면은 세션이 없을 때(401)만 머리 정지를 잠근다. DESIGN.md C9 예외 문구를 지운다.

### Consequences

보기 전용 계정도 사이트 전체 정지(래치)를 걸 수 있다. 잘못 누르면 운영자가 해제해야 하므로 정지 횟수가 늘 수 있다. 감사 기록에 누른 주체가 남는다. 해제 권한은 넓히지 않았으므로 안전 쪽으로만 넓어진다.
