# Fleet–Gazebo 실제 통신·주행 검증 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 두 대의 Gazebo 로봇이 실제 CORE/Fleet 프로세스를 통해 작업을 받고, 공유 구간에서 충돌 없이 이동하며, 장애와 재시작 후 중복 실행 없이 상태를 대조하는 것을 재현 가능한 증거로 확인한다.

**Architecture:** Fleet REST/WS와 CORE 공개 계약을 사용한다. 기존 Gazebo model-pose 기반 ideal odometry는 첫 회차의 명시적 시뮬 전제다. 독립 observer의 추가 truth 채널은 운행 판단에 주입하지 않으며, 이 회차로 장치형 위치추정 정확도를 증명하지 않는다. 단일 Fleet writer와 로봇별 CORE 최종 cmd_vel writer를 유지한다.

**Tech Stack:** ROS 2 Jazzy, Gazebo Harmonic, ros_gz_bridge, Nav2, FastAPI/WebSocket, SQLite, pytest, Linux/WSL.

**Status:** Proposed (2026-10-03). 이번 변경은 ADR·구현 계획 작성이다. `Create` 파일과 예정 CLI는 아직 구현되지 않았다.
**Origin:** 사용자가 승인한 실제 Fleet–Gazebo 연동·소통 확인 방향. 실물 주행·배포를 승인하는 문서가 아니다.

---

**ADR:** [D-426](../adr/D-426-fleet-gazebo-end-to-end-conformance.md)

## 현재 근거와 범위

- 기준 checkout main `7c60571cd`. `src/site/fleet/fleet/server/traffic.py`에는 경로 근접 판정이 있다. 빈 경로를 충돌로 보지 않는 계산을 진입 허가로 쓰면 안 된다.
- `docs/validation/map-v2-fleet-real-profile-2026-09-30/result.md`는 렌더 외형 비교이며 주행 합격 시험이 아니다. 기존 ROS-SIM 기록은 이번 회차의 합격 증거가 아니다.
- D-382 통신 적합성, D-316 명령 상관, D-395 위치 확정, D-407 복구, D-419 링크 상실을 재사용한다. D-420은 Proposed이므로 신규 Device Action 원장을 선행 의존시키지 않는다. v1은 현재 navigation Task 경로를 검증한다. D-421도 Proposed이므로 현재 구현을 대조하고 미구현 의미는 차단 조건으로 기록한다.
- 첫 대상: 한 Fleet·두 Pinky 시뮬 로봇·한 지도·교차로 하나·좁은 통로 하나. Vision은 추가 증거 경로로 별도 시험하고 미설정이면 NOT_RUN이다. OMX·Isaac Sim·여러 Fleet 서버·실물은 별도 수용 단계다.
- 링크 상실 시험에는 FleetAgent의 실제 WELCOME/heartbeat가 필요하다. REST 폴링만 하는 구성에 D-419가 적용된다고 주장하지 않는다.

## 공통 실행 규칙

1. 소스는 F:, 모든 캐시·로그·DB·세션·colcon 산출물은 `X:/DevTemp/fleet-gazebo/<run_id>/`, WSL은 `/mnt/x/DevTemp/fleet-gazebo/<run_id>/`에 둔다. `PYTHONDONTWRITEBYTECODE=1`, pytest `-p no:cacheprovider --basetemp`를 지정한다.
2. run_id별 포트·ROS domain·namespace·GZ_PARTITION·PID/시작 시각을 예약한다. Gazebo 서버/GUI/CLI·bridge·observer에 같은 고유 partition을 전달하고 누락/불일치는 READY를 거절한다. 같은 world 이름의 두 회차를 동시에 실행해 clock/pose/service/명령이 서로 섞이지 않는지 시험한다. 해당 실행의 프로세스만 종료한다. `tools/run_fleet_sim.sh`의 전체 killall과 공용 `/tmp` 탐색은 재사용하지 않는다.
3. API 경로·envelope는 기존 API Reference/schema에서 가져온다. 신규 wire 계약은 API Reference·`src/contracts/foundation/core_common/protocol/schemas.py`·생산자/소비자 시험을 같이 변경한 뒤 사용한다.
4. 시뮬 토큰은 런타임 생성하고 환경 또는 접근 제한 파일로만 전달한다. 원문 Authorization·페어링 토큰·실제 장치 주소는 보고서에 남기지 않는다. 실물 설정을 시뮬에서 쓰지 않는다.
5. Task별 실패 시험 → 최소 구현 → 관련 시험 → 명시적 파일 staging → 커밋 순서다. T1–T3 전에는 통행권 기능을 기본 활성화하지 않는다.

## Task 1 — 실행 격리와 preflight

**Files:** Create `tools/validation/fleet_gazebo/run.py`, `tools/validation/fleet_gazebo/preflight.py`, `test/test_fleet_gazebo_run_contracts.py`; modify `src/sim/gz_sim/launch/gz_multi.launch.py`; inspect `tools/run_fleet_sim.sh`, `src/sim/gz_sim/launch/map_v2_fleet_real.launch.py`.

1. 남의 프로세스 보존, 오래된 manifest 거절, 포트 충돌, overlay 부재, world/map/profile hash 누락의 실패 시험을 작성하고 실패를 확인한다.
2. 실행 루트·설정·PID 소유권·지원 버전·source/설정 hash manifest를 생성한다. run_id와 시작 시각에 결속하고 실행 루트 밖 symlink를 거절한다.
3. runner가 run별 CORE overlay와 manifest를 생성하여 로봇별 `fleet.hub_url`·`fleet.pairing_token`·manifest `fleet_pairing_token`을 일치시킨다. launch에 runner 소유 overlay/manifest/출력 루트 입력을 추가한다. Fleet은 run별 `--tasks-db`·`--events-db`와 로봇 REST/페어링과 별도 콘솔 인증으로 실행한다. 두 Agent의 실제 세션 확인 전 READY를 내지 않는다.
4. 실제 Linux 버전과 실행 인자를 기록한다. `--help`로 launch 지원을 확인하고 world/map hash와 robot identity를 대조한다.
5. clock·scan·odom·TF·Nav2 lifecycle·CORE HTTP·WS WELCOME/heartbeat를 각기 확인한다. 하나라도 불명확하면 READY를 내지 않는다.
6. `python -m pytest test/test_fleet_gazebo_run_contracts.py -q -p no:cacheprovider --basetemp X:/DevTemp/fleet-gazebo/t1` 후 커밋한다.

## Task 2 — 실제 통신과 결과 상관 (T1 필요)

**Files:** Create `tools/validation/fleet_gazebo/probe.py`, `src/site/fleet/test/test_gazebo_protocol_probe.py`; inspect/modify as needed `src/site/fleet/fleet/server/task_service.py`, `src/site/fleet/fleet/server/task_results.py`, `src/runtime/services/core_features/fleet_agent/agent.py`, `src/runtime/api_web/core_api_web/api/v1/navigation.py`.

1. identity 충돌·WELCOME 거절·계약 불일치·수락 없는 완료·다른 attempt 결과·유실/중복/역순 결과의 실패 시험을 작성한다.
2. fake HTTP/WS는 LOCAL만 증명한다. ROS-SIM에서는 실제 Fleet/CORE 프로세스 사이 페어링→heartbeat→REST goal→correlated CORE event→Fleet Task terminal projection을 확인한다.
3. 원본 관측 age와 표시 age를 분리한다. clock 변환 불가능하면 stale/unknown이다. timeout은 자동 실패/성공이 아니라 조회·이벤트 대조 대상으로 남긴다. 부작용 명령을 자동 재전송하지 않는다.
4. `python -m pytest src/site/fleet/test/test_gazebo_protocol_probe.py src/site/fleet/test/test_server_traffic.py -q -p no:cacheprovider --basetemp X:/DevTemp/fleet-gazebo/t2` 후 커밋한다.

## Task 3 — 독립 관측기와 수치 판정 (T1–T2 필요)

**Files:** Create `tools/validation/fleet_gazebo/observer.py`, `tools/validation/fleet_gazebo/assertions.py`, `test/test_fleet_gazebo_assertions.py`; modify `src/sim/description/urdf/rosy_gz.urdf.xacro`, run 소유 world 구성과 bridge; inspect `src/sim/gz_sim/scripts/swarm_bench.py`, `src/products/pinky_pro/profile/config/profile.yaml`.

1. 성공 이벤트만 있고 이동 없음·잘못된 로봇 이동·map/odom 혼용·stale pose·contact·관측 중단·pause/reset을 판정하는 실패 시험을 작성한다.
2. observer만 Gazebo pose/contact와 final cmd_vel publisher를 읽는다. 추가 observer truth를 Fleet/CORE에 주입하지 않는다. 기존 ideal odometry 전제는 manifest에 기록한다. run 소유 model/world에 contact sensor·Gazebo contact system을 구성하고 Gazebo model pose/contact를 직접 수집한다. 의도적 접촉을 검출하는 양성 대조가 통과하지 않으면 contact 0건 단언을 금지한다. publisher 이름뿐 아니라 endpoint/GID와 프로세스 소유권도 확인한다.
3. 시뮬 목표치: 위치 오차 ≤0.10 m, 방향 오차 ≤10°, |v|≤0.01 m/s·|w|≤0.03 rad/s를 1 s 연속 유지. 로봇 footprint 경계 간 여유 ≥0.10 m, contact 0건. 중심점 거리만 쓰지 않는다.
4. 관측 20 Hz 이상, 샘플 사이 최대 이동량을 보수적으로 반영한다. 원본 관측 빈 구간 >0.15 s면 충돌 판정 INCONCLUSIVE다. 물리 진행/도착 시간은 sim time, 네트워크 시한은 monotonic으로 분리한다. pause/reset은 새 epoch이며 이전 물리 단언을 이어 붙이지 않는다.
5. 단언마다 PASS/FAIL/NOT_RUN/INCONCLUSIVE·관측원·단위·시계·임계값·원본 위치를 남긴다. 의도적 잘못된 실행이 판정기를 FAIL시키는지도 확인한다.
6. `python -m pytest test/test_fleet_gazebo_assertions.py -q -p no:cacheprovider --basetemp X:/DevTemp/fleet-gazebo/t3` 후 커밋한다.

## Task 4 — 공유 구간 진입 허가와 점유 (T2–T3 필요)

**Files:** Create `src/site/fleet/fleet/server/traffic_reservations.py`, `src/site/fleet/test/test_traffic_reservations.py`; inspect/modify `src/site/fleet/fleet/server/traffic.py`, `src/site/fleet/fleet/server/task_service.py`, `src/site/fleet/fleet/server/task_store.py`, `src/site/fleet/fleet/server/dispatch_admission.py`; wire 변경 시 API Reference/schema와 양쪽 시험도 변경한다.

1. 동시 진입·빈/낡은 경로·다른 map revision·위치 미확정·허가 만료·Fleet 재시작·취소 경합의 실패 시험을 작성한다.
2. 기존 Task DB 트랜잭션과 dispatch admission을 확장한다. competing dispatcher를 만들지 않는다. 구간 상태는 FREE→RESERVED→OCCUPIED→RELEASING→FREE, 불명은 UNKNOWN. Fleet만 기록 writer다.
3. 구간 ID·지도 revision·진입/출구·안전 대기점·footprint 여유를 명시한다. 진입 후 시간 만료/링크 상실만으로 FREE가 되지 않는다. 신선한 출구 이탈 관측과 실행 결과를 대조해야 해제한다.
4. v1은 안전 대기점까지 goal과 허가 후 출구까지 goal로 분할한다. 실제 Nav2 경로가 승인 corridor 밖으로 재계획되면 진입 전 취소/HOLD한다. 로봇 측 실행 경로까지 제약을 보장하지 못하면 T4는 HOLD다. goal 분할만으로 진입 gate가 됐다고 주장하지 않는다.
5. grant는 Task/attempt·robot·구간·지도 revision·expiry·기존 dispatch generation에 결속한다. 수락 측에서도 일치·만료·세대를 검증해야 한다. 신규 robot-side gate가 필요하면 D-18 절차로 명시적으로 구현한다. Fleet 메모리 검사만으로 stale command 방어 완료를 주장하지 않는다.
6. expiry는 실제 footprint 진입 시한이다. 수락 후 대기하다 만료된 grant는 진입 경계에서 다시 검사해 밖에서 정지한다. RESERVED도 이전 실행이 구간 밖에서 비활성·정지했음을 확인하기 전 FREE로 풀지 않는다. 불명은 UNKNOWN이다. 수락 뒤 장애물로 만료까지 지연시킨 후 장애물을 치우는 반증 시험을 추가한다.
7. 우선순위는 승인 순서와 robot ID로 안정화한다. 대기 >60 s면 운영자 대조 필요로 남긴다. 자동 후진은 하지 않는다.
8. `python -m pytest src/site/fleet/test/test_traffic_reservations.py src/site/fleet/test/test_server_traffic.py -q -p no:cacheprovider --basetemp X:/DevTemp/fleet-gazebo/t4` 후 커밋한다.

## Task 5 — 장애 주입과 재시작 대조 (T4 필요)

**Files:** Create `tools/validation/fleet_gazebo/scenarios.py`, `test/test_fleet_gazebo_scenario_contracts.py`; reuse `src/runtime/services/test/test_fleet_loss.py`, `src/runtime/gateway/test/test_fleet_loss_wiring.py`, 기존 Task persistence와 D-407 recovery 시험; Create `src/sim/gz_sim/scripts/command_watchdog.py`, `src/sim/gz_sim/test/test_command_watchdog.py`; modify sim launch/base input remap. 이 bridge는 CORE의 operational cmd_vel writer를 늘리지 않고 sim base 입력만 감시한다.

1. injector는 해당 run 소유 프로세스/프록시만 대상으로 한다. REST-only·WS-only·둘 다 blackhole을 별도 회차로 실행한다. shutdown 시험을 packet blackhole 증거로 쓰지 않는다.
2. 현재 Gazebo DiffDrive에는 command watchdog이 보장되지 않는다. CORE와 별도 수명인 sim-base bridge가 최신 cmd_vel을 monotonic으로 감시하고 기본 0.30 s 만료 시 base 입력을 zero로 만든다. clock pause에도 만료는 작동한다. CORE kill·bridge 재시작·입력 단절을 시험한다. bridge 자체 사망 시 actuator 정지까지 보장되지 않으면 그 결함을 HOLD로 남기고 전체 process-crash safety를 주장하지 않는다.
3. 반개방 WS·지연 답·중복/역순 이벤트·Fleet/CORE 재시작·위치 stale·교차로 내 정지·전체 취소/dispatch 경합을 재현한다. CORE 재시작은 Gazebo base watchdog 정지까지 관측한다.
4. D-419 기본 STOP은 마지막 허브 수신 후 timeout+timer 여유(기본 5.0 s+0.2 s) 내 정책 적용을 확인한다. 실제 정지는 별도로 속도와 감속 시간을 측정한다. 둘을 같은 시한으로 쓰지 않는다. 첫 시뮬 profile은 v_max=0.15 m/s, w_max=0.5 rad/s로 제한하고 정책 적용 후 정지 시간 ≤0.50 sim s, 이동 ≤0.05 m, 회전 ≤0.25 rad를 모두 요구한다. CORE kill은 입력 만료 ≤0.30 monotonic s 뒤 같은 정지 제한을 요구한다. 실행 전 speed·감속·샘플 여유와 대기점 정지 거리를 manifest에 고정한다. 미충족은 FAIL이며 실물 한계로 일반화하지 않는다.
5. 재접속 후 CORE 활성 navigation correlation/실행 상태와 Task/attempt·위치·점유를 조회하고 불명 구간은 UNKNOWN이다. 부작용을 재전송하지 않는다. 재개 전 옛 세대 발행을 차단하고, 이전 실행을 조회/취소하여 비활성·신선한 정지를 확인한다. 이 확인을 못 하면 새 하달을 막는다. 링크 상실 timeout보다 짧은 Fleet 재시작과 옛 수락/완료 지연을 시험한다. 재개는 그 대조 뒤 명시적 재승인에 따른 새 실행이다.
6. `python -m pytest test/test_fleet_gazebo_scenario_contracts.py src/runtime/services/test/test_fleet_loss.py -q -p no:cacheprovider --basetemp X:/DevTemp/fleet-gazebo/t5` 후 커밋한다.

## Task 6 — 실제 Linux 회차와 증거 보고 (T1–T5 필요)

**Files:** Create `tools/validation/fleet_gazebo/report.py`, `docs/validation/fleet-gazebo-conformance-<date>/result.md`; update 바뀐 모듈 `logs.md`, 증명한 `progress.md` gate만 변경.

1. 지원 ROS/Gazebo·overlay·world를 preflight로 확정한다. colcon 산출물은 `/mnt/x/DevTemp/.../{build,install,log}`로 보낸다. 운영 로봇에는 연결하지 않는다.
2. 예정 CLI: `python tools/validation/fleet_gazebo/run.py --robots 2 --scenario all --output-root /mnt/x/DevTemp/fleet-gazebo`. T1에서 구현·`--help`·실패 exit code 검증 전 실행 가능한 명령으로 보고하지 않는다.
3. M01–M08 각각 고정 seed 3개 ×3회, 회차마다 시나리오 검증의 필수 단언 PASS를 요구한다. 주행 판정과 검증 시나리오 판정을 별도 필드로 저장한다. M08의 의도적 관측 누락은 주행 INCONCLUSIVE가 정확히 기록되고 잘못된 성공이 0이면 시나리오 PASS지만, 해당 주행은 계속 INCONCLUSIVE다. 평균·대표 영상으로 실패를 숨기지 않는다. crash/timeout/관측 누락은 합격이 아니다.
4. 원본 rosbag·JSONL·DB·영상·스크린샷은 X:에 둔다. public 보고서는 secret 검사 후 commit/설정/hash/판정 요약만 담는다. 재현 입력·원본 위치·보존 담당자를 명시한다.
5. 문서/판정기 시험, `python tools/harness/rosy_harness.py generate`, `lint` 후 SOURCE/LOCAL/ROS-SIM을 따로 보고한다. DEVICE/FIELD는 승격하지 않는다.

## 회차별 수용 행렬

| ID | 시나리오 | 필수 단언 |
|---|---|---|
| M01 | 두 대 등록·개별 목표 | identity/지도 일치, attempt 수락·이동·도착·결과 상관, 다른 로봇 오작동 0 |
| M02 | 교차로 동시 접근 | 동시 점유 0, 대기점 정지, 출구 확인 후 후속 진입, 둘 다 완료 |
| M03 | 좁은 통로 마주 접근 | 밖에서 대기, contact 0, footprint 여유, 둘 다 완료 |
| M04 | 출구 장애물·위치 stale | 새 진입 금지, 이유 기록, 불명 Task 자동 재생 0 |
| M05 | REST/WS/전체 blackhole | 적용 범위·monotonic 시한, 실제 정지, 점유 자동 해제 0 |
| M06 | Fleet/CORE 재시작·결과 역순 | 중복 부작용 0, 옛 결과로 새 Task 완료 0, UNKNOWN·대조 |
| M07 | 취소/발행 경합·비상 정지 | 늦은 수락 처리, 응답/실제 정지 분리, 래치 해제 후 자동 재개 0 |
| M08 | pause/reset·관측 누락 | 잘못된 성공 0, 시계 분리, 불명 회차 INCONCLUSIVE |

## 재검토한 결정과 완료 조건

- 경로 전체 잠금은 첫 두 대 시험을 단순하게 하지만 불필요한 대기를 늘린다. v1은 구간 예약, 시간 기반 예약은 후속이다.
- goal 분할의 corridor 준수는 T4 반증 시험이다. 실패하면 로봇 측 진입 gate부터 보완하며 데모로 우회하지 않는다.
- 수치 임계값은 시뮬 수용 목표이며 실물 안전 기준이 아니다. T3에서 센서 주기·footprint·속도를 기록하고 임계값을 몰래 완화하지 않는다.
- 문서 완료는 ADR/계획/검토/harness다. 구현 완료는 T1–T6와 M01–M08 전 회차 증거다. 서로 구분한다.