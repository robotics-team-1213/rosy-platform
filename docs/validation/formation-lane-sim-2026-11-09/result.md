# D-1002 편대 주행 Gazebo SIM — 2026-11-09 실행 기록

증거 등급: **시나리오 미완료.** 세 번 실행해 환경 결함 셋을 고쳤고(아래), 합격선을 재는 주행 구간까지는 가지 못했다. 간격·접촉·정지 지연 수치는 **없다.** 깨끗한 결과로 적지 않는다([규칙](../../solutions/workflow-issues/inability-to-check-recorded-as-clean-result.md)). 노트북에서는 Gazebo를 돌리지 않았고 실물 로봇은 건드리지 않았다. [D-1002](../../adr/D-1002-formation-driving-on-site-lanes.md)

- 실행 호스트: 모델 PC(`remote_sim.py --host model`, D-571; 다른 세션의 착지 pytest·Harbor 작업과 같이 쓰는 기계라 sim 바닥(6코어·8 GB) 아래인 시간이 길었다). AI PC는 다른 사람의 alone 작업으로 내내 바닥 아래.
- 명령: `python tools/remote/remote_sim.py --host model --minutes 45 cmd -- 'python3 tools/sim/formation_lane.py --out "$OUT/formation" --robots 2 --render gpu'`
- 합격선(스크립트 `checks`): 리더 이동 중 팔로워 경로 간격 오차 p95 ≤ 0.10 m·최대 ≤ 0.15 m, 두 중심 최소 거리 ≥ 0.30 m, 리더 정지 8 s 뒤 전원 < 0.01 m/s, 팔로워 상실 뒤 1.5 s 안에 전원 정지 + 세션 HOLD.

## 실행

| run | 커밋 | 결과 | 원인 | 고침 |
|---|---|---|---|---|
| 1 (05:14) | `e4dcb31e0a` | Gazebo 서버 segfault(exit 139, llvmpipe EGL `driCreateNewScreen3`), CORE는 떴다가 내려감, `ArmingFailed TRANSPORT` | 모델 PC에서 소프트웨어 렌더 금지(`fleet_trips.py`도 `--render gpu`를 요구) · 준비 판정이 CORE `/state`만 보고 Nav2 전에 통과 | `--render gpu` 안내, 준비 판정을 두 CORE의 `/ws/swarm/pose` `frame == map`으로 바꿈 (`f4922aa710`) |
| 2 (05:20–06:12) | — | 12회 재시도 모두 "no host": 모델 PC 야간 재부팅(프로브 코드 4) 뒤 다른 작업으로 바닥 아래 | 호스트 부족 | — |
| 3 (09:55–10:00) | `097c48272b` | Gazebo GPU 정상(참값 17,390행, 두 로봇 스폰 위치 확인: rosy_01 (0.813, −0.509), rosy_02 (0.013, −0.510)), CORE 두 대 API 기동, **rosy_02의 Nav2 노드(map_server·controller·smoother·lifecycle) abort**: `rmw_cyclonedds_cpp: rmw_create_node: failed to create domain`; AMCL 자세가 `map`이 되지 않아 300 s 뒤 `robots not ready` | 두 로봇의 참가자를 한 도메인에 올리면서 루프백 CycloneDDS 설정이 없었다(`fleet_trips.py`는 `cyclonedds_localhost.xml`을 쓴다) | `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` + `CYCLONEDDS_URI=…/cyclonedds_localhost.xml` (`072a821679`) |
| 4 (10:05–10:23) | `072a821679` | 5회 재시도 모두 "no host"(모델 PC −15코어), 그 뒤 노트북 메모리 부족으로 재시도 루프가 종료됨 | 호스트 부족 | 재실행은 사용자 지시 뒤 |

run 3의 경고로 남은 것: `planner_server` "inflation radius (0.100) smaller than inscribed radius (0.113)" — gz_multi nav 프로필의 기존 설정이며 이 시나리오가 만든 것이 아니다. 차로에서 팔로워가 Nav2 비용지도에 어떻게 보일지는 TRAIL(Nav2 미사용)에서는 무관하다.

## 확인한 것 / 못 한 것

- 확인: 현장 차로 월드(`map_v2_fleet_real`)가 gz_multi + GPU 렌더로 뜨고, 두 CORE가 뜨며, Gazebo 참값 스트림이 두 로봇을 50 Hz로 준다. `fleet.bench` 경로로 세션을 만드는 코드 경로는 run 1에서 리더 연결 거부까지 갔다(무장 전 거절, 안전 쪽 동작).
- 못 함: 무장, 리더 Nav2 주행, 리더 급정지, 팔로워 상실 주입, 채점. 다음 실행에서 `result.json`의 `checks` 네 항목이 판정이다.

## 다음 실행

같은 명령을 호스트 여유가 있을 때(`python tools/remote/remote_sim.py --check`가 모델 PC를 고를 때) 돌린다. 로그는 `$ROSY_SCRATCH/remote-sim/<sha>/formation/`에 `result.json`·`truth.jsonl`·`events.jsonl`·`launch.log`로 남는다. 두 대가 통과하면 `--robots 3`.

## Runs 5-7 (2026-11-09 11:4x-12:0x, model PC, GPU) — scenario driven, FAIL

| run | commit | result | cause | fix |
|---|---|---|---|---|
| 5 | `52c0e89efb` base | `robots not ready` after 300 s; rosy_02 stayed `odom` | Cyclone "Failed to find a free participant index for domain 27": two Nav2 stacks exceed the default 9 auto indexes on unicast loopback (amcl, controller, map_server, behavior_server died). Run 3's loopback profile was not enough. | `formation_lane.py` writes a profile with `MaxAutoParticipantIndex` 120 (same as `fleet_trips --nav`) |
| 6 | `52c0e89efb` | ready (both `map`), arming refused: `max_speed 0.26 exceeds the SAF-004 ceiling 0.2` | script default above CORE's limit | default `--max-speed 0.2` (guard not touched) |
| 7 | `082fa961cd` | ran to scoring: **FAIL** | leader Nav2 goal 1 failed, see below | not fixed |

Run 7 numbers (`result.json`, 2 robots, spacing 0.8 m, follower cap 0.2 m/s):

- spacing: **false**. Follower p95 error 1.268 m, max 1.32 m, mean -0.82 m (583 samples), off-path max 0.556 m. The leader barely moved, so the follower stayed near its start 0.8 m behind a leader that was not leaving.
- no_contact: **true**. Minimum centre distance 0.556 m (limit 0.30), at t=53 s.
- leader_stop_followers_stop: **true**. Both robots 0.0 m/s 8 s after the stop; session HOLDING. (The test only samples speed at 8 s, so it has no finer HOLD timing.)
- lost_follower_degrades_safely: **false**. Injected at 12:00:15. rosy_02 raised `safety.estop`; all robots stopped within 8.09 s (limit 1.5 s); session was already HOLDING (left RUNNING in 0.017 s only because it was not running), reason `nav.failed (rosy_01)`. The check is not meaningful here: the session was already HELD by the earlier leader failure and leader_stop, so it never measured a RUNNING session losing a follower.
- Collisions: none by the centre-distance proxy.

Cause of the leader failure (launch.log, rosy_01 planner/controller): at goal 1 the leader reported `RegulatedPurePursuitController detected collision ahead!` repeatedly, backed to (0.67, -0.49), then `GridBased plugin failed to plan ... "Start occupied"`, `Goal failed`; goal 2 failed the same way in 0.5 s; later goals (a minute on) planned and succeeded (`Goal succeeded`). The leader spawns on the lane at (0.81, -0.51) and its start cell reads occupied in the global costmap (inflation 0.10 vs inscribed 0.113, the gz_multi nav profile warning noted in run 3). Not confirmed whether the lane wall or the follower's scan returns cause it. Next check: dump the rosy_01 global costmap around the spawn, or spawn the leader farther from the wall. The scenario needs a leader goal that plans before the other checks mean anything.

Logs: model PC `~/rosy-test/runs/sim-082fa961cd-9671a6-out/formation/`; copies in `Rosy/docs/workspace-records/2026-11-09/formation-driving/sim-run5-8/`.
