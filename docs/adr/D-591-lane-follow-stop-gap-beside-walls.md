## D-591 차선추종 몸 정지 간격 0.02 m — 벽 옆 주행에서 LiDAR 사각 바닥을 끈다(Pinky Pro)

**Status:** Accepted (2026-10-10, 사용자 결정 "0.02 m까지 낮춰서", "벽에 붙어 있는 경우가 많은데 돌 때마다 못 움직이면 아무것도 못 한다").

고치는 결정: [D-422](D-422-line-follow-body-referenced-obstacle-stop.md) 정지 간격 바닥(range_min) · [D-424](D-424-one-robot-body-for-every-near-check.md) 공유 간격 규칙의 Pinky Pro 값. 안전 분리: [D-430](D-430-safety-as-a-separate-concern.md).

### Context

- 2026-10-10 03:28 KST, 8kcn(릴리스 069)에서 CAMERA_LINE이 1.6 s 추종한 뒤 `HOLD obstacle_ahead`로 섰다. 몸과 오른쪽 흰 벽의 간격(`body_gap_m`)은 0.048 m였다.
- 정지 간격은 `margin 0.02 + v·latency 0.15 + v²/(2·0.5)`(0.03 m/s에서 약 0.026 m)이지만, D-422는 이 값을 LiDAR 사각 바닥 `range_min − (body_front_x − body_lidar_x)`(C1 range_min 0.10–0.15 m, 0.059 m 앞 → 약 0.04–0.09 m) 아래로 내리지 않는다. 벽 옆 차선에서는 굽이마다 이 바닥에 걸린다.

### Decision

1. `line_follow.obstacle_blind_floor`(기본 `true`)를 둔다. `false`면 움직이는 차선추종의 정지 간격을 LiDAR 사각 바닥으로 올리지 않는다. 제자리 회전은 원래대로 회전 반경 + margin이다.
2. Pinky Pro 로봇 층(`middleware/apps/device/pinky/profile/config/core.yaml`)은 `obstacle_blind_floor: false`, `obstacle_latency_s: 0.0`이다. 정지 간격은 `0.02 + v²/(2·0.5)`, 순항 0.04 m/s에서 0.0216 m다.
4. **옆 벽은 몸이 닿을 때만 센다.** 경로 검사는 이미 URDF 몸 윤곽(반폭 0.05655 m)을 의도한 호를 따라 쓸고 옆 여유를 더하지 않는다. 남은 과잉은 초음파였다. 반향 하나를 원뿔 ±15° 전체 점으로 펴서, 0.10 m 반향이 축에서 0.026 m(몸 폭 안)에 놓였다. 굽이에서 옆 벽 반향이 정면 장애물로 읽혔다. Pinky Pro는 `obstacle_ultrasonic_half_angle_deg: 5.0`(0.009 m)이다.
3. 남는 보호: range_min 아래로 빠진 반사는 바퀴 명령으로 기억한 점이 계속 막고(D-422 H2), 초음파 반향은 점을 더한다. 0.02 m 안의 반사는 여전히 선다. CORE e-stop·watchdog·속도 상한은 바뀌지 않는다.

### Consequences

- 잃는 것: range_min 안쪽 띠(약 0.04–0.09 m)에서 처음 나타난 물체는 LiDAR가 못 본다. 그 띠의 보호는 기억한 점과 초음파뿐이다. 반응 시간 항을 0으로 두어, 정지 간격은 제동 거리만 남는다(0.04 m/s에서 1.6 mm).
- 운영자 오버레이는 두 값을 다시 켤 수 있다(`obstacle_blind_floor: true`, `obstacle_latency_s: 0.15`).
- 시험: `middleware/core/gateway/test/test_line_follow_body_stop.py`(0.048 m 벽 통과, 0.015 m 정지, Pinky 값 고정).
- 현장 확인: 두 로봇 병렬 차선추종으로 벽 옆 정지 빈도를 잰다(2026-10-10, X:\DevTemp\lf-wall-runs).
