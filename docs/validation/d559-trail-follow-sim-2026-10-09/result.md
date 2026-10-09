# D-559 리더 자취 따라가기 Gazebo SIM (모델 PC), 2026-10-09

증거 등급: **부분 — SIM 지표 측정 전에 중단.** 두 대 Gazebo·CORE·Fleet 무장 경로는 모델 PC에서 떴고, 그 실행이 제품 결함 하나를 찾았다(아래 결함 1, 고침). 경로 편차·간격·정지 지표는 **아직 재지 못했다.** 모델 PC가 19:00 KST 무렵부터 tailscale에서 오프라인이 되어(ssh 시간 초과, `tailscale ping` 응답 없음) 다시 돌릴 수 없었다. [D-559](../../adr/D-559-leader-trail-follow-path-replay.md) 합격선(최대 편차 ≤ 0.10 m, RMS ≤ 0.04 m, 접촉 0)은 **판정하지 않았다.**
노트북에서는 Gazebo를 돌리지 않았다. 실물 로봇은 건드리지 않았다. 대상: `feat/swarm-trail-follow` 스냅숏 `f22da9fed`(r1–r4), 결함 1 수정은 `0492324b9`.

## 시험 장치 (`evidence/`)

- `run_sim.sh`: 모델 PC 작업공간(`~/rosy_trail_ws`, 브랜치 HEAD의 `git archive`, `colcon build --symlink-install --packages-up-to gz_sim core control description`)에서 `gz_multi.launch.py robots:=2 mode:=nav core:=true headless:=true world_name:=rosy_swarm_bench.world nav_composition:=true`, 리더 `rosy_01` (-1.8, -2.2, 0), 팔로워 `rosy_02` (-2.4, -2.2, 0). 로봇마다 Nav2 + AMCL(map 프레임)과 CORE. `systemd-run --user --scope -p MemoryMax=8G`.
- `trail_sim.py`(rclpy 없음): 두 CORE의 리더 스트림 `frame`이 둘 다 `map`일 때까지 기다린 뒤 무장한다.
  - 기본: Fleet `fleet.bench` `FormationSession(Formation.TRAIL, spacing 0.6, max_speed 0.18)` — 실제 Fleet 무장(답의 `mode` 확인)과 릴레이(`fleet/swarm/relay.py`).
  - `--direct`: `POST /api/v1/swarm/follow {mode: trail, distance: 0.6}`(명단 없음)와 `relay.py`와 같은 일을 하는 작은 릴레이(리더 `/ws/swarm/pose` 프레임을 그대로 팔로워 `/ws/swarm/reference`로, 멈출 수 있음). Fleet 대형은 늘 `members`를 보내 스트림 단절이 D-20 승계(follow 종료)가 되므로, SWM-004 HOLD→이어 가기는 이 경로로만 잴 수 있다.
  - 리더는 CORE teleop(MANUAL, 10 Hz, 0.12 m/s): 직진 2.0 m → 왼쪽 호 R 0.4 m 90° → 직진 0.8 m → S자(왼쪽·오른쪽 R 0.5 m 각 90°) → 직진 0.6 m → 정지 10 s → 제자리 오른쪽 90° → 직진 2.0 m(시작 4 s 뒤 릴레이 5 s 끊음) → 정지 12 s. 약 100 s.
  - 참값: `gz topic -e -t /world/rosy_swarm_bench/dynamic_pose/info --json-output`, 로봇마다 50 Hz로 솎음.
- `analyze.py`: 참값만으로 팔로워 위치와 리더가 실제로 달린 폴리라인(무장 때 팔로워 위치에서 리더 시작점까지의 직선 포함) 사이 거리(최대·RMS·p95), 중심 간 최소 거리, 경로 간격(리더 호 길이 − 팔로워 투영) 최소, 접촉 대용(중심 거리 < 2 × URDF 회전 반경 0.165 m), 리더 정지 구간의 팔로워 속도·간격, 끊김 뒤 `holding`·정지·재출발 시간, 경로 그림 `paths.png`.

## 실행 기록

| run | 경로 | 결과 |
|---|---|---|
| r1 | Fleet | 런치 실패: `seed_initialpose.py` 실행 비트 없음(symlink 설치가 저장소의 100644를 그대로 씀). 작업공간에서 `chmod +x`로 우회, 저장소는 고치지 않음 |
| r2 | Fleet | CORE 기동 실패: `rosy.contracts` 이름공간 패키지가 PYTHONPATH에 없음. `run_sim.sh`에 `*/src/rosy` 경로 추가(d495 SIM과 같은 방법) |
| r3 | Fleet | Fleet `TRAIL` 무장 성공(`rosy_02` `distance 0.6, lateral 0.0`, 답 `mode: trail`). 그러나 무장이 Nav2/AMCL보다 먼저(런치 15 s 지연) 일어났고, 팔로워는 끝까지 `own_pose_not_map`·`reference_frame_odom`으로 서 있었다(자취 0 m — 안전 쪽으로 멈춤). 릴레이 5 s 끊김에서 팔로워는 명단 승계로 follow를 끝냈고 세션 `HOLDING`, `resume`은 `rosy_02 is no longer following`으로 거절됐다(D-20 그대로). 편차 지표 없음 |
| r4 | `--direct` | Gazebo 서버 segfault(exit 139) 직후, 리더 스트림이 pose가 하나도 없는 CORE에서 `frame: "map"`과 (0, 0, 0)을 보냈다 → **결함 1**. 대기 조건이 그 값에 속아 바로 무장을 시도했고 CORE가 이미 내려가 연결 실패로 끝남 |
| r5 | — | 모델 PC 오프라인(19:00 무렵부터). 실행하지 못함 |

모델 PC 부하: r3 시작 때 load 3–6, r4 무렵 다른 세션의 pytest와 겹쳐 8–35(24코어, 메모리 15 GB). 다른 세션 테스트와 이 SIM, 이 브랜치의 원격 pytest가 동시에 돌았다. 오프라인의 원인은 확인하지 못했다.

## 결함·발견

1. **(고침, `0492324b9`) pose가 아직 없는 CORE의 리더 스트림이 `frame: "map"`을 보냈다.** `StateManager._pose_frame` 초기값이 `"map"`이라 첫 pose 전의 (0, 0, 0)이 map 좌표로 나갔다. trail 팔로워가 그 표본으로 자취를 시작하면 엉뚱한 점에서 시작한다(1.5 m 넘으면 `trail_join_too_far`로 끝나지만, 가까우면 그대로 잇는다). 수정: 초기값 `None`(pose 없음), trail은 `frame == "map"` 표본만 쓴다(필드가 없는 옛 리더도 trail에서는 멈춘다). 단위 시험 추가.
2. **(설계 확인, ADR 4항에 기록) Fleet 대형의 스트림 단절은 HOLD가 아니라 승계다.** `FormationSession`은 늘 `members`를 보내므로 팔로워는 `stream_timeout_ms` 뒤 follow를 끝내고 선다(0 twist). 이어 가려면 운영자가 다시 무장한다. 명단 없는 follow만 HOLD 후 이어 간다.
3. (장치 메모) 모델 PC 작업공간은 저장소 스크립트 실행 비트와 `rosy` 이름공간 경로를 손으로 맞춰야 한다. 앞선 SIM 기록들과 같은 우회다.

## 모델에 없는 것

- Wi-Fi 지연·손실(릴레이는 같은 기계 루프백), 실제 바퀴 미끄럼·카펫, 장치 CPU(20 Hz 틱의 지터), Rosy Cam 위치, 두 로봇 사이의 실제 위치 일치. AMCL은 시뮬 LiDAR로 돈다.
- 장애물: 방에 기둥 둘뿐이고 경로는 그 밖이다. D-422 몸체 정지 판정은 이 SIM에서 리더 꽁무니만 본다(섹터 모드, `rosy_default`).

## 남은 일 (사람·다음 세션)

1. 모델 PC가 돌아오면 `bash run_sim.sh r5 --direct`(HOLD→이어 가기, 편차 지표)와 `bash run_sim.sh r6`(Fleet `TRAIL`)을 돌리고 `analyze.py`의 `summary.json`으로 이 기록에 결과 표를 더한다. 작업공간은 `0492324b9` 이후 스냅숏으로 다시 만든다.
2. 합격선 판정은 그 뒤다. 그 전에는 trail의 경로 정밀도에 대한 SIM 주장은 없다. 호스트 단위 시험(운동학 두 대)에서는 호 R 0.4·S자 편차 < 0.03 m, 제자리 90° 모서리 < 0.08 m이다(`test_swarm_trail.py`).
