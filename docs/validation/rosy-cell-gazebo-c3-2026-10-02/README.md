# Rosy Cell C3 Gazebo 단일 pick/place · 2026-10-02

## 범위와 판정

[C3 하위 계획](../../plans/2026-10-02-rosy-cell-c3-gazebo.md)의 ROS-SIM 실행 기록이다. 해석 IK 플래너(D-402) → `PickPlaceRunner` → 단일 `ArmCommandOwner` → `/arm_controller/follow_joint_trajectory` 경로로 Rosy Cell 데모 Job의 `CELL_TRANSFER` 하나를 Gazebo에서 실행했다. Fleet 경로(C4), 종단 Job(C6), 실물·DEVICE·FIELD는 범위 밖이다.

**판정: C3 ROS-SIM HOLD. 경로는 끝까지 돌았지만 블록을 목표에 놓지 못했다.**

- 플래너가 만든 네 phase는 owner와 vendor 컨트롤러가 모두 수락·완료했다(run8, `SUCCEEDED`).
- 그러나 owner/runner를 수정 없이 쓰면 첫 phase에서 HOLD가 난다. 문제 1·2를 probe 쪽 대역(stand-in)으로 우회해야 끝까지 갔다. 대역은 아래와 evidence JSON에 표시했다.
- 마찰 파지는 실패했다(문제 4·5). 명시한 sim aid(DetachableJoint)도 손가락 불안정으로 owner 관절 한계 HOLD를 냈다. 허용오차 안의 배치는 0회다.

## 재현 정보

| 항목 | 값 |
|---|---|
| 소스 | 브랜치 `feat/rosy-cell-c3-gazebo` (base main `4804d417`) |
| 이미지 | `rosy-omx-pilot:recording-local`, ID `sha256:faeb86d666c6848ec61478a72087f7cadfc55d6b23e54dff891202b21029efb2` (현재 `Dockerfile.pilot`과 같은 headless·switch-timeout 패치). 기반 `rosy-omx-workstation:native-action-only-local` `sha256:b47034e4…f9f0`. 재빌드·재태그 없음. `rosy-omx-pilot:local`(`e9466260…`)에는 headless 패치가 없어 broadcaster 활성화가 5 s에 시간 초과했다. |
| vendor | `open_manipulator` `0a4af6a923b8b7d80b8c20506d1839c54d2e993e` (`stack.lock.yaml`) |
| 월드 | `src/sim/gz_sim/worlds/omx_cell_workcell.sdf` sha256(LF) `5906ef27edd9aac907b499bb3a4de668960d24508e7d57559829687f8fc71d36`; sim aid 변형 `omx_cell_workcell_sim_aid.sdf` `5c139aee839829eaebd32915298495de5d2a2c6a0da9ce21c5b81e767ebd5e2b`. 두 파일은 `infeed_block`의 DetachableJoint 플러그인만 다르다. |
| profile_revision | `f49251c4c5cc150daf06aac0fa083eb7f6764c730bfe12d0cd431f102ea1634f` (`deploy/robot/omx/sim/cell_profile.yaml`, 변경 없음) |
| kinematics_revision | `27cd572830f931b57eedec55081b77749f65dcd059d11e34199bdcb1bb6db04d` |
| cell_sha256 (rosy_cell content hash) | `4b2cc0c3144ff92426acda09d140976cd5b6d89e6485caa163630a0ed0aea5a8` |
| recipe_sha256 | `7513c39ea5404035505a318e627da2b0382dd5f2e42d14a74cebe0c4d12b6176` |
| 컨테이너 | `rosy-cell-c3-sim`, `--network none`, 장치 grant 없음, 저장소 read-only, `ROS_DOMAIN_ID=77`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`, 포트 publish 없음 |

월드 좌표 = OMX `robot_base`(`link0`). vendor launch가 `-x 0 -y 0 -z 0`으로 spawn하고 URDF `world_fixed`가 항등이다. 실측 `gz model -m omx_f -p` = (0, 0, 0, 0, 0, 0).

```powershell
# 저장소 루트(PowerShell). 스크래치는 X:\DevTemp\rosy-cell-c3
$wt = (Resolve-Path .).Path
docker run -d --rm --name rosy-cell-c3-sim --network none `
  --mount "type=bind,source=$wt,target=/repo,readonly" `
  --mount "type=bind,source=X:\DevTemp\rosy-cell-c3,target=/scratch" `
  -e OMX_CELL_LOG_DIR=/scratch `
  [-e OMX_CELL_WORLD=/repo/src/sim/gz_sim/worlds/omx_cell_workcell_sim_aid] `
  rosy-omx-pilot:recording-local bash /repo/deploy/robot/omx/run_cell_sim.sh
docker exec rosy-cell-c3-sim bash -c "source /opt/ros/jazzy/setup.bash; source /opt/omx_ws/install/setup.bash; `
  export ROS_DOMAIN_ID=77 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST; `
  python3 /repo/deploy/robot/omx/probe_cell_transfer.py --out /scratch/<run> --transfer-index 3 `
  --submit-from rebind --feedback-to-runner first --grasp-depth 0.015 [--sim-aid detachable-joint `
  --world /repo/src/sim/gz_sim/worlds/omx_cell_workcell_sim_aid.sdf]"
docker stop rosy-cell-c3-sim
```

probe는 한 프로세스에 owner 하나를 만든다(D-403 §8). 시작할 때 `pilot_sim_server`나 다른 probe가 있으면 거절한다. `run_cell_sim.sh`는 owner 없이 vendor follower만 띄운다.

## 배치와 도달 범위

호스트 실측(해석 IK + 시뮬 프로필 한계, heading 5개 × yaw 0/90°):

| TCP z | 모든 heading·yaw에서 가능한 TCP 반경 |
|---|---|
| 0.005 m | 0.058–0.269 m |
| 0.05 m | 0.058–0.261 m |
| 0.08 m | 0.058–0.251 m |
| 0.12 m | 0.058–0.232 m |
| 0.15 m | 0.058–0.212 m |

데모(`src/site/cell/examples/omx_sim/`)는 **2 팔레트 × 2층 × 4블록 + 슬립시트 2장**이다. 줄이지 않았다.

- 블록 40 × 30 × 30 mm, 20 g. 그리퍼는 30 mm 폭을 쥐고, 42 mm 패드가 40 mm 길이 방향에 놓인다.
- 팔레트 0.10 × 0.08 × 0.01 m 판 두 개, 윗면 모서리 (0.13, ±0.01/−0.09, 0.01). `grid`, gap 15 mm.
- 인피드 블록 윗면 (0, 0.17, 0.03). 슬립시트 스테이션 (0, −0.17, 0.03), 28 mm 받침 위.
- home (0.12, 0, 0.12), `approach_clearance_m` 0.03, `carry_z` 0.132.
- 블록 중심 TCP 반경은 최대 0.230 m다. 18개 transfer가 모두 거절 없이 계획된다. 최장 phase는 transfer 34.9 s(팔레트 B 먼 칸)로 40 s 상한 안이다(`test/test_cell_omx_sim_layout_contract.py`).
- 첫 배치에서 슬립시트를 탁자 위(z 0.002)에 두었더니 `OUTSIDE_WORKSPACE`로 거절됐다. 프로필 TCP 바닥이 z 0.005이기 때문이다. 받침 위로 올렸다.

## 실행 기록

모든 회차는 home 이동(같은 owner, 관절공간 goal 하나) 뒤 계획 → 네 phase 순서다. 원본 JSON·로그는 `X:\DevTemp\rosy-cell-c3\run*`에 있다.

| 회차 | transfer | 제출 방식 | 결과 | 원인 |
|---|---|---|---|---|
| run1 | 0 (A L0 먼 칸) | runner 그대로 | approach 로컬 거절(journal `FAILED`) | owner `joint_state_sequence_mismatch` (문제 1) |
| run2 | 0 | start/advance를 joint-state 콜백 그룹에서 | 수락 0.57 s 뒤 owner HOLD `joint_state_stale`, goal 취소 | 콜백 그룹 독점 (문제 2) |
| run3 | 0 | rebind 대역 | 수락 뒤 HOLD `joint_state_stale` | feedback마다 SQLite (문제 2) |
| run4 | 0 | rebind, feedback 전부 runner로(계측) | approach 2.3 s(sim) 뒤 HOLD `joint_state_stale` | feedback 119건, runner 처리 합계 5.94 s, 최대 0.27 s |
| run5 | 0 | rebind + 첫 feedback만 | approach `SUCCEEDED` 12.5 s sim / 41 s wall; 뒤에 `gz model -p` 빈 출력으로 probe 중단 | probe 결함(재시도 추가). 이때 호스트 pytest 병행으로 RTF ≈ 0.3 |
| run6 | 3 | rebind | home goal부터 `joint_state_sequence_mismatch` | 문제 1은 runner만의 문제가 아님 |
| run7 | 3 | rebind + 첫 feedback | approach 성공, grasp 수락 뒤 HOLD `joint_state_stale` | journal 쓰기 하나가 0.64 s(`/tmp`, 문제 2) |
| run8 | 3 | rebind + 첫 feedback, journal tmpfs | 네 phase 모두 `SUCCEEDED`, probe 종료 0. **블록은 운반 중 떨어졌다** | 마찰 파지 실패 (문제 4·5) |
| run9 | 3 | grasp depth 25 mm | 계획 거절 `OUTSIDE_WORKSPACE` (pick TCP z 0.00499 < 0.005) | 부동소수 경계 |
| run10/11 | 3 | grasp depth 22 mm | grasp 뒤 transfer start-state 거절, Action HOLD `PHASE_START_STATE_INVALID` | 쥐는 힘이 손목을 비틀었다: joint5 −0.327 rad, joint4 +0.028 rad (문제 5) |
| run12 | 3 | sim aid, depth 15 mm | 블록이 home 이동 중 link5에 붙어 끌려 갔고, grasp 뒤 gripper 0.064로 hold 증명 실패 → probe가 HOLD | 시작 시 detach를 `gz topic -p` 한 번으로 보냈는데 discovery 전에 사라졌다. gz-transport로 연결 확인 + 상태 echo 확인으로 고쳤다 |
| run13 | 3 | sim aid, depth 15 mm | detach·attach 확인됨. transfer start-state 거절 | joint4 +0.019, joint5 −0.015 rad(settle 시점), 제출 시점 0.02 초과 (문제 5) |
| run14 | 3 | sim aid, depth 12 mm | 같은 거절 | joint4 +0.022, joint5 −0.023 rad |
| run15 | 3 | sim aid, depth 15 mm, 팔 start 허용오차 0.05 rad(대역) | attach 미확인(echo 없음), 운반 중 낙하. release 전 hold 재확인이 잡아 HOLD | publish 한 번이 연결 상태에서도 사라졌다. 확인될 때까지 반복하도록 고쳤다 |
| run16 | 3 | run15와 같음, attach 반복 | 아래 결과 절 | |

transfer 3은 팔레트 A 층 0의 패턴 슬롯 0(가까운 왼쪽 칸, base (0.1525, 0.0275))이다. Job 순서상 첫 transfer(0)는 먼 칸이 먼저다(far-first). transfer 0은 transfer phase 28.6 s(sim)라 RTF 0.3–0.7에서 owner의 45 s wall 시간 초과(문제 3)와 맞닿아 있어, 성공 경로 실측은 transfer 3으로 했다.

## 결과

**정상 배치(블록이 팔레트 A 슬롯 0에 허용오차 안으로 놓임)는 한 번도 얻지 못했다.** 네 phase가 ROS에서 끝까지 간 회차는 run8 하나이고, 그 회차에서 블록은 떨어졌다. 이 사실을 성공으로 적지 않는다.

목표 블록 중심 = place Step (0.1525, 0.0275), z_top 0.04 − h/2 = 0.025, yaw 0.

| 측정 | run8 (마찰, depth 15 mm) | run16 (sim aid, depth 15 mm, 팔 허용오차 0.05 대역) |
|---|---|---|
| home | 계획 8.66 s, sim 9.5 s, wall 18.6 s; gripper 0.99971 / 짝 −0.99971 | 같음(0.99996) |
| approach | 계획 12.51 s, sim 12.83 s, wall 24.15 s; 블록 변화 0 | sim 13.01 s, wall 19.44 s; 블록 변화 0 |
| grasp | 계획 3.50 s, sim 4.55 s, wall 7.97 s; gripper_joint_1 **0.400**, 짝 −0.420; `verify_held_object` 통과; 블록 11° 기울고 2.5 mm 들림 | sim 3.91 s, wall 6.40 s; gripper 0.402; hold 통과 → attach 확인(`state_echo: attached`) |
| transfer | 계획 14.44 s, sim 16.42 s, wall 33.35 s, `SUCCEEDED`; 끝에 gripper −0.0006(빈손) | sim 24.8 s(취소까지), owner HOLD **`joint_state_limit`**: gripper_joint_1 −0.420, 짝 +0.709(프로필 하한 −0.1 밖). goal 취소 |
| release | 계획 11.03 s, sim 11.72 s, wall 21.15 s; gripper 1.0000, `verify_released_object` 통과 | 실행 안 함(HOLD) |
| 최종 블록 `sim_model_pose` | (0.1077, 0.0565, 0.0197), roll −1.571: 탁자에 옆으로 누움 | 손에 붙은 채 (0.1675, 0.0219, 0.0323), pitch −0.32 |
| 배치 오차 | xy **53.4 mm**(dx −44.8, dy +29.0), z −5.3 mm, yaw −0.075 rad, tilt 1.59 rad → 불합격 | 미배치. 그 순간 중심 오차 xy 16 mm, z +7.3 mm, tilt 0.33 rad |

sim aid는 run13–16에서 detach·attach 상태 echo로 확인됐다. 하지만 블록을 link5에 고정하자 손가락이 블록을 지나 닫히며 mimic이 깨졌다. 그 결과 owner가 관절 한계 HOLD를 냈다. 이는 owner의 올바른 거절이다. 고정 관절을 쓰는 sim aid는 손가락 접촉을 끄지 못하므로 이 월드에서는 쓸 수 없다. C6에서 다시 쓰려면 grasp 뒤 그리퍼 명령을 접촉각에서 멈추거나, 블록과 손가락 충돌을 끄는 방법이 먼저 필요하다.

그리퍼 readback 판정(`sensor_revision` `omx-sim-gripper-joint-position-v1:contact>0.08:open+-0.05`):
- `object_present`는 "닫힘 목표 0.0보다 0.08 rad 넘게 위에서 멈춤"이다. 무하중 닫힘은 이번 실행에서 측정하지 않았다(대신 하중 아래 0.39–0.58, 빈손 −0.0006·0.064).
- 무하중 열림 readback 오차는 0.0003 rad 이내다. 2026-10-01에 본 0.011 rad 오프셋은 정지 상태에서 재현되지 않았다.

## 발견한 문제 (플래너·owner·runner)

1. **owner의 정확한 sequence 일치 요구가 joint-state 흐름과 경쟁한다.** `ArmCommandOwner.submit`은 `command.source_state_sequence == 최신 joint-state sequence`를 요구한다. `PickPlaceRunner._submit_phase`는 snapshot 뒤 `begin_phase`(SQLite)와 digest를 거친 다음 제출한다. 그 사이 /joint_states(약 60–100 Hz)가 들어오면 거절된다(run1). 같은 경쟁이 home goal 단건 제출에서도 났다(run6). probe는 owner lock 안에서 start-state를 다시 확인하고 최신 sequence로 rebind하는 대역 `RebindingPort`로 우회했다. C4는 운영 해법을 정해야 한다(예: owner가 lock 안에서 최신 상태로 start-state를 검사하고 바인딩, 또는 sequence 유효 창).
2. **runner의 ROS 이벤트 journal이 owner의 joint-state 구독을 굶긴다.** `RosArmCommandRuntime`의 joint-state 구독, watchdog timer, ActionClient 콜백이 노드 기본(상호 배제) 콜백 그룹을 공유한다. `PickPlaceRunner.on_ros_goal_event`는 `RUNNING_FEEDBACK`마다 SQLite를 연다(`mark_running` 실패 시 `phases()` 조회). JTC feedback은 약 100 Hz다. run4에서 3.4 s 동안 feedback 119건, 처리 합계 5.94 s, 최대 0.27 s였다. joint-state가 0.5 s 넘게 처리되지 않아 owner가 `joint_state_stale` HOLD로 goal을 취소했다. 첫 feedback만 runner에 넘기면 처리 합계가 0.04 s로 줄었다(run8). journal을 `/tmp`(overlay)에 두면 쓰기 한 번이 0.64 s까지 걸렸다(run7). tmpfs에서는 최대 0.06 s였다. C4는 runner가 RUNNING을 한 번만 기록하고, ROS 콜백 경로에서 저장소 I/O를 빼거나 joint-state 구독을 별도 콜백 그룹에 두어야 한다.
3. **owner의 시간 상한은 wall clock이고 궤적 시간은 sim time이다.** `action_timeout_s` 45 s, `max_joint_state_age_s` 0.5 s는 `time.monotonic` 기준이다. 실측 RTF는 0.3–0.95로 흔들렸고, 카메라를 켜면 0.06이었다. approach 12.5 s(sim)가 24–41 s(wall)였다. transfer 28.6 s짜리 phase는 RTF 0.6 아래에서 시간 초과다. 그래서 월드에서 카메라를 빼고 물리 step을 2 ms로 올렸다. C6는 RTF를 측정해 기록하거나 시뮬 owner의 시간 기준을 sim time으로 맞춰야 한다.
4. **D-402 §8의 그리퍼 판정 위치로는 운반 중 낙하를 못 잡는다.** run8은 grasp 뒤 `verify_held_object`(gripper_joint_1 0.400 > 0.08)와 release 뒤 `verify_released_object`를 모두 통과했고 네 phase가 `SUCCEEDED`였다. 하지만 블록은 transfer 중 떨어져 탁자에 옆으로 누웠다(최종 xy 오차 53 mm, tilt 1.59 rad). transfer 끝의 gripper 값 −0.0006은 빈손이었다. probe는 release 전에 같은 계약으로 hold를 다시 확인하도록 고쳤다. C4/D-402 개정 후보다.
5. **OMX-F 마찰 파지는 이 시뮬에서 성립하지 않는다.** 30 mm 블록에서 gripper_joint_1은 0.40–0.58 rad에서 멈췄다(URDF mesh로 추정한 손가락 끝 접촉각 약 0.2 rad보다 크다. 접촉은 손가락 뿌리 쪽이다). mimic 짝(gripper_joint_2)은 하중 아래 0.02–0.09 rad 어긋났다. 무하중 열림에서는 1.0 대비 0.0003 rad 이내였다. 그래서 2026-10-01의 0.011 rad는 정지 상태 오차가 아니라 짧은 goal 끝의 과도 오차로 본다. 깊이 15 mm: 블록이 11° 기울고 운반 중 미끄러졌다. 깊이 22 mm: 블록은 그대로이고 joint5가 −0.327 rad 비틀려 runner가 transfer를 HOLD했다. 이는 runner의 올바른 동작이다.
6. **Step z는 물건 윗면인데 OMX-F TCP는 손가락 끝이다.** `end_effector_link`는 손가락 끝에서 약 2.5 mm 안쪽이다. 윗면 TCP로 쥐면 손가락이 2–3 mm만 걸친다. probe는 `--grasp-depth`를 pick·place z에서 빼서 보정했다. 이 값을 싣는 필드가 `rosy_cell`(AGENTS: "`z_top` is the grasp height")에도 grant에도 없다. 깊이는 TCP 바닥 z 0.005와 부동소수 경계에 걸렸다(run9).
7. 기타. 열린 손가락(1.0 rad)은 끝이 TCP보다 약 20 mm 위로 들린다. 그래서 approach 동안 블록을 건드리지 않았다(블록 포즈 변화 0). 슬립시트(2 mm)는 이 그리퍼로 집을 수 없다. 이번 Job에서는 계획만 확인했다.

## C4·C6가 반영할 것

- 문제 1·2의 운영 해법(owner lock 안 rebind 또는 유효 창, feedback journal 축소·콜백 그룹 분리, journal 저장 위치).
- grasp 깊이를 담는 자리(recipe item 또는 셀 공구 오프셋)와 grant 필드. carry_z 계산과도 맞춰야 한다.
- release 전 hold 재확인을 D-402 §8 판정에 넣을지 결정.
- 파지: 마찰이 안 되면 C6도 sim aid를 쓰고, 증거에 그렇게 적는다. 슬립시트 파지 방법을 정한다.
- 시뮬 owner의 wall/sim 시간 기준과 RTF 기록. 카메라 영상(C6 증거)은 RTF를 0.06까지 떨어뜨린다.
- `CELL_TRANSFER` grant schema(C4). probe는 PICK_PLACE envelope를 검증한 뒤 `action_kind`만 바꾼 대역 grant를 썼다. RGB-D 필드는 자리채움값이며 아무 판정에도 쓰지 않았다.
