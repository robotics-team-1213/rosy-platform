# Rosy Cell C3 Gazebo 단일 pick/place · 2026-10-02

## 범위와 판정

[C3 하위 계획](../../plans/2026-10-02-rosy-cell-c3-gazebo.md)의 ROS-SIM 실행 기록이다. 해석 IK 플래너(D-402) → `PickPlaceRunner` → 단일 `ArmCommandOwner` → `/arm_controller/follow_joint_trajectory` 경로로 Rosy Cell 데모 Job의 `CELL_TRANSFER` 하나를 Gazebo에서 실행했다. Fleet 경로(C4), 종단 Job(C6), 실물·DEVICE·FIELD는 범위 밖이다.

**판정: C3 ROS-SIM HOLD. 경로는 끝까지 돌았지만 블록을 목표에 놓지 못했다.** 결함을 고친 C3b 재실행은 단일 transfer를 대역 없이 xy 0.30 mm로 놓았다([C3b](#c3b--2026-10-02--결함-수정-뒤-재실행)).

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

## C3b · 2026-10-02 · 결함 수정 뒤 재실행

**판정: 단일 `CELL_TRANSFER`(인피드 → 팔레트 A 층 0 슬롯 0) ROS-SIM 통과. C3 대역은 모두 걷었고, 남은 것은 표시된 sim attach aid와 sim 그리퍼 센서, C4 범위의 grant 봉투·stop fence다. 층 채우기(3회 연속)는 배치 자체는 3/3 허용오차 안이지만, 마지막 배치가 이웃 블록을 밀어 층 판정은 실패다.**

Fleet 경로(C4), 종단 Job(C6), 실물·DEVICE·FIELD는 여전히 범위 밖이다. Action 부모는 `RUNNING`으로 남는다. `CELL_TRANSFER` 완료 journal은 C4다.

### 고친 것 (커밋)

| 항목 | 커밋 | 설계 |
|---|---|---|
| A1 sequence 경쟁 | `bc6a9955` | `TrajectoryCommand.start_state_window`(관절 → 기대값, 허용오차). owner가 lock 안에서 자기 최신 joint state로 같은 검사를 하고 그 sequence에 묶는다. 오래된 state는 HOLD, 벗어난 state는 `start_state_deviation`, 본 적 없는 sequence나 이미 쓴 sequence는 거절이다. home 단건 goal도 같은 창을 쓴다. |
| A2 feedback journal | `1df18501`, `3d4a693b` | RUNNING은 goal마다 한 번만 기록하고, 이후 feedback은 메모리에서 세기만 한다. 수는 terminal result에 `feedback_events`로 남긴다. joint-state 구독과 watchdog은 한 콜백 그룹, ActionClient는 다른 그룹이다. 모든 호출자는 MultiThreadedExecutor다. Gazebo run9에서 대기열의 GOAL_ACCEPTED를 실시간 feedback이 앞질러 owner가 `action_failed` HOLD를 냈다. replay가 끝날 때까지 event lock을 쥐게 고쳤다. |
| A3 시계 | `e9d5c1b6` | `RosArmCommandRuntime(owner_clock="sim")`: owner 시계와 joint-state 시각이 노드 시계(sim time)다. steady 시계는 `wall_clock_bound_factor`(프로필 4.0) × sim 한계의 바깥 상한이다. 멈춘 sim은 `joint_state_stale_wall_clock`, 기는 sim은 `action_wall_timeout`으로 HOLD한다. Pilot은 기본값 `steady` 그대로다. |
| A4 release 전 hold | `c832a53d` | `CellTransferPlan` runner는 `gripper_readback`과 `held_object_id`를 요구한다. release 제출 직전에 `verify_held_object`를 다시 한다. 실패하면 `ITEM_LOST_IN_TRANSIT` HOLD이고 release는 나가지 않는다. |
| A5 손목 처짐 | `2b534abf`, `4316246b` | 프로필 `phase_start_state_tolerance_rad.{transfer,release}.<팔 관절>` (grasp 뒤만, 기준 이상, 0.1 rad 이하). 실측 처짐은 아래 표에 있다. 기준 0.02로 충분해 덮어쓴 관절은 없다. |
| B1 파지 깊이 | `a31ebde1` | 레시피 `box.grasp_depth`(물건마다; 슬립시트는 0). 상자 Step z = 윗면 − 깊이, `carry_z` 매달린 높이 = `height − grasp_depth`. 요청 필수 필드 `grasp_depth_m`. D-401·D-402 보강. |
| B2 폭 맞춤 닫힘 | `bd56fa7a`, `2de7832d` | gap(q) = 2(o + x sin q + y cos q). o는 URDF 손가락 축이다. 접촉점 (x, y)는 Gazebo 보정값이다(아래). 닫힘 목표는 폭 − `squeeze_m` 3 mm다. release는 폭 + 10 mm까지만 열고, carry_z로 올라간 뒤 완전히 연다. |
| B3 sim aid | `cb58f71f` | 부모 `omx_f::link5`, 자식 블록인 DetachableJoint다. readback이 hold를 증명한 뒤에만 `entity/system/add`로 붙이고, release 직전에 뗀다. 월드 파일에는 표시만 있고 플러그인은 없다. |

### 재현 정보 (C3b)

| 항목 | 값 |
|---|---|
| 소스 | `feat/rosy-cell-c3-gazebo` `f63bb564` |
| 이미지 | C3와 같다: `rosy-omx-pilot:recording-local` `sha256:faeb86d6…efb2`. 재빌드하지 않았다. |
| 월드 | `omx_cell_workcell_sim_aid.sdf` sha256(LF) `afe637e6a3081148e54a1cbf6776adce633111329b8ec83b4ec6f3573229aa31` (본 월드와 머리 주석만 다르다) |
| profile_revision | `d639cbf7fcf1d8a64bc53ed0b631608d3f1bed9277206bb1db28f196dc7b4e64` |
| cell_sha256 / recipe_sha256 | `a5d4221f…4549` / `8b620e59…bd0c` |
| 컨테이너 | `rosy-cell-c3-sim`, C3와 같은 격리(`--network none`, `ROS_DOMAIN_ID=77`, 저장소 read-only) |
| 원본 | `X:\DevTemp\rosy-cell-c3\c3b\` (`final-single/`, `final-three/`, run1–run18, diag1–diag6) |

```powershell
docker exec rosy-cell-c3-sim bash -c "source /opt/ros/jazzy/setup.bash; source /opt/omx_ws/install/setup.bash; `
  export ROS_DOMAIN_ID=77 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST; `
  python3 /repo/deploy/robot/omx/probe_cell_transfer.py --out /scratch/final-single --transfers 3"
# 3회: --transfers 1,2,3 (Job 순서: 슬롯 1, 2, 0)
```

probe에는 대역 플래그가 없다(`--submit-from`, `--feedback-to-runner`, `--arm-start-tolerance`, `--grasp-depth`, `--sim-aid` 삭제). journal은 overlay `/tmp`에 둔다.

### 단일 transfer 결과 (`final-single`, transfer 3 → 슬롯 0)

| phase | 계획 s | sim s | wall s | RTF | feedback | gripper_joint_1 / 짝 | 다음 phase 시작 대비 최대 팔 편차 |
|---|---|---|---|---|---|---|---|
| home | 8.66 | 9.50 | 14.73 | 0.65 | — | 1.0000 | — |
| approach | 11.38 | 12.02 | 16.90 | 0.71 | 321 | 1.0000 / −1.0000 | 0.0000 |
| grasp | 2.55 | 2.85 | 4.55 | 0.63 | 73 | **0.4162** / −0.4181 (목표 0.3804) | 0.0003 (joint5) |
| transfer | 13.52 | 14.20 | 23.41 | 0.61 | 444 | 0.4194 / −0.4190 | 0.0019 (joint5) |
| release | 9.64 | 10.17 | 21.94 | 0.46 | 396 | 1.0000 / −1.0000 | — |

- 배치 오차: xy **0.30 mm**(dx −0.30, dy +0.02), yaw **0.0009 rad**(π 법), 윗면 z **0.0 mm**, 기울기 0. 허용오차 5 mm / 0.05 rad / 2 mm를 넘지 않는다.
- 그리퍼: 30 mm 블록의 닫힘 목표 0.3804, 보정 모델의 접촉각 0.4069, hold 판정 문턱 = 목표 + 0.0132. grasp 뒤 readback 0.4162 → `verify_held_object` 통과 → aid 부착이 확인됐다(`attached` echo). 부착 1 s 뒤 0.4188, release 직전 0.4194다. 손가락은 블록을 지나 닫히지 않았다. runner의 release 전 재확인은 `object_present: true`였다.
- journal: 네 phase `SUCCEEDED`. feedback은 phase마다 73–444건이었고, 저장소 쓰기는 RUNNING 한 번뿐이다. owner HOLD 0회.

### 3회 연속 (`final-three`, Job 순서 transfer 1, 2, 3 → 슬롯 1, 2, 0)

| transfer → 슬롯 | 배치 xy / yaw / 윗면 z | grasp readback | phase sim s (approach/grasp/transfer/release) | RTF | 최대 팔 편차 | 앞서 놓은 블록 |
|---|---|---|---|---|---|---|
| 1 → 슬롯 1 (0.2075, 0.0275) | 0.31 mm / 0.0007 / 0.0 | 0.4165 | 12.0 / 3.2 / 18.9 / 13.8 | 0.80–0.95 | 0.0025 | — |
| 2 → 슬롯 2 (0.1525, 0.0725) | 0.14 mm / −0.0039 / 0.0 | 0.4160 | 12.0 / 4.3 / 16.7 / 11.4 | 0.58–0.62 | 0.0049 | 슬롯 1: 0.3 mm |
| 3 → 슬롯 0 (0.1525, 0.0275) | 0.31 mm / 0.0042 / 0.0 | 0.4162 | 12.1 / 3.3 / 19.0 / 10.4 | 0.31–0.44 | 0.0014 | 슬롯 1: 0.3 mm, **슬롯 2: 24.9 mm** |

- 세 배치는 모두 그 순간 허용오차 안이었다. 그러나 transfer 3의 transfer phase(슬롯 0으로 하강)에서 슬롯 2 블록이 (0.1489, 0.0896, yaw −0.33)으로 밀렸다. 손가락이 y 방향으로 닫히므로, +y 손가락이 슬롯 0과 슬롯 2 사이 15 mm 틈에 들어간다. Gazebo의 실효 손가락은 그 틈보다 넓다. probe는 앞서 놓은 블록을 phase마다 다시 읽어 이를 잡았고 종료 코드 2를 냈다. **층 채우기 판정: 실패.**
- RTF 0.31–0.44(transfer 3)는 같은 시각 호스트 pytest 실행과 겹친 값이다. sim-time owner와 4배 wall 상한 아래에서 HOLD는 없었다.
- 손목 처짐(A5 근거): run10·11·12·15·18의 13회(검사 26번)에서 계획된 transfer/release 시작 대비 팔 관절 최대 0.0115 rad(joint4 ≤ 0.0099, joint5 ≤ 0.0056)였다. 최종 4회는 ≤ 0.0049다. 기준 0.02 rad에 1.7배 여유가 있다.

### 실행 기록 (C3b)

| 회차 | 내용 | 결과 |
|---|---|---|
| run1 | 메시 사상(0.060, −0.00915), 닫힘 목표 0.223 | 손가락이 0.408에서 멈췄다. C3의 블록 쪽 aid 부착 뒤 손가락이 지나 닫혀 owner `joint_state_limit` HOLD |
| diag1 | 접촉 순간 link 포즈 | 메시 손가락은 블록 중심에서 24 mm(면에서 9 mm), 볼록 껍질도 19.7 mm 떨어져 있었다. Gazebo의 실제 접촉은 메시보다 넓다 |
| diag3 | 20/30/40 mm 블록 보정 | gripper_joint_1 0.3187 / 0.4072 / 0.4956 → 접촉점 (0.0543, −0.01703), 잔차 0.03 mm |
| run2 | 보정 사상 + 3 mm squeeze, 블록 쪽 aid | 네 phase 성공. 부착 순간 블록이 pitch −0.15 rad 기울어 xy 7.6 mm 불합격 |
| run3 | squeeze 1 mm | transfer 중 손가락 튐 → `joint_state_limit` HOLD. 블록 쪽 aid를 버렸다 |
| run4–8 | 로봇 쪽 runtime aid | 손가락이 블록에 닿지 않고 0.52에서 멈췄다. 빈손 시험(diag4/diag6): joint5 ≈ 0이면 0.0까지 닫히고, joint5 = 1.5이면 0.46–0.51에서 손목에 걸린다. yaw 0 인피드 pick은 joint5 ≈ π/2를 요구하므로 인피드를 yaw π/2로 돌렸다. 엔티티 이름만으로는 플러그인이 붙지 않아 id로 바꿨다 |
| run9 | | approach `SUCCEEDED` 뒤 owner `action_failed`: GOAL_ACCEPTED replay 경쟁(A2 보강 `3d4a693b`) |
| run10 | 깊이 10 mm | 첫 정상 배치 xy 0.21 mm |
| run11 | 3회, 슬롯 0 먼저, release 완전 열림 | 배치 3/3 통과. 그러나 슬롯 0 블록이 팔레트 밖으로 옆으로 누웠다(release 손가락 휩쓸기) → release를 폭 + 10 mm로 제한 |
| run12 | 같은 순서, 부분 열림 | 슬롯 0 블록이 22 mm 밀렸다(yaw −0.73) |
| run13/14/17 | | 첫 부착 echo를 놓쳤다(부착은 실제로 됐다) → 감시 노드를 probe 수명 동안 유지하고, 재명령 fallback을 넣었다 |
| run15 | Job 순서 1,2,3, gap 15 mm | 배치 3/3 통과. transfer 3이 슬롯 2 블록을 15.7 mm 밀었다 |
| run18 | 같은 순서, gap 20 mm(시험만, 되돌림) | 슬롯 2 블록이 21.7 mm 밀렸다. gap을 넓혀도 해결되지 않는다 |

### 남은 대역과 표시

- **SIM AID**(표시): 런타임 DetachableJoint, hold 증명 뒤에만 붙인다. 운반 중 낙하 여부는 시험하지 않았다. aid가 붙어 있는 동안 블록은 떨어질 수 없다.
- **A4(release 전 hold 재확인)는 단위 시험으로만 검증했다**(`test_omx_cell_transfer_runner.py`: 잃음·오래됨·다른 물건·readback 실패 → `ITEM_LOST_IN_TRANSIT`). Gazebo에서는 aid 때문에 운반 중 낙하가 일어나지 않는다. 그래서 이 검사는 매 회차 통과만 기록됐고, 잡아낸 적은 없다.
- **SIM 그리퍼 센서**(표시): gripper_joint_1 위치 기준. hold = 목표 + squeeze 각의 절반 이상. open = 1.0 ± 0.05.
- **인피드 재적재**: 반복 transfer는 다음 블록을 인피드에 spawn한다(sim 준비 단계, 동작 아님).
- **C4 범위**(동작 아님): PICK_PLACE로 검증한 grant 봉투에 `action_kind`만 바꾼 것, 항상 열린 stop fence.

### C4·C6로 넘길 것

1. **이웃 간섭.** Gazebo의 실효 손가락이 레시피 gap 15–20 mm보다 넓다. 2×2 층에서는 마지막 배치가 이웃을 민다. 레시피/셀 검증에 공구 폭 대비 gap 검사가 필요하고, 플래너에는 충돌 장면이 필요하다(D-402 §7).
2. **사상 출처.** 접촉점은 Gazebo 보정값이다. 고정된 메시만으로는 30 mm에서 0.25 rad를 예측하지만, Gazebo는 0.41에서 멈춘다(메시가 아직 5–9 mm 떨어진 상태). 실물은 자기 측정값이 필요하다.
3. **손목 자기 간섭.** joint5 ≈ π/2에서 손가락이 0.46–0.51 rad 아래로 닫히지 않는다. 플래너가 모르는 제약이다. 인피드 yaw로 피했을 뿐이다.
4. **C3 결과의 재해석.** C3 월드의 블록 쪽 aid는 로드 때 블록을 link5에 붙였다가 뗐다. 그 뒤로는 위 손목 간섭이 나타나지 않았다(C3·diag3의 joint5 ≈ π/2 pick이 0.40에서 블록에 닿음). 원인은 확인하지 않았다. 보정은 그 상태에서 했고, joint5 ≈ 0인 최종 회차의 접촉(0.416, 3 mm squeeze)과 맞는다.
5. 슬립시트 파지 방법 없음(폭 2 mm → `GRIPPER_WIDTH_INVALID`). `CELL_TRANSFER` grant schema와 완료 journal(C4).

### 리뷰 수정 뒤 (2026-10-02, FIX REQUIRED → 수정)

- **B1 블로커**(성공한 goal이 `action_failed`로 끝남): goal 응답 전에 온 feedback을 버퍼에 두었다가 GOAL_ACCEPTED 뒤에 하나로 재생한다(`e63c0b42`). ROS 종료 status는 journal보다 먼저 기록한다(`7ae0f65c`). 첫 20회 반복 중 Fleet-to-ROS 시험이 1회 실패해서 찾은 결함이다.
  - WSL Jazzy 반복: `wsl -e bash -lc 'source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=77 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST; cd <worktree>; for i in $(seq 25); do python3 -m pytest -q src/products/omx/adapter/test/test_omx_ros_runtime.py src/products/omx/adapter/test/test_omx_ros_runtime_vendor_sim.py src/products/omx/adapter/test/test_omx_fleet_ros_actionserver.py src/products/omx/adapter/test/test_omx_ros_camera_runtime.py; done'`
  - 결과: **25/25 통과**(회당 8 passed, 1 skipped). 원본: `X:\DevTemp\rosy-cell-c3\c3b\wsl-loop2.txt`.
- minor 1–5·7은 단위 시험과 함께 고쳤다: 시작 창 상한·포함 범위, 시계 역행 HOLD, release 폭 거절, `fingertip_overhang_m`, 수락 레시피 폭·깊이. minor 8은 `logs.md`에 적었다.
- **Gazebo 단일 재실행**(`review-single`, `7ae0f65c` 소스, transfer 3 → 슬롯 0)
  - 배치 오차: xy **0.11 mm**, yaw 0.0006 rad, 윗면 z 0.0 mm, 기울기 0 → 통과.
  - phase sim s: approach 11.89, grasp 2.93, transfer 14.27, release 10.02. RTF 0.35–0.82(다른 세션의 WSL Gazebo와 겹침).
  - grasp readback 0.4165, 부착 뒤 0.4191, release 전 재확인 `object_present: true`. 최대 팔 편차 0.0032 rad. owner 최종 `ready`.
  - profile_revision `b14c5430…eee`. `carry_z` 0.117(fingertip overhang 2.57 mm < 매달린 높이 15 mm라 변하지 않음).

