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

결과는 `<log-dir>/out/trips/result.json`(`pass`, 로봇별 `states`, `moved_m`), `api-log.jsonl`, `launch.log`, `fleet.log`다. 종료 코드 0은 두 trip이 모두 `arrived`이고 각자 TRIP_M의 절반 이상 움직였다는 뜻이다. 시험 PC에서 직접 돌릴 때는 ROS와 colcon install을 source한 셸에서 `python3 tools/sim/fleet_trips.py --out DIR [--render gpu]`.

## 고친 것 (gap → 원인 → 변경)

1. **trip이 모두 `lane_guard_stale`로 섰다.** multi_real launch에 IR 바닥 ray와 observer IR 교정이 없었다. `map_v2_fleet_multi_real.launch.py`가 로봇마다 `/<ns>/ir/{left,mid,right}` 브리지와 `sim_ir_floor.py`를 띄우고, observer에 `gz_multi_parts.SIM_IR_CALIBRATION`을 준다. 값은 센서 모형에서 나온다: SIM 바닥은 항상 `FLOOR_RAW` 2000(반사율 없음)이라 검정 끝점, ADC 포화 4000(`hazard.py`의 유효 IR < 4000)이 흰 끝점. `test_sim_sensors.py`가 두 값을 출처에 고정한다. 따라서 SIM IR은 선을 보지 못하고(가드 `clear`), 신선한 교정 IR만 증명한다. rig의 `learned_paint_target: lane_marking` 변경은 launch 인자(기본은 장치 기본값 `lane_marking`, `drivable` 선택 가능)로 옮겼다. `drivable`은 `line/lane_guide` 생산자가 있어야 하는데 제품에는 아직 없다(rig는 `sim-lane-guide.py` 대역을 썼다).
2. **onnxruntime 없음.** D-373 1항에 따라 onnxruntime은 CORE 요구사항에 넣지 않는다(별도 prefix, payload runtime id 밖). `remote_sim.py` DEPS가 장치와 같은 `learned-perception-requirements.txt`(해시 고정)를 `$PYDEPS/learned`에 깔고 `ROSY_LEARNED_SITE`로 넘긴다. 저장소에 모델이 없으므로 `learned_lane_pointer`는 선택이고, 비면 observer는 denoise 페인트로 돈다. 그 실행은 학습 페인트 실행이 아니다.
3. **pydantic 2.13.5(CORE) / 2.13.4(Fleet).** 맞추지 않았다. CORE 쪽은 장치 런타임 pin(D-189)이고 Fleet 쪽은 현장 PC 설치 pin이라 SIM 때문에 운영 pin을 바꾸지 않는다. PyYAML, uvicorn, websockets도 서로 다르다. 대신 한 인터프리터에 CORE pin을 깔고 Fleet pin 가운데 CORE가 이름을 갖지 않은 것(oauthlib, zeroconf …)만 더한다. `remote_pytest.py` VENV가 장치 세트에 하는 것과 같고, CI 시험 venv에서 Fleet이 그 pin으로 돈다.
4. **커밋된 두 로봇 trip 실행기 없음.** `tools/sim/fleet_trips.py`(+ `remote_sim.py` 벤치 `fleet_trips`). D-426 `Reservations`로 domain 80–99·포트를 정하고, 잠금은 remote_sim의 것을 쓰거나 혼자 돌 때 `~/rosy-jobs`에 쓴다. CORE 오버레이는 rig/m29와 같은 규제 설정(line authority, map entry, route context, path 정지, IR guard, site floor, junction signal, sensor adapter enforce), Fleet은 `fleet_sim_camera_site.yaml` + authority + trip lease(ttl 8 s). Fleet은 D-725 `NativeGazeboMapPosePort`를 묶은 내부 `fleet` 모드로 띄운다(rig bootstrap의 D-763 harness 경로와 bend 장소 패치는 넣지 않았다). trip은 좌표 목적지 하나: rosy_01은 동쪽 도로 남쪽 직선(동향), rosy_02는 서쪽 도로 서쪽 직선(남향), 각각 0.30 m, 모서리·횡단보도·주차 분기 밖. 정리는 `FLEET_TRIPS_RUN` 표시가 있는 자기 자식 프로세스만 끈다.

## 상태 (2026-10-15)

- 커밋: `6268b8b71`, `5cba01019`, `ca7be811d`, 이 문서. 착지·푸시 안 함.
- 원격 회귀: 관련 8개 파일 exit 0, `known_failures` NEW 0 (`X:/DevTemp/sim-multi/pytest-2/run-1.txt`, 모델 PC). 첫 실행(`pytest-1`)에서 launch 인자 기본값 누락 NEW 2를 잡아 `5cba01019`로 고쳤다.
- 실제 Gazebo 실행: 이 문서 커밋 시점에 첫 실행 `run-1`(AI PC, `--render cpu`, remote_sim ai 상한 4 CPU/4 GB)이 진행 중이다. 결과는 `X:/DevTemp/sim-multi/run-1.out`과 `run-1/out/trips/result.json`. 그때까지 두 시험 PC 모두 sim 하한(6 cores/8 GB) 아래였다.

## 남은 일

1. 실제 실행에서 두 trip이 `arrived`하는지 확인한다. 아니면 `result.json`의 `core_ready`/`localized`/`camera`와 `states`로 어디서 멈췄는지 보고 고친다. 4 GB 상한에서 메모리가 모자라면 모델 PC(`--host model -- --render gpu`, 6 GB)로 다시 돈다. 상한 변경은 D-571 결정이라 여기서 하지 않았다.
2. 통과하면 `integrations/simulation/gazebo/logs.md`에 증거 한 줄을 추가하고 `python tools/harness/rosy_harness.py generate`.
3. 통과한 뒤 AI PC의 개인 rig `~/rosy-test/d763-sim`(1.3 GB)은 지워도 된다(사용자 메모). 그 전에는 지우지 않는다.
4. 범위 밖으로 남긴 것: bend 장소가 있는 SIM 사이트 지도(모서리를 도는 trip, 한 바퀴), D-763 slice 6의 `hold_job`/`release_job` HTTP 진입점(제품 slice 7), `line/lane_guide` 생산자(drivable 목표), 학습 모델 위치(저장소에 없음).
