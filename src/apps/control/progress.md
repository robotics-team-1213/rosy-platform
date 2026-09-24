---
module: control
logical_modules: [M05, M06, M07, M11]
owner: CONTROL
last_verified: { commit: "uncommitted", date: 2026-09-22 }
gates:
  SOURCE:
    state: GO
    evidence: "흡수 패키지 배치·메타데이터·안내 문서 계약 시험 통과 (2026-09-16 재확인, 6 passed) — 폴더 구성, package.xml/README/guide의 CORE 소유권 문구를 단언한다"
    cmd: "python3 -m pytest test/test_control_absorption_package.py -q"
  LOCAL:
    state: GO
    evidence: "1179 passed, 28 skipped (2026-09-22 Windows, 패키지 cwd). D-162 T1/T2 장면 프로파일·매처 27 시험 + T3 노드 wiring·additive payload 11 시험 포함 — D-137/D-151/D-152 회귀 없음"
    cmd: "cd src/apps/control && python -m pytest test -q"
  ROS-SIM:
    state: HOLD
    blocker: "정확한 v2 mapping/CORE/Fleet 슬라이스는 2026-09-21 GO(52/52, 접근 가능 unknown 0%, 충돌 없음). 그러나 Control 전체 gate에는 sensing/camera/calibration/planning/safety-policy 노드 그래프 재실행과 물리 센서가 남아 있다. 레거시 전체 스택은 CORE와 병행 기동하지 않는다(D-38). 단, D-162 슬라이스(road_observer_node+scene context)는 2026-09-22 노드 그래프 검증을 통과했다(docs/validation/scene-context-control-node-2026-09-22)."
  ARTIFACT:
    state: HOLD
    blocker: "서명된 ARM64 manifest·immutable digest 발행 전. 흡수된 코드는 deploy가 소유하는 OS 이미지에 번들된다"
  DEVICE:
    state: HOLD
    blocker: "Pi bench Device 설치와 device-readback.sh --json 증거 없음. Control sensor adapter 활성화는 Device 보정 generation에 묶인다(D-47)"
  FIELD:
    state: PARKED
adrs: [D-37, D-38, D-40, D-42, D-47, D-50, D-57, D-58, D-77, D-118, D-119, D-143, D-151, D-152, D-149, D-155, D-156, D-162, D-168, D-183, D-199]
plans:
  - docs/plans/2026-09-06-module-split-criteria.md
  - docs/plans/2026-09-12-rosy-control-absorption-plan.md
  - docs/plans/2026-09-12-control-absorption-results.md
  - docs/plans/2026-09-13-control-safety-boundary.md
  - docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-17-interface-design-implementation-design.md
  - docs/plans/2026-09-21-line-follow-modes-design.md
  - docs/plans/2026-09-21-line-follow-modes.md
  - docs/plans/2026-09-21-semantic-road-control-design.md
  - docs/plans/2026-09-21-semantic-road-control.md
  - docs/plans/2026-09-22-scene-context-road-design.md
  - docs/plans/2026-09-22-scene-context-road.md
  - docs/plans/2026-09-21-camera-preview-dashboard-design.md
  - docs/plans/2026-09-21-camera-preview-dashboard.md
---
## 지금 상태

- 흡수된 ROS 2 Jazzy 패키지로 sensing/camera·OpenCV/calibration/planning/safety-policy/navigation-session 순수 로직을 제공한다(AGENTS.md).
- 최종 `cmd_vel` 발행과 이동 명령 중재는 CORE 소유다(D-38). 이 패키지의 레거시 전체 스택은 CORE와 병행 기동하지 않는다.
- 흡수된 Control sensor adapter는 기본 비활성이며, 켜면 Device 보정 generation에 묶인다(D-47; `core/progress.md` 참조).
- `web_node`+`dashboard.html`은 레거시 런치 진단 화면이다. 운용자 콘솔이 아니며 compose에 없다(D-77).
- LOCAL 증거는 `8fdd8d2` 기준이다. Windows에서는 `PYTHONPATH`를 `;`로 구분한다.
- `map_260905_update_v2` 단일 로봇 mapping 슬라이스는 Gazebo Harmonic에서 완주했다. 접근 가능한 본체 구성공간의 unknown/occupied는 모두 0%이고 CORE가 최종 `cmd_vel`을 단독 발행했다.
- D-143 차선 추종은 IR 또는 카메라 한 소스만 관제에서 선택하며, Control은 evidence만 내고 CORE가 제한된 Navigation 후보 명령을 만든다. hardware mode의 IO 이미지에는 V4L2 카메라와 Pinky I²C ADC 센싱 경로가 포함된다.

## 다음 gate

1. ROS Jazzy container에서 mapping 외 control 노드 그래프를 재실행해 모듈 전체 ROS-SIM HOLD를 해소한다.
2. 서명된 ARM64 artifact 발행 후 Pi readback으로 Control sensor adapter 활성화 경로를 확인한다(ARTIFACT → DEVICE).
3. Pinky에서 IR 검정/흰색 끝점, 카메라 방향·노출, 좌우 조향 부호, stale zero와 E-stop을 측정한다(D-143 DEVICE/FIELD).

## 2026-09-21 IR·camera line-follow status

- Dashboard에서 `OFF`, `IR_LINE`, `CAMERA_LINE`을 배타적으로 선택하고 오차·신뢰도·명령·정지 사유를 읽는다.
- `rosy-io`가 sensing-only observer, V4L2/OpenCV camera fallback, 0x08 I²C 12-bit IR ADC publisher를 실행한다. 최종 `cmd_vel` publisher는 CORE 하나뿐이다.
- 원본 영상 header 시각부터 0.3초 stale을 계산하며 malformed/저신뢰/미검출은 즉시 zero, 3초 손실은 재선택 전까지 latch다. manager의 API/ROS 공유 상태는 잠금으로 직렬화된다.
- 폐루프 host simulation에서 초기 횡오차 3.5 cm가 IR -0.03 cm, camera 0.006 cm로 수렴했고 두 모드 모두 stale zero와 loss latch를 통과했다.
- 외부 read-only YAML로 IR 끝점과 detector 임계값을 이미지 재빌드 없이 조정하며, 카메라 영상은 exposure/white-balance 수동 잠금 readback 전까지 전달하지 않는다.
- mode generation과 sensor evidence revision을 한 잠금에서 확인해 mode 전환이나 더 최신의 차선 상실 evidence 뒤에 이전 주행 명령이 적용되지 않는다.
- LOCAL Control `1084 passed, 26 skipped`, CORE `955 passed, 11 skipped`, root `1008 passed, 13 skipped`. Pi 카메라·I²C readback과 물리 차선 주행은 DEVICE/FIELD HOLD다.

## 2026-09-22 scene context status

- D-162(Proposed): 학습된 장면은 설정이지 권한이 아니다. `sensing/scene_context.py`(프로파일/스토어/매처)와 `road_observer_node` wiring(T3)이 착지했다. 비활성이 기본이며, 활성 시 payload에 additive `context` 필드를 실고 보정 명령 시 matcher 세션을 폐기한다. CORE 수용(T5)은 `core` 모듈 게이트 참조.
- **2026-09-22 노드 그래프 검증 PASS**: WSL2 Jazzy에서 road_observer_node를 scene_context_enabled로 기동, 합성 카메라 3페이스에서 generic→lane_follow→stop_line→crosswalk 순서 전환·리비전 결합·twist 토픽 0을 확인했다(docs/validation/scene-context-control-node-2026-09-22). D-162 슬라이스의 ROS-SIM 증거는 담겼고, 전체 그래프·물리 센서는 기존 HOLD 유지다.
- **2026-09-22 Gazebo 실렌더링 검증 PASS**: semantic_road_dashboard 헤드리스 실행에서 실제 렌더링 프레임으로 정지선 구간 stop_line 100% 분류, 표식 통과 후 generic 보수 폴백 확인(docs/validation/scene-context-gazebo-2026-09-22). crosswalk 배치 미검출로 crosswalk 컨텍스트는 호스트 시험만 존재.
- context는 인지 파라미터만 바꾼다. 정지·명령 결정은 여전히 LiDAR/IR 메트릭과 CORE가 소유하며(D-137/D-151), 프로파일 값 튜닝은 DEVICE gate 전까지 제네릭과 동일하게 둔다.
- LOCAL: `1179 passed, 28 skipped` (2026-09-22).

## 현재 유효한 금지사항

- 순수 로직 결정은 `control/control/`, `control/planning/`, `control/sensing/`, `control/watch.py`에만 두고 ROS import를 넣지 않는다(AGENTS.md).
- 이 패키지의 레거시 최종 `/cmd_vel` publisher를 CORE와 나란히 기동하지 않는다(AGENTS.md, D-38).
- `config/robot.yaml`이 단일 공유 파라미터 소스이며 per-node yaml은 이후에만 override한다(AGENTS.md).

## 2026-09-21 camera preview status

- road observer가 동일 detector frame의 overlay JPEG를 기본 2 FPS·최대 폭 640으로 발행한다. preview는 관측 전용이고 detector 입력이나 주행 명령을 바꾸지 않는다.
- HOST-SIM JPG/GIF와 dashboard 렌더는 통과했다. Pi CSI 실제 frame, exposure/AWB readback과 물리 homography는 DEVICE/FIELD HOLD다.

## 2026-09-20 adaptive speed authorization status

- Geometry/sensor estimates now have candidate and active certificate states, context binding, evidence digests, bounds, observability checks, and independent holdout promotion.
- Motion envelopes are direction-specific and bind stopping, latency, lateral error, environment, payload, battery, temperature, wheel revision, and the active geometry digest.
- Runtime limiting is fail-closed for stale/unknown evidence and continuously reduces speed using uncertainty plus latency/braking distance. Drift immediately returns authority to at most `0.014 m/s`.
- The Control-to-CORE snapshot carries a numeric `linear_limit`; CORE remains the sole final `cmd_vel` owner.
- Current default and sensor-node publication remain `0.014 m/s`. A higher ceiling requires explicit commissioned configuration and is not active in this change.
- Verified: focused Control `37 passed`; CORE package `895 passed, 11 skipped`; IMU host `4 passed, 10 skipped`.
- Final host Control gate: `1038 passed, 26 skipped`; the startup-profile fixture now supplies the declared empty `web_port` and `web_backend_port` defaults.
- ROS-SIM HOLD: no Jazzy runtime proof for the new policy.
- DEVICE HOLD: no Pi/ARM64 build, BNO055 live readback, stopping trials, `map_260905_update_v2` traversal, or physical clearance proof.
- FIELD HOLD: no unattended complete-route or supervision acceptance.

## 2026-09-20 flexible clearance recovery status

- The fixed 0.08 m execution cap and compatibility fallback are removed from the measured escape executor.
- A fresh proposal must bind `robot_diameter_m` and `max_reposition_m`; the latter cannot exceed the calibrated circumscribed diameter or the current measured corridor.
- Reverse is preferred among equivalent recovery candidates, but forward remains available when rear evidence is unsafe or produces no improvement.
- The episode stops on restored turn clearance, stale scan/proposal, geometry revision change, pose deviation, no progress, hazard, or budget exhaustion. Its bound may shrink but cannot expand while moving.
- Verified in pure logic and the real legacy adapter: `30 passed` focused tests, `102 passed` in the wider recovery/adaptive-speed/certificate/calibration set, and final full Control `1038 passed, 26 skipped`. The active CORE/Nav2 recovery connection remains HOLD to preserve CORE as the only final `cmd_vel` owner.

## 2026-09-20 optional camera ground homography status

- A camera-ground profile is now separated into candidate, eligible, requested, and active states. Reported residuals are ignored; reference and independent validation errors are recomputed from the point pairs.
- The runtime image size, processed rotation, camera profile revision, intrinsic/undistorted-point contract, coordinate semantics, bounded thresholds, independent image names/count/distance span, and four physical attestations all fail closed.
- `camera_ground_mode` keeps `pinhole` as the default. A validated homography can be enabled for the current session from the diagnostic dashboard; the switch cannot override failed checks and is not persisted.
- Board-relative lateral coordinates provide forward distance only. Camera metric output remains advisory and does not create speed or final command authority.
- SOURCE verification is covered by host pure-logic and wiring tests. DEVICE/FIELD remain HOLD until a complete profile, independent captures, measured Pinky Pro distances, and live readback are available.

## 2026-09-21 exact-map live mapping status

- `final_22` ran the installed `map_260905_update_v2` world through all 52 waypoints and returned to the start after `13.754679 m` of model-pose odometry.
- The footprint-aware audit found `0.0%` unknown, `0.0%` occupied, and `0.0%` outside-raster samples in the spawn-connected robot-center configuration space. The sealed lower-left pocket remains separately reported as inaccessible topology.
- Sampled body overlap was false and the minimum sampled body-to-wall margin was `0.021789 m` for a `0.172 m` diameter.
- Adaptive motion was measured in the same run: narrow-space median `0.067975 m/s`, open-space median `0.122453 m/s`, maximum `0.158851 m/s`.
- CORE was the sole final `cmd_vel` publisher, stopped at zero, and Fleet read back the robot online with `map_id=occupancy:326966090e60`.
- This is ROS-SIM evidence only. It does not promote the camera homography, device calibration, stopping envelope, Pi artifact, or physical FIELD gate.

## 2026-09-21 semantic-road control status

- `map_260905_update_v2` 파생 장면에 차선, 정지선, 횡단보도, 신호등을 추가했고 기본 16-wall geometry는 변경하지 않았다.
- 합성 camera frame은 실제 road detector, strict decoder, traffic policy, atomic command gate를 통과했다. 의미 YAML 정답은 detector에 입력하지 않았다.
- red에서는 완전 정지와 dwell/대기, green에서는 제한 속도 재출발, stale evidence에서는 `HOLD` zero command를 확인했다.
- 관제는 상태·사유·scene/policy revision을 읽고 stage 후 정지 상태에서만 apply한다. tuning과 simulation signal은 안전 경계를 우회하지 못한다.
- 이 결과는 HOST simulation PASS다. 실제 Gazebo camera graph와 Pinky Pro 카메라·모터·제동거리는 ROS-SIM/DEVICE/FIELD HOLD다.

## 2026-09-23 calibration rotation freshness hold

- 회전 검증이 자기 끝점 계산(`match_motion`, rig 0.3–0.6 s)으로 executor를 막아 스스로 입력을 낡게 만들던 결함을 고쳤다. 정지 중에는 최대 1 s 동안 0을 유지하며 대기하고, 끝점 등록 뒤에는 새 증거가 충분히 신선할 때까지 다음 구간을 시작하지 않는다.
- rig 분리 모드의 간헐 실패 중 회전 단계 몫은 교차 실행에서 사라졌다(기준 2/5, 수정 5/5, 최종본 11회 연속 통과). translation 단계 실패(부하 20 이상에서 decision 큐 대기)는 별도 과제로 남는다.
- 실기 영향: Pi에서 `match_motion` 소요 시간은 미측정이다. 0.25 s 창과 `dt <= 0.5` 검사에 걸리는지 DEVICE 단계에서 확인해야 한다. SOURCE/ROS-SIM 근거이고 DEVICE/FIELD는 HOLD.

## 2026-09-23 calibration wall tracker cost

- 직진 교정용 벽 추적(`wall_tracker._fit`)을 결과가 비트 단위로 같게 벡터화했다. scan당 27 ms에서 7 ms로 줄었다. 부하가 높은 rig에서 calibration 노드가 스스로 포화하던 원인(class B의 첫 층)이 줄었다.
- 남은 class B는 박스 초과 할당(부하 25–30 이상)에 따른 OS 스케줄링 공백이다. 코드 결함이 아니다. rig 판정은 부하가 낮은 시간대에 하거나 환경 가드를 둔다.
- 실기: Pi에서 scan 콜백 시간과 10 Hz 주기 대비 점유율은 DEVICE 단계에서 확인한다.

## 2026-09-24 planning map inflation cost (D-185 R1)

- 경로 안전에 쓰는 지도 부풀리기(`OccupancyMap.inflate`)를 결과가 셀 단위로 같게 벡터화했다. 호출당 비용이 6–8배 줄었다(host). goal·wander의 계획 tick이 가벼워진다.
- 실기: Pi에서의 goal tick 비용은 D-185 R8에서 확인한다.

## 2026-09-24 calibration late-scan hold

- 회전 검증에서 늦게 도착한 scan을 "없음"이 아니라 "늦음"으로 판정한다. 정지 중에는 기존 1 s 대기로 넘기고, 구조가 잘못된 scan은 여전히 즉시 실패한다. rig에서 본 회전 단계 잔여 실패 경로를 닫았다.

## 2026-09-24 rig environment guard (D-185 R4)

- rig가 과부하 박스에서 돈 실행을 "환경 무효"로 표시하고 종료 코드 3을 낸다. 판정 스크립트는 이 실행을 통과·실패로 세지 않는다. 속도 증거가 없으면 판정을 보류하고, 실제 실패를 무효로 덮지 않는다.
- 세션 간 Gazebo 잠금은 이 rig부터 적용했다. 다른 Gazebo 실행기의 채택은 단계적이다.

## 2026-09-24 Pi hot-path measurement tool (D-185 R8)

- `tools/device/hotpath_measure.py`가 세 핫패스(`_segments`, `match_motion`, `inflate`)의 소요 시간과 control 노드별 CPU%·RSS·부하·PSI를 JSON으로 남긴다. Raspberry Pi에서 돈 보고서만 실기 증거로 표시한다.
- 실기: 도구만 준비됐고 Pi 실행은 HOLD다. 수치가 나오기 전까지 D-185의 실기 항목은 그대로 HOLD다.

## 2026-09-24 EventsExecutor opt-in (D-185 R3)

- control 노드와 rig가 `ROSY_EXECUTOR=events`로 EventsExecutor를 쓸 수 있다. 기본값은 이전과 같은 SingleThreadedExecutor다. rig A/B와 실기 측정이 남아 있어 기본값 전환은 하지 않았다.

## 2026-09-24 footprint sweep cost (D-185 R5)

- sim safety의 footprint sweep과 직진 한계 계산을 결과가 비트 단위로 같게 줄였다. 증명된 거리 하한으로 먼 scan 점을 빼고, 시간 샘플을 묶어 계산한다. host에서 sweep 호출당 1440점 21→4–6 ms, 직진 한계 5–39→2–8 ms. 점이 모두 가까운 최악 입력에서는 원본과 비슷하다.
- 실기 경로가 아니다(rig 여력 회복).

## 2026-09-24 latest-only subscriptions (D-185 R2)

- 최신 값만 쓰는 구독 12개가 옛 값을 쌓지 않는다. rig 유효 실행에서 기준본과 같은 결과(전부 `ready`)를 확인했다.

## 2026-09-24 rig /clock relay (D-185 R6)

- `RIG_CLOCK_HZ=N`이면 rig가 `/clock`을 벽시계 초당 최대 N개로 줄인다. rig 노드 CPU가 절반 이하가 됐다. 기본값은 예전 bridge다.

## 2026-09-24 EventsExecutor rig result, single-process cause (D-185 R3·R7)

- rig에서 EventsExecutor가 결과를 그대로 두고 rig 노드 CPU를 약 60% 줄였다. 기본값 전환은 실기 측정 뒤로 미룬다.
- 한 프로세스 모드 실패는 교정 신선도 hold 수정(`c67437d1`)으로 이미 닫혔다. 수정 전 트리에서만 재현된다.

## 2026-09-24 first device bench (D-185 R8)

- Pi 5 실기에서 wall_tracker는 2.3배, inflate는 7.4배 빨라졌다. match_motion(호출당 약 70 ms)이 다음 CPU 후보다.
