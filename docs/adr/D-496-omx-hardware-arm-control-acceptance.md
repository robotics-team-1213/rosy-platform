## D-496 OMX 실물 팔 조종 수용 — 실측 프로필과 벤치 관문 없이는 활성화하지 않는다

**Status:** Proposed (2026-10-07, 실물 하드웨어 없음 — OMX-AI 스펙 기반 조건 설계. 하드웨어 도착 전까지 어떤 런타임 프로필도 활성화하지 않는다)

## 배경과 확인한 차이

- D-411 B·C로 Pilot의 팔 조종 화면(`rosy.controls/1` 서술자 조립, `joint_jog` 조이스틱, 그리퍼 절대 목표·readback)는 **시뮬레이션에서만** 수용됐다(ROS-SIM Gazebo 관문 2회차, 2026-10-03). 실물 OMX 조종은 D-390 §5가 범위 밖으로 유지하고 있다.
- 실물 OMX-F는 현재 없다. 스펙은 확보돼 있다: 제조사 공식 문서 조사(2026-09-12, `docs/plans/2026-09-12-omx-hardware-spec-research.md`)와 `deploy/robot/omx/stack.lock.yaml`의 ROBOTIS `open_manipulator` 5.1.2 (rev `0a4af6a9…`) 고정.
- 시뮬 셀 프로필(`deploy/robot/omx/sim/cell_profile.yaml`)은 **명목값**이다. 머리 주석이 명시하듯 "no ROBOTIS hardware limit for OMX-F has been pinned yet. Real hardware needs its own measured profile and collision scene." 특히 그리퍼 jaw 접촉점(`contact_point_m`)은 Gazebo에서 보정된 값이고, Gazebo의 손가락 콜리전이 메시보다 약 7 mm 두껍다.
- `middleware/apps/device/omx/profile/config/omx.disabled.yaml`은 `model: omx_ai`, `enabled: false`로 실측 revision·driver·mount·power·payload·ports·recovery를 기다린다.
- 실물 API는 계약에 없다. API Ref와 `core_common.protocol` 스키마는 `/api/v1/sim/omx`만 안다(D-18: 경로와 스키마는 함께 바뀐다).
- 사용자 요청(2026-10-07): 실물 팔 없이 OMX-AI 스펙을 조사해 실물 지원을 미리 설계한다.

## 결정

1. **실물 활성화의 유일한 전제는 실측 프로필이다.** 스키마 `rosy.omx-hardware-profile.v1`을 설계 문서(`docs/plans/2026-10-07-omx-hardware-arm-enablement-design.md`)가 소유한다. 프로필이 채워지고 검증을 통과하기 전에 `omx.disabled.yaml`의 `enabled`는 `false`를 유지하며, 빈 `hardware_plugin`·joint map을 채워 넣지 않는다(프로필 모듈 AGENTS 규칙 유지).
2. **시뮬 프로필을 실물에 가져다 쓰지 않는다.** 관절 위치 한계(URDF ±2π를 좁힌 명목값), 속도(벤더 moveit 초심자 스케일 0.5 rad/s), 그리퍼 jaw 보정·squeeze·workspace는 실물에서 다시 잰 그 값만 쓴다. 시뮬 프로필의 각 주석이 근거를 이미 밝히고 있다.
3. **실물 명령 경로는 별도 계약이다.** `/api/v1/sim/omx`의 실물 대응은 새 경로·스키마와 함께 API Ref·`core_common.protocol`을 같은 커밋에서 바꾼다(D-18). 이 ADR은 조건만 정하고 경로를 정하지 않는다. Pilot의 `omx_sim` 드라이버는 `simulation: true`가 없는 목표를 계속 거절한다(drivers/AGENTS 규칙 유지).
4. **소유권·안전 규칙은 실물에 그대로 이어진다.** 팔 최종 명령은 OMX 로컬 컨트롤러 소유(D-296), 한 번에 제한 목표 하나·이전 목표 종결 후에만 다음 목표·100 ms 스트림 금지(D-390 §2, D-411 B 10항·구현 부록 1), HOLD와 `recover(operator_confirmed)`(D-386), leader(OMX-L) 동시 명령 금지. 런타임은 워크셀당 native systemd 인스턴스 1개(D-246·D-281·D-282).
5. **수용 사다리는 BENCH → DEVICE다.** BENCH는 실물이 도착한 뒤 사람이 지켜보는 벤치에서 EEPROM 한계 확인, 속도 사다리, jaw 보정, 통신두절·전원상실·재시작·HOLD 복구를 재고, 증거는 `docs/validation/omx-hardware-<date>/`에 남긴다. 합격선은 설계 문서의 측정 체크리스트가 정한다. DEVICE는 사용자 확인이다.
6. **가반하중은 자세 조건부다.** OMX-F는 최대 신장 100 g / normal reach 250 g이다. 파지 대상의 질량·파지 자세를 명시하지 않은 임무는 수용하지 않는다(2026-09-12 조사의 판단 유지).
7. **Pilot 앱은 화면을 재사용하고 드라이버만 추가한다.** D-411 B·C의 화면·위젯은 전송 무관하다. 실물 드라이버는 `omx_sim.js`와 별개 파일로, 계약 확정 뒤 다섯 곳(app.py `pilot_assets`, sw.js SHELL, dev_server PILOT_MIME, CMakeLists, Android 번들 검증)에 함께 등록한다.

## 범위 밖

- OMX-L 리더(leader)를 이용한 교시·텔레옵 UX — 벤더 leader remap은 시뮬에서 이미 제거했다(`omx-ai-native-action-only.patch`). 필요하면 별도 제안.
- Pinky 탑재 이동 조작(D-55 유지), 직교좌표 조그(D-404), 카메라 모델 선택(워크스테이션 계획 P2), 실물 녹화·수용(D-411의 DEVICE 절차는 로봇 공유 규칙에 따른다).

## 검토한 대안

| 대안 | 판단 |
|---|---|
| 시뮬 프로필·jaw 보정을 실물에 그대로 적용 | Gazebo 콜리전 두께·물리가 달라 파지 폭·squeeze가 어긋난다. 셀 프로필 주석이 스스로 금지한다. |
| 실물 API를 `/api/v1/sim/omx`의 플래그로 재사용 | 시뮬 경로는 `simulation: true` 강제가 계약이다. 한 경로에 두 의미를 두면 안전 경계가 흐려진다. |
| 하드웨어 도착 후 한 번에 설계 | 측정 항목·합격선이 그때 처음 생기면 벤치 회차가 설계와 뒤섞인다. 지금 조건을 고정하고 도착 후에는 측정만 하게 한다. |
| Leader(OMX-L) 교시를 1차 실물 UX로 | 동시 명령 금지를 지키려면 소유권 규칙이 먼저다. 시뮬에서 이미 leader remap을 제거한 이유와 같다. |

## 수용 기준과 증거 경계

- **SOURCE(지금):** 이 ADR과 설계 문서, 프로필 스키마 문서화. 런타임·API 변경 없음(`omx.disabled.yaml`·Pilot 코드 무변경).
- **BENCH(하드웨어 도착 후):** 설계 문서 체크리스트의 정량 합격선 통과, `docs/validation/omx-hardware-<date>/` 증거, 실측 프로필 리비전 확정.
- **DEVICE:** 사용자 확인 후 별도 기록. 이 ADR만으로 승격하지 않는다.

**관련 결정:** [D-18](D-18-.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-246](D-246-runtime-flexibility-native-default-container-sidecar-lane.md), [D-273](D-273-omx-camera-stream-and-arm-control-order.md), [D-281](D-281-site-host-placement-and-omx-instance-isolation.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-386](D-386-omx-async-goal-acceptance-and-phase-state.md), [D-390](D-390-pilot-omx-simulation-practice-boundary.md), [D-404](D-404-omx-setup-teaching-api-simulation-first.md), [D-411](D-411-pilot-robot-recording-control-descriptor-and-gripper.md)
