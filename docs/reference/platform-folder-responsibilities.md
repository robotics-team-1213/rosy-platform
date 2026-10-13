# ROSY Platform 현재 폴더 책임

2026-10-11 local main `d4988bffba`에 반영한 소스 배치. 실제 폴더 이동과 경로 수정의 커밋·머지 이후 이 안내를 정리했다. [이동·검증·착지 기록](../validation/d637-remaining-folders-2026-10-11/result.md)에서 소스·설치·시험·배포·장치·현장 증거를 구분한다.

구조 결정은 Accepted [D-625](../adr/D-625-semantic-structure-and-staged-migration.md), [D-626](../adr/D-626-d625-holder-migration-execution.md), [D-627](../adr/D-627-core-drive-composition-seam.md), [D-628](../adr/D-628-core-drive-output-and-recovery-boundaries.md), [D-630](../adr/D-630-remaining-platform-semantic-holders.md), [D-637](../adr/D-637-remaining-decision-console-learning-folders.md)에 따른다. CORE 세부 책임은 [CORE·Drive 안내](core-drive-responsibilities.md), 소유권·import 규칙은 [platform_parts.yaml](../../tools/harness/platform_parts.yaml)이 기준이다. 과거 `d427_target`은 소유권 식별자이고 현재 경로는 `path`와 필요한 `layout_target`으로 읽는다.

`middleware`는 장치 실행과 권한, `operations`는 관측 사실과 작업 조정, `learning`은 경험·학습·평가·아티팩트 관리를 맡는다. `contracts`는 교환 형식, `integrations`는 외부 기술 접점, `shared/web`은 여러 UI가 실제로 공유하는 기반이다. 같은 concern이 같은 실행 권한을 뜻하지 않는다.

## 편집 집

세션이 코드를 찾을 때 쓰는 열두 집이다. 소유와 import의 정본은 아래 manifest root와 [platform_parts.yaml](../../tools/harness/platform_parts.yaml)이다. 이 절은 그 root를 유지보수 단위로 묶는다. 집을 위해 폴더를 새로 만들거나 설치 이름 `control`, `core_features`, `fleet`를 바꾸지 않는다. 경로로 실행 PC를 추정하지 않는다(D-315). 2026-10-11 소스 배치 스냅샷은 그대로다.

| 집 | 이름 | 현재 경로 |
|---|---|---|
| 1 | CORE 창구 | `middleware/core/gateway`, `middleware/core/api`, `middleware/core/events`. 로봇 화면 원본은 `middleware/ui` |
| 2 | CORE 공통 | `middleware/core/services`. 명령·공통 Safety·전원. 장치 로컬 허용 동작은 `core_features.decision` |
| 3 | Drive 동작 | `middleware/control/drive/behaviors/<동작 하나>`. 설치 이름은 `core_features.*` |
| 4 | Drive 근거 | `middleware/control/drive/{safety,tracking,planning,recovery,calibration}` |
| 5 | 인지 구현 | `middleware/perception/sensors/sensing`, `middleware/perception/vision/perception` |
| 6 | 인지 노드 | `middleware/perception/control`. ROS 패키지 이름은 `control`. 다섯 호환 초기화 폴더는 설치 이름만 잇고, 노드·어댑터 파일이 이 집의 본체다 |
| 7 | 장치 | `middleware/devices`, `middleware/drivers` |
| 8 | Fleet 원장 | `operations/fleet/fleet/server`의 mission, task, trip, admission, auth. 채널 구현은 같은 패키지의 `server/channel`. 이 행은 그 파일들을 새 디렉터리로 옮긴 상태가 아니다 |
| 9 | Fleet 조정 | `operations/fleet/fleet/{traffic,routing,swarm,formation,stuck,incidents}` |
| 10 | 순수 판단 | `operations/world`, `operations/situation`, `operations/decision`, `operations/execution` |
| 11 | 현장 표면 | `operations/processes`, `operations/site_devices`, `operations/ui/{console,cam}`, `operations/apps`, `operations/vision` |
| 12 | 학습 | `learning/{curation,training,evaluation,registry}` |

집 10은 Fleet, ROS, 장치 writer를 import하지 않는다. World의 `predicted`는 odom dead reckoning이다. 집 8만 Fleet SQLite 전이를 쓴다. 최종 Base 명령 선택은 집 2의 `core_features.command`, `core_features.safety`와 `core.bridge`에 남는다. 집 12는 실행 권한이 없다.

같은 영어 단어는 집을 나눈다.

| 단어 | 의미 | 집 | 현재 경로 |
|---|---|---|---|
| control | 센서·카메라 노드 조립 | 6 | `middleware/perception`. ROS 패키지 `control` |
| control | Drive 알고리즘 | 3, 4 | `middleware/control/drive` |
| decision | 장치 로컬 허용 동작 | 2 | `core_features.decision` |
| decision | 현장 후보·모델 제안 | 10 | `operations/decision`. 설치는 Fleet 배포 |
| safety | 공통 E-stop·배터리·Fleet 상실 | 2 | `core_features.safety` |
| safety | 동작 후보의 속도·바닥 검사 | 4 | `middleware/control/drive/safety` |
| execution | 로봇 로컬 policy·receipt | 별도 root | `middleware/execution/local` |
| execution | 현장 목표·진척 | 10 | `operations/execution` |
| vision | 앞 카메라 구현 | 5 | `middleware/perception/vision` |
| vision | 천장 관측 | 11 | `operations/vision` |

`middleware/skills`와 `middleware/execution/local`은 집 7과 같은 장치 측 wheel이고 별도 manifest root다. `contracts`, `integrations`, `shared/web`, `deploy`, `tools`, `test`, `docs`는 아래 파트 설명 그대로다. 행동 조건부 미래 예측 폴더는 만들지 않는다.

## 폴더 이름과 묶음

[D-738](../adr/D-738-folder-one-authority.md)이 트리 전체의 규칙이다. `control` 한 곳의 개명이 아니다. 위의 편집 집 표는 현재 경로다. 아래 목표 폴더는 아직 만들지 않았다.

규칙은 여섯 가지다. 디렉터리의 마지막 이름은 권한 하나다. import와 ROS 패키지 이름은 유지한다. 같은 입력과 같은 출력은 한 기능 폴더에 둔다. 사실, 명령, 원장, 임대, 후보 검사는 나눈다. 경로는 실행 PC가 아니다. 한 커밋에 한 단계만 착지한다.

| 단계 | 목표 | 이 문서가 기록한 시점 |
|---|---|---|
| 1 | `middleware/control`을 `middleware/drive`로 | 이동 전 |
| 2–3 | 인지 노드의 순수 판단을 그 기능 폴더로 모으고, 남는 조립 폴더를 `middleware/perception/nodes`로 | 이동 전 |
| 4 | `robot_execution`, `site_execution` | 이동 전 |
| 5 | `robot_ui`, `site_ui` | 이동 전 |
| 6 | `overhead`, `front_camera` | 이동 전 |
| 7 | `lane_rules`, `safety_gate`, `preview`, `motion_limits`. 옛 import 패키지는 남긴다 | 이동 전 |
| 8 | Fleet `server`를 원장, 채널, 셀 어댑터, 콘솔 조립, 피어로 | 이동 전. SQLite는 하나 |
| 9 | `perception/tools`의 호스트 도구를 `tools/sim`, `tools/calibration`로 | 이동 전 |
| 10 | MapPose 호출자를 World로 옮긴 뒤 별칭을 거둠 | 이동 전 |

권한이 다른 폴더는 이름이 같아도 합치지 않는다. 보정 세션 임대, 공통 Safety, 장치 로컬 허용 동작, 상황 사실, 로봇 로컬 실행, 천장 관측, CORE 조립은 각 단계를 지나도 자기 폴더에 남는다. 다섯 설치 이름 폴더 `control`, `planning`, `safety`, `sensing`, `wander`도 남는다.

## 현재 의미 구조와 깊이

**후속 구조 제안:** 현재 배치는 아래 표 그대로이며, 공통 상황평가·작업 규칙·Fleet 어댑터의 추가 책임 분리는 [D-648](../adr/D-648-shared-judgment-target-structure.md)의 [목표 설계](../plans/2026-10-11-shared-judgment-structure-design.md)와 [단계별 계획](../plans/2026-10-11-shared-judgment-structure.md)을 검토한다. Proposed 목표를 이미 이동·설치된 현재 상태로 집계하지 않는다.

의미 폴더 깊이는 저장소 아래 책임 분류를 최대 5단계로 세는 기준이다. `middleware/control/drive/planning/nav2`는 5단계이다. `src/rosy/world`, `core_features`, `rosy_situation` 같은 언어 namespace와 ament의 `test/resource/config`는 패키지 내부 배치다. 이를 책임 분류 단계로 합산하여 기존 import를 억지로 바꾸지 않는다. 아래는 현재 존재하는 폴더만 보여 주며, 패키지 내부 경로는 괄호로 표시한다.

```text
rosy-platform/
├─ middleware/
│  ├─ core/
│  │  ├─ gateway/ (core/services.py, core/drive, core/system, core/bridge)
│  │  ├─ services/ (core_features: command, safety, line_follow, navigation 등)
│  │  ├─ api/ (core_api_web)
│  │  └─ events/ (core_events)
│  ├─ control/drive/
│  │  ├─ planning/{nav2,grid}
│  │  ├─ tracking/wander
│  │  ├─ recovery/
│  │  ├─ calibration/
│  │  └─ safety/adapter
│  ├─ perception/
│  │  ├─ sensors/sensing
│  │  ├─ vision/perception (learned 등)
│  │  └─ control/ (기존 ROS node 조립·import 호환 진입점)
│  ├─ devices/{pinky,omx}/ (bringup·profile·description 또는 adapter·agent)
│  ├─ drivers/{imu_bno055,pinky_adc,pinky_lamp,pinky_led}
│  ├─ skills/{api,manipulation}
│  ├─ execution/local
│  └─ ui/{robot,pilot,face}
├─ operations/
│  ├─ fleet/ (transaction·serving·기존 배포 owner)
│  │  └─ fleet/incidents/ (handoff.py: 사람 인수, notifications.py: 팀 알림)
│  ├─ decision/ (src/rosy/decision, 기존 Fleet 배포에 포함)
│  ├─ world/ (src/rosy/world/api, state/projections)
│  ├─ situation/ (rosy_situation/assessment, snapshot_assessment, analyzers, incidents)
│  ├─ execution/ (src/rosy/execution/api, site: goal_evidence, workflow 등)
│  ├─ processes/{cell,palletizing}
│  ├─ vision/signal_observer
│  ├─ site_devices/{dock,signal}/firmware
│  ├─ apps/{fleet,games}
│  └─ ui/{cam,console}
├─ learning/
│  ├─ curation/{pinky,omx,perception}
│  ├─ training/{pinky,omx,perception} (trainer만)
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

## 전체 manifest root 판정

현재 manifest의 **90개 root를 각각 한 행**으로 기록했다. 하위 root는 상위 root의 일부를 따로 소유하므로 행 개수를 패키지 개수로 읽지 않는다. `유지`는 실제 책임이 현재 위치에 맞는다는 뜻이다. `이전 완료`·`분리 완료`는 소스 holder 변경을 뜻한다. `후속 분리 보류`는 기존 패키지·transaction 소비자를 유지한다는 결정이며 새로운 빈 폴더를 뜻하지 않는다. ROS 배포명과 Python import명이 다른 경우 둘 다 적었다.

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
| `middleware/core/services/core_features/safety` | `core_features.safety` | 유지 — CORE 공통 E-stop·person·battery·fleet-loss 보호. Drive 전용 sweep proof와 구분 |
| `middleware/core/services/core_features/decision` | `core_features.decision` | 유지 — 장치 local lane/router/allowed-action 규칙. Fleet의 deliberative decision과 구분 |
| `middleware/core/events` | ROS `core_events`; `core_events` | 유지 — CORE/Fleet의 event bus·audit 형식과 연결 |
| `middleware/core/api` | ROS `core_api_web`; `core_api_web` | 이전 완료 — 기존 api_web 배포/import명 유지, API·WebSocket·UI 제공 소스 holder만 간소화 |
| `middleware/control/drive/planning/nav2` | ROS `navigation`; `navigation` | 이전 완료 — Nav2 launch/config/backend. CORE goal facade·취소 세대·최종 command 경계 유지 |
| `middleware/perception` | ROS `control`; `control`, `control.sensing`, `control.sensing.perception` | 분리 완료 — sensors/vision 소스와 node 조립·recorder·map resource. Drive 구현은 별도 holder; 하나의 기존 배포 패키지로 설치 |
| `middleware/control/drive` | 기존 ROS `control` 배포의 `control.control`, `control.planning`, `control.wander` | 분리 완료 — tracking/recovery/calibration과 grid planning. node/provider 소비자와 기존 relative import·monkeypatch identity 유지 |
| `middleware/control/drive/safety` | 기존 ROS `control` 배포의 `control.control.*`, `control.safety` | 분리 완료 — actuation·speed·command gate·floor/body/sweep 정책, sensor-only adapter. 별도 final writer 없음 |
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
| `operations/execution` | wheel `rosy-execution`; 배포 metadata | 유지 — 아래 API/site 하위 root의 배포 단위. local 실행 wheel은 별도 middleware 소유 |
| `middleware/execution/local` | wheel `rosy-execution-local`; `rosy.execution.local` | 유지 — local policy loader·receipt binding. `rosy-execution`과 중복 설치하지 않음 |
| `operations/execution/src/rosy/execution/api` | `rosy.execution.api` | 유지 — PlanBundle 내부 API. site producer와 현재 wheel 결합을 보존; 일반 contracts 이전은 후속 분리 보류 |
| `operations/execution/src/rosy/execution/site` | `rosy.execution.site` | 분리 완료 — 기존 site 실행·권한 projection과 D-657 순수 `goal_evidence`, `workflow` 전체 progress 계산 및 시각/step 상태 helper. producer 인증·원장 전이·local loader·장치 writer는 소유하지 않음 |
| `middleware/ui/robot` | ROS `dashboard`; web assets | 유지 — CORE가 제공하는 robot dashboard. 명령 admission은 CORE API에 남음 |
| `middleware/ui/pilot` | ROS `pilot`; web assets | 유지 — CORE 제공 Pilot UI. 장치 API의 현재 소비자 |
| `middleware/ui/pilot/android` | Android native discovery shell | 유지 — 기존 Pilot web UI를 재사용하는 발견 shell. 별도 제어 권한 없음 |
| `middleware/ui/face` | ROS `emotion`; `emotion` | 유지 — robot face/display. 제어 정책과 구분 |
| `operations/site_devices/dock` | dock contract·firmware 소스 | 유지 — 현장 dock 소유. robot docking manager의 직접 `/status` polling은 그대로 |
| `operations/site_devices/dock/firmware` | dock MCU firmware | 유지 — limit-switch interlock·0 V boot. CORE/Arm Safety와 별도 현장 보호 대상 |
| `operations/site_devices/signal` | signal contract·driver library | 유지 — Fleet 소비 signal 장치. Fleet가 sequence·command owner를 유지 |
| `operations/site_devices/signal/firmware` | signal MCU firmware | 유지 — boot·supervision-loss failsafe. 관측용 signal observer와 구분 |
| `operations/vision/signal_observer` | measured-light 관측 서비스·소스 | 유지 — read-only light evidence. CORE traffic observer 소비; 실행 host 결정이나 signal command 권한 추가 없음 |
| `operations/fleet` | ROS `fleet`; `fleet` | 분리 완료 — pure MapPose는 World, 순수 목표/진척 규칙은 execution 소비. D-657 `server/model_feedback_dispatch` 원장 어댑터와 admission·claim·dispatch·producer 인증·MapPoseService 조립·trip consumer는 Fleet 소유 |
| `operations/fleet/fleet/incidents` | `fleet.incidents.handoff`, `fleet.incidents.notifications` | 분리 완료 — D-661 이름 있는 담당자의 사건 인수와 기존 Fleet DB의 알림 outbox·고정 채널 worker·receipt. 판단·resolver는 `fleet/stuck`, 인증·라우트·worker 생명주기는 `fleet/server`에 유지. 실제 운영 수용은 HOLD |
| `operations/decision` | `rosy.decision`; 기존 `fleet` 배포 | 이전 완료 — ER2/VLM·candidate·provider-neutral tool 계약/제안. store 결속 dispatcher는 D-657에서 Fleet로 이전; 기존 transaction/배포 유지, 옛 module shim 없음 |
| `operations/ui/console` | source assets; 설치 `fleet.server.web` | 이전 완료 — canonical Console 자산, 동일 allowlist/CSP/URL. wheel·sdist는 checkout 없이 self-contained; server는 Fleet 소유 |
| `operations/apps/fleet` | wheel `rosy-app-gateway`; `rosy_gateway` | 유지 — site gateway 앱 조립. Fleet ROS 패키지·device agent와 구분 |
| `operations/world` | wheel `rosy-world`; `rosy.world` | 이전 완료 — ObservationSnapshot/API와 `state/projections/map_pose.py`. Fleet MapPoseService·trip·swarm·lane compliance·history가 실제 소비 |
| `operations/processes/palletizing` | wheel `rosy-palletizing`; `rosy.processes.palletizing` | 유지 — palletizing process 정의/조정. Arm owner·skill·site execution 소비 경계 유지 |
| `operations/processes/cell` | ROS `rosy_cell`; `rosy_cell` | 유지 — cell process·site 조립. agent/gateway contract 소비; 직접 joint writer가 아님 |
| `operations/situation` | `rosy_situation` | 분리 완료 — 기존 사실과 제한된 advisory 제안은 별도 출력. D-652 `assessment`는 개입 필요성, `snapshot_assessment`는 관측 변환을 소유하며 Fleet/Situation이 내부 shadow로 소비. 기존 import/patch identity 유지 |
| `operations/vision` | ROS `rosy_vision`; `rosy_vision` | 유지 — overhead vision worker·sighting evidence. Fleet pose consumer로 전달, cmd_vel 권한 없음 |
| `operations/ui/cam` | Android Cam 앱 | 유지 — camera/operator surface. vision·robot UI와 현재 책임 구분 |
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

`control` ROS 배포는 유지된다. `control.sensing`의 실제 구현은 `middleware/perception/sensors/sensing`, `control.sensing.perception`은 `middleware/perception/vision/perception`에 있다. `control.control`의 평탄한 module identity는 Drive의 `safety/recovery/tracking/calibration` holder에서 설치하고 `control.planning`, `control.wander`, `control.safety`도 기존 이름으로 설치한다. `control` 아래 compatibility 진입점은 source 조회의 좁은 path 연결과 기존 export를 맡는다. 설치된 배포가 checkout의 sibling 경로를 필요로 하는 구조로 해석하지 않는다. build는 정적 source mapping을 사용하고 sdist는 실제 source snapshot을 포함한다.

Fleet의 `fleet.localization.map_pose`는 World 구현 module의 명시적인 identity alias다. MapPose 알고리즘은 World에 있고 HTTP route·roster·admission·claim·dispatch는 Fleet에 남는다. Situation의 기존 `deadlock`, `incident_context`, `vlm`은 이동한 module identity를 유지하는 명시적 alias이며 analyzers package는 기존 기호를 명시적으로 export한다. 호환 코드에 알고리즘을 복제하지 않는다.

Gazebo의 launch와 script는 manifest에서 각각 별도 concern을 갖지만 실제 ROS 배포명은 `gz_sim`이다. launch가 장치 pipeline을 시작한다는 이유만으로 resource/install owner를 다른 패키지로 분리하지 않았다. robot description·map/STL lineage·기존 share resource를 그 패키지 소비자와 함께 유지한다.

## 현재 상태와 미래 행동 예측

D-652 공통 필요성 평가는 Situation의 순수 모듈에 있고 Fleet는 현장 상태 수집·사건 연결·기존 resolver를 소유한다. Fleet wheel과 현장 source image에는 `__init__.py`, `assessment.py`, `snapshot_assessment.py`만 포함한다. 빌드 조합은 `tools/packaging/fleet_sources.py`가 소유하고 source archive의 `_build` 사본으로 checkout 밖 재빌드를 지원한다. 이 내부 shadow 구현은 D-648 전체 목표 구조의 수용과 구분한다.

D-657은 D-648 단계 2와 단계 3의 첫 계산 단위만 수용한다. 실제 원장 모델 도구 구현은 `fleet.server.model_feedback_dispatch`, 순수 목표 검증은 `rosy.execution.site.goal_evidence`, 기존 시각·신선도·step 상태 투영은 `rosy.execution.site.workflow`가 소유한다. D-656 후속 통합은 Fleet가 제공하는 일관된 snapshot의 읽기 진행 계산 전체를 같은 workflow의 `project_progress`에 둔다. DB 전이·auth·claim·admission·transport는 Fleet에 남긴다. Fleet는 기존 execution wheel dependency를 사용하고 execution 파일을 중복 포장하지 않는다. site source image도 해당 source closure를 포함한다. 다른 Mission 전이·복구 규칙 및 D-648 단계 4는 후속으로 유지한다. 소스/설치 검증과 실제 이미지 빌드·배포·현장 정확도는 별도다.

사용자의 후속 처리 요청으로 `project_progress` 전체 계산도 같은 workflow에 분리했다. Fleet adapter가 하나의 transaction에서 읽은 snapshot과 clock을 제공하고 execution은 기존 wire 결과를 투영한다. 단독 helper import는 stdlib만 필요하며 projection 호출 시 기존 foundation schema를 불러온다. 이는 DB 상태 전이·복구나 D-660~D-662 운영 판단 기능의 승인/착지를 대신하지 않는다.

후속 main `7afb0e2c4`의 소스에서는 D-661 인수·알림이 `fleet/incidents/{handoff,notifications}.py`에 있다. 다음 구조 작업도 이 직접 import 경로와 책임을 유지한다. Situation의 `rosy_situation/incidents`는 상황 근거를 구성하는 모듈이며 Fleet의 담당 인수·전송 원장과 구분한다. [하위 패키지 이동 계획](../plans/2026-10-11-fleet-team-incidents-subpackage.md)과 [책임 분리 계획](../plans/2026-10-11-responsibility-authority-orchestration.md)을 따른다. D-660~D-662 소스 반영과 최종 검증 receipt·실제 운영 수용은 별개이며, 실제 채널 수신·현장 정답 검수 및 단계 6 모델 토론은 HOLD다.

현재 World 구현은 `ObservationSnapshot`과 관측/odom을 합성하는 `MapPoseTracker`다. `MapPoseService`, trip admission/progress/ports, swarm anchor, lane compliance, path history가 이를 소비한다. World 내부의 `predicted` 표기는 마지막 관측에서 odom으로 갱신하는 dead reckoning이며, 행동 후보를 넣고 미래 상태·불확실성을 내는 action-conditioned rollout이 아니다. Situation은 현재 stuck/traffic/incident 사실과 일부 analyzer의 제한된 WAIT/BACK_AND_RETRY 제안을 별도로 출력한다. 기존 제안 출력을 모두 사실 또는 새 공통 assessment로 집계하지 않는다.

행동 조건부 미래 예측은 D-625의 **계획 책임**이다. 구현하려면 현재 state revision, action candidate, horizon, model revision, 만료/불확실성 결과, 실제 decision 소비자, 독립 평가가 먼저 있어야 한다. `operations/prediction/world_model` 및 대응 학습·평가 holder는 현재 생성하지 않았다. `learning/training/omx/act_inference.py`의 ACT policy action 출력은 그 World model의 구현으로 집계하지 않는다. 기존 state projection, 학습/연구, 미래 예측 계획을 각각 기록한다.

이 안내의 이전/분리 완료는 local main에 반영한 소스 수준 판정이다. 90개 root를 판정했고 실제 빈 제품 폴더는 없었다. `data/drive/.gitkeep`는 계약용 placeholder로 유지했다. 공유 main의 이전 `middleware/core/api_web`, `middleware/apps/device` 경로에는 추적 제품 파일이 없지만 ignored cache·`.omc` 상태가 남을 수 있다. 동료 도구 상태를 삭제하거나 옮겨 제품 이동으로 집계하지 않는다. Decision/Console source 분리는 완료했고 기존 Fleet 배포·transaction·serving을 유지한다. 별도 배포 패키지 생성과 행동 조건부 World model은 이번 범위가 아니다. 해당 committed SHA의 remote 시험, checkout 밖 설치 확인과 남은 CI·ROS·ARM64·배포·장치·현장 gate는 [검증 기록](../validation/d637-remaining-folders-2026-10-11/result.md)에서 확인한다.

D-637에서 기존 298파일과 동시 개발로 추가된 Console `inbox.js` 1파일, 총 299파일을 처리했다. Console은 67개 source 파일 중 65개 설치 자산이며 AGENTS와 package.json은 개발 안내/도구 입력이다. `test/learning/perception`은 기존 99파일의 shared workflow 시험 위치다. 퇴역 WSL 도구 6개는 `docs/reference/legacy-tools/wsl`로 동결했고 현재 운영 경로에 재연결하지 않는다.

## D-649 책임 이동 보완

후속 책임·권한·결과 확인 계약은 Accepted [D-656](../adr/D-656-responsibility-authority-and-orchestration-boundaries.md)과 [실행 계획](../plans/2026-10-11-responsibility-authority-orchestration.md)을 따른다. 수용 범위는 논리 경계와 이행 순서이며 위 표의 현재 소스 배치와 D-652 내부 shadow 외의 구현/운영 수용을 뜻하지 않는다.

`middleware/control/drive/behaviors/{line_follow,docking,navigation,localization,swarm,road_behaviour,traffic_policy}`가 Base 행동 구현의 정본이다. CORE 서비스 배포가 기존 `core_features.*` 이름으로 설치하며 구현 복사본은 없다. `middleware/control/drive/runtime/`는 기존 control/goal/wander/safety ROS 진입 모듈을 소유하고 `control.*` 이름으로 설치한다. 위의 이전 배치 설명은 이 이동으로 보완된다. CORE 공통 Command/Safety와 `core/drive` 조립은 유지한다.

반복 이름은 세 종류다: 설치 패키지 이름(`core`, `control`, `fleet`, `rosy` namespace), 서로 다른 권한(장치-local execution/현장 execution, 관측 safety adapter/CORE Safety), 실제 혼재했던 행동 구현(이번 Drive 이동). 호환 initializer에는 알고리즘을 추가하지 않는다. 일반 캘리브레이션 lease와 카메라 장애 복구 자격 판정은 CORE 공통 admission이며 Drive 탈출 운동 구현과 다르다. Perception localization 노드는 상태/관측 근거를 소유한다.

현재 물리 이동과 설치 매핑, 원격 시험, 배포/장치 수용은 별도 기록이다. [D-649](../adr/D-649-drive-behavior-source-ownership.md), [실행 계획](../plans/2026-10-11-role-folder-boundaries.md)을 따른다.

D-671의 현재 Discord source는 `integrations/messaging/discord/rosy_discord/intake.py`의 순수 envelope/signature adapter다. 기존 Fleet 배포물에 설치하며 source image는 같은 코드를 포함한다. 기명 계정 연결·인증·접수 원장은 `operations/fleet/fleet/server/channel_requests.py`, 조회 표면은 기존 Console 작업 화면이 소유한다. 별도 실행 서비스·wheel·Mission DB는 없다. Gateway 실행기와 실제 수신, 후보·승인·위험 조치/reply는 미구현이며 D-669 후속이다.
