# OMX 실물 팔 활성화 설계 — 하드웨어 도착 전에 고정하는 측정 프로필과 벤치 관문

작성일: 2026-10-07. 대상 결정: [D-496](../adr/D-496-omx-hardware-arm-control-acceptance.md) (Proposed).
전제: 실물 OMX-F 하드웨어는 아직 없다. 이 문서는 하드웨어가 도착했을 때 **측정만 하면 되도록** 조건을 미리 고정한다. 런타임·API·Pilot 코드를 지금 바꾸지 않는다.

## 1. 목표와 범위

Pilot 앱에서 OMX 실물 팔을 조종하는 날까지의 경로를 조건으로 만든다. 범위는 OMX-F follower 1대를 책상 고정 워크셀로 쓰는 것까지. Pinky 탑재(D-55), 리더 교시 UX, 직교좌표 조그(D-404), 카메라 선택은 범위 밖이다.

## 2. 확보된 스펙

근거: 제조사 공식 문서 조사(2026-09-12), `deploy/robot/omx/stack.lock.yaml`(ROBOTIS `open_manipulator` 5.1.2, rev `0a4af6a923b8b7d80b8c20506d1839c54d2e993e`), 워크스테이션 런타임 계획(2026-09-26).

| 항목 | 값 | 비고 |
|---|---|---|
| 형상·자유도 | 팔 5 + 그리퍼 1 (`joint1`–`joint5`, `gripper_joint_1`) | 벤더 `omx_f_follower_ai` 컨트롤러, 100 Hz |
| 구동기 | XL430-W250-T ×3, XL330-M288-T ×3 | TTL 1 Mbps 내부 버스 |
| 무게·도달 | 팔 자체 560 g, 최대 도달 400 mm | |
| 가반하중 | **최대 신장 100 g / normal reach 250 g** | 250 g을 전 작업공간 허용으로 쓰지 않는다 |
| 전원·연결 | 12 VDC, USB-C | 벤더 기본 포트 `/dev/ttyACM0`, by-id 권장 |
| 그리퍼 폭 | OMX-F 텍스트 사양에 없음(구형 RM-X52 20–75 mm 참고) | 실측 필수 |
| 호스트 | amd64 워크스테이션, 워크셀당 native systemd 1인스턴스 | D-246·D-281·D-282 |

## 3. 시뮬이 가정한 값, 실물이 다시 잴 값

`deploy/robot/omx/sim/cell_profile.yaml`은 Gazebo 명목한계다. 각 항목을 실물에서 같은 방식으로 다시 잰 값만 실물 프로필에 들어간다.

| 항목 | 시뮬 값(근거) | 실물 측정이 필요한 이유 |
|---|---|---|
| 관절 위치 한계 | joint1 ±2.6, joint2 [-1.7,1.2], joint3 [-1.3,1.7], joint4 [-0.3,2.3], joint5 ±2.0 (URDF ±2π를 좁힘) | "ROBOTIS hardware limit 미고정" — EEPROM 한계·기구 간섭으로 확정 |
| 속도·가속 | 0.5 rad/s (벤더 moveit 5.0 × 초심자 0.1) | 실물 부하·토크에서 사다리 시험으로 |
| 그리퍼 범위 | [-0.1, 1.1], open 1.0, closed 0.0 | 닫힘 아래 여유(-0.1)는 모방 readback 오차 전제 — 실물 오차로 재확인 |
| jaw 접촉점 | `contact_point_m: [0.0543, -0.01703]` — **Gazebo 보정값** | "hardware needs its own measured value" — Gazebo 콜리전이 메시보다 ~7 mm 두꺼움 |
| 파지 폭·squeeze | 10–50 mm 인정, squeeze 3 mm, release 여유 10 mm | 블록 폭별 정지 위치를 실물에서 재보정 |
| preload | 0.05 rad (D-411 C 쥔 채 조임) | stall 위치가 실물에선 다르다 |
| workspace | ±0.28 m × [0.005, 0.22] m (링크 길이 계산) | 실물 장착면 높이·테두리로 재측정 |
| 정지·복구 | owner의 `max_joint_state_age_s` 0.5·`action_timeout_s` 45 (sim 시간, wall 4배) | 통신두절·전원상실·재시작은 실물에서 "unverified" 상태 |
| 소유·좌석 | 단일 owner·seat·HOLD·`recover(operator_confirmed)` (D-386) | 규칙은 동일, 시간값은 실물 재측정 |

## 4. 하드웨어 프로필 스키마 제안 — `rosy.omx-hardware-profile.v1`

`omx.disabled.yaml`이 기다리는 필드를 채우는 측정 문서다. 시뮬 `cell_profile.yaml`과 짝을 이루되 **실측 리비전 없이는 유효하지 않게** 로더가 강제한다. 값은 비워 두고 항목만 고정한다(빈 `hardware_plugin`·joint map을 지금 채우지 않는다 — 프로필 모듈 AGENTS 규칙). 실제 시리얼 by-id·호스트 주소는 `private/`(D-226).

```yaml
schema: rosy.omx-hardware-profile.v1
profile: hardware            # cell_profile.yaml 의 profile: simulation 과 대비
measured:
  date: ""                   # 측정 회차 날짜 (docs/validation/omx-hardware-<date>/ 와 짝)
  revision: ""               # 실물 리비전 (구매처·일련번호·펌웨어)
  evidence: ""               # docs/validation 경로
serial:
  by_id: ""                  # /dev/serial/by-id/... (preflight 가 받는 형식, private/ 소유)
  baudrate: 1000000          # TTL 1 Mbps (제조사 사양)
joints:                      # joint1..5 — position [min,max], velocity, acceleration
  joint1: {position: ["", ""], velocity: "", acceleration: ""}
  # ... EEPROM 한계 ∩ 기구 측정
gripper:
  joint: gripper_joint_1
  position: ["", ""]
  open: ""
  closed: ""
  preload: ""
  jaw: {pivot_y_m: [0.0075, -0.0108], contact_point_m: ["", ""], squeeze_m: "", min_grasp_width_m: "", max_grasp_width_m: "", release_clearance_m: ""}
workspace: {min_m: ["", "", ""], max_m: ["", "", ""]}
owner: {max_joint_state_age_s: "", action_timeout_s: "", wall_clock_bound_factor: ""}
power: {supply_v: 12, noted_load_a: ""}   # 정격·실측 소비
```

로더·검증 시험은 하드웨어 도착 후 실물 활성화 브랜치에서 `omx_adapter`에 추가한다. 지금은 문서가 스키마를 소유한다.

## 5. 벤치 측정 체크리스트 (BENCH 게이트 합격선)

하드웨어 도착 후 순서. 각 단계 증거는 `docs/validation/omx-hardware-<date>/`. 사람이 지켜보며, 비상정지 수단(전원 차단)을 손에 두고 시작한다.

- **B0 연결 확인**: by-id 경로 해석, 문자장치·읽기쓰기 접근 preflight 통과(기존 `deploy/robot/omx/preflight.py` 재사용). 합격선: 추측 없는 by-id 1개만 해석.
- **B1 전원·대기**: 12 V 공급 아래 팔 무동작 시 전류 기록. 합격선: 정격 내, 토크 유지 on/off 확인.
- **B2 EEPROM 한계 읽기**: 관절별 위치·속도 한계 읽어 프로필 `position`·`velocity` 초안 채움. 합격선: 6개 관절 모두 읽힘, 시뮬 명목값과의 차이 기록.
- **B3 속도 사다리**: 낮은 속도부터 관절별 단독 구동, 진동·이탈 관찰. 합격선: 프로필 velocity가 관측된 안정 속도 이하.
- **B4 workspace 실측**: 장착면 기준 도달 박스 측정, 셀 프로필 값과 대조. 합격선: 측정 박스가 프로필 workspace를 포함.
- **B5 그리퍼 보정**: 알려진 폭(예: 20/30/40 mm 게이지 블록)의 정지 위치로 jaw `contact_point_m` 재보정. 합격선: 세 폭 재현 오차 ≤ 0.5 mm(시뮬 보정 재현오차 0.03 mm의 현실 여유).
- **B6 파지·가반하중**: 대상 질량·자세별 파지·이동. 합격선: 파지 대상 질량이 신장 조건 포함 명시돼 있고, 100 g(최대 신장)/250 g(normal) 한계 내.
- **B7 통신두절·전원상실·재시작**: USB 뽑기·전원 차단·프로세스 재시작에서 각각 관절이 안전하게 멈추는지, HOLD 진입·`recover(operator_confirmed)` 복구가 도는지. 합격선: 세 시나리오 모두 무제어 움직임 없음, 복구는 운용자 확인 뒤에만.
- **B8 Pilot 종단**: 실물 API 계약(D-496 3항, 별도 커밋으로 API Ref·스키마 동시 변경)이 정해진 뒤 Pilot 실물 드라이버로 조작·정지·그리퍼 readback 확인. 합격선: 시뮬 관문(D-411)과 같은 조작 시나리오 통과.

B7까지 통과하면 실측 프로필 리비전을 확정하고 그때 `omx.disabled.yaml` 활성화를 별도 변경으로 제안한다.

## 6. Pilot 앱 실물 드라이버 설계 (계약 대기 상태)

- `drivers/omx.js`: `omx_sim.js`와 같은 모양(`kind`, `discover`, `request`)의 실물 전송. 경로는 실물 API 계약이 정하는 대로. `omx_sim.js`는 `simulation: true` 강제를 유지한다.
- `app.js`: `registerDriver(omx.kind, omx)` 한 줄 추가. 화면(`screens/arm.js`·`compose.js`·위젯·`arm-stick.js`·`controls.js`)은 D-411 B·C 그대로 재사용 — 서술자 조립이라 실물 서술자만 바꾸면 된다.
- 등록 다섯 곳(빠뜨리면 404, `test_shell_assets.py`가 잡는다): `api/app.py` `pilot_assets`, OMX `pilot_sim_api.py` `PILOT_ASSETS`(실물 API 쪽 대응), `sw.js` SHELL(+CACHE 이름 올림), `test/dev_server.py` `PILOT_MIME`, `CMakeLists.txt`.
- Android 앱: 화면 JS가 APK에 번들되는 구조는 동일(`bundleScreens`의 `drivers/**/*.js` 패턴이 `omx.js`를 자동 포함). `ProxyGuard` 경로 allowlist가 실물 API 경로를 허용하는지 그때 확인(오늘 확인된 규칙: `/api/v1/` 접두 허용).
- 지금은 아무 파일도 만들지 않는다. API가 계약에 없는 경로를 발명하지 않는다(Working In This Directory 규칙).

## 7. 남은 것과 순서

1. (지금) 이 설계·D-496 착지 — 조건 고정.
2. 시뮬 ROS-SIM HOLD 잔여 정리: 그리퍼 정밀 도달·전체 재시작 회복·Pinky 재측정(`middleware/ui/pilot/progress.md`). 실물 관문과 병렬이지만, 파지 보정 방법론은 시뮬 관문에서 먼저 다듬는다.
3. 하드웨어 도착 → B0–B7 측정, 실측 프로필 리비전 확정.
4. 실물 API 계약 설계(API Ref·스키마 동시 변경) → Pilot 실물 드라이버 + 다섯 곳 등록 → B8.
5. DEVICE 게이트: 사용자 확인 후 `docs/validation/` 기록.
