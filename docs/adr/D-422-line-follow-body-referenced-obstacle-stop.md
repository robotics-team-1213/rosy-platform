## D-422 차선 추종 앞물체 정지는 몸 기준으로, 의도한 차선 경로를 따라, 초음파를 합쳐 판정한다

**Status:** Proposed (2026-10-02, 동작·설정 결정; 사용자 지시 2026-10-02 "13 cm 면 이 작은 로봇에 충분하다. URDF·교정으로 몸과 회전 반경을 알 수 있다. 초음파도 있다 — 써라"). CORE 차선 추종(D-143, D-344 §11 보강)의 path 판정만 바꾼다. sector 판정, Nav2, 도킹, 군집은 바꾸지 않는다. D-407 막힘 복구의 후진 규칙은 그대로다.

## 배경

- **실물 증거(8kcn, 2026-10-02, 사용자 확인).** 차선 추종이 CORE 가 잰 0.10–0.13 m 앞 실제 물체에 거듭 멈췄다. 설정은 `obstacle_stop_m` 0.12, `obstacle_resume_m` 0.17, `obstacle_mode: path`, 띠 반폭 0.072, horizon 0.30, 순항 0.04 m/s 였다.
- **거리를 LiDAR 원점에서 쟀다.** `obstacle_stop_m` 은 LiDAR 원점(URDF x −0.017) 기준이다(`clearance.py` `front_clearance`/`path_clearance`, `manager.py` 의 정지 판정). 몸 앞끝은 그보다 약 6 cm 앞이고, 그 값은 어디에도 내보내지 않았다. 0.12 m 는 몸 앞 약 6 cm 다. 0.04 m/s 의 정지 거리는 1 cm 미만 + 지연 약 0.1 s 이므로 이 작은 로봇에는 넉넉하다.
- **멈춘 로봇은 모서리에서 다시 출발하지 못했다.** path 판정은 의도 선속도가 0 이면 제자리 회전으로 보고, LiDAR 에서 `max(반폭, obstacle_stop_m)` 안의 점을 모두 거리 0 으로 셌다. 차선이 벽에서 꺾여 나가는 모서리에 선 로봇은 옆 벽 때문에 영영 풀리지 않았다.
- **띠는 몸이 아니다.** 띠 반폭 0.072·0.09 는 손으로 정한 값이다. URDF 몸 반폭은 0.05655 m, 회전 반경은 0.08257 m 다(D-397 geometry.yaml).
- **초음파는 깨우기에만 썼다.** 앞 초음파(URDF x 0.0267, 높이 0.037)는 PWR-002 근접 깨우기에만 쓰였다. Pinky 의 C1 LiDAR 는 `range_min`(드라이버 보고값, 약 0.15 m 로 알려짐) 안을 보지 못한다.
- **사용자 규칙.** 모든 기하 기본값은 URDF 공칭에서 오고, 로봇별 교정 기록이 다듬는다. 손으로 정한 숫자를 두지 않는다(D-397).

## 결정

1. **여유는 몸 윤곽에서 잰다.** URDF 충돌 메시에서 몸 앞끝 `footprint.front_x_m` 을 내보낸다(`tools/calibration/urdf_nominal.py`, geometry.yaml, drift 시험; Pinky 0.04205 m, 화면 받침이 가장 앞). 몸 윤곽은 base_footprint 기준 사각형 [`body_rear_x_m`, `body_front_x_m`] × [±`body_half_width_m`] 을 회전 반경 `body_rotation_radius_m` 원으로 자른 모양(둥근 모서리)이다. 로봇 패키지 `core.yaml` 의 `line_follow.body_front_x_m`·`body_ultrasonic_x_m` 은 geometry.yaml 값이고 drift 시험이 묶는다. 교정 저장소(D-47 부록)에 몸 윤곽 종류가 생기면 그 기록이 다듬고, 운영자 overlay 가 둘 다 이긴다. 지금은 몸 윤곽 교정 종류가 없어 URDF 공칭 < overlay 두 층이다.
2. **정지 간격은 유도한다.** `stop_gap = obstacle_body_margin_m(0.02) + v·obstacle_latency_s(0.15) + v²/(2·obstacle_decel_mps2(0.5))`, `v` 는 의도 선속도(정지 중에도 다시 출발할 속도). 재출발은 `stop_gap + obstacle_resume_hysteresis_m(0.03)`. 감속도 0.5 m/s² 는 측정값이 없어 둔 보수적 기본값이다(Nav2 설정 2.5 의 1/5); 실측 뒤 로봇 패키지에서 바꾼다.
   - **덮어쓰기.** `obstacle_stop_m`·`obstacle_resume_m` 은 LiDAR 원점 기준의 운영자 덮어쓰기로 남는다. 어느 층에든 하나라도 있으면 그 값이 이긴다(path + 몸 기하에서는 `값 − (front_x − lidar_x)` 몸 간격으로 바꿔 쓴다 — 직진에서 옛 뜻과 같다). 한쪽만 있으면 다른 쪽은 옛 기본값(0.20 / 0.28)이라 옛 overlay 는 D-422 이전과 똑같이 읽힌다.
   - **기본 yaml 에는 두 키를 두지 않는다.** 기본 층의 값도 덮어쓰기로 보이기 때문이다(`docs/solutions/logic-errors/default-key-for-a-renamed-setting-collides-with-old-overlays-2026-10-02.md`). 비어 있으면 sector 와 몸 기하 없는 path 는 옛 0.20 / 0.28(LiDAR 원점)을 쓴다.
   - **LiDAR 사각.** 신선한 초음파가 없으면 정지 간격은 적어도 `range_min − (front_x − lidar_x)`(직진에서 물체가 LiDAR 에서 사라지는 몸 간격)이다. 덮어쓰기에도 적용한다 — 안 보이는 곳까지 다가가지 않는다.
3. **판정 경로는 의도한 차선 경로다.** 차선 제어기가 장애물 판정 전에 낼 (선속도, 각속도)(`_steer`)를 쓴다. 출력이 0 으로 막힌 동안에도 마찬가지다. 그 호를 따라 몸 윤곽을 쓸어(5 mm 간격 + 이분법) 첫 접촉까지의 base_footprint 이동 거리를 몸 간격 `body_gap_m` 으로 한다. 호는 `obstacle_path_horizon_m` 또는 반 바퀴까지다.
   - **제자리 회전**(의도 선속도 0, 각속도 ≠ 0)은 URDF 회전 반경 원 밖 여유로 판정한다. 회전은 가까워지지 않으므로 정지·재출발 간격은 둘 다 `obstacle_body_margin_m` 이다(앞으로 가다 걸린 정지가 돌아 나갈 수 있는 회전을 막지 않게). 의도가 (0, 0) 이면 순항 속도 직진으로 본다.
   - 몸 기하(`body_front_x_m`·`body_lidar_x_m`·`body_rear_x_m`·`body_half_width_m`·`body_rotation_radius_m`)가 하나라도 없으면 옛 path 띠 판정을 그대로 쓴다.
4. **초음파를 합친다.** 신선한(`obstacle_ultrasonic_stale_s` 0.3 s 이내) 앞 초음파 거리 `r` 은 센서 위치(`body_ultrasonic_x_m`, URDF)에서 ±`obstacle_ultrasonic_half_angle_deg`(15°) 호 위의 점들로 바꿔 LiDAR 점과 같이 몸 윤곽 쓸기에 넣는다. 직진 정면에서 간격은 `r − (front_x − ultrasonic_x)` 다. 둘 중 가까운 쪽이 이기고 `clearance_source` 가 `lidar` | `ultrasonic` 을 알린다.
   - **더 일찍 멈추게만 한다.** 점을 더할 뿐이라 간격은 줄기만 한다. 오래된 값은 버린다.
   - 걸러 쓰기는 `translate.usable_range` 와 같다. 범위 위(포화, +inf)는 "범위 안 메아리 없음"으로 신선하게 기록한다. NaN·음수·`min_range` 아래는 아무것도 증명하지 못하므로(센서에 닿은 물체일 수 있다) 기록하지 않고 늙게 둔다 — 그동안은 LiDAR 사각 하한(2)이 적용된다.
   - **센서 한계.** 매끈한 벽에 비스듬히 닿으면 메아리가 돌아오지 않는다(정면 벽만 믿을 만하다). 다른 로봇의 초음파와 섞일 수 있다(가까운 값 → 더 일찍 멈출 뿐). 원뿔 폭과 바닥 반사는 실물에서 확인한다. 초음파 하나는 정면 원뿔만 덮으므로, 호를 따라 옆으로 도는 몸의 사각은 덮지 못한다.
5. **D-407 과의 관계.** 막힘은 새 판정의 `obstacle_ahead` 가 `obstacle_escalate_s` 이어질 때 열린다. 재판단의 `front_clear` 는 몸 기하가 있으면 몸 간격 ≥ 재출발 간격이다(직진 띠는 보고만 한다). `RESUME` 거부(`object_within_stop_distance`)는 직진 띠를 지금 정지 간격의 LiDAR 원점 환산값과 비교한다. 후진 규칙은 그대로다.
6. **상태와 사건.** `GET /api/v1/line-follow` 에 `body_gap_m`·`stop_gap_m`·`clearance_source`(몸 판정이 아니면 null), `nav.line_obstacle_hold` 데이터에 같은 세 필드를 더한다. 몸 판정에서 `clearance_m` 은 `body_gap_m` 과 같은 몸 간격이다.

## Pinky Pro 숫자 (URDF 공칭)

- 몸 앞끝 0.04205, LiDAR −0.017 → LiDAR 에서 몸 앞까지 0.05905 m. 초음파 0.0267 → 몸 앞까지 0.01535 m.
- 0.04 m/s: 정지 간격 0.0276 m(LiDAR 원점 환산 약 0.087 m), 재출발 0.0576 m(약 0.117 m). 0.10 m/s: 0.045 m.
- 8kcn 장면: 0.10–0.13 m(LiDAR) 앞 물체는 몸 간격 0.041–0.071 m 다. 기본(덮어쓰기 없음)이면 의도 호가 그 물체를 쓸고 지날 때만 몸 간격 0.0276 m(약 0.087 m)까지 다가가 멈추고, 차선이 꺾여 비켜 가면 멈추지 않는다. 8kcn overlay 의 0.12 / 0.17 이 남아 있으면 정지 간격은 0.061 m 로 직진은 옛 0.12 m 와 같지만, 몸 폭·의도 호·회전 반경 판정은 새 규칙을 따른다. 유도 간격을 쓰려면 8kcn overlay 에서 두 키를 지운다.
- LiDAR 가 정말 `range_min` 0.15 m 를 보고하면 초음파 없이 정지 간격은 0.091 m(LiDAR 약 0.15 m)로 올라간다. 8kcn 이 0.10 m 를 잰 것을 보면 그 로봇의 `range_min` 은 더 작다 — 실물에서 확인한다.

## 결과

- 사람이 정한 거리 대신 URDF 몸과 속도로 멈춘다. 작은 로봇이 13 cm 앞 물체를 피해 차선을 돌아 나갈 수 있다.
- 모서리에서 멈춘 로봇이 회전 반경으로 판정되어 다시 돌아 나갈 수 있다.
- 초음파가 LiDAR 의 근거리 사각과 낮은 물체(높이 0.037 m)를 메운다. 오래된 초음파와 메아리 없음은 출발 근거가 되지 않는다.
- 판정 비용: 틱마다 근처 점 × 쓸기 단계(약 60) — 호스트에서 수 ms. Pi 측정은 장치 검증 때 한다.

## 검증

- 호스트: 모서리 재현(옛 규칙 HOLD, 새 규칙 회전 허용), 직진 의도에서 유도 간격 정지·재출발 이력, 속도별 간격, 몸 폭 밖 물체, 초음파는 더 일찍만·오래된 값 무시·LiDAR 사각 하한, 덮어쓰기 우선, 기본 + Pinky + 옛 overlay 병합 해석, D-407 `front_clear`, 사건 필드(`src/runtime/gateway/test/test_line_follow_body_stop.py`). URDF drift(`tools/calibration/test/test_urdf_nominal.py`).
- Gazebo: 차선 끝 모서리와 지도 한 바퀴(path 기본 전환 조건, D-344 §11 보강)를 사용자 승인 뒤 다시 돈다.
- 실기: 사용자 승인 뒤 8kcn·9dfk 에서 `range_min`, 초음파 원뿔·바닥 반사·두 로봇 간섭, 0.04 m/s 실제 정지 거리(감속도 실측)를 녹화와 함께 확인한다.

## 잇는 결정

D-143(차선 추종), D-344 §11·§11 보강(앞물체 정지, path), D-397(URDF 공칭·로봇별 교정), D-407(막힘 복구), D-47 부록(교정 저장소), PWR-002(초음파 깨우기), D-2(단일 cmd_vel).
