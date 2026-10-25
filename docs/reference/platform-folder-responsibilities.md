# ROSY Platform 현재 폴더 책임

제품 앱의 개발 위치는 `applications/<제품명>`이다. [D-822](../adr/D-822-fleet-application-source-boundary.md)에 따라 Fleet 화면은 `applications/fleet/web`, 앱 조립은 `applications/fleet/gateway`에 둔다. API·원장·실행 조정은 `operations/fleet`에 남고 Fleet 배포·설치 신원은 유지한다. 시작 방법은 [Fleet 앱 안내](../../applications/fleet/README.md)를 본다.

2026-10-13 폴더 정리의 착지 범위는 [최신 단계 기록](../validation/folder-remaining-2026-10-13/result.md)이다. 아래 단계 표의 S3–S10은 그 기록과 같고, S1은 D-743, S2는 D-747이다. 원격 재검증·CI·배포·장치는 그 기록이 NOT RUN으로 남긴 항목이다. 단계 표와 편집 집·manifest가 다르면 편집 집 표와 manifest가 현재 경로다.

2026-10-13 D-743 S1 보완: 현재 Drive holder는 `middleware/drive`다. 기존 설치 identity와 CORE 조립은 유지하며 [검증 기록](../validation/drive-holder-s1-2026-10-13/result.md)에 source/설치/착지와 배포/장치 증거를 구분한다.

2026-10-11 local main `d4988bffba`에 반영한 소스 배치. 실제 폴더 이동과 경로 수정의 커밋·머지 이후 이 안내를 정리했다. [이동·검증·착지 기록](../validation/d637-remaining-folders-2026-10-11/result.md)에서 소스·설치·시험·배포·장치·현장 증거를 구분한다.

구조 결정은 Accepted [D-625](../adr/D-625-semantic-structure-and-staged-migration.md), [D-626](../adr/D-626-d625-holder-migration-execution.md), [D-627](../adr/D-627-core-drive-composition-seam.md), [D-628](../adr/D-628-core-drive-output-and-recovery-boundaries.md), [D-630](../adr/D-630-remaining-platform-semantic-holders.md), [D-637](../adr/D-637-remaining-decision-console-learning-folders.md)에 따른다. CORE 세부 책임은 [CORE·Drive 안내](core-drive-responsibilities.md), 소유권·import 규칙은 [platform_parts.yaml](../../tools/harness/platform_parts.yaml)이 기준이다. 과거 `d427_target`은 소유권 식별자이고 현재 경로는 `path`와 필요한 `layout_target`으로 읽는다.

`middleware`는 장치 실행과 권한, `operations`는 관측 사실과 작업 조정, `learning`은 경험·학습·평가·아티팩트 관리를 맡는다. `contracts`는 교환 형식, `integrations`는 외부 기술 접점, `shared/web`은 여러 UI가 실제로 공유하는 기반이다. 같은 concern이 같은 실행 권한을 뜻하지 않는다.

D-747 S2: 위치 보조·상태는 `middleware/perception/localization`, graph 건강은 `graph_health`, snapshot 판단은 `snapshots`, 차선 관측은 `sensors/line_observation`, advisory object 관측은 `front_camera/object_observation`에 전용 ROS adapter와 같이 둔다. `nodes`에는 잔여 보정·기록·provider/executor/TF/web 조립, `control`에는 설치/source 호환 초기화만 남는다. 기존 control.* 설치 이름은 유지한다.

## 편집 집

세션이 코드를 찾을 때 쓰는 열두 집이다. 소유와 import의 정본은 아래 manifest root와 [platform_parts.yaml](../../tools/harness/platform_parts.yaml)이다. 이 절은 그 root를 유지보수 단위로 묶는다. 집을 위해 폴더를 새로 만들거나 설치 이름 `control`, `core_features`, `fleet`를 바꾸지 않는다. 경로로 실행 PC를 추정하지 않는다(D-315). 아래 현재 경로는 2026-10-13 후속 착지 기준이며 과거 검증 스냅샷과 구분한다.

| 집 | 이름 | 현재 경로 |
|---|---|---|
| 1 | CORE 창구 | `middleware/core/gateway`, `middleware/core/api`, `middleware/core/events`. 로봇 화면 원본은 `middleware/robot_ui` |
| 2 | CORE 공통 | `middleware/core/services`. 명령·공통 Safety·전원. 장치 로컬 허용 동작은 `core_features.decision` |
| 3 | Drive 동작 | `middleware/drive/behaviors/<동작 하나>`. 설치 이름은 `core_features.*` |
| 4 | Drive 근거 | `middleware/drive/{motion_limits,tracking,planning,recovery,calibration}` |
| 5 | 인지 구현 | `middleware/perception/sensors/{sensing,line_observation}`, `middleware/perception/front_camera/{perception,object_observation}`, `middleware/perception/{localization,graph_health,snapshots}` |
| 6 | 인지 노드 | `middleware/perception/nodes`. ROS 패키지 이름은 `control`; `control/`의 다섯 호환 초기화는 설치 이름만 잇는다. 기능별 전용 adapter는 해당 판단 holder에 둔다 |
| 7 | 장치 | `middleware/devices`, `middleware/drivers` |
| 8 | Fleet 원장 | `operations/fleet/fleet/server/{ledger,auth,cell,console,peer}`와 기존 `server/channel`. app.py는 조립하고 기존 fleet.server.* 설치 이름을 유지한다 |
| 9 | Fleet 조정 | `operations/fleet/fleet/{traffic,routing,swarm,formation,stuck,incidents}`, 그리고 `server/tracking`(D-457 천장 무마커 추적, 표시·대조 전용)과 `server/pose`(D-395 위치 서비스, D-494 지도 자세, D-594 경로 기록). 두 holder는 기존 `fleet.server.*` 설치 이름을 유지하고, 원장 테이블이 아닌 자기 기록 테이블(추적 보정, 경로 기록)에만 쓴다 |
| 10 | 순수 판단 | `operations/world`, `operations/situation`, `operations/decision`, `operations/site_execution` |
| 11 | 현장 표면 | `applications/fleet/{web,gateway}`, `operations/processes`, `operations/site_devices`, `operations/site_ui/{cam,media}`, `operations/apps`, `operations/overhead`, `operations/signal_observation` |
| 12 | 학습 | `learning/{curation,training,evaluation,registry}` |

집 10은 Fleet, ROS, 장치 writer를 import하지 않는다. World MapPose는 받은 sighting·운영자 pin·odom의 현재 자세다. Fleet은 `rosy.world.state.projections.map_pose`를 직접 읽는다(D-752). `source=bridged`는 dead reckoning이고 미래 예측이나 완료 증거가 아니다. Fleet 원장 테이블(`fleet_tasks`, `fleet_task_history`, `fleet_robot_reservations`, `fleet_action_claims`)은 집 8의 `task_store`가 만들지만, 쓰는 모듈은 집 8 안팎에 열 개다. 그 목록은 `test/architecture/test_fleet_ledger_writers.py`가 고정하고, 새 writer는 리뷰를 거쳐 목록에 올려야 한다. stuck·incidents 등은 자기 테이블에만 쓴다. 최종 Base 명령 선택은 집 2의 `core_features.command`, `core_features.safety`와 `core.bridge`에 남는다. 집 12는 실행 권한이 없다.

같은 영어 단어는 집을 나눈다.

| 단어 | 의미 | 집 | 현재 경로 |
|---|---|---|---|
| control | 센서·카메라 노드 조립 | 6 | `middleware/perception`. ROS 패키지 `control` |
| control | Drive 알고리즘 | 3, 4 | `middleware/drive` |
| decision | 장치 로컬 허용 동작 | 2 | `core_features.decision` |
| decision | 현장 후보·모델 제안 | 10 | `operations/decision`. 설치는 Fleet 배포 |
| safety | 공통 E-stop·배터리·Fleet 상실 | 2 | `core_features.safety` |
| safety | 동작 후보의 속도·바닥 검사 | 4 | `middleware/drive/motion_limits` |
| execution | 로봇 로컬 policy·receipt | 별도 root | `middleware/robot_execution/local` |
| execution | 현장 목표·진척 | 10 | `operations/site_execution` |
| vision | 앞 카메라 구현 | 5 | `middleware/perception/front_camera` |
| vision | 천장 관측 서비스 Rosy Vision | 11 | `operations/overhead`. 패키지 `rosy_vision`, 명령 `rosy-vision`. 화면은 없다. 폴더 이름이 단어와 다른 것은 D-748 |
| vision | 신호등 관측 | 11 | `operations/signal_observation`. 천장 카메라 앱이 아니다 |
| console | Rosy Fleet 화면 | 11 | `applications/fleet/web`. 표시 이름은 Rosy Fleet이다(D-487). 레지스트리 id, 아이콘 `console.svg`, 경로 `/console`은 유지한다 |
| console | 로봇 한 대의 운용 칸 | 1 | Rosy Robot의 경로 `/console`. 폴더는 `middleware/robot_ui/robot`이고 포트는 CORE 8080 |
| console | Fleet 서버의 콘솔 조립 | 8 | `operations/fleet/fleet/server/console`. 화면 파일이 아니다 |
| fleet | 현장 서비스와 원장 | 8, 9 | `operations/fleet`. 패키지 `fleet`. 화면 표시 이름 Rosy Fleet과 같은 서비스다 |
| fleet | 사이트 게이트웨이 휠 | 11 옆 | `applications/fleet/gateway`. 휠 `rosy-app-gateway`, 명령 `rosy-site-gateway`. Rosy Fleet 화면이 아니고 `operations/fleet`도 아니다 |
| ui | 로봇 쪽 화면 집 | 1 | `middleware/robot_ui`. 권한은 자식 `robot`, `pilot`, `face`에 있다. 각각 Rosy Robot, Rosy Pilot, 얼굴 LCD |
| ui | 현장 캡처·미디어 | 11 | `operations/site_ui/{cam,media}`. Rosy Fleet 화면은 `applications/fleet/web` |

`middleware/skills`와 `middleware/robot_execution/local`은 집 7과 같은 장치 측 wheel이고 별도 manifest root다. `contracts`, `integrations`, `shared/web`, `deploy`, `tools`, `test`, `docs`는 아래 파트 설명 그대로다. 행동 조건부 미래 예측은 D-782 기반 위치(`operations/prediction`, `learning/{training,evaluation}/world_model`)에만 둔다.

## 폴더 이름과 묶음

[D-738](../adr/D-738-folder-one-authority.md)이 트리 전체의 규칙이다. `control` 한 곳의 개명이 아니다. 위의 편집 집 표가 현재 경로다. S1은 D-743, S2는 D-747, S6은 D-748, S7은 D-749, S8은 D-750, S9는 D-751, S10은 D-752다. S3부터 S10의 소스 착지는 [남은 폴더 정리](../validation/folder-remaining-2026-10-13/result.md)다. 그 기록의 원격 pytest·CI·배포·장치는 NOT RUN이다. 편집 집 표나 manifest와 다르면 편집 집 표와 manifest가 현재 경로다.

규칙은 여섯 가지다. 디렉터리의 마지막 이름은 권한 하나다. import와 ROS 패키지 이름은 유지한다. 같은 입력과 같은 출력은 한 기능 폴더에 둔다. 사실, 명령, 원장, 임대, 후보 검사는 나눈다. 경로는 실행 PC가 아니다. 한 커밋에 한 단계만 착지한다.

| 단계 | 목표 | 소스 착지 |
|---|---|---|
| 1 | `middleware/drive` | D-743. 설치 이름은 유지한다. 원격 검사·배포·장치는 그 검증 기록 |
| 2 | 인지의 순수 판단을 기능 폴더로 | D-747. 편집 집 5가 현재 경로다 |
| 3 | 남는 조립은 `middleware/perception/nodes`. `perception/control`은 다섯 설치 호환 초기화 | 검증 기록 S3. 원격·장치는 NOT RUN |
| 4 | `middleware/robot_execution`, `operations/site_execution` | 검증 기록 S4. 설치 이름은 `rosy.execution.local`, `rosy.execution` |
| 5 | `middleware/robot_ui`, `operations/site_ui` | 검증 기록 S5. 설치 이름은 `dashboard`, `emotion`, `fleet.server.web`, Rosy Cam |
| 6 | `operations/overhead`, `operations/signal_observation`, `middleware/perception/front_camera` | D-748. 검증 기록 S6. 패키지 `rosy_vision` |
| 7 | `action_rules`, `safety_gate`, `preview`, `motion_limits`. 옛 import 패키지는 facade | D-749. 검증 기록 S7. 폴더 이름 `lane_rules`는 쓰지 않는다 |
| 8 | Fleet `server`를 원장, 채널, 셀 어댑터, 콘솔 조립, 피어로 | D-750. 검증 기록 S8. SQLite는 하나. 사이트 문맥·로그 미러(D-796)는 원장 밖 파생 저장소다 |
| 9 | 호스트 도구를 `tools/sim`, `tools/calibration`, `tools/validation`로 | D-751. 검증 기록 S9. `middleware/perception/tools/device`의 hotpath·IR 측정은 그 자리에 남긴다 |
| 10 | MapPose 호출자를 World로 옮긴 뒤 별칭을 거둠 | D-752. 검증 기록 S10. 소비자는 `rosy.world.state.projections.map_pose`를 직접 import |

권한이 다른 폴더는 이름이 같아도 합치지 않는다. 보정 세션 임대, 공통 Safety, 장치 로컬 허용 동작, 상황 사실, 로봇 로컬 실행, 천장 관측, CORE 조립은 각 단계를 지나도 자기 폴더에 남는다. 다섯 설치 이름 폴더 `control`, `planning`, `safety`, `sensing`, `wander`도 남는다.

## 현재 의미 구조와 깊이

**후속 구조 제안:** 현재 배치는 아래 표 그대로이며, 공통 상황평가·작업 규칙·Fleet 어댑터의 추가 책임 분리는 [D-648](../adr/D-648-shared-judgment-target-structure.md)의 [목표 설계](../plans/2026-10-11-shared-judgment-structure-design.md)와 [단계별 계획](../plans/2026-10-11-shared-judgment-structure.md)을 검토한다. Proposed 목표를 이미 이동·설치된 현재 상태로 집계하지 않는다.

의미 폴더 깊이는 저장소 아래 책임 분류를 최대 5단계로 세는 기준이다. `middleware/drive/planning/nav2`는 4단계이다. `src/rosy/world`, `core_features`, `rosy_situation` 같은 언어 namespace와 ament의 `test/resource/config`는 패키지 내부 배치다. 이를 책임 분류 단계로 합산하여 기존 import를 억지로 바꾸지 않는다. 아래는 현재 존재하는 폴더만 보여 주며, 패키지 내부 경로는 괄호로 표시한다.

```text
rosy-platform/
├─ middleware/
│  ├─ core/
│  │  ├─ gateway/ (core/services.py, core/drive, core/system, core/bridge)
│  │  ├─ services/ (core_features: command, safety_gate, action_rules, preview)
│  │  ├─ api/ (core_api_web)
│  │  └─ events/ (core_events)
│  ├─ drive/
│  │  ├─ behaviors/
│  │  ├─ planning/{nav2,grid}
│  │  ├─ tracking/wander
│  │  ├─ recovery/
│  │  ├─ calibration/
│  │  └─ motion_limits/
│  ├─ perception/
│  │  ├─ sensors/{sensing,line_observation}
│  │  ├─ front_camera/{perception,object_observation}
│  │  ├─ {localization,graph_health,snapshots}
│  │  ├─ nodes/ (ROS 패키지 control의 남는 조립)
│  │  └─ control/ (설치 이름 다섯 개의 호환 초기화)
│  ├─ devices/{pinky,omx}/
│  ├─ drivers/{imu_bno055,pinky_adc,pinky_lamp,pinky_led}
│  ├─ skills/{api,manipulation}
│  ├─ robot_execution/local
│  └─ robot_ui/{robot,pilot,face}
├─ operations/
│  ├─ fleet/ (원장·서빙·패키지 fleet)
│  │  └─ fleet/server/{ledger,auth,cell,console,peer,channel,tracking,pose}
│  ├─ decision/
│  ├─ world/ (state/projections/map_pose)
│  ├─ situation/
│  ├─ site_execution/ (rosy.execution)
│  ├─ processes/{cell,palletizing}
│  ├─ overhead/ (rosy_vision)
│  ├─ signal_observation/
│  ├─ site_devices/{dock,signal}/firmware
│  ├─ apps/{fleet,games} (fleet는 rosy-app-gateway, games는 경기 보드)
│  └─ site_ui/{console,cam}
├─ learning/
│  ├─ curation/{pinky,omx,perception}
│  ├─ training/{pinky,omx,perception}
│  ├─ registry/{policy,perception}
│  ├─ evaluation/perception
│  └─ envs/isaac
├─ contracts/{foundation,ros_idl,motion,skill,learning}
├─ integrations/{robots/omx,simulation/gazebo}
├─ shared/web
└─ profiles/ deploy/ tools/ test/ docs/ data/ reference/ .github/ .claude/
```

CORE의 `core/drive`는 같은 CORE 프로세스 안의 조립 코드다. `line_follow.py`는 기존 manager 생성과 live angular provider, envelope와 recovery 연결을 맡고, `docking.py`는 docking/swarm 조립, `traffic.py`는 traffic policy와 명시적으로 바인딩된 signal observer 조립을 맡는다. 공통 power/battery parser와 조립은 `core/system/power.py`에 있다. US005는 `core/services.py`의 공통 객체 조립과 기존 service listener 상대 순서를 유지하고 parser를 명시적으로 재export한다. D-628의 CommandManager invalidation callback prefix 추가는 별도 주행 경계 보강이다.

CORE의 공통 Safety와 최종 Base 명령 선택은 `core_features.safety`, `core_features.command`, `core.bridge`에 남는다. Drive의 body/sweep/floor/envelope 검사는 해당 운동 후보의 실행 근거이며 공통 Safety를 대체하지 않는다. Arm의 joint/action writer와 stop/rearm/HOLD는 OMX owner에 남는다. Base `cmd_vel`과 Arm 출력을 하나의 writer로 합치지 않는다.

## manifest root 판정 기록

아래는 각 소유 경계를 판정한 기록이다. 현재 root 목록과 권한은 `tools/harness/platform_parts.yaml`이 정본이다. 하위 root는 상위 root의 일부를 따로 소유하므로 행 개수를 패키지 개수로 읽지 않는다. `유지`는 실제 책임이 현재 위치에 맞는다는 뜻이다. `이전 완료`·`분리 완료`는 소스 holder 변경을 뜻한다. `후속 분리 보류`는 기존 패키지·transaction 소비자를 유지한다는 결정이며 새로운 빈 폴더를 뜻하지 않는다. ROS 배포명과 Python import명이 다른 경우 둘 다 적었다.

| 현재 manifest root | 실제 패키지·import 또는 형식 | 판정과 현재 책임·소비자 |
|---|---|---|
| `learning/training/pinky` | Python 연구 CLI, import prefix 없음 | 유지 — 기록 velocity 비교·평가. `curation/pinky`와 policy ledger를 소비하며 runtime 권한 없음 |
| `learning/curation/pinky` | Python 기록·Episode CLI | 유지 — Pinky 기록 provenance와 Episode 변환. 학습·검증·registry 소비자와 함께 유지 |
| `learning/registry/policy` | policy 아티팩트·metadata ledger | 유지 — curation/training의 고정 revision·검증 기록. 실행 admission 소유자가 아님 |
| `learning/training/omx` | ACT 연구 CLI (`act_inference.ACTInference`) | 유지 — offline policy inference/replay 연구. 미래 World 상태 예측기나 Arm writer가 아님 |
| `contracts/learning` | wheel `rosy-contracts-learning`; `rosy.contracts.learning` | 유지 — Episode·artifact 형식, curation/registry 소비. 학습 실행·배포 정책 없음 |
| `contracts/foundation` | ROS `core_common`; `core_common` | 유지 — CORE/Fleet 공통 protocol·profile·identity·body 형식. 구현 정책은 각 owner에 남음 |
| `contracts/ros_idl` | ROS `interfaces` | 유지 — ROS 메시지·서비스 IDL. driver/bridge/bringup 소비 |
| `contracts/skill` | wheel `rosy-contracts-skill`; `rosy.contracts.skill` | 유지 — SkillInvocation·AttemptIdentity·ReceiptBinding. skills/local execution의 동일 객체 reexport |
| `contracts/motion` | wheel `rosy-contracts-motion`; `rosy.contracts.motion` | 유지 — Motion Intent·DeviceControlPort 형식. Pinky writer binding 소비; 전 producer admission 완료로 해석하지 않음 |
| `middleware/core/gateway` | ROS `core`; `core` | 분리 완료 — CORE 조립·ROS bridge. 내부 `drive`와 `system/power`로 기존 조립 추출; 외부 attribute·기존 service listener 상대 순서 유지 |
| `middleware/core/services` | ROS `core_features`; `core_features` | 유지 — 기존 feature manager·알고리즘. Drive 기능은 line_follow/navigation/localization/docking/swarm의 실제 owner에 남음 |
| `middleware/core/services/core_features/safety_gate` | `core_features.safety` | 유지 — CORE 공통 E-stop·person·battery·fleet-loss 보호. Drive 전용 sweep proof와 구분 |
| `middleware/core/services/core_features/action_rules` | `core_features.decision` | 유지 — 장치 local lane/router/allowed-action 규칙. Fleet의 deliberative decision과 구분 |
| `middleware/core/events` | ROS `core_events`; `core_events` | 유지 — CORE/Fleet의 event bus·audit 형식과 연결 |
| `middleware/core/api` | ROS `core_api_web`; `core_api_web` | 이전 완료 — 기존 api_web 배포/import명 유지, API·WebSocket·UI 제공 소스 holder만 간소화 |
| `middleware/drive/planning/nav2` | ROS `navigation`; `navigation` | 이전 완료 — Nav2 launch/config/backend. CORE goal facade·취소 세대·최종 command 경계 유지 |
| `middleware/perception` | ROS `control`; `control`, `control.sensing`, `control.sensing.perception` | 분리 완료 — sensors/vision 소스와 node 조립·recorder·map resource. Drive 구현은 별도 holder; 하나의 기존 배포 패키지로 설치 |
| `middleware/drive` | 기존 ROS `control` 배포의 `control.control`, `control.planning`, `control.wander` | 분리 완료 — tracking/recovery/calibration과 grid planning. node/provider 소비자와 기존 relative import·monkeypatch identity 유지 |
| `middleware/drive/motion_limits` | 기존 ROS `control` 배포의 `control.control.*`, `control.safety` | 분리 완료 — actuation·speed·command gate·floor/body/sweep 정책, sensor-only adapter. 별도 final writer 없음 |
| `middleware/drivers/imu_bno055` | ROS `imu_bno055` | 유지 — IMU I/O. 장치 bringup이 소비; 지각 판단이나 작업 dispatch를 소유하지 않음 |
| `middleware/drivers/pinky_adc` | ROS `sensor_adc` | 유지 — Pinky ADC I/O. IR 등 센서 소비자 연결 |
| `middleware/drivers/pinky_lamp` | ROS `lamp_control` | 유지 — Pinky lamp I/O. 장치 UI/bringup 소비 |
| `middleware/drivers/pinky_led` | ROS `led`; `led` | 유지 — Pinky LED I/O. 장치 조립·표시 소비 |
| `middleware/devices/pinky/bringup` | ROS `bringup`; `bringup`, `rosylib` | 이전 완료 — Pinky 장치 기동·writer binding. 기존 entrypoint/share 유지 |
| `middleware/devices/pinky/profile` | ROS `pinky_pro`; YAML | 이전 완료 — Pinky 장치 capability/profile. 배포 설치 pin인 최상위 `profiles`와 구분 |
| `middleware/devices/omx/adapter` | ROS `omx_adapter`; `omx_adapter` | 이전 완료 — OMX joint/action owner·body validation·HOLD. demonstration은 device capture, offline export는 `learning/curation/omx`, 검증 형태는 `contracts/learning`이 소유 |
| `middleware/devices/omx/profile` | ROS `omx`; YAML | 이전 완료 — OMX composition config. adapter가 검증·소비하며 설치 pin을 소유하지 않음 |
| `middleware/devices/pinky/description` | ROS `description`; URDF | 이전 완료 — 실물/Gazebo 공용 Pinky 기구 모델. bringup·시뮬레이션·라벨 geometry의 현재 패키지 소비자 유지 |
| `middleware/devices/omx/agent` | wheel `rosy-app-agent`; `rosy_agent` | 이전 완료 — cell local Action 조립. site gateway/process와 통신하고 Arm owner 경계 유지 |
| `middleware/skills/api` | wheel `rosy-skill-api`; `rosy.skills.api` | 유지 — skill API root. contracts identity를 재사용하고 robot I/O나 site scheduling을 소유하지 않음 |
| `middleware/skills/manipulation` | wheel `rosy-skill-manipulation`; `rosy.skills.manipulation` | 유지 — manipulation skill 정의/수행 접점. Arm 장치 제어와 site process 구분 |
| `operations/site_execution` | wheel `rosy-execution`; 배포 metadata | 유지 — 아래 API/site 하위 root의 배포 단위. local 실행 wheel은 별도 middleware 소유 |
| `middleware/robot_execution/local` | wheel `rosy-execution-local`; `rosy.execution.local` | 유지 — local policy loader·receipt binding. `rosy-execution`과 중복 설치하지 않음 |
| `operations/site_execution/src/rosy/execution/api` | `rosy.execution.api` | 유지 — PlanBundle 내부 API. site producer와 현재 wheel 결합을 보존; 일반 contracts 이전은 후속 분리 보류 |
| `operations/site_execution/src/rosy/execution/site` | `rosy.execution.site` | 분리 완료 — 기존 site 실행·권한 projection과 D-657 순수 `goal_evidence`, `workflow` 전체 progress 계산 및 시각/step 상태 helper. producer 인증·원장 전이·local loader·장치 writer는 소유하지 않음 |
| `middleware/robot_ui/robot` | ROS `dashboard`; web assets | 유지 — CORE가 제공하는 robot dashboard. 명령 admission은 CORE API에 남음 |
| `middleware/robot_ui/pilot` | ROS `pilot`; web assets | 유지 — CORE 제공 Pilot UI. 장치 API의 현재 소비자 |
| `middleware/robot_ui/pilot/android` | Android native discovery shell | 유지 — `pilot-device-lobby`만 소유한다. 수동 운전과 비상 정지의 소유자는 Rosy Pilot PWA다 (D-639) |
| `middleware/robot_ui/face` | ROS `emotion`; `emotion` | 유지 — robot face/display. 제어 정책과 구분 |
| `operations/site_devices/dock` | dock contract·firmware 소스 | 유지 — 현장 dock 소유. robot docking manager의 직접 `/status` polling은 그대로 |
| `operations/site_devices/dock/firmware` | dock MCU firmware | 유지 — limit-switch interlock·0 V boot. CORE/Arm Safety와 별도 현장 보호 대상 |
| `operations/site_devices/signal` | signal contract·driver library | 유지 — Fleet 소비 signal 장치. Fleet가 sequence·command owner를 유지 |
| `operations/site_devices/signal/firmware` | signal MCU firmware | 유지 — boot·supervision-loss failsafe. 관측용 signal observer와 구분 |
| `operations/signal_observation` | measured-light 관측 서비스·소스 | 유지 — read-only light evidence. CORE traffic observer 소비; 실행 host 결정이나 signal command 권한 추가 없음 |
| `operations/fleet` | ROS `fleet`; `fleet` | 분리 완료 — pure MapPose는 World, 순수 목표/진척 규칙은 execution 소비. D-657 `server/model_feedback_dispatch` 원장 어댑터와 admission·claim·dispatch·producer 인증·MapPoseService 조립·trip consumer는 Fleet 소유 |
| `operations/fleet/fleet/incidents` | `fleet.incidents.handoff`, `fleet.incidents.notifications` | 분리 완료 — D-661 이름 있는 담당자의 사건 인수와 기존 Fleet DB의 알림 outbox·고정 채널 worker·receipt. 판단·resolver는 `fleet/stuck`, 인증·라우트·worker 생명주기는 `fleet/server`에 유지. 실제 운영 수용은 HOLD |
| `operations/decision` | `rosy.decision`; 기존 `fleet` 배포 | 이전 완료 — ER2/VLM·candidate·provider-neutral tool 계약/제안. store 결속 dispatcher는 D-657에서 Fleet로 이전; 기존 transaction/배포 유지, 옛 module shim 없음 |
| `applications/fleet/web` | source assets; 설치 `fleet.server.web` | 이전 완료 — canonical Console 자산, 동일 allowlist/CSP/URL. wheel·sdist는 checkout 없이 self-contained; server는 Fleet 소유 |
| `applications/monitoring` | 독립 상태 앱의 소유·표면 기준, backend 브라우저 계약 | D-876 등록 — 서비스의 scoped read API를 소비한다. 현재 화면 구현/G1·G2·G3는 HOLD이며 API 브라우저 시험을 화면 완성으로 계산하지 않는다 |
| `applications/fleet/gateway` | wheel `rosy-app-gateway`; `rosy_gateway` | 유지 — site gateway 앱 조립. Fleet ROS 패키지·device agent와 구분 |
| `operations/world` | wheel `rosy-world`; `rosy.world` | 이전 완료 — `ObservationSnapshot`과 `state/projections/map_pose.py`. Fleet은 그 모듈을 직접 import한다(D-752). MapPoseService·trip·swarm·lane·history의 서비스와 원장은 Fleet |
| `operations/monitoring` | wheel `rosy-monitoring`; `rosy.monitoring`, CLI `rosy-monitoring` | D-876 독립 수집·집계·durable 관측·scoped read API/POSIX 실행기. CORE/Fleet/host 기존 출력을 읽으며 명령·원장·복구 소유권을 갖지 않는다 |
| `operations/processes/palletizing` | wheel `rosy-palletizing`; `rosy.processes.palletizing` | 유지 — palletizing process 정의/조정. Arm owner·skill·site execution 소비 경계 유지 |
| `operations/processes/cell` | ROS `rosy_cell`; `rosy_cell` | 유지 — cell process·site 조립. agent/gateway contract 소비; 직접 joint writer가 아님 |
| `operations/situation` | `rosy_situation` | 분리 완료 — 기존 사실과 제한된 advisory 제안은 별도 출력. D-652 `assessment`는 개입 필요성, `snapshot_assessment`는 관측 변환을 소유하며 Fleet/Situation이 내부 shadow로 소비. 기존 import/patch identity 유지 |
| `operations/overhead`, `operations/signal_observation` | ROS `rosy_vision`; `rosy_vision` | 유지 — overhead vision worker·sighting evidence. Fleet pose consumer로 전달, cmd_vel 권한 없음 |
| `operations/site_ui/cam` | Android Cam 앱 | 유지 — camera/operator surface. vision·robot UI와 현재 책임 구분 |
| `operations/apps/games` | ROS `games`; `games` | 유지 — overhead camera를 쓰는 game host. 범용 process/control backend가 아님 |
| `learning/training/perception` | trainer Python CLI·library | 분리 완료 — 학습 job·trainer·COLAB docs. 인식 runtime은 middleware vision 소유 |
| `learning/curation/perception` | dataset/review Python CLI·app | 분리 완료 — 기록·정답·dataset provenance·review source. 서명 closure와 source mismatch 거절 유지 |
| `learning/registry/perception` | artifact/store/delivery Python CLI | 분리 완료 — datasets/evalsets/inbox/model 공용 artifact·provenance store, 고정 revision·승격·서명 배포. 실행 writer 아님 |
| `learning/evaluation/perception` | road replay Python CLI | 분리 완료 — 기존 replay 평가. 미래 World rollout 평가 구현으로 집계하지 않음 |
| `tools/perception` | rosy_ml·operator SSH CLI | 분리 완료 — 네 learning owner의 운영 조합, 자체 runtime 제어·승격 우회 없음 |
| `tools/perception_prototype` | calibration·real-run prototype CLI | 유지 — 학습 loop 밖의 개발 prototype. product inference나 학습 승격 경로로 사용하지 않음 |
| `learning/envs/isaac` | ROS `isaac_sim`; sim assets·scripts | 유지 — 연구 environment·Isaac 자산. Isaac Lab 학습/field acceptance를 이 폴더 존재로 주장하지 않음 |
| `learning/curation/omx` | offline demonstration/Episode CLI | 유지 — OMX LeRobot export. contract 기반 변환; middleware owner import·activation 없음 |
| `data` | data drop 안내·기록 영역 | 유지 — recordings/data 배치 계약. gitignored 대용량 출력은 제품 소스나 배포 evidence를 대신하지 않음 |
| `integrations/robots/omx` | wheel `rosy-integration-robot-omx`; `rosy.integrations.robots.omx` | 유지 — 외부 OMX 접점 adapter. middleware local API/contract 소비; owner 정책은 장치에 유지 |
| `integrations/simulation/gazebo` | ROS `gz_sim`; worlds/models/plugins/params | 유지 — Gazebo integration의 배포·resource owner. 아래 launch/scripts도 이 실제 패키지의 설치 소비자를 유지 |
| `integrations/simulation/gazebo/launch` | `gz_sim` launch assets | 유지 — sim device owner를 동일 middleware pipeline으로 기동. control concern이지만 별도 middleware ROS package로 carve하지 않음 |
| `integrations/simulation/gazebo/scripts` | `gz_sim` bench·converter scripts | 유지 — sim acceptance·world/map 변환·Fleet swarm bench. integration 패키지 설치/launch 소비자를 유지하며 runtime 제어 library로 승격하지 않음 |
| `shared/web` | ROS `web_common`; shared UI assets | 유지 — robot/operator UI 공용 기반. domain 정책·범용 core 저장소가 아님 |
| `profiles` | installation/profile YAML | 유지 — site/device 조합·pin. 장치 capability profile과 구분 |
| `deploy` | images·units·payload·operator 배포 코드 | 유지 — source holder/manifest를 소비하는 배포 조립. live 적용은 별도 readback 필요 |
| `tools` | 최상위 loose 개발 CLI | 유지 — 하위 도구는 각 manifest root로 구분. product algorithm 공통함으로 사용하지 않음 |
| `tools/packaging` | build-time source composition | 분리 완료 — D-652 Fleet 소스 구성·wheel/sdist 빌드. sdist는 자체 `_build` helper를 포함하며 설치 runtime에는 helper 없음 |
| `tools/validation` | host Fleet/Gazebo conformance CLI | 유지 — preflight·run planning, 장치에 설치하지 않음 |
| `tools/calibration` | offline per-robot fit/store CLI | 유지 — 측정 calibration 처리. runtime sensor/drive calibration 알고리즘과 구분 |
| `tools/capture` | operator capture CLI | 유지 — CORE API를 통한 supervised capture. 자체 cmd_vel writer나 autonomous admission 없음 |
| `tools/device_test` | operator device test CLI | 유지 — preflight·temporary overlay·readback/restore·recording. 실행·장치 수용 증거를 단계별 보존 |
| `tools/device_twin` | development twin test CLI | 유지 — 검증 도구, 제품/장치 payload 아님 |
| `tools/harness` | manifest·구조·Safety·ADR·영향 시험 도구 | 유지 — root ownership·검증 규칙의 소비자. 실행 authority를 생성하지 않음 |
| `tools/hooks` | git hook 검사 | 유지 — 작업/커밋 gate, 제품 runtime 아님 |
| `tools/icons` | icon 생성/관리 도구 | 유지 — UI 제작 지원, 제품 정책 아님 |
| `tools/remote` | remote pytest runner | 유지 — 시험 PC resource 선정·committed SHA 실행. 노트북 local pytest 우회 경로가 아님 |
| `tools/release` | release 제작/검사 도구 | 유지 — 배포 payload consumer. 아티팩트 제작과 장치 readback을 구분 |
| `tools/sim` | sim bench/scenario CLI | 유지 — 연구·검증 runner. world prediction 서비스나 robot writer가 아님 |
| `tools/ssh` | operator SSH enrollment CLI | 유지 — operator PC의 접근 설정. runtime policy나 credential 저장소가 아님 |
| `.github` | CI workflows | 유지 — source/wheel/test/image 소비자. CI와 장치 실행 증거 구분 |
| `.claude` | 프로젝트 agent skill·settings | 유지 — 개발 작업 규칙. product code/학습 모델이 아님 |
| `test` | repository architecture/integration tests | 유지 — manifest·installed package·boundary 검증. 통과가 device/field acceptance를 뜻하지 않음 |
| `docs` | ADR·SRS·계획·참조·evidence 안내 | 유지 — 계약과 검증 상태 기록. 계획을 구현으로 집계하지 않음 |
| `reference` | 참조 자료 | 유지 — provenance/reference 입력. live build/runtime의 새 owner로 사용하지 않음 |

## source holder와 기존 package identity

`control` ROS 배포는 유지된다. `control.sensing`의 실제 구현은 `middleware/perception/sensors/sensing`, `control.sensing.perception`은 `middleware/perception/front_camera/perception`에 있다. `control.control`의 평탄한 module identity는 Drive의 `safety/recovery/tracking/calibration` holder에서 설치하고 `control.planning`, `control.wander`, `control.safety`도 기존 이름으로 설치한다. `control` 아래 compatibility 진입점은 source 조회의 좁은 path 연결과 기존 export를 맡는다. 설치된 배포가 checkout의 sibling 경로를 필요로 하는 구조로 해석하지 않는다. build는 정적 source mapping을 사용하고 sdist는 실제 source snapshot을 포함한다.

MapPose 구현은 `operations/world`의 `rosy.world.state.projections.map_pose` 하나다. Fleet 소비자는 그 모듈을 직접 import하고, D-630의 Fleet identity alias는 D-752에서 제거했다. HTTP route·roster·admission·claim·dispatch는 Fleet에 남는다. Situation의 기존 `deadlock`, `incident_context`, `vlm`은 이동한 module identity를 유지하는 명시적 alias이며 analyzers package는 기존 기호를 명시적으로 export한다. 호환 코드에 알고리즘을 복제하지 않는다.

Gazebo의 launch와 script는 manifest에서 각각 별도 concern을 갖지만 실제 ROS 배포명은 `gz_sim`이다. launch가 장치 pipeline을 시작한다는 이유만으로 resource/install owner를 다른 패키지로 분리하지 않았다. robot description·map/STL lineage·기존 share resource를 그 패키지 소비자와 함께 유지한다.

## 현재 상태와 미래 행동 예측

D-652 공통 필요성 평가는 Situation의 순수 모듈에 있고 Fleet는 현장 상태 수집·사건 연결·기존 resolver를 소유한다. Fleet wheel과 현장 source image에는 `__init__.py`, `assessment.py`, `snapshot_assessment.py`만 포함한다. 빌드 조합은 `tools/packaging/fleet_sources.py`가 소유하고 source archive의 `_build` 사본으로 checkout 밖 재빌드를 지원한다. 이 내부 shadow 구현은 D-648 전체 목표 구조의 수용과 구분한다.

D-657은 D-648 단계 2와 단계 3의 첫 계산 단위만 수용한다. 실제 원장 모델 도구 구현은 `fleet.server.model_feedback_dispatch`, 순수 목표 검증은 `rosy.execution.site.goal_evidence`, 기존 시각·신선도·step 상태 투영은 `rosy.execution.site.workflow`가 소유한다. D-656 후속 통합은 Fleet가 제공하는 일관된 snapshot의 읽기 진행 계산 전체를 같은 workflow의 `project_progress`에 둔다. DB 전이·auth·claim·admission·transport는 Fleet에 남긴다. Fleet는 기존 execution wheel dependency를 사용하고 execution 파일을 중복 포장하지 않는다. site source image도 해당 source closure를 포함한다. 다른 Mission 전이·복구 규칙 및 D-648 단계 4는 후속으로 유지한다. 소스/설치 검증과 실제 이미지 빌드·배포·현장 정확도는 별도다.

사용자의 후속 처리 요청으로 `project_progress` 전체 계산도 같은 workflow에 분리했다. Fleet adapter가 하나의 transaction에서 읽은 snapshot과 clock을 제공하고 execution은 기존 wire 결과를 투영한다. 단독 helper import는 stdlib만 필요하며 projection 호출 시 기존 foundation schema를 불러온다. 이는 DB 상태 전이·복구나 D-660~D-662 운영 판단 기능의 승인/착지를 대신하지 않는다.

후속 main `7afb0e2c4`의 소스에서는 D-661 인수·알림이 `fleet/incidents/{handoff,notifications}.py`에 있다. 다음 구조 작업도 이 직접 import 경로와 책임을 유지한다. Situation의 `rosy_situation/incidents`는 상황 근거를 구성하는 모듈이며 Fleet의 담당 인수·전송 원장과 구분한다. [하위 패키지 이동 계획](../plans/2026-10-11-fleet-team-incidents-subpackage.md)과 [책임 분리 계획](../plans/2026-10-11-responsibility-authority-orchestration.md)을 따른다. D-660~D-662 소스 반영과 최종 검증 receipt·실제 운영 수용은 별개이며, 실제 채널 수신·현장 정답 검수 및 단계 6 모델 토론은 HOLD다.

현재 World 구현은 `ObservationSnapshot`과 관측·운영자 pin·odom을 합성하는 `MapPoseTracker`다. Fleet의 `MapPoseService`, trip admission/progress/ports, swarm anchor, lane compliance, path history가 `rosy.world.state.projections.map_pose`를 직접 소비한다. `source=bridged`는 마지막 관측에서 odom으로 잇는 dead reckoning이며, 행동 후보를 넣고 미래 상태·불확실성을 내는 action-conditioned rollout이 아니다. `road_region`은 카메라 구역 입력의 시각·프레임·보정·근거 검사이고 주행이 아니다(D-665). 관측 타입의 정본은 `core_common.observation`이다(D-667). Situation은 현재 stuck/traffic/incident 사실과 일부 analyzer의 제한된 WAIT/BACK_AND_RETRY 제안을 별도로 출력한다. 기존 제안 출력을 모두 사실 또는 새 공통 assessment로 집계하지 않는다.

행동 조건부 미래 예측은 D-625의 **계획 책임**이다. 구현하려면 현재 state revision, action candidate, horizon, model revision, 만료/불확실성 결과, 실제 decision 소비자, 독립 평가가 먼저 있어야 한다. D-782(Proposed)가 그 항목을 OMX 팔 기준으로 정했고, 사용자 요청(2026-10-17)으로 기반을 만들었다. `contracts/learning`의 `prediction.py`(요청·결과·M1 artifact·단일 forward), `learning/curation/omx/world_model_dataset.py`(W1), `learning/training/world_model`(M1), `learning/evaluation/world_model`(두 기준선 수용), `operations/prediction/world_model`(검사기·그림자 기록)이다. 예측은 REJECT·HOLD 근거로만 쓰며 Fleet admission·owner에 결선하지 않았다(W4는 사용자 승인·D-430 Safety 리뷰·D-773 A4 뒤). `learning/training/omx/act_inference.py`의 ACT policy action 출력은 그 World model의 구현으로 집계하지 않는다. 기존 state projection, 학습/연구, 미래 예측 계획을 각각 기록한다.

이 안내의 이전/분리 완료는 local main에 반영한 소스 수준 판정이다. 90개 root를 판정했고 실제 빈 제품 폴더는 없었다. `data/drive/.gitkeep`는 계약용 placeholder로 유지했다. 공유 main의 이전 `middleware/core/api_web`, `middleware/apps/device` 경로에는 추적 제품 파일이 없지만 ignored cache·`.omc` 상태가 남을 수 있다. 추적 파일이 없는 `middleware/ui`, `middleware/execution`, `operations/execution`, `operations/vision`, `middleware/perception/vision`도 소유자가 아니다. 현재 경로는 `robot_ui`, `robot_execution`, `site_execution`, `overhead`, `front_camera`다. 동료 도구 상태를 삭제하거나 옮겨 제품 이동으로 집계하지 않는다. Decision/Console source 분리는 완료했고 기존 Fleet 배포·transaction·serving을 유지한다. 별도 배포 패키지 생성과 행동 조건부 World model은 이번 범위가 아니다. 해당 committed SHA의 remote 시험, checkout 밖 설치 확인과 남은 CI·ROS·ARM64·배포·장치·현장 gate는 [검증 기록](../validation/d637-remaining-folders-2026-10-11/result.md)에서 확인한다.

D-637에서 기존 298파일과 동시 개발로 추가된 Console `inbox.js` 1파일, 총 299파일을 처리했다. Console은 67개 source 파일 중 65개 설치 자산이며 AGENTS와 package.json은 개발 안내/도구 입력이다. `test/learning/perception`은 기존 99파일의 shared workflow 시험 위치다. 퇴역 WSL 도구 6개는 `docs/reference/legacy-tools/wsl`로 동결했고 현재 운영 경로에 재연결하지 않는다.

## D-649 책임 이동 보완

후속 책임·권한·결과 확인 계약은 Accepted [D-656](../adr/D-656-responsibility-authority-and-orchestration-boundaries.md)과 [실행 계획](../plans/2026-10-11-responsibility-authority-orchestration.md)을 따른다. 수용 범위는 논리 경계와 이행 순서이며 위 표의 현재 소스 배치와 D-652 내부 shadow 외의 구현/운영 수용을 뜻하지 않는다.

`middleware/drive/behaviors/{line_follow,docking,navigation,localization,swarm,road_behaviour,traffic_policy}`가 Base 행동 구현의 정본이다. CORE 서비스 배포가 기존 `core_features.*` 이름으로 설치하며 구현 복사본은 없다. `middleware/drive/runtime/`는 기존 control/goal/wander/safety ROS 진입 모듈을 소유하고 `control.*` 이름으로 설치한다. 위의 이전 배치 설명은 이 이동으로 보완된다. CORE 공통 Command/Safety와 `core/drive` 조립은 유지한다.

반복 이름은 세 종류다: 설치 패키지 이름(`core`, `control`, `fleet`, `rosy` namespace), 서로 다른 권한(장치-local execution/현장 execution, 관측 safety adapter/CORE Safety), 실제 혼재했던 행동 구현(이번 Drive 이동). 호환 initializer에는 알고리즘을 추가하지 않는다. 일반 캘리브레이션 lease와 카메라 장애 복구 자격 판정은 CORE 공통 admission이며 Drive 탈출 운동 구현과 다르다. Perception localization 노드는 상태/관측 근거를 소유한다.

현재 물리 이동과 설치 매핑, 원격 시험, 배포/장치 수용은 별도 기록이다. [D-649](../adr/D-649-drive-behavior-source-ownership.md), [실행 계획](../plans/2026-10-11-role-folder-boundaries.md)을 따른다.

D-671의 현재 Discord source는 `integrations/messaging/discord/rosy_discord/intake.py`의 순수 envelope/signature adapter다. 기존 Fleet 배포물에 설치하며 source image는 같은 코드를 포함한다. 기명 계정 연결·인증·접수 원장은 `operations/fleet/fleet/server/channel/requests.py`, 조회 표면은 기존 Console 작업 화면이 소유한다. 별도 실행 서비스·wheel·Mission DB는 없다. Gateway 실행기와 실제 수신, 후보·승인·위험 조치/reply는 미구현이며 D-669 후속이다.
