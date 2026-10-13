# D-559 리더 자취 따라가기 Gazebo SIM, 2026-10-09

증거 등급: **ROS-SIM, 두 대 Gazebo + 로봇마다 CORE·Nav2·AMCL, 참값 채점.** 합격선(최대 편차 ≤ 0.10 m, RMS ≤ 0.04 m, 접촉 0)은 세 번 모두 통과했다. DEVICE·현장 수용이 아니다. D-395 위치 판정(loc_assist)은 이 시험에서 껐다(아래 "모델에 없는 것").
노트북에서는 Gazebo를 돌리지 않았다. 실물 로봇은 건드리지 않았다. [D-559](../../adr/D-559-leader-trail-follow-path-replay.md)

- **실행 호스트: AI PC**(24코어, 메모리 15 GB, 사용자 지정). 다른 사람의 작업과 같이 쓰는 기계라 load 평균이 실행 전후 2–44 사이를 오갔다(채점 run 시작 때 3.7–7.7). 모든 프로세스는 `systemd-run --user --scope -p MemoryMax=8G -p CPUQuota=1000%`와 `nice -n 10` 아래서 돌았고, run마다 끝에 이 run의 `GZ_PARTITION` 프로세스를 모두 내렸다.
- 첫 시도는 모델 PC(OMEN)였다(r1–r4, 아래). 모델 PC는 19:00 KST 무렵 tailscale에서 오프라인이 되어 이어 쓰지 못했다.
- 대상: 브랜치 `feat/swarm-trail-follow` 스냅숏 `141e31a0c`(`git archive`, 결함 1 수정 포함) + 이 기록과 같은 커밋의 SIM 스크립트. 제품 코드는 스냅숏 그대로다.

## 결과

경로: 리더 `rosy_01` (−1.8, −2.2, 0)에서 CORE teleop 0.12 m/s로 직진 2.0 m → 왼쪽 호 R 0.4 m 90° → 직진 0.8 m → S자(R 0.5 m 왼쪽·오른쪽 각 90°) → 직진 0.6 m → **정지 10 s** → 제자리 오른쪽 90° → 직진 2.0 m(시작 4 s 뒤 **릴레이 5 s 끊음**) → 정지 12 s. 팔로워 `rosy_02`는 0.6 m 뒤에서 시작, `distance`(경로 간격) 0.6 m, `max_speed` 0.18 m/s, `stream_timeout_ms` 1000. 리더가 실제로 달린 길(참값) 8.2 m.

| run | 무장 | 표본 | 최대 편차 | RMS | p95 | 최소 중심 거리 | 최소 경로 간격 | 접촉 대용 | 리더 정지 중 팔로워 | 릴레이 5 s 끊음 |
|---|---|---|---|---|---|---|---|---|---|---|
| r7d | `--direct` (명단 없음) | 2614 | **0.066 m** (제자리 90° 모서리) | **0.014 m** | 0.025 m | 0.541 m | 0.600 m | 없음 | 속도 0, 경로 간격 0.628 m | `holding` 1.20 s, 정지 1.12 s, 재개 뒤 0.14 s에 다시 움직임, HOLD 동안 속도 0 |
| r9d | `--direct` (반복) | 2620 | **0.041 m** | **0.019 m** | 0.034 m | 0.524 m | 0.582 m | 없음 | 속도 0, 경로 간격 0.608 m | `holding` 1.14 s, 정지 1.00 s, 재개 뒤 0.16 s, HOLD 동안 속도 0 |
| r8f | Fleet `FormationSession(TRAIL)` | 2611 | **0.032 m** | **0.018 m** | 0.028 m | 0.552 m | 0.600 m | 없음 | 속도 0, 경로 간격 0.611 m | 명단 승계로 follow 종료(D-20), 정지 1.09 s, Fleet `resume` 거절(`no longer following`) — 설계대로 |

- 편차 = 팔로워 참값 위치에서 리더 참값 폴리라인(무장 때 팔로워 위치→리더 시작점 직선 포함)까지의 거리, 무장부터 끝까지 50 Hz. 접촉 대용 = 중심 거리 < 2 × URDF 회전 반경(0.165 m). 최소 경로 간격 0.582 m(r9d)는 gap 0.6 m보다 1.8 cm 짧다 — 두 로봇의 AMCL 위치 차이만큼이다(정지 때는 0.608 m).
- 가장 큰 편차는 r7d·r9d 모두 제자리 90° 모서리 직후(무장 뒤 70.6 s)다. 리더가 꼭짓점을 만들면 pure pursuit가 앞보기 0.20 m만큼 깎는다. 단위 시험의 운동학 상한 0.08 m 안이다. 호와 S자 구간은 2–3 cm 안이다(그림).
- 스트림 끊김: 팔로워는 `stream_timeout_ms` 1 s 뒤 0 twist로 섰다(바퀴 정지 1.0–1.12 s). 명단 없는 follow는 HOLD(`hold_reason: stream_lost`)를 지나 표본이 돌아오자 새 명령 없이 이어 갔다. 끊긴 동안 리더가 간 약 0.6 m 직선은 직선 구간이라 실제 길과 같다. Fleet 대형은 늘 `members`를 보내므로 D-20 승계가 follow를 끝낸다(ADR 4항).
- 리더 정지: 팔로워는 gap에서 섰고 정지 10 s 동안 참값 속도 0이었다.
- 그림: `evidence/runs/<run>/paths.png`. 요약: `evidence/runs/<run>/summary.json`, 사건: `events.jsonl`.

## 시험 장치 (`evidence/`)

- `run_sim.sh`: `gz_multi.launch.py robots:=2 mode:=nav core:=true headless:=true world_name:=rosy_swarm_bench.world` (6 × 6 m 방, 기둥 둘), 로봇마다 Nav2 + AMCL(map 프레임)과 CORE. 이 run들은 `NAV_COMPOSITION=false LOC_ASSIST=false ENV_SCRIPT=~/rosy_trail_ws/overlay_env.sh`로 돌았다.
- `trail_sim.py`(rclpy 없음): 두 CORE의 리더 스트림 `frame`이 둘 다 `map`일 때까지 기다린 뒤 무장한다(r3 문제 수정). D-395 상태가 있으면 둘 다 `LOCALIZED`까지 기다리고, `CANDIDATES`면 참값에 가장 가까운 로봇 자신의 후보를 `source: human`으로 답한다(이번 채점 run에서는 loc_assist를 꺼서 쓰이지 않았다).
  - 기본: Fleet `fleet.bench` `FormationSession(Formation.TRAIL, spacing 0.6, max_speed 0.18)` — 실제 무장(답의 `mode` 확인)과 `fleet/swarm/relay.py`.
  - `--direct`: `POST /api/v1/swarm/follow {mode: trail, distance: 0.6}`(명단 없음)와 `relay.py`와 같은 일을 하는 작은 릴레이(리더 프레임을 그대로 전달, 멈출 수 있음).
  - 참값: `gz topic -e -t /world/rosy_swarm_bench/dynamic_pose/info --json-output`, 로봇마다 50 Hz.
- `analyze.py`: 위 지표와 그림(시스템 numpy/matplotlib으로 돌린다).

## AI PC 환경 기록 (남의 기계 — 추적용)

sudo는 비밀번호가 필요해 쓰지 않았다. 시스템 패키지는 설치·변경·제거하지 않았다. 바꾼 것은 전부 `~/rosy_trail_ws` 안이다.

- 이미 있던 사용자 공간 ROS/Gazebo 오버레이 `~/nav_overlay`(풀어 둔 deb: gz-sim 8.15.0, ros_gz, nav2, slam_toolbox, ruby)를 **읽기만** 했다. `~/rosy_trail_ws/overlay_env.sh`가 그 경로를 환경 변수로 잡는다(LD_LIBRARY_PATH, AMENT_PREFIX_PATH, RUBYLIB, GZ_CONFIG_PATH(경로를 바꾼 yaml 복사본 `~/rosy_trail_ws/gzconf`), GZ_SIM_* 플러그인 경로, `OGRE2_RESOURCE_PATH`, `GZ_RENDERING_RESOURCE_PATH`).
- `gz_multi`는 `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`를 쓰는데 이 기계에는 없었다. 루트 없이 내려받아 풀었다:
  `apt-get download ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-cyclonedds ros-jazzy-iceoryx-binding-c ros-jazzy-iceoryx-hoofs ros-jazzy-iceoryx-posh` → `dpkg-deb -x <deb> ~/rosy_trail_ws/ovl2`. 버전: rmw-cyclonedds-cpp 2.2.4-1noble.20260911.095700, cyclonedds 0.10.5-1noble.20260225.142613, iceoryx-binding-c 2.0.6-1noble.20260225.140829, iceoryx-hoofs 2.0.6-1noble.20260225.055330, iceoryx-posh 2.0.6-1noble.20260225.135341. 내려받은 deb는 `~/rosy_trail_ws/debs`.
- 두 대가 한 기계에서 DDS 참여자를 40개 가까이 만들어 cyclone 기본 `MaxAutoParticipantIndex`(9)가 모자랐다 → `CYCLONEDDS_URI`로 120(오버레이 스크립트 안).
- 스냅숏 안에서만 고친 것(저장소는 그대로): `integrations/simulation/gazebo/CMakeLists.txt`의 `find_package(ros_gz REQUIRED)`·`find_package(gz_ros2_control REQUIRED)`를 선택으로, `find_package(gz-sim8)`·`(gz-plugin2)`를 주석(오버레이 gz-gui가 Qt5 QuickControls2를 찾지 못함 → 램프 플러그인 빠짐, 주행과 무관). `scripts/*.py` 실행 비트(`chmod +x`, 저장소 모드는 100644).
- CORE Python 의존성: 같은 기계의 원격 pytest venv `site-packages`를 `~/rosy_trail_ws/pydeps`로 복사(numpy 2.x라 분석은 시스템 python으로).

## 첫 시도(모델 PC, r1–r4)와 결함

| run | 결과 |
|---|---|
| r1 | `seed_initialpose.py` 실행 비트 없음 → 작업공간에서 `chmod +x` |
| r2 | `rosy.contracts` 이름공간 경로 없음 → `run_sim.sh`에 `*/src/rosy` 경로 추가 |
| r3 | Fleet `TRAIL` 무장 성공(`distance 0.6, lateral 0.0`, 답 `mode: trail`). 무장이 AMCL보다 먼저라 팔로워는 끝까지 `own_pose_not_map`·리더 비-map 프레임으로 서 있었다(안전 쪽). 끊김에서 승계로 follow 종료 |
| r4 | **결함 1** 발견 뒤 모델 PC 오프라인 |

AI PC에서 채점 run 전 시도(r5, r6d)는 위 환경 문제(cyclone 없음, ogre2 경로, 참여자 수, D-395 `CANDIDATES`에서 사람 결정이 3 s 확인에서 `inject_rejected`)로 무장 전에 멈췄다. 채점에 쓴 것은 r7d·r8f·r9d다.

1. **(고침, `0492324b9`) pose가 아직 없는 CORE의 리더 스트림이 `frame: "map"`을 보냈다.** `StateManager._pose_frame` 초기값이 `"map"`이라 첫 pose 전의 (0, 0, 0)이 map 좌표로 나갔다. 수정: 초기값 `None`, trail은 `frame == "map"` 표본만 쓴다. 단위 시험 추가.
2. **(설계 확인, ADR 4항) Fleet 대형의 스트림 단절은 HOLD가 아니라 승계다.** r3·r8f에서 확인. 명단 없는 follow만 HOLD 후 이어 간다(r7d·r9d).
3. (환경 메모, 미해결) 이 SIM 호스트에서 D-395 사람 결정이 3 s 주입 확인을 통과하지 못했다(`SUSPECT inject_rejected`, 부하 큰 시점). D-559 문제가 아니라 채점 run에서 loc_assist를 껐다. D-395 쪽에서 다시 볼 일이다.

## 모델에 없는 것

- **D-395 위치 판정**(loc_assist 끔): 팔로워 무장의 `LOCALIZED` 문은 상태가 없어 열려 있었다(장치 기본과 다르다). AMCL은 시드 초기 자세에서 시작했다.
- 두 로봇의 위치는 각자의 AMCL이다. 참값과 2 cm 안팎으로 맞았고, 그 차이가 편차와 간격에 들어 있다. 현장(Rosy Cam·장치 AMCL)의 위치 일치는 재지 않았다(ADR 열린 항목 1, 2).
- Wi-Fi 지연·손실(릴레이는 같은 기계 루프백), 실제 바퀴 미끄럼·카펫, 장치 CPU, 램프 플러그인.
- 장애물: 경로 위에 없다. D-422 판정은 섹터 모드(`rosy_default`)로 리더 꽁무니만 보았고 막힌 적이 없다. 장애물 앞 정지·재개는 호스트 시험만 있다.
- 3대 이상, 사슬, 차로 위 주행.

## 재현

```bash
# AI PC: ~/rosy_trail_ws = git archive 스냅숏 + colcon build --symlink-install --packages-up-to gz_sim core control description
cd ~/rosy_trail_ws
LOC_ASSIST=false NAV_COMPOSITION=false ENV_SCRIPT=$HOME/rosy_trail_ws/overlay_env.sh \
  systemd-run --user --scope -p MemoryMax=8G -p CPUQuota=1000% nice -n 10 \
  bash src/rosy-platform/docs/validation/d559-trail-follow-sim-2026-10-09/evidence/run_sim.sh r7d --direct
# Fleet 대형: 마지막 인자 없이 (r8f)
```

전체 기록(참값 `truth.jsonl`, `swarm.jsonl`, 런치 로그)은 저장소 밖 `X:\DevTemp\trail-follow\runs\ai_runs.tgz`(r7d·r8f, 500,908 bytes, SHA-256 `0f372edb9739e029cc1d42ee4e33468eae0bc2313a7f6dd44f120bf54666c9f5`)와 `ai_r9d.tgz`(259,265 bytes, SHA-256 `904818be72cb721c5b20e52efba25d0d454e73a5a606c9b55ed3b3ddc30221d8`), 그리고 AI PC `~/rosy_trail_ws/runs`에 있다.
