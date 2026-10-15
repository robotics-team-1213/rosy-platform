# 두 로봇 Fleet + Gazebo 차선 trip을 커밋된 구성으로 (2026-10-15)

브랜치 `fix/sim-multi-robot-trips`. 목적: D-763 SIM 점검이 AI PC의 개인 rig(`~/rosy-test/d763-sim`) 없이 커밋된 launch와 실행기로 돌게 한다. 근거는 `X:\DevTemp\d763-sim-check\results.md` 「Recipe gaps」 1–4와 그 `rig/`다.

## 실행 방법

시험 PC에서만 돈다(D-584). 노트북에서 Gazebo나 pytest를 돌리지 않는다.

```bash
# 커밋된 HEAD를 보내 빌드하고 두 로봇 + Fleet을 띄워 로봇마다 차선 trip 하나를 보낸다.
# 역할 이름을 쓰려면 ROSY_SIM_HOSTS에 역할을 붙인다(private/lab-hosts.json에 sim_hosts가 없다).
ROSY_SIM_HOSTS="rosy@100.98.162.71=model ai@100.108.76.123=ai" \
  python tools/remote/remote_sim.py --host model --minutes 60 --log-dir X:/DevTemp/sim-multi/run-N \
  fleet_trips -- --render gpu        # 모델 PC는 GPU 렌더(llvmpipe는 거기서 죽는다)
# AI PC: --host ai ... -- --render cpu
```

결과는 `<log-dir>/out/trips/result.json`(`pass`, 로봇별 `states`, `moved_m`), `api-log.jsonl`, `launch.log`, `fleet.log`다. 종료 코드 0은 두 trip이 모두 `arrived`이고 10 s 뒤 자세가 장소에서 Fleet `arrive_lane_m`(0.15 m) 안이라는 뜻이다(`short_m`). 시험 PC에서 직접 돌릴 때는 ROS와 colcon install을 source한 셸에서 `python3 tools/sim/fleet_trips.py --out DIR [--render gpu]`.

## 고친 것 (gap → 원인 → 변경)

1. **trip이 모두 `lane_guard_stale`로 섰다.** multi_real launch에 IR 바닥 ray와 observer IR 교정이 없었다. `map_v2_fleet_multi_real.launch.py`가 로봇마다 `/<ns>/ir/{left,mid,right}` 브리지와 `sim_ir_floor.py`를 띄우고, observer에 `gz_multi_parts.SIM_IR_CALIBRATION`을 준다. 값은 센서 모형에서 나온다: SIM 바닥은 항상 `FLOOR_RAW` 2000(반사율 없음)이라 검정 끝점, ADC 포화 4000(`hazard.py`의 유효 IR < 4000)이 흰 끝점. `test_sim_sensors.py`가 두 값을 출처에 고정한다. 따라서 SIM IR은 선을 보지 못하고(가드 `clear`), 신선한 교정 IR만 증명한다. rig의 `learned_paint_target: lane_marking` 변경은 launch 인자(기본은 장치 기본값 `lane_marking`, `drivable` 선택 가능)로 옮겼다. `drivable`은 `line/lane_guide` 생산자가 있어야 하는데 제품에는 아직 없다(rig는 `sim-lane-guide.py` 대역을 썼다).
2. **onnxruntime 없음.** D-373 1항에 따라 onnxruntime은 CORE 요구사항에 넣지 않는다(별도 prefix, payload runtime id 밖). `remote_sim.py` DEPS가 장치와 같은 `learned-perception-requirements.txt`(해시 고정)를 `$PYDEPS/learned`에 깔고 `ROSY_LEARNED_SITE`로 넘긴다. 저장소에 모델이 없으므로 `learned_lane_pointer`는 선택이고, 비면 observer는 denoise 페인트로 돈다. 그 실행은 학습 페인트 실행이 아니다.
3. **pydantic 2.13.5(CORE) / 2.13.4(Fleet).** 맞추지 않았다. CORE 쪽은 장치 런타임 pin(D-189)이고 Fleet 쪽은 현장 PC 설치 pin이라 SIM 때문에 운영 pin을 바꾸지 않는다. PyYAML, uvicorn, websockets도 서로 다르다. 대신 한 인터프리터에 CORE pin을 깔고 Fleet pin 가운데 CORE가 이름을 갖지 않은 것(oauthlib, zeroconf …)만 더한다. `remote_pytest.py` VENV가 장치 세트에 하는 것과 같고, CI 시험 venv에서 Fleet이 그 pin으로 돈다.
4. **커밋된 두 로봇 trip 실행기 없음.** `tools/sim/fleet_trips.py`(+ `remote_sim.py` 벤치 `fleet_trips`). D-426 `Reservations`로 domain 80–99·포트를 정하고, 잠금은 remote_sim의 것을 쓰거나 혼자 돌 때 `~/rosy-jobs`에 쓴다. CORE 오버레이는 rig/m29와 같은 규제 설정(line authority, map entry, route context, path 정지, IR guard, site floor, junction signal, sensor adapter enforce), Fleet은 `fleet_sim_camera_site.yaml` + authority + trip lease(ttl 8 s). Fleet은 D-725 `NativeGazeboMapPosePort`를 묶은 내부 `fleet` 모드로 띄운다(rig bootstrap의 D-763 harness 경로와 bend 장소 패치는 넣지 않았다). trip은 site map 1판에 미리 넣은 stop 장소 하나(차선 trip의 끝은 장소여야 한다, `LANE_END_NOT_A_PLACE`): rosy_01은 동쪽 도로 남쪽 직선(동향), rosy_02는 서쪽 도로 서쪽 직선(남향), 각각 0.42 m(Fleet `pass_window_m` 0.3보다 길게), 모서리·횡단보도 밖(서쪽은 주차 분기까지). 정리는 `FLEET_TRIPS_RUN` 표시가 있는 자기 자식 프로세스만 끈다.

## 상태 (2026-10-15)

- 커밋: `6268b8b71`, `5cba01019`, `ca7be811d`, 이 문서. 착지·푸시 안 함.
- 원격 회귀: 관련 8개 파일 exit 0, `known_failures` NEW 0 (`X:/DevTemp/sim-multi/pytest-2/run-1.txt`, 모델 PC). 첫 실행(`pytest-1`)에서 launch 인자 기본값 누락 NEW 2를 잡아 `5cba01019`로 고쳤다.
- 실제 Gazebo 실행 `run-1`(AI PC, ca7be811d, `--render cpu`, ai 상한 4 CPU/4 GB): 빌드·두 CORE 응답·두 로봇 Fleet `LOCALIZED`(D-725 native pose)·두 카메라 front status가 모두 참이었다. 두 계획은 200이었지만 출발이 `422 TRIP_MODE_UNSUPPORTED {reason: LANE_END_NOT_A_PLACE}`로 거절돼 아무도 움직이지 않았다. 차선 trip의 끝은 장소여야 한다. `48b5c9c85`가 trip 끝마다 stop 장소를 site map 1판에 미리 넣는다. `run-2`(AI PC, 48b5c9c85): 두 trip 모두 출발 200, Fleet `started/running → arrived`, 정리 뒤 남은 프로세스 0. 그러나 두 로봇은 0.031 m만 움직였고 장소까지 0.269 m가 남았다. 원인: Fleet 차선 도착 규칙(`trip_progress._arrived`)은 "CORE가 이 장소의 stop을 잡고 남은 거리 ≤ `pass_window_m`(0.3, `trip_ports.py`)"도 도착으로 친다. 0.30 m trip은 시작부터 그 창 안이라 stop이 바로 나가고 1 s 만에 `arrived`가 됐다. 벤치의 FAIL 판정은 맞다(이동 기준은 이제 spawn에서 잰다; 전에는 첫 poll 표본이 늦어 같은 0.031이 우연히 맞았다). 다음 커밋이 TRIP_M을 0.42 m로 늘렸다. 창 밖에서 출발하므로 움직이기는 하지만, 같은 규칙이면 장소 0.3 m 앞에서 `arrived`가 날 수 있다. 그러면 이동 0.12 m < TRIP_M/2라 FAIL로 드러난다. 그 경우는 실행기가 아니라 Fleet 도착 규칙(창 안 stop을 도착으로 치는 것)의 문제로 보고 Fleet 소유자와 정한다. 로그: `X:\DevTemp\sim-multi\run-2\out\trips\`.

- `run-3`(AI PC, 9852e2ec2, TRIP_M 0.42): 두 로봇이 Fleet 통행권 아래 실제로 달렸다(rosy_01 0.143 m, rosy_02 0.168 m). 두 trip 모두 `arrived`였고 정리 뒤 남은 프로세스는 0이다. 그러나 `arrived`를 본 순간 장소까지 0.277/0.252 m가 남아 있었다. 위 Fleet 도착 규칙과 맞는 값이다. 그 뒤 CORE가 장소까지 마저 가는지는 이 실행이 재지 않았다. 다음 커밋이 판정을 바꿨다: `arrived` 10 s 뒤의 자세를 다시 읽고, 장소까지 `arrive_lane_m` 안일 때만 통과다. 로그: `X:\DevTemp\sim-multi\run-3\out\trips\`.

- **`run-4`(AI PC, 5eb721d11, `--render cpu`, 4 CPU/4 GB): PASS, exit 0.** 두 CORE 응답, 두 로봇 `LOCALIZED`, 카메라 live. 두 trip 모두 `running → arrived`였다. 10 s 뒤 rosy_01(동쪽 도로)은 0.423 m를 움직여 장소에서 0.021 m, rosy_02(서쪽 도로)는 0.401 m를 움직여 장소에서 0.019 m에 섰다. 정리 뒤 남은 프로세스는 0이다. Fleet은 장소 약 0.25 m 앞에서 `arrived`를 내고, CORE는 그 뒤 장소의 stop까지 간다(run-3의 수치는 그 중간 표본이었다). 로그: `X:\DevTemp\sim-multi\run-4\out\trips\`(result.json, api-log.jsonl, launch.log, fleet.log). SIM 증거일 뿐이다. 학습 페인트(모델 없음, denoise)도, DEVICE·FIELD 수용도 아니다.

## 남은 일

1. 끝남: `run-4` PASS. 남은 관찰 하나: Fleet `arrived`는 CORE가 장소에 서기 전(약 0.25 m 앞)에 난다. trip 끝 이벤트를 쓰는 소비자(D-763 work 행, 다음 단계 시작)가 그 사이 로봇이 아직 움직인다는 것을 알아야 하는지 Fleet 소유자와 정한다.
2. 했음: `integrations/simulation/gazebo/logs.md`에 기록.
3. 커밋된 실행기가 통과했으므로 AI PC의 개인 rig `~/rosy-test/d763-sim`(1.3 GB)은 지워도 된다(사용자 메모). 이 세션은 지우지 않았다. D-763 probe를 이 실행기 위에 올리기 전에 rig의 `probe-d763.py`를 저장소로 옮길지 먼저 정한다.
4. 범위 밖으로 남긴 것: bend 장소가 있는 SIM 사이트 지도(모서리를 도는 trip, 한 바퀴), D-763 slice 6의 `hold_job`/`release_job` HTTP 진입점(제품 slice 7), `line/lane_guide` 생산자(drivable 목표), 학습 모델 위치(저장소에 없음).
