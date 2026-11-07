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

## Amendment 2026-11-07: station recovery requests and 사람 부탁 (API v1.372)

Nothing above changes. This adds two things beside the return mode; neither moves a robot.

**Station recovery request (slice S1, default off).** `fleet.station_recovery.enabled` (site config, default false) lets Fleet ask, for each online robot whose battery level is warning or lower with fresh evidence, whether a charge bay could take it (`fleet/station_recovery.py`, pure; bay choice reuses the charge-bay plan). The answer is a bay or one reason: `no_station`, `no_free_bay`, `position_unknown`, `already_stopped` (an e-stop is never released), `busy`, `another_returning`, `state_unknown` (no stop flag, mode or motion verdict in the row: an empty state is not "idle and clear"); stale or missing battery evidence answers `battery_evidence_missing`, never ok and never low. `GET /api/fleet/station-recovery` lists the answers (`disabled` while off); `POST /api/fleet/station-recovery/{robot_id}/approve` (named operator) records the approval and answers `started: false`. An approval whose current answer is not actionable is 409 with the reason; no reason can be overridden. Motion is S2.

**사람 부탁 (person requests).** The system asks a person for a physical act and the person answers on the console. Fleet keeps the durable record (kinds `unplug_charger`, `plug_charger`, `move_robot`, `clear_area`, `other`; states `open`, `done`, `cannot`, `expired`, `withdrawn`); tools create it with an operator or the existing service credential, poll it by id, and the requester may withdraw it. A request with a robot also reaches that robot (CORE holds one, with its expiry; the dashboard shows a Korean card; the face draws a short English strip such as `UNPLUG CHARGER` and beeps with the existing `call` pattern on arrival and every 15 s). Only one request per robot is on its screen, the newest open one; an older open request shows as `waiting` ("not on the robot's screen") and comes up when the newer one is answered, withdrawn or expires. Fleet's existing one-second loop runs a reconcile step every 5 s: it reads `GET /api/v1/person-request`, shows the newest request again when CORE lost it (a restart) or holds another, removes a request Fleet has closed, and retries a clear that failed. A request is `delivered` only for what was read back, with `age_s` since that read; the console says "표시 중" only for a read-back within 30 s and otherwise "확인 불가". A delivery that fails reads `not_delivered`. A request answered or withdrawn while its PUT is in flight is taken back, and a closed record is never marked shown. Per robot a requester has one open request (a repeat returns it, with no new beep) and at most three requests are open; the CORE-held expiry is the time Fleet has left.

**Battery urgent wins (D-502 Amendment 2026-11-07).** While the panel is dark at 10% or under, a request shows nothing on the robot: no `call` beep, no amber lamp, and `person` is stripped from the dark screen. The urgent beep is the one sound; the e-stop and failed sounds still come first, and the person's `call` waits for a loop in which nothing else sounded. The amber request lamp covers only an idle or ready lamp, never a navigating, manual or docking one.

**Rule.** An answer is a person's statement only. It never starts motion, releases a stop or satisfies a safety check; tools still read the evidence. The only thing an answer sends to a robot is the removal of the request from its screen. Station recovery will reuse this for the arrival notice "충전기 연결 필요" (S3, not built).

**Not done.** The answer buttons exist only on the Fleet console; the robot dashboard says "관제에서 답해 주세요". The state snapshot carries no `person_request` field because that needs the safety-tagged `core_features/state/manager.py`; the dashboard and Fleet read `GET /api/v1/person-request`. Requests without a robot appear in the API but not in the per-robot attention queue.

