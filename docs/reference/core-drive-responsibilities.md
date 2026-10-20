# CORE·Drive·Arm의 현재 책임 구조

2026-10-13 D-743 S1 보완: 현재 Drive holder는 `middleware/drive`다. 기존 설치 identity와 CORE 조립은 유지하며 [검증 기록](../validation/drive-holder-s1-2026-10-13/result.md)에 source/설치/착지와 배포/장치 증거를 구분한다.

2026-10-11 local main `7f391fa2d`에 반영한 소스 배치. Accepted [D-625](../adr/D-625-semantic-structure-and-staged-migration.md), [D-626](../adr/D-626-d625-holder-migration-execution.md), [D-627](../adr/D-627-core-drive-composition-seam.md), [D-628](../adr/D-628-core-drive-output-and-recovery-boundaries.md), [D-630](../adr/D-630-remaining-platform-semantic-holders.md)에 따른다. [전체 폴더 안내](platform-folder-responsibilities.md)는 현재 manifest의 모든 root를 기록한다. [검증·착지 기록](../validation/d630-platform-holders-2026-10-11/result.md)에서 source와 remote 시험 결과를 배포·장치 수용과 구분한다.

```text
middleware/
├─ core/
│  ├─ api/ (core_api_web: 기존 HTTP/WebSocket/UI)
│  ├─ gateway/core/
│  │  ├─ services.py (공통 조립·service attribute·listener 연결)
│  │  ├─ drive/{line_follow,docking,traffic}.py (기존 Drive 조립)
│  │  ├─ system/power.py (공통 power/battery parser·생성)
│  │  └─ bridge/ (ROS 입출력·최종 Base cmd_vel 발행)
│  ├─ services/core_features/
│  │  ├─ command/ (mode·candidate admission·최종 선택)
│  │  ├─ safety/ (공통 보호·policy·velocity 검증)
│  │  └─ state, power, diagnostics, calibration lease, recovery admission 등
│  └─ events/ (core_events)
├─ drive/
│  ├─ behaviors/{line_follow,docking,navigation,localization,swarm,road_behaviour,traffic_policy}
│  ├─ runtime/ (기존 control/goal/wander/safety ROS 진입 모듈)
│  ├─ planning/{nav2,grid}
│  ├─ tracking/wander
│  ├─ recovery/
│  ├─ calibration/
│  └─ motion_limits/adapter
├─ perception/
│  ├─ sensors/sensing (control.sensing)
│  ├─ front_camera/perception (control.sensing.perception)
│  └─ control/ (기존 node 조립·compatibility)
└─ devices/
   ├─ pinky/{bringup,profile,description}
   └─ omx/{adapter,profile,agent}
```

## 조립과 구현 owner

| 책임 | 현재 실제 owner | 보존하는 경계 |
|---|---|---|
| CORE 공통 조립 | `middleware/core/gateway/core/services.py` | 공통 state·identity·Command/Safety 객체와 service attribute. subsystem parser는 명시적 legacy reexport |
| Drive 조립 | `core/drive/line_follow.py`, `docking.py`, `traffic.py` | 기존 line manager와 live angular provider, docking/swarm, policy/observer 생성. 새로운 framework/process/container 없음 |
| 공통 power/battery | `core/system/power.py`, `core_features.power` | 기존 parser fallback·validation·data path와 power→battery 생성 순서. shutdown sentinel은 요청이며 host unit이 halt 소유 |
| Drive planning backend | `middleware/drive/planning/nav2`, `planning/grid` | ROS `navigation`과 기존 `control.planning` identity. CORE goal facade·취소 generation·backend 입출력 구분 |
| 차선·군집·localization 실행 | `middleware/drive/behaviors`의 해당 구현 | D-649로 소스 이전. 설치 identity는 기존 `core_features.*`, 새 library/process 없음 |
| 기존 Control Drive 알고리즘 | `middleware/drive/{tracking,recovery,calibration,motion_limits}` | ROS `control` 배포의 기존 `control.control.*`, `control.wander`, `control.safety` identity. sensor-only adapter 유지 |
| 공통 Base 명령/Safety | `core_features.command`, `core_features.safety`, `core.bridge` | CORE 최종 command 선택과 ROS publisher. E-stop/readiness/deadman·policy·세대 검증 |
| Drive 기하·운동 proof | `line_follow/{clearance,body_stop}`, recovery sweep, Drive envelope·floor/body 검사 | 현재 후보의 곡률·전진·후진·pivot 근거. CORE 공통 Safety를 대체하지 않음 |
| Arm 실행/Safety | `middleware/devices/omx/adapter/omx_adapter` | joint/action owner, limits·fresh feedback·stop/rearm/HOLD. Base cmd_vel slot에 합치지 않음 |
| 센서·vision evidence | `middleware/perception/{sensors/sensing,front_camera/perception}` | 기존 provider/import·model/resource identity. operational final writer 추가 없음 |

US005 조립 추출은 기존 네 parser의 본문과 constructor 인자를 유지한다. `core.services`의 `_battery_config`, `_power_config`, `_traffic_policy_config`, `_signal_observer_binding`, `SHUTDOWN_SENTINEL_NAME` import는 계속 제공한다. signal observer는 명시적 binding과 policy map/scene 검증 뒤에 기존 위치에서 start한다. line recovery/envelope provider 연결은 기존 순서에 남는다.

D-628은 CommandManager의 stop/policy/mode invalidation callback을 기존 service listener 앞에 등록한다. 그 뒤 mode mirror→docking 해제→EMERGENCY release 처리와 E-stop의 state→docking→swarm→nav cancel→line stop→traffic reset 순서는 유지한다. 이 의도적인 invalidation prefix와 US005의 기존 service listener 상대 순서 보존을 구분한다.

## D-628 현재 주행 경계

ModeMachine은 mode 전환/release마다 epoch를 갱신한다. NAVIGATION·DOCKING 후보는 검증한 mode/epoch 아래 원자적으로 저장되는 불변 candidate이며 다른 mode에서 들어온 후보는 admission되지 않는다. 모드 이탈은 기존 slot을 무효화하므로 재진입으로 오래된 후보가 복원되지 않는다. CommandManager는 mode epoch·input epoch와 선택한 candidate의 객체 동일성을 Safety/policy 평가 전후에 다시 확인한다. 평가 중 mode·candidate 교체나 E-stop이 발생하면 출력은 zero다. 미래 timestamp·nonfinite 입력/상한도 정상 후보로 사용하지 않는다.

이것은 같은 NAVIGATION mode 안에서 모든 외부 ROS Twist의 Nav2 goal identity를 검증하는 완성된 producer 계약이 아니다. 기존 Nav2 goal generation과 lease/MANUAL fencing은 유지하지만 전 producer의 MotionIntent admission과 goal-bound 외부 입력은 **D-442 후속 단계**다. 외부 ROS Twist에 identity를 추정하여 붙이지 않는다.

차선 후보는 정적 profile nav 상한을 먼저 적용한 뒤 traffic gate에 들어간다. traffic은 기존 linear scale 의미를 유지하며 body/envelope가 검토하는 arc family에 포함된다. 이후 session/person/policy 상한은 line 후보의 `v`, `w`를 같은 비율로 줄인다. 내부 `preserve_curvature` 표식은 line 경로에만 적용되고 MANUAL/Nav2/docking의 기존 axis clip과 Arm은 유지한다. 보정 출력이 검토한 line 곡선을 바꾸거나 부호·pivot·finite·freshness 검증에 실패하면 거절한다. 움직이는 곡선은 부호를 포함한 `w/v`, pivot은 회전 sweep, 후진은 후방 sweep으로 평가한다.

## 복구의 현재 근거와 옵션

`RESUME`, `BACK_AND_RETRY`, `YIELD`, `REALIGN`은 답변 시점의 scan·calibration·상한 근거를 현재 manager clock으로 다시 읽는다. 이 갱신은 recovery phase를 tick하거나 stuck ID·attempt budget을 초기화하지 않는다. standalone recovery는 저장 snapshot의 실제 경과 시간을 scan/trail age에 더하고 미래·역행·nonfinite clock과 잘못된 저장 age를 거절한다. `WAIT`, `MANUAL`, `ABORT` 정지 출구는 오래된 snapshot에서도 유지한다. 답변 후 기존 evidence revision을 갱신하여 답변 전에 계산한 motion candidate를 재사용하지 않는다.

KTURN 후진 arc는 기존 rear strip·blind band·trail·freshness 거절 검사를 먼저 거친 뒤 차체의 회전 후진 궤적 `_rear_sweep_clear`를 확인한다. 직선 strip 밖의 측면 장애물도 sweep에서 거절한다. PIVOT의 sector/turn clearance와 전진 arc의 body/object 검사는 각 기존 owner에 남는다.

`LineFollowConfig`의 `recovery_local_enabled`, `progress_watch_enabled`, `stuck_realign_enabled` 기본값은 모두 `False`다. REALIGN 활성 config는 기존 `obstacle_mode: path` 조건을 요구한다. 이번 소스 변경은 현장 overlay·모델·자동 복구를 활성화하지 않으며 동일 문제의 bounded attempt·취소·정지 경계를 유지한다.

## World와 검증 상태

현재 World의 MapPose 구현은 `operations/world/src/rosy/world/state/projections/map_pose.py` 하나다. Fleet·sim·시험은 `rosy.world.state.projections.map_pose`를 직접 import한다. D-630의 Fleet identity alias는 D-752에서 제거했다. service·trip·claim·dispatch transaction은 Fleet이 소유한다. `source=bridged`는 마지막 관측 이후의 odom dead reckoning이고, 행동 조건부 미래 rollout이 아니다. action-conditioned World model과 그 학습·독립 평가·decision 소비자는 D-625의 후속 계획이며 빈 prediction 폴더를 만들지 않았다.

[독립 Safety 리뷰](../validation/d628-core-drive-2026-10-11/safety-review.md)는 소스 범위 판정이다. remote 회귀·known_failures·harness/Safety·checkout 밖 설치 결과와 local main 착지는 [검증 기록](../validation/d630-platform-holders-2026-10-11/result.md)에 있다. 옛 경로 때문에 실패한 시험과 수정 후 재검사를 각각 기록했다. CI·ROS 실행·ARM64 이미지·배포 readback·실물·현장 수용은 확인하지 않았다. 후속 작업은 [CORE 계획](../plans/2026-10-11-core-responsibility-and-driving.md), [D-628 실행 계획](../plans/2026-10-11-core-drive-remaining.md), [전체 이전 계획](../plans/2026-10-11-platform-structure-migration.md)을 따른다.

## D-649 책임 이동 보완

`middleware/drive/behaviors/{line_follow,docking,navigation,localization,swarm,road_behaviour,traffic_policy}`가 Base 행동 구현의 정본이다. CORE 서비스 배포가 기존 `core_features.*` 이름으로 설치하며 구현 복사본은 없다. `middleware/drive/runtime/`는 기존 control/goal/wander/safety ROS 진입 모듈을 소유하고 `control.*` 이름으로 설치한다. 위의 이전 배치 설명은 이 이동으로 보완된다. CORE 공통 Command/Safety와 `core/drive` 조립은 유지한다.

반복 이름은 세 종류다: 설치 패키지 이름(`core`, `control`, `fleet`, `rosy` namespace), 서로 다른 권한(장치-local execution/현장 execution, 관측 safety adapter/CORE Safety), 실제 혼재했던 행동 구현(이번 Drive 이동). 호환 initializer에는 알고리즘을 추가하지 않는다. 일반 캘리브레이션 lease와 카메라 장애 복구 자격 판정은 CORE 공통 admission이며 Drive 탈출 운동 구현과 다르다. Perception localization 노드는 상태/관측 근거를 소유한다.

현재 물리 이동과 설치 매핑, 원격 시험, 배포/장치 수용은 별도 기록이다. [D-649](../adr/D-649-drive-behavior-source-ownership.md), [실행 계획](../plans/2026-10-11-role-folder-boundaries.md)을 따른다.
