# PWR-005 절전·LiDAR 듀티 벤치 검증 절차

**대상:** Raspberry Pi 5 + Pinky Pro 실기, ROSY Phase 1
**목적:** `power.lidar.standby_stop` 을 켜도 되는지 판정한다. 이 문서의 활성화
체크리스트를 통과하기 전에는 플래그를 `true` 로 바꾸지 않는다.

배경과 설계 근거는 [Deep Power States Design](../plans/2026-09-01-deep-power-states-design.md)
과 ADR D-25에 있다. 이 문서는 그 설계가 실기에서 성립하는지 확인하는 절차만
다룬다.

## 0. 왜 게이트가 있는가

STANDBY LiDAR 정지는 인터록상 안전하다. STANDBY 는 로봇 모드가 `IDLE` 일 때만
진입하고, 모든 웨이크 경로(활동·근접·비 IDLE 모드·배터리 경보·API)가 모터
재기동을 선행한다. 단위 테스트가 이 경로를 전부 덮는다.

검증이 필요한 것은 그 인터록이 아니라 **실행 중인 Nav2 라이프사이클이 5분짜리
스캔 단절을 어떻게 받아들이는가**, 그리고 **재기동 후 스캔이 실제로 언제부터
신뢰할 만한가**이다. 둘 다 코드를 읽어서는 답이 나오지 않는다.

## 1. 사전 조건

- 실기가 기동되어 있고 `rosy-io` 런타임 모드로 sllidar 드라이버가 돌고 있다.
- operator 이상 권한의 API 토큰이 있다.
- 배터리 전류를 볼 수 있는 인라인 전류계 또는 전자부하가 있다.
  전류 측정은 스크립트가 하지 않는다.
- 로봇을 안전하게 세워둘 수 있다. 검증 중 STANDBY 를 강제하므로 통로에 두지
  않는다.
- **로봇 모드가 `IDLE` 이어야 한다.** 내비게이션·수동주행을 끝내고 E-Stop 을
  해제한다. 모드가 `IDLE` 이 아니면 절전 인터록이 `ACTIVE` 를 고정하므로
  STANDBY 강제가 조용히 무시되고, 실측 자체가 성립하지 않는다.

## 2. 자동 점검

`verify-power.sh` 는 읽기 전용 점검을 항상 실행하고, 토큰이 있으면 STANDBY
강제와 스핀업 실측까지 진행한다. `ros2` CLI 가 필요하므로 런타임 컨테이너
안에서 실행한다.

```bash
# 로봇에서
cd /opt/rosy/deploy/robot
docker compose exec rosy-core bash

# 컨테이너 안에서
export ROSY_API_TOKEN='<operator 토큰>'
bash /opt/rosy/deploy/robot/verify/verify-power.sh --csv /tmp/power-samples.csv
```

점검 항목과 판정:

| 라벨 | 확인 내용 | 기대 |
|---|---|---|
| `PLATFORM` | `/sys/power/state` 실제 내용 | `freeze` 만 — `mem`/`disk` 가 보이면 D-25 전제를 재검토 |
| `EEPROM` | `POWER_OFF_ON_HALT` 설정 여부 | 정보성. 딥 halt 를 쓰지 않으므로 미설정이 정상 |
| `API` | `/api/v1/power` 의 `mode`/`lidar_spinning`/`lidar_ready` | 세 필드 모두 존재 |
| `CONFIG` | `power.lidar` 실제 적용값 | 검증 전에는 `standby_stop=false` |
| `LIDARSVC` | `start_motor`/`stop_motor` 서비스 존재 | 둘 다 보여야 한다 |
| `SCANBASE` | ACTIVE 스캔 주기 | 드라이버 정격 주기 |
| `STANDBY` | STANDBY 진입 시 `lidar_spinning` | `False` |
| `QUIET` | STANDBY 중 스캔 | 멈춰 있어야 한다 |
| `SPINUP` | 웨이크 → 첫 스캔 실측 | 설정된 `spinup_s` 이하 |

`standby_stop=false` 인 동안 제어 점검은 의도적으로 건너뛴다(`CONTROL` 경고).
실측하려면 아래 4절 순서를 따른다.

## 3. 전류 측정 (수동)

스크립트는 전류를 재지 않는다. 인라인 전류계를 배터리와 로봇 사이에 넣고,
소비원을 하나씩 분리해 모드별로 기록한다. 설계 문서의 소비 순위 주장
(모터 홀딩 토크 > LiDAR 모터 > LCD 백라이트 > SoC)을 실측으로 확정하는 것이
목적이다.

측정 조합 — 각 조합에서 60초 평균을 기록한다:

| # | 구성 | 모드 | 기록 |
|---|---|---|---|
| 1 | 전체 기동 | ACTIVE | 기준선 |
| 2 | 전체 기동 | STANDBY (`standby_stop=false`) | ADC·LCD 듀티만의 이득 |
| 3 | 전체 기동 | STANDBY (`standby_stop=true`) | LiDAR 정지의 추가 이득 |
| 4 | LiDAR 커넥터 분리 | ACTIVE | LiDAR 단독 소비 |
| 5 | LCD 백라이트 오프 | ACTIVE | 백라이트 단독 소비 |
| 6 | 모터 토크 오프 (수동) | ACTIVE | 홀딩 토크 소비 — D-25 유보 항목의 근거 |

3번과 2번의 차이가 PWR-005 의 실제 이득이다. 이 값이 측정 오차 수준이면
활성화할 이유가 없으므로 그대로 기록하고 활성화하지 않는다.

`--csv` 로 남긴 표본에는 시각·라벨·스캔 주기·배터리 전압이 들어간다. 전류계
로그와 시각으로 맞춰 본다.

## 4. `spinup_s` 보정

현재 `spinup_s: 2.0` 은 **추정값이며 측정된 값이 아니다.** 실측 절차:

1. `power.lidar.standby_stop` 을 임시로 `true` 로 두고 런타임을 재기동한다.
2. `verify-power.sh` 를 토큰과 함께 실행한다. `SPINUP` 항목이 웨이크부터 첫
   스캔까지의 실측 시간을 출력한다.
3. 최소 10회 반복해 최댓값을 취한다. 단발 측정으로 정하지 않는다.
4. 최댓값보다 여유 있게 `spinup_s` 를 설정한다. 실측이 설정값을 넘으면
   `lidar_ready` 가 스캔이 유효해지기 전에 참이 되므로 스크립트가 FAIL 을 낸다.

첫 스캔 도착과 "스캔이 신뢰할 만함"은 같지 않다. 회전이 정격 속도에 오르기
전의 초기 스캔은 각도 분포가 왜곡될 수 있으므로, 가능하면 RViz 또는
`ros2 topic echo` 로 초기 프레임의 품질도 함께 본다.

## 5. Nav2 스캔 단절 관찰

이 절이 게이트의 핵심이다. Nav2 라이프사이클이 활성인 상태에서:

1. 목표 없이 Nav2 를 올려둔 채 로봇을 `IDLE` 로 5분 이상 방치해 STANDBY 에
   진입시킨다.
2. 그 동안 다음을 기록한다:
   - `controller_server` / `planner_server` 로그의 스캔 타임아웃 경고
   - 로컬 코스트맵이 비거나 stale 로 표시되는지
   - 라이프사이클 노드가 스스로 비활성/에러 전이를 하는지
3. 웨이크 후 즉시 내비게이션 목표를 준다. 다음을 확인한다:
   - 목표가 정상 수락되는가
   - 코스트맵이 복구되는가, 복구에 걸리는 시간
   - 복구 행동(recovery behavior)이 불필요하게 트리거되는가

## 6. `standby_stop` 활성화 체크리스트

**아래를 전부 만족해야 `power.lidar.standby_stop` 을 `true` 로 전환한다.**
하나라도 미확인이면 전환하지 않는다.

- [ ] `verify-power.sh` 가 토큰과 함께 실기에서 실패 0건으로 통과
- [ ] `PLATFORM` 이 `mem`/`disk` 를 보고하지 않음 (D-25 전제 성립)
- [ ] 3절 측정 3번과 2번의 차이가 유의미한 절감으로 확인됨
- [ ] 4절 스핀업 실측 10회의 최댓값이 설정된 `spinup_s` 이하
- [ ] 5절에서 Nav2 가 스캔 단절 구간을 통과한 뒤 목표를 정상 수행
- [ ] 5절에서 라이프사이클 노드가 에러 전이를 일으키지 않음
- [ ] 웨이크 경로 4종(근접·활동·API·배터리 경보) 각각에서 LiDAR 재기동 확인

전환 후에는 `rosy_default.yaml` 또는 `/etc/rosy/rosy.yaml` 의 값을 바꾸고
런타임을 재기동한 뒤, `verify-power.sh` 를 한 번 더 실행해 `CONTROL` 경고가
사라지고 제어 점검이 모두 통과하는지 확인한다.

## 7. 미실행 시 상태

체크리스트를 돌리지 않았다면 `standby_stop` 은 `false` 로 남는다. 이 경우
PWR-005 코드 경로는 존재하고 단위 검증도 되어 있지만 **실측 절감은 0** 이다.
설계 문서와 ADR D-25 는 이 상태를 전제로 쓰여 있다.

## 8. 기기별 전원 정책 벤치 (D-440)

기기별 전원 정책(D-24 개정, [D-440](../adr/D-440-per-device-power-policy.md))은 한 스위치
`power.device_policy.enabled` 뒤에 있다. 기본 `false` 이며 이 절을 통과하기 전에는
켜지 않는다. 한 로봇에서만 시험할 때는 그 로봇의 오버레이
(`/var/lib/rosy/core/.rosy/rosy.yaml`)에 쓴다. 기기 하나만 시험하려면
`power.device_policy.devices.<기기>.enabled: true` 를 쓴다(스위치보다 우선).
시간은 같은 오버레이의 `power.idle_after_s`·`standby_after_s` 로 줄여 시험해도 된다.

```yaml
power:
  idle_after_s: 30
  standby_after_s: 90
  device_policy:
    enabled: true
```

체크리스트 — 로봇은 바퀴를 띄우거나 막힌 곳에 두고, 모든 항목을
`docs/validation/device-power-<YYYY-MM-DD>/` 에 증거로 남긴다.

- [ ] 1. 스위치 꺼짐(기본): STANDBY 까지 무명령으로 둔 뒤 `GET /api/v1/power` 의 `devices[]` 가 모두
      `level: on`, `managed: false`, `motion_ready: true`. `power/devices` 토픽이 한 번도 발행되지 않는다.
- [ ] 2. 대시보드·Pilot 화면을 열어 둔 채(WS 구독·GET 폴링) 무명령이면 IDLE→STANDBY 로 간다.
- [ ] 3. 초음파 잡음: 사람이 없는 상태로 30 분 STANDBY 유지, `power.wake` 이벤트 0 건
      (`proximity` 웨이크 없음). 손을 0.4 s 이상 대면 깨어난다.
- [ ] 4. 배터리 WARNING 아래에서 시작해도 `warning_standby_after_s` 뒤 STANDBY 로 간다.
- [ ] 5. 스위치 켬, STANDBY: LiDAR 모터 정지(소리·전류), `camera_detect_node` 로그
      `camera paused by power policy`, `camera/blocked` 가 true. 전류계로 ACTIVE/STANDBY 전류 기록.
- [ ] 6. IDLE: perception `reduced` — `camera/telemetry` 주기가 약 1/4.
- [ ] 7. STANDBY 에서 `POST /api/v1/teleop`(MANUAL): 즉시 `power.wake{reason: command}`,
      `motion_ready=false` 동안 바퀴 0, 스캔이 다시 들어오고 `wake_ready_s`(2.0 s)가 지난 뒤에만 움직인다.
      실측 스핀업이 2.0 s 보다 길면 로봇 패키지 `core.yaml` 의 `wake_ready_s` 를 고친다.
- [ ] 8. 확인 없는 웨이크: LiDAR 커넥터를 뺀 채(또는 드라이버를 내린 채) 7번을 되풀이하면
      `motion_ready` 가 계속 false 이고 바퀴는 60 s 뒤에도 0 이다.
- [ ] 9. STANDBY 중 CORE 만 재시작(`rosy-core` 컨테이너): 다시 뜬 CORE 가 LiDAR·카메라를 켜고,
      첫 스캔과 `wake_ready_s` 전에는 `motion_ready=false` 다. ACTIVE 에서 CORE 를 재시작하면
      이미 도는 LiDAR 가 `start_motor` 를 한 번 더 받는다 — 스캔이 끊기거나 모터가 멈칫하지 않는다.
- [ ] 10. 카메라 재기동: `power/device_ready` 에 camera false → true(워밍업 뒤), 그 전까지
      라인 추종이 blocked 로 서 있다. 실측 시간이 `camera.wake_ready_s`(3.0 s)보다 길면 고친다.
- [ ] 11. STANDBY 중 E-Stop(`POST /api/v1/safety/stop`)과 teleop 워치독이 그대로 동작한다.
- [ ] 12. Nav2 가 떠 있는 상태에서 STANDBY 5 분 → 웨이크 → 목표 주행이 재초기화 없이 된다(§5 와 같은 관찰).
- [ ] 13. Fleet 콘솔: 로봇 카드가 상시/유휴/절전을 보이고, 절전 버튼이 IDLE 로봇을 STANDBY 로,
      깨우기 버튼이 ACTIVE 로 바꾼다. 일하는 로봇의 절전 버튼은 막혀 있다.
- [ ] 14. 모두 통과하면 `rosy_default.yaml` 의 `power.device_policy.enabled` 를 `true` 로 바꾸는
      커밋을 독립 리뷰와 함께 올린다.

바퀴 토크 해제(STANDBY 에서 모터 드라이버 토크 off)는 이 절의 범위가 아니다. 별도 ADR 후속이다.
