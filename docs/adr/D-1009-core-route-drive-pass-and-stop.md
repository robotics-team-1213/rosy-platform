## D-1009 CORE는 pass/stop 점 경로를 한 번에 받아 stop 점에서만 서고, 막힘은 이동을 유지하며 재계획한다

**Status:** Accepted (2026-11-10, 사용자 지시). SOURCE와 Gazebo SIM까지다. 기체 적용과 실물 주행은 하지 않았다.

> "너무 많이 멈추고, 멈추더라도 빠르게 이동하면서 판단하는 로직을 개선해. 지금은 지점마다 너무 많이 멈춘다. 멈추는 곳과 지나가는 곳을 구분해서 해야지." (2026-11-09, 실물 주행 뒤)

잇는 결정: [D-2](D-2-cmd-vel.md)(최종 `cmd_vel`은 CORE 하나), [D-463](D-463-fleet-lane-route.md)(짧은 앞 점 목표), [D-550](D-550-fleet-robot-communication-contract.md) 10(목표 임대), [D-1003](D-1003-nav2-free-goals-in-the-robot-map-frame.md)(free 구간 목표를 기체 프레임으로), [D-609](D-609-route-plan-execution-pipeline.md) 4항(free 구간 실행), NAV-006(진척 없음).

### Context

2026-11-09 geg6(릴리스 177, SLAM 모드 Nav2, R 현장 지도 `world_261026`) 실물 관측이다.

1. `POST /api/v1/navigation/goal`은 목표 하나만 받고 주행 중 새 목표는 409 `NAVIGATION_ACTIVE`다. 매트 차선을 따라가려면 0.15~0.33 m마다 목표를 보내야 했고, 점마다 `ARRIVED` 뒤 다음 목표라 로봇이 점마다 섰다.
2. 매트 끝 U턴 꼭짓점(벽에서 0.15 m 이내)은 planner가 "no valid path"로 실패했고 BT가 대안 없이 곧바로 `FAILED`였다. Nav2 Jazzy 기본 BT는 실패 원인이 `WouldAPlannerRecoveryHelp`·`WouldAControllerRecoveryHelp`에 해당할 때만 복구하고, 해당하지 않으면 그 자리에서 끝난다.
3. 주행 중 `RegulatedPurePursuitController detected collision ahead!` 경고 뒤 정지했다.
4. 기본 `navigate_through_poses` BT는 0.333 Hz로 재계획하고 `RemovePassedGoals` 반경이 0.7 m라, 0.2 m 간격 점은 한꺼번에 삼켜져 모서리를 자른다.

### Decision

1. **경로 API.** `POST /api/v1/navigation/route` `{points: [{x, y, yaw?, kind: pass|stop}], correlation_id?, lease_ttl_s?, expected_boot_id?, expected_owner_generation?}`. `kind` 기본값은 `stop`이다. 점은 1~64개, 마지막은 `stop`이다. 기존 `/navigation/goal`과 같은 관문(수동 해제, 차선 추종·trip lease, 능력, `navigation.goal_navigation`, 위치 확인)과 같은 소유권(`reserve_goal`, owner generation, native run 영수증, `NAVIGATION_ACTIVE`)을 쓴다. 경로 하나가 native run 하나(`kind: navigate`)·상관 식별자 하나·목표 임대 하나다. 영수증 종류 열거를 늘리지 않아 Fleet의 native 소비자는 바뀌지 않는다.
2. **정지 점마다 Nav2 액션 하나.** 경로를 stop 점에서 잘라 구간으로 만든다. pass 점이 있는 구간은 `NavigateThroughPoses`(pass 점 + stop 점), 없으면 `NavigateToPose`로 보낸다. 구간이 `SUCCEEDED`면 같은 run 안에서 CORE가 다음 구간을 바로 보낸다(`NavigationManager.on_result` → `route_continue`). 구간 사이에 `ARRIVED`·`IDLE`이 나오지 않고 상태는 `NAVIGATING`을 유지한다. 마지막 stop 도착이 run의 `SUCCEEDED`(`ARRIVED`)다. pass 점의 헤딩은 다음 점 방향, `yaw` 없는 stop은 직전 점에서 오는 방향이라 도착 때 제자리 회전이 생기지 않는다.
3. **건너뛰기 규칙(pass 점만, stop 점은 건너뛰지 않는다).** (a) 구간을 보내기 전에 전역 코스트맵(`maps.get_costmap("global")`)에서 값이 253 이상(내접·치명·미지)이거나 지도 밖인 pass 점은 건너뛴다. 코스트맵이 아직 없으면 거르지 않는다. (b) 구간이 실패했는데 앞에 pass 점이 남았으면 그 첫 점을 건너뛰고 같은 구간을 다시 보낸다. 재전송마다 점이 하나씩 줄어 유한하다. 로봇이 이미 지나간 pass 점(자세가 0.12 m 안)은 다시 보내지 않는다.
4. **실패 규칙.** pass 점이 없는 구간이 실패하거나, 다음 구간 전송이 예외를 내거나, NAV-006(30 s 진척 없음)이 끊으면 경로는 `FAILED`다. 취소·E-Stop·임대 만료는 단일 목표와 같은 `cancel` 경로로 경로 전체를 `CANCELED`로 끝내고 이후 늦은 Nav2 결과는 무시한다.
5. **진행 읽기.** `GET /api/v1/navigation/state`에 `route`: `active`, `result`, `legs`·`leg`·`stops_made`, `actions`(보낸 Nav2 액션 수), `next_stop`, `remaining`, `skipped`, 점별 `state`(`pending|reached|skipped|stopped`). 새 목표나 경로를 받으면 이전 읽기는 사라진다.
6. **Nav2 설정(근거 포함).** `middleware/drive/planning/nav2/behavior_trees/rosy_navigate_to_pose.xml`·`rosy_navigate_through_poses.xml`을 새로 두고 launch가 `bt_navigator`의 `default_nav_*_bt_xml`로 가리킨다(`params_rewrite.write_prefixed_nav2_params`, SIM `gz_multi.launch.py`). Jazzy 기본 트리와 다른 점은 다음뿐이다.

   | 항목 | 기본 | 이번 | 근거 |
   |---|---|---|---|
   | through 재계획 주기 | 0.333 Hz | 2 Hz | 막힌 길을 0.5 s 안에 알아채고 주행 중에 다시 계획한다 |
   | to_pose 재계획 주기 | 1 Hz | 2 Hz | 같은 이유, 정지 구간도 동일 |
   | `RemovePassedGoals` 반경 | 0.7 m | 0.15 m | 0.2 m 간격 점이 한꺼번에 삼켜지면 모서리를 자른다 |
   | 복구 진입 | `WouldA*RecoveryHelp`가 참일 때만 | 모든 planner·controller 실패 | "no valid path"·"collision ahead"도 코스트맵을 비우고 다시 계획한다 |
   | 복구 동작 | 코스트맵 비우기, 제자리 회전 1.57 rad, 5 s 대기, 0.30 m 후진 | 코스트맵 비우기, 1 s 대기 | 벽 0.15 m 옆 회전·후진은 새 충돌 위험이고 5 s 대기는 멈춤이다 |
   | 복구 횟수 | 6 | 20 | 약 12 s 동안 계속 재계획한 뒤에만 액션이 실패한다. 그 위에 SimpleProgressChecker(10 s, 0.5 m)와 NAV-006(30 s)이 진척 없음을 끊는다 |

   속도·가속·목표 허용오차·`failure_tolerance`·costmap은 그대로다. CORE가 속도 한도를 자르는 방식(`feat/speed-limit-config`)도 그대로다.
7. **Fleet 연동은 이번에 하지 않는다.** 차선 trip(lane segment)을 이 API로 한 번에 보내는 일은 다음 단계다. D-1003(`feat/nav2-site-map-goals`, 아직 로컬 main에 없음)이 구간 끝 장소 하나와 409 재전송으로 고치는 `trip_steps`·`robot_frame_goal`과 같은 파일을 건드리므로, 그 브랜치가 착지한 뒤 그 위에 얹는다. Fleet이 경로 점을 보낼 때는 D-1003의 `robot_frame_goal`로 각 점을 기체 프레임으로 바꾼 뒤 보낸다(경로 API는 기체 `map` 프레임 좌표를 받는다). D-463의 0.2 m 앞 점 목표와 지점마다의 409 재시도는 이 API로 대체한다.

### 한계

- 코스트맵이 5초 가까이 낡을 수 있다(`publish_frequency 0.2`). 건너뛰기 (a)는 정적 벽과 이미 본 장애물만 거른다. 새 장애물은 (b)와 BT가 처리한다.
- (b)는 실패한 점이 아니라 "앞에 남은 첫 pass 점"을 건너뛴다. 실패 원인이 다른 점이면 한 번 더 실패한 뒤 그 점을 건너뛴다. 재전송 횟수만큼 BT 실패 시간이 더해진다.
- 2 Hz 재계획은 Pinky Pro(Pi 5) CPU에서 재지 않았다. SIM은 GPU 렌더 호스트에서 돌았다. 실물에서 `planner_server` CPU가 문제면 두 XML의 `RateController hz`만 낮추면 된다.
- 복구에서 회전·후진을 뺐다. 벽에 코가 박혀 코스트맵을 비워도 못 빠지는 경우는 20번 재계획 뒤 `FAILED`가 되고 상위(Fleet, 사람)가 판단한다.
- 정지 점의 "멈춤"은 목표 허용오차(0.10 m, yaw 0.25 rad) 안에서 Nav2가 서는 것이다. 정지 점 사이 대기 시간(dwell)은 없다.

### 검증

- 호스트: `middleware/core/gateway/test/test_navigation_route.py`(구간 수 = stop 수와 한 run, pass 없는 구간, 409 없음, 입력 검증, 헤딩, 코스트맵 건너뛰기와 stop 불가침, 실패 시 재전송과 소진, 지난 점 보존, 취소 뒤 늦은 결과, 전송 예외, REST 전체와 임대, 브리지 목표 변환).
- SIM: `tools/sim/route_drive.py`(`remote_sim.py ... route_drive`). 결과는 `docs/validation/route-pass-stop-sim-2026-11-10/result.md`.
- 기체 적용은 하지 않았다. 필요한 것은 아래 「기체 적용」이다.

### 기체 적용에 필요한 것

릴리스에 `navigation` 패키지의 `behavior_trees/`(CMake 설치)와 CORE 변경이 함께 들어가야 한다. 기체 launch(`hardware.launch.py`)는 `write_prefixed_nav2_params`로 BT 경로를 넣는다. 현장 첫 주행은 한 기체·한 경로, 속도 한도 아래에서, 비상 정지를 손에 두고 한다. 안전 태그 경로 변경이라 `Safety-Review:` 독립 검토를 받았다(커밋 trailer).

### 기각

- **Nav2 `FollowWaypoints`:** 점마다 `WaitAtWaypoint`로 서는 모델이고 pass/stop 구분과 건너뛰기를 우리가 규칙으로 가질 수 없다(D-609도 FollowWaypoints API를 만들지 않기로 했다).
- **모든 점을 `NavigateThroughPoses` 한 액션으로:** stop 점에서 서지 못한다. 정지 점마다 액션을 나누는 이유다.
- **CORE 목표 API가 진행 중 새 목표를 선점:** D-550·owner generation 계약을 깨고, 선점되는 목표의 결과가 늦게 와서 오판한다(goal_tracker 주석의 SWM-001 사례).
- **건너뛰기를 Fleet에서만:** Fleet은 기체 코스트맵을 보지 못하고, 실패 직후의 재시도는 기체 안이 가장 빠르다.
