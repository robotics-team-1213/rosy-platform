## D-721 스테이션과 제자리로 돌아오는 복귀 모드가 필요하다

- Status: Accepted
- Date: 2026-10-12
- Related: D-28, D-385, D-419, D-433, D-502, D-688

**Status:** Accepted (2026-10-12)

## Context

운영자는 2026-10-12에 복귀 모드가 나중에 필요하다고 정했다. 목적지는 둘이고, 둘 다 필요하다.

1. station. 충전 도크가 있는 스테이션으로 돌아온다.
2. 제자리. 이번 외출이 시작된 자세로 돌아온다. 그 자세는 도크와 다르고, 저장해 둔 `__home__`과도 다르다. 운영자가 그 자세를 home으로 저장한 경우에만 둘이 겹친다.

지금 있는 경로는 그 모드의 목적지와 다르다.

`ROBOT_MODES`는 `IDLE`, `MANUAL`, `NAVIGATION`, `DOCKING`, `EMERGENCY`뿐이다.

SAF-005 Critical의 `RETURN_HOME`은 `NavigationManager.home()`으로 예약 waypoint `__home__`에 간다(NAV-003, WPT-004). 도킹이 이미 진행 중이면 `nav.home`을 보내지 않는다. `battery_return_suppressed`이거나 지역화가 `LOCALIZED`가 아니거나 home을 보내지 못하면 e-stop `battery_policy`다(D-502). `__home__`은 기본으로 만들어지지 않는다(D-28). 가르치지 않은 로봇에서 이 정책은 정지로 남는다.

SAF-003의 `RETURN_HOME`도 `nav.home(source="fleet_loss")`로 `__home__`에 간다. home을 보내지 못하면 선 채로 남고(`applied: STOP`, `home_unavailable`) e-stop은 걸지 않는다(D-419).

DNC-006 자동 복귀는 Warning 20%이고 도크가 있을 때다. 도크가 없는 로봇은 SAF-005의 `RETURN_HOME` 또는 `STOP`이 남는다.

`DOCKING`은 도킹 액션이 스테이징부터 접점까지 소유한다(DNC-002). 도크는 waypoint가 아니다(DNC-005). 모드 전이표는 `NAVIGATION`에서 `DOCKING`으로 가지 못한다(D-28).

얼굴은 `NAVIGATION`이면 `Going`, `DOCKING`이면 `Docking`이다(D-385, D-433, D-688). `__home__`으로 가는 `NAVIGATING`도 `Going`이다. 차선의 retrace와 return은 짧은 차선 보정이며, 스테이션으로 가는 이동은 여기 범위 밖이다.

## Decision

1. 제품에는 복귀 모드가 필요하다. 목적지는 `station`과 `outing_start`(제자리)다. 둘을 `__home__`이나 `DOCKING` 하나로 합치는 결정이 아니다.

2. 전선에는 여섯 번째 `RobotMode`를 더하지 않는다. 모드 전이표는 `NAVIGATION`에서 `DOCKING`으로 가지 못하고, 도킹 우선순위는 주행보다 앞이다(D-28, DNC-002). 복귀는 그 이동을 이미 소유한 모드 위에 목적지 코드만 싣는다. `station`은 `DOCKING`, `outing_start`는 `NAVIGATION`이다. 코드는 이 둘뿐이다.

3. `station`은 가르쳐 둔 도크에 대한 기존 도킹 명령이다. 그 명령이 스테이징부터 접점까지 `DOCKING`을 유지한다. `nav.home()`이나 `__home__`으로 대신하지 않는다. 도크가 없으면 `__home__`으로 넘어가지 않고, 그 복귀는 출발하지 않는다.

4. `outing_start`는 이번 외출이 시작된 맵 자세다. 로봇이 머물던 자리에서 `NAVIGATION` 또는 선 따라가기로 나가기 시작할 때, 지역화가 `LOCALIZED`이면 그 자세 하나를 로봇 안에 기억한다. 도크에서 나온 외출은 언도킹이 끝난 뒤의 자세다. `__home__` waypoint로 저장하지 않고, 도크 데이터베이스에도 넣지 않는다. 다음 외출이 시작되면 그 자세로 바뀐다. 그 자리로 도착하면 잊는다. `LOCALIZED`가 아니면 이번 외출의 제자리는 없다.

5. `outing_start` 이동은 기억한 자세로의 기존 내비게이션 목표다. 도착하면 `IDLE`이다. 접점으로 이어가지 않는다.

6. SAF-003과 SAF-005의 `RETURN_HOME`, DNC-006의 Warning 자동 복귀는 이 기록이 바꾸지 않는다. 배터리 귀환을 station이나 제자리로 다시 정의하지 않는다.

7. 얼굴 문자열은 목적지가 스냅샷에 발행된 뒤에만 말한다. 예약 문구는 ASCII `Station`과 `Origin`이다. 발행 전에는 `NAVIGATION`이 `Going`, `DOCKING`이 `Docking`이다. 이 변경은 그 키와 문구를 코드에 넣지 않는다.

## Consequences

복귀 모드의 목적지, 전선, 제자리 기록, station의 도크 인계가 정해졌다. `RobotMode`와 스냅샷 필드는 그대로다. 모드를 넣는 변경은 안전 우선순위와 명령 수락을 바꾸므로 여기 포함하지 않는다. 기존 `__home__` 귀환과 도킹 시퀀스는 그대로 동작한다. 목적지 코드를 발행하는 구현과 얼굴 줄은 후속이다.

## Verification

SRS의 SAF-003, SAF-005, NAV-003, WPT-004, DNC-002, DNC-005, DNC-006과 D-28, D-419, D-502, D-688, 모드 전이표, `ROBOT_MODES`, `NavigationManager.home()`을 대조했다. 시험은 돌리지 않았다. 복귀 모드 값, 스냅샷 필드, 얼굴 줄은 없다.
