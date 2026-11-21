# CORE events 실행기 주행 확인 (D-1058 남은 확인 일부) — 2026-11-20

대상은 Pinky geg6(`rosy_42`)이고 릴리스는 2026.11.20-204다(CORE 기본 events). 사람이 옆에 있는 상태에서 사용자가 허락했다. 시험은 CORE teleop(MANUAL)으로 했고, 0.06 m/s 직진·후진만 했다(재승인 측정값 0.064 m/s 이하).

- 기록은 로봇 쪽에서 `<ns>/cmd_vel`(CORE 최종 출력)과 `odom` twist를 벽시계로 남겼다.
- threaded는 systemd drop-in `ROSY_CORE_EXECUTOR=threaded`로 비교했고, 끝난 뒤 지웠다.
- rosy-navigation은 켜져 있었다(Nav2 active, `ROSY_NAVIGATION_BACKEND=slam`).

## 주행 중 `cmd_vel` 간격

| 시나리오 | events Hz / p99 / 최대 ms | threaded Hz / p99 / 최대 ms |
|---|---|---|
| 직진 3 s + 후진 3 s | 50.1 / 25.8 / 36.6 | 49.1 / 34.9 / 40.4 |
| 직진 중 E-Stop | 50.1 / 24.8 / 27.5 | 49.6 / 34.7 / 45.4 |
| 직진 중 명령 끊김 | 50.1 / 24.6 / 29.6 | 49.0 / 39.3 / 54.0 |

두 모드 모두 100 ms 이상 간격은 0회였다.

## 정지 반응

시간은 마지막 0이 아닌 `cmd_vel`에서 잰다.

| 경우 | events: 0 출력 / 바퀴 정지 | threaded: 0 출력 / 바퀴 정지 |
|---|---|---|
| E-Stop(`POST /safety/stop`) | 20 ms / 203 ms | 15 ms / 191 ms |
| 명령 끊김(teleop watchdog 300 ms) | 18 ms / 176 ms | 18 ms / 194 ms |

- E-Stop 뒤 teleop 요청은 모두 거절됐다(events 15건). `/safety/release` 뒤 모드는 IDLE이었다.
- **고장 주입(CORE SIGSTOP 1.0 s, 후진 중, events):** bringup deadman(0.5 s)이 바퀴를 SIGSTOP 뒤 683 ms에 세웠다. CONT 뒤에는 운전자가 계속 보내던 teleop이 다시 적용됐다. 이것은 의도된 동작이다(조작자가 계속 누르는 상태).
- threaded 고장 주입은 무효다. SIGSTOP 시점에 이미 정지 상태였다(24 ms).

## 하지 않은 것

- **navigation을 켠 수 시간 운전:** 사람이 계속 지켜볼 수 없어 하지 않았다.
- **실기 slam `save_map`:** 하지 않았다.
- **Nav2 목표 주행 중 간격:** teleop만 했다.

## 부수 영향

시나리오마다 전진과 후진의 합이 0이 아니어서 geg6가 약 +x로 10~15 cm 밀렸다(S3 정지선 앞). 다음 Nav2 정지 정확도 판단에서 이 이동을 빼야 한다. 원시 기록은 노트북 `$ROSY_SCRATCH/core-load-1120/motion/*.json`에 있다.
