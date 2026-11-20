# CORE events 실행기 확인 (D-953 후속 3) — 2026-11-20

대상: Pinky y8xs(Pi 5, `rosy_45`). 바퀴는 움직이지 않았다. CORE가 0 `cmd_vel`만 냈고, 모든 표본에서 0이 아닌 값은 0건이었다. 실행기는 systemd drop-in `Environment=ROSY_CORE_EXECUTOR=events`로 바꿨고, 끝난 뒤 지웠다. 시뮬은 원격 모델 PC·AI PC의 Gazebo에서 Nav2·slam 확인 스크립트(저장소 밖 벤치 `nav_events_probe.py`, 별도 PR 예정)로 돌렸다. 기본값은 바꾸지 않았다.

## CPU (한 코어 %, /proc 20 s)

| 조건 | threaded | events |
|---|---|---|
| navigation 켬, 릴리스 196 + CORE dev 오버레이 | 76.8 | 25.4 |
| navigation 꺼짐, 릴리스 201 + 오버레이 | 59.4 | 15.1 |

## 확인별 결과

| # | 내용 | 결과 |
|---|---|---|
| 1 | `cmd_vel` 간격 30 s (navigation 꺼짐). p50/p99/최대 ms | threaded: 유휴 20.1/28.7/33.7, CPU 부하(3코어 busy loop) 20.0/31.2/47.6, 디스크 동기 쓰기(dd dsync 100 MB×3) 20.0/28.6/34.5. events: 20.0/24.4/34.8, 20.0/27.9/35.1, 20.0/24.1/29.9. 모두 약 50 Hz, 100 ms 이상 간격 0회. navigation 켬·유휴 12 s: threaded p99 33.8, events 28.0 |
| 2 | `/clock` | 단순 rclpy 노드에서 정지·재개·앞뒤 점프 통과(두 모드). Gazebo pause 5 s→unpause에서 CORE `cmd_vel`과 목표 진행이 재개됨(두 모드) |
| 3 | API 스레드의 서비스 호출 | Gazebo에서 `slam/start`·`save`·`stop` 모두 200. save 응답은 events 1.76 s, threaded 2.12 s. pilot recorder start/stop은 201/200(두 모드). 실기 slam_toolbox에서는 확인하지 않음 |
| 4 | 종료 | stop: threaded 3.2 s, events 0.9 s. SIGINT: 1.7 s / 1.4 s. 둘 다 exit 0, 포트 해제, 로그 순서 같음 |
| 5 | estop | 정지 상태에서 `safety/stop`·`release`가 두 모드 같음. `cmd_vel` 801개 모두 0. 고장 주입과 주행 중 estop은 하지 않음 |
| 6 | 장시간 | events 45분(navigation 꺼짐): CPU 15.1~16.2%, RSS 154.5→156.7 MB(약 25분 뒤 평탄), 경고 이상 로그 0건. 24분 별도 실행에서도 RSS가 평탄했음 |
| — | Nav2 ActionClient | Gazebo에서 목표 수락→도착, 목표→취소→CANCELED가 두 모드 모두 통과 |

## 코드 검토(읽기 전용 패널)

- 실행기 콜백 안에서 future를 블로킹으로 기다리는 곳은 없다. `save_map`과 pilot recorder의 `wait=True`는 API 스레드에서만 쓴다. `control_adapter`는 공개 실행기 API만 쓴다.
- 실행기 스레드에서 1초마다 fsync가 약 2번 일어난다(status·face inputs). 위 디스크 동기 쓰기 부하에서 `cmd_vel` 간격은 나빠지지 않았다.
- 취소 뒤 `nav.failed{error_code: CANCELED}`가 따라오는 것은 두 실행기에서 같고, 의도된 동작이다(`test_core_logic.py`). Fleet에서 운영자 취소가 FAILED로 기록되는 문제는 따로 다룬다.

## 남은 것 (기본값 전환 전, 사람이 옆에 있어야 함)

- 주행 중 `cmd_vel` 간격과 deadman·watchdog 반응. map·costmap·scan 부하와 navigation을 켠 상태에서.
- 주행 중 estop과 고장 주입.
- navigation을 켜고 수 시간 운전.
- 실기 slam_toolbox `save_map`.

같은 날 rosy-core를 재시작한 뒤 rosy-navigation이 멈춘 상태로 잰 일이 있었다. 그 표본은 위 표에서 조건을 따로 적었다([교훈](../../solutions/deployment/core-restart-leaves-navigation-stopped-2026-11-20.md)).
