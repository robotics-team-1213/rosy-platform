# 인계 — 차로 주행·규제(횡단보도·신호)·Gazebo 연속 바퀴 (2026-10-15)

다른 컴퓨터에서 이어 갈 사람을 위한 문서다. 세션 rosy-49(전 rosy-44/rosy-c5와 다른 세션; 차로·규제 담당)이 썼다. 모든 작업은 local main에 착지했고(마지막 33c7bfd16), 푸시는 rosy-4c가 맡는다.

## 1. 지금 상태 (local main 기준)

- Gazebo map_v2_fleet, 로봇 한 대, SDK enforce, Fleet 연결: **m29에서 15바퀴 연속**(실행기 시간 한도로 끝남). 횡단보도 16번 멈춰 살피고 건넘, NW 회전교차로 출구 15회, W3 굽이 출구 16회 모두 차로 가운데, stuck 0. 주행 일지: `docs/plans/2026-10-12-gazebo-lane-lap.md`.
- 그 뒤 신호 계획(m32–m34)과 두 대(m33–m35)에서 나온 결함을 고쳐 착지했다(아래 2절). **고친 main으로 다시 돈 결과(m36 신호, m37 두 대)는 아직 받지 못했다** — 모델 PC 실행기 산출물 `/home/ai/rosy-test/lap-main-a/artifacts/m36`, `m37`에서 확인할 것.

## 2. 이번에 착지한 것 (모두 독립 안전 검토 LAND)

| 주제 | ADR | API |
|---|---|---|
| 횡단보도 살핌 구역: 벽 오검출(차로 방향 틀, 느슨한 판독 제외, 빠진 틱은 마지막 차로 유지, 마지막 차로 방향 기억) | D-573 개정 5 (6–8항) | – |
| 굽이 시작 lead: 고정 송신 여유 제거, 현장 설정 `fleet.trip.bend_send_s`(기본 0.01 s) | D-507 | – |
| 교차로 회전 출구를 지도 방향으로(`map_entry` on turns, 기본 꺼짐) | D-759 개정 1 | v1.231 |
| 굽이: 지도 진입 방향이 카메라 기준점을 대신(TRACKING·|오차| ≤ 0.3일 때만) | D-759 노트 | – |
| keeper 근거리 직선(가파른 굽이선 앞) — `corner_turning`일 때만 | – | – |
| 짧은 odom 공백 중 기동 유지(제자리면 같은 기동) | D-507 주석 14 | – |
| Fleet 규제 대기 예외(`_wait_bound`, CORE `regulation_wait`) | D-763 8 | – |
| 규제 capability `lane_crosswalk_gate`·`lane_junction_signal` — 필드 없는 구버전 로봇은 경고만, false는 거절 | D-763 10 | v1.238 |
| trip 중 신호 무응답이면 우회전 대체 대신 정지; 통행권 HOLDING 대기는 기동 시계 정지(EXPIRED/NONE·횡단보도는 15 s 상한) | D-620 노트, D-760 개정 4 | v1.239 |
| Fleet: 한 구역을 여러 간선으로 지나는 경로에서 진입 방향 유지(`blocks.py`) | D-525 | – |
| 학습 모델 역할 검사: floor gate에 필요한 역할이 없는 모델은 시작 때 거절, 이유를 로그·디버그 묶음에 | D-588 | – |
| 순간 차로 상실·조향 튐에서 경로 유지 — **점검과 결정 방향만**, 구현 없음 | D-768 (Proposed) | – |

## 3. 남은 일 (우선순위 순)

1. **m36·m37 결과 확인.** 신호 계획에서 초록에만 진입하는지, 두 대에서 서쪽 횡단보도 오검출이 사라졌는지, B_W4 `no_anchor`가 몇 번 나는지.
2. **B_W4 `no_anchor`의 근본 원인.** NW 회전교차로 출구에서 조금 치우치면 추종이 흔들려(오차 0.6–1.0) 0.15 m 뒤 B_W4 굽이의 기준을 못 잡는다. 후보: Fleet가 Rosy Cam 자세와 지도 차로의 옆 거리를 `map_entry`에 실어 보내는 옆 위치 확인(새 필드, D-759 개정 필요), 또는 NW 출구 정밀도 개선.
3. **D-768 구현.** 튄 프레임을 "없는 프레임"으로 보고 D-476 이어 가기로 넘김, `low_confidence`를 이어 가기 사유에 추가(D-476 개정), SIM에서 `bridge_enabled: true`로 m29 대비 측정. 장치에서 켜는 것은 사용자·안전 검토 결정.
4. **학습 칠 바퀴.** SIM 모델(model-v1, 실제 카펫으로 학습)은 SIM 바닥에서 1바퀴 안에 차로를 놓친다(m30 `drivable`, m31 `lane_marking`+gate 끔). 학습 칠 한 바퀴는 실제 로봇에서 하거나 SIM 영상으로 학습한 모델이 필요하다. SIM 실행기는 대체 칠로 둔다(모델은 이제 시작 때 이유와 함께 거절된다).
5. **장치 쪽 확인 전 조건.** `bend_send_s`는 현장 Wi-Fi에서 잰 송신 시간으로 설정. `bend_map_entry_enabled`·`turn_map_entry_enabled`는 SIM 한 바퀴 뒤에만 켬. 장치의 `site_floor_map_id`·`ir_guard_enabled`가 꺼져 있어 굽이 통과·차로 호·이어 가기가 모두 꺼진다(D-768 Context 4).
6. **크기 단위.** Fleet `server/trip_checks`(trip_admission만) 338/342 — 다음에 trip_admission을 키우는 변경은 먼저 `crosswalks_on`·`signals_on`·규제 capability 검사를 `server/trip_regulation`으로 옮겨야 한다(판정문). `line_follow/crosswalk/gate.py`는 600줄 근처.

## 4. Gazebo 실행기 다루는 법 (모델 PC)

- 실행기 자리: 모델 PC의 `/home/ai/rosy-test/lap-main-a`(스크립트 `runner-mNN.py`, `probe-mNN.py`, `run-mNN.sh`, `loop-mNN.sh`, `native-pose-bootstrap-mNN.py`, 산출물 `artifacts/mNN`, 끝나면 `mNN.done`), 빌드 `/home/ai/rosy-test/lap-main-side`(`source`, `install`, `build.sh`), launch overlay `overlay-side/share/gz_sim`(학습 칠 대상 `lane_marking` + IR 보정).
- 새 회차는 이전 회차 스크립트를 `sed s/mOLD/mNEW/`로 복사한다. 실행기 설정: `trip_lease_ttl_s` 8.0(D-760 1: 통행권 5 s보다 커야 함), `bend_map_entry_enabled`·`turn_map_entry_enabled` True, 신호 계획 시험은 `junction_signal_enabled` True와 Fleet 사이트 설정의 `fleet.traffic.signals`(실행기의 서쪽 일방통행 덮어쓰기 때문에 접근 이름은 `west:fwd`).
- 진단: 설치된 crosswalk 모듈 끝에 붙이는 기록기(`xwalk-mNN.jsonl`)와 Fleet 사본의 굽이 송신 기록(`bend-sends-mNN.jsonl`)은 **한 번만** 붙인다(두 번 붙이면 CORE가 죽는다). 이름만 `sed`로 바꾼다.
- 소스 보내기: 노트북→모델 PC 큰 전송은 끊기므로 8 MB 조각으로 보내고 체크섬을 맞춘다(`git archive --format=tar.gz main`을 `split -b 8m`).
- 실행 전 포트 31251–31253이 비었는지, 다른 세션의 pytest로 부하가 높지 않은지 본다. 실행은 `nohup setsid`로 띄운다. 같은 ssh 줄 안에서 자기 명령을 `pgrep -f`/`pkill -f`로 찾지 않는다.
- 시험(pytest)은 노트북에서 돌리지 않는다: `python tools/remote/remote_pytest.py --log-dir <X:/DevTemp/...> -- <paths>` 후 `python test/known_failures.py <log>`.

## 5. 함께 맞춘 것 (다른 세션과)

- API 번호: v1.237 rosy-e9 조각 4, v1.238 regulation-capabilities, v1.239 signal-no-fallback, v1.240 rosy-e9 proposal-read-scope, v1.241 rosy-84 instruction-pose-stamp(D-767 A).
- `tools/harness/adr_gaps.txt`의 D-767 줄은 rosy-84가 D-767을 착지할 때 지운다.
- D-767(앞길 미리보기) 답: 굽이 시작은 pose_stamp로(P3a 불필요), 횡단보도 기준점은 CORE의 가까운 가장자리, P2 감속은 min으로만, P3b(끊김 중 무장)는 미룸, route_context를 먹이고 trip 중엔 context.next를 대체.
