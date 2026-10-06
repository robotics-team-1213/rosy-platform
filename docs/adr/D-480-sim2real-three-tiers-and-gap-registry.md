## D-480 sim2real 차이는 세 갈래로 나눈다 — 싸게 그릴 것은 시뮬에, 그리기 어려운 것은 실주행 재생에, 예외는 장치의 런타임 지원으로

**Status:** Proposed (2026-10-06; 문서와 레지스트리 lint만, 시뮬·CORE 코드 변경 없음. 결정 2·3·4의 구현과 ROS-SIM/DEVICE/FIELD 수용은 별도). D-364·D-378·D-397·D-400·D-322의 결정은 고치지 않는다. 관계는 「기존 결정과 관계」에만 둔다.

### Context

- **시뮬 값의 출처가 하나가 아니다.** 실물 기하는 D-397 보정 해석(URDF NOMINAL < 승인 레코드 < 운영자, `contracts/foundation/core_common/calibration_store.py:379` `resolve`)에 있는데, 시뮬 launch는 카메라 피치를 상수로 든다. `map_v2_fleet_lane.launch.py`는 25°(`:33`, `:108`, `:138`), `map_v2_fleet_real.launch.py`는 URDF NOMINAL 8°·0.06343 m(`:26-33`)다. 실측은 11.2–11.8°, 0.058–0.060 m다. `integrations/simulation`에는 `calibration_store`를 읽는 곳이 없다. 2026-09-24 해법 문서(`docs/solutions/workflow-issues/measure-the-real-camera-from-recorded-video-before-tuning-sim-perception-2026-09-24.md`)가 같은 실수를 이미 기록했다.
- **시뮬을 추론으로 가른다.** `is_robot_scan`(`middleware/perception/control/sensing/lidar.py:42-64`)은 빔 수·range_max·stamp로 원격 Gazebo scan을 버린다. 유일한 opt-in `enable_simulation_scans`는 720 빔 + `pinky/` frame만 받는데(`lidar.py:32-39`), 공용 Gazebo LiDAR는 640 샘플이다(`middleware/apps/device/pinky/description/urdf/rosy_gz.urdf.xacro:98`). CORE는 opt-in을 부르지 않는다(호출은 perception의 `camera_region_range.py`·`object_detector_node.py`·보정 rig뿐).
- **최신 안전 의존 기능은 시뮬에서 설 수 없다.** D-476 Gazebo 검증(`docs/validation/d476-gazebo-model-pc-2026-10-06/result.md`, branch `docs/d476-gazebo-model-pc`) 결과 2: enforce를 켜도 sim scan 거부, IR·IMU 없음, line clock(sim 초, `middleware/core/gateway/core/bridge/traffic_gate.py:10-18`)과 정책 snapshot(monotonic) 불일치가 막는다. 결과 1: 장치와 같은 `control.sensor_adapter` 꺼짐에서는 D-468 바닥 증명이 늘 false라 D-468/D-476 동작 증명이 서지 않는다.
- **그리기 어려운 차이를 시뮬 튜닝으로 쫓았다.** 흰 벽, 카펫, 반사, 도색 마모는 Gazebo에 없다(카메라 센서에 노이즈·노출 설정이 없다, `rosy_gz.urdf.xacro:125-151`). 실물 녹화 재생(D-378, D-379, `learning/training/perception/road_replay.py`)이 이미 이 차이를 잰다.
- **런타임 예외는 자리가 없다.** Wi-Fi 끊김·지연, 바퀴 미끄러짐, 센서 끊김, 배터리 처짐은 시뮬 충실도로 닫히지 않는다. 저장소에 고장 주입 도구가 없다.
- **노트북은 Gazebo를 돌리지 않는다.** D-395 S2(개정 10)와 D-400 G-sim(D-430 표: "호스트 부하로 미결")은 노트북 부하로 끝내지 못했다. 시뮬 호스트는 모델 PC·관제 PC다(D-434). D-476 검증은 모델 PC에서 RTF 0.99–1.02로 돌았다.

### Decision

1. **모든 차이는 세 층 가운데 하나로 분류한다.**
   - **M (시뮬 모델링):** 기하·센서 배치·시계·센서 유무·조명 프리셋·바닥/벽 반사율처럼 보정 레코드나 측정 분포에서 값을 가져올 수 있고, 월드·xacro·launch 수정으로 끝나는 것. 대상은 Gazebo다. Isaac Sim은 D-322 게이트를 통과하기 전까지 이 구조에 넣지 않는다.
   - **R (실주행 재생):** 실물 외관(흰 벽, 카펫, 반사, 저조도, 도색 마모, 움직임 흐림)과 실측 응답(명령→odom 지연, odom 오차). D-379 세션을 인식·CORE 판정 코드에 개루프로 재생한다. D-378 R0가 이 층이다.
   - **D (장치 런타임 지원):** 모델링하지 않고 런타임이 감지하고 안전하게 물러서야 하는 것(센서 끊김, 미끄러짐, 링크 끊김·지연, 배터리, 처음 보는 교차로). 각각 (a) 런타임 감지 신호, (b) 정지·HOLD·Fleet 보고 같은 안전 폴백, (c) 벤치 고장 주입 시험, (d) 사용자 승인 뒤 녹화와 함께 하는 장치 시험을 갖는다.
   - 경계가 애매하면 싼 쪽부터 시도한다(M → R → D). D 항목도 감지·폴백 로직은 M·R에서 먼저 시험한다. 실행 환경 문제(호스트 성능)는 `infra`로 적는다.
2. **시뮬 값은 로봇 하나의 보정 해석에서 온다.** 시뮬 launch는 `robot:=<id>`를 받고 기본값은 8kcn이다(가장 많이 실측한 로봇: 카메라 피치 약 11.2°, 높이 0.058–0.060 m, roll −1.5°, LiDAR 정면 약 181–182°). 카메라·LiDAR·바퀴 값을 `calibration_store.resolve`로 얻는다. launch·월드에 기하 숫자를 새로 두지 않는다. `robot:=nominal`로 돈 결과와, 보정 저장소를 못 읽어 `resolve`가 URDF NOMINAL로 떨어진 결과는 "NOMINAL"이라고 적고 특정 로봇의 증거로 쓰지 않는다. 실물 기하가 아닌 월드(25° 차선 월드)는 `synthetic`으로 표시하고 실물 인식 합격의 근거로 쓰지 않는다.
3. **시뮬 전용 동작은 명시 플래그로만 켠다.** D-182 시뮬 프로파일이 넘긴 값 하나(`simulation_sensors: true`)가 CORE 워커의 sim scan 수용, 시뮬 IR, sim 시계 정렬, 시뮬 전용 sensor_adapter enforce를 켠다. 빔 수·stamp 추론은 방어로 남기되 켜는 수단이 아니다. 장치 프로파일에는 이 플래그가 없고, 장치 이미지 시험이 그 부재를 확인한다.
4. **시뮬 enforce 합격.** D-468/D-476처럼 D-400 enforce에 기대는 기능은 결정 3의 플래그로 시뮬에서만 enforce를 켜고 ROS-SIM 단계를 합격할 수 있다. 장치 enforce는 D-400 계획 3 그대로이고, 시뮬 합격이 장치 활성화의 근거가 되지 않는다.
5. **사다리와 층마다 주장할 수 있는 것.** 수용 기준의 gate를 다시 쓰고, R 단계를 끼운다.

   | 단계 | 주장할 수 있는 것 | 주장할 수 없는 것 |
   |---|---|---|
   | LOCAL (호스트 pytest) | 로직·경계·폴백 분기 | ROS 그래프, 실물 |
   | ROS-SIM (M) | 폐루프 상호작용, 시계·QoS·다중 로봇, 그 보정 프로필에서의 기하 | 실물 외관·센서 잡음·장치 안전 |
   | REPLAY (R, D-378 R0) | 실물 입력에서의 인식·판정 정확도 | 폐루프 결과, 모터 응답 |
   | SHADOW (D-378 R1) | 실물 실시간에서 판정 일치 | 명령 효과 |
   | DEVICE | 그 artifact·그 로봇의 실제 I/O와 폴백 | 반복 현장 업무 |
   | FIELD | 대표 환경 반복 | 다른 사이트·하드웨어 |

   각 단계는 앞 단계를 대신하지 않는다. 시뮬 실행은 RTF를 기록하고, RTF < 0.9이면 INCONCLUSIVE다.
6. **차이는 층을 옮겨 간다.** 현장에서 새 예외가 나오면 (1) D-378 오류 표와 D-379 세션 카탈로그에 증거로 남기고, (2) 그 세션이 재생 사례가 되며, (3) 값으로 표현할 수 있으면 M으로 옮긴다. 옮긴 뒤에도 재생 사례는 지우지 않는다. 시뮬 가정이 바뀌면 그 가정 위의 합격은 레지스트리에서 다시 연다.
7. **레지스트리는 harness YAML 하나다.** `tools/harness/sim2real_gaps.yaml`(`harness.yaml`의 `sim2real_gaps`). `python tools/harness/rosy_harness.py lint`가 검사한다.
   - 필수 필드: `id`(`G-NN`, 유일), `gap`, `evidence`(목록), `tier`(목록, `M` `R` `D` `infra`에서 중복 없이. 첫 값이 지금 자리, 뒤 값이 옮겨 갈 자리), `owner`, `status`(`OPEN` `IN-PROGRESS` `CLOSED` `HOLD`), `next`.
   - `evidence` 한 항목은 ADR id(Log에 있어야 함), 저장소 경로(선택 `:33`, `:26-33`, `:33,108`. 파일이 있고 인용 줄이 파일 길이 안이어야 함), 또는 브랜치 전용 `{path, branch}`(그 브랜치에 파일이 있어야 함. 브랜치를 못 찾으면 경고만 하고, 착지하면 일반 경로로 바꾼다).
   - `CLOSED` 행은 `validated_by`(같은 경로 규칙)가 있어야 한다.
   - `generate`가 사람이 읽을 표 `docs/reference/sim2real-gaps.md`를 만든다. 표는 손으로 고치지 않는다.
   - 검증 실행(`docs/validation/*`)은 다룬 행 id를 적고 같은 커밋에서 그 행의 상태를 고친다.
8. **자리.** 시뮬 모델·월드·시뮬 센서는 `integrations/simulation`에, 재생은 `learning/training/perception`에, 런타임 감지·폴백은 `middleware`의 소유 모듈에 둔다(D-427). 시뮬·재생은 모델 PC나 관제 PC에서만 돌린다. 고장 주입 중 로봇이 움직이는 시험은 사용자 승인 뒤에만 한다.
9. **병렬.** 레지스트리 한 행이 한 브랜치·한 주제다(D-372). 서로 다른 행은 동시에 진행한다.

### 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-364 | 재생 벤치·헤드리스 Gazebo 먼저를 유지. 외관 차이는 R로 보낸다는 분류를 더함 |
| D-378 / D-379 | R0 재생·R1 섀도·세션 카탈로그를 R 층으로 재사용 |
| D-397 | 보정 해석 순서를 시뮬 월드까지 넓힘(결정 2), 기본 8kcn |
| D-400 | 시뮬에서는 명시 플래그로 enforce 시험·합격 허용(결정 4). 장치 enforce는 계획 3 그대로 |
| D-182 | 시뮬 플래그 출처를 그대로 씀(결정 3) |
| D-322 / D-434 | Isaac Sim은 D-322 통과 전까지 이 구조 밖. 호스트는 모델 PC·관제 PC |
| D-426 | 이상적 model-pose odom은 시뮬 전제로 유지. 실물 odom 오차는 `odom_wheel`로 별도 실행 |
| D-427 | 층 이동 없음 |
| D-476 / D-468 | ROS-SIM 단계는 결정 3·4로 가능 |
| D-61 | harness lint·generate에 레지스트리 검사와 표 생성을 더함 |

### Alternatives

- 모든 차이를 시뮬 충실도로 닫기: 비싸고 외관은 실물 재생이 더 정확하다. 기각.
- 시뮬을 건너뛰고 장치에서 바로: 로봇이 공유되고 승인 없는 이동이 금지돼 있어 느리고 위험하다. 기각.
- D-364 개정: 인식 범위라 시계·센서 플래그·링크 고장을 담지 못한다.
- markdown 표 레지스트리: 도구 없이 쉽지만 lint가 없어 행이 썩는다. 사용자 결정으로 harness YAML.

### Consequences

- 시뮬 합격은 보정 프로필 이름(기본 8kcn, 아니면 NOMINAL)을 달고 나온다. 프로필이 바뀌면 합격이 다시 열린다.
- 첫 일감은 G-03·G-04·G-05·G-06(시뮬 배관)이다. branch `feat/sim-sensor-fidelity`에서 진행 중이다.
- 25° 차선 월드의 기존 합격은 실물 인식 근거에서 빠진다.
- 레지스트리의 인용 줄 번호가 코드 변경으로 파일 길이를 넘으면 lint가 실패한다. 그 커밋에서 행을 고친다.

### Validation

- 결정 3: 장치 프로파일에 `simulation_sensors`가 없으면 CORE가 sim scan을 버림(LOCAL), 시뮬 프로파일에서 받음(ROS-SIM).
- 결정 2: 시뮬 launch에 기하 숫자 리터럴 0건(D-182식 래칫), `robot:=` 해석이 `calibration_store.resolve`와 같음.
- 결정 7: `test/test_sim2real_gaps.py`(규칙마다 실패 사례, 저장소 레지스트리 lint 0건·표 생성), `python tools/harness/rosy_harness.py lint` 0 error.
- 호스트 pytest 통과는 장치·ARM64 이미지·현장 수용이 아니다.
