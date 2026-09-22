# ROSY 모듈 실제 동작 판정 기준

문서 ID: `ROSY-MODULE-ACCEPTANCE-001`  
상태: 기준 문서  
적용 대상: Rosy OS의 20개 ROS 패키지와 `deploy`, `dock`, `docs` 운영 모듈

## 1. 목적

이 문서는 “모듈이 존재한다”, “테스트가 통과한다”, “프로세스가 떠 있다”를
“실제로 동작한다”와 구분한다. 각 모듈의 입력, 관측 가능한 결과, 실패 시 안전한
상태, 필요한 실행 환경과 증거를 고정해 같은 결과에 같은 판정을 내리게 한다.

현재 상태는 이 문서에 복제하지 않는다. 최신 GO/HOLD/PARKED/N/A 판정은
[`STATUS.md`](../../STATUS.md)와 각 모듈의 `progress.md`가 소유한다. 이 문서는
그 판정을 내릴 때 적용할 기준이며, 문서를 추가했다는 사실만으로 어느 gate도
승격하지 않는다.

계약 우선순위는 SRS·API·ADR > 이 기준 > `progress.md`의 실행 기록 > 로그다.
충돌하면 상위 계약을 먼저 고치거나 새 ADR을 추가한 뒤 기준과 구현을 함께
정렬한다.

## 2. 판정 단위와 용어

### 2.1 두 종류의 모듈

- **실행 모듈**: `src/`의 ROS 패키지 20개와 `deploy`, `dock`, `docs`다. 빌드,
  설치, 실행, 장애 격리의 경계다.
- **논리 모듈**: M01–M14다. 제품 기능과 업무 인수의 경계다. 하나의 논리
  모듈은 여러 실행 모듈을 가로지를 수 있다.

실행 모듈 하나가 GO라고 해서 관련 논리 모듈 전체가 GO인 것은 아니다. 반대로
M01–M14의 설계가 있어도 이를 수행하는 실행 모듈과 증거가 없으면 HOLD다.

### 2.2 “실제 동작”의 정의

모듈은 지정한 프로파일과 환경에서 다음 조건을 모두 만족할 때만 **동작 GO**다.

1. 이 문서가 지정한 목표 gate와 그 이전 gate가 모두 GO다.
2. 필수 의존 모듈도 같은 release manifest가 선언한 소스 revision, 설정
   generation과 호환 artifact 관계에 대해 필요한 gate가 GO다. 서로 다른
   core/io/firmware artifact에 동일 digest를 요구하지 않는다.
3. 정상 경로뿐 아니라 대표 장애, 중단, 재시작 또는 복구 경로를 실행했다.
4. 결과를 외부에서 관측했다. 함수 반환, HTTP 200, 노드 생존만으로는 부족하다.
5. 안전·보안·단일 소유권 불변식을 위반하지 않았다.
6. 실행 명령, 환경, 입력, 측정값, 로그와 판정자가 남아 있다.

`FIELD READY`는 별도 판정이다. DEVICE GO나 ROS-SIM GO를 현장 사용 승인으로
읽지 않는다. `FIELD READY`는 특정 `(module, scenario, profile, device/site)`에
대해 FIELD gate와 모든 적용 가능한 선행 gate가 GO라는 집계 결과다. 범위를
생략한 전역 `FIELD READY` 판정은 만들지 않는다.

### 2.3 의존성 판정

- 필수 의존성이 HOLD이면 소비 모듈도 그 시나리오에서는 HOLD다.
- 선택 기능을 명시적으로 비활성화했고 capability가 이를 정확히 광고하면 그
  선택 모듈은 N/A일 수 있다.
- 선행 gate의 N/A는 이 문서와 module profile이 그 gate를 구조적으로 적용하지
  않는다고 명시한 경우에만 충족으로 취급한다. HOLD와 PARKED는 충족이 아니다.
- 의존 모듈의 GO를 소비 모듈의 GO로 복사하지 않는다. 예를 들어 `interfaces`
  빌드 성공은 `led`의 실물 점등을 증명하지 않는다.
- 공유 artifact에 함께 들어가도 모듈별 관측 결과는 따로 남긴다.

## 3. 공통 증거 gate

| gate | 증명할 것 | 최소 증거 | 이 gate가 증명하지 않는 것 |
|---|---|---|---|
| `SOURCE` | 소유권, 계약, 의존성, fail-closed 기본값이 코드에 존재 | 현재 tree를 읽는 모듈 자체의 기능/계약 시험, 관련 SRS·ADR 추적 | 실행 중인 ROS graph, 바이너리, 실물 I/O |
| `LOCAL` | 소유 코드의 정상·오류·복구 로직이 호스트에서 재현 | 현재 commit/dirty 상태, 명령, 테스트 결과, fixture | ROS executor, DDS, ARM64, 센서·모터 |
| `ROS-SIM` | 현재 tree를 colcon 빌드한 ROS 2 Jazzy 환경에서 노드와 통신 경로가 동작 | 해당 tree의 `install/setup.bash`, 노드 graph, 토픽/서비스/action 결과, 시나리오 로그 | 서명 artifact, Pi 설치, 실물 정확도·안전 |
| `ARTIFACT` | 배포할 정확한 산출물이 재현·식별·검증 가능 | native ARM64 빌드, manifest, 서명 검증, immutable digest, SBOM/입력 lock, 패키지 포함 확인 | 대상 장치 설치와 물리 동작 |
| `DEVICE` | 정확한 artifact가 지정 장치에서 실제 I/O와 함께 동작 | Device identity, 설치/activation record, `verify-pi.sh`, `device-readback.sh --json`, 물리 측정, 장애·재시작 결과 | 반복 현장 업무와 운영자 인수 |
| `FIELD` | 대표 환경에서 업무 시나리오와 안전·복구가 반복 가능 | 현장 조건, 반복 횟수, 성공률/오차/지연, 운영자·안전 담당 승인, rollback 결과 | 다른 하드웨어·사이트·프로파일에 대한 일반화 |

`N/A`는 모듈 성격상 그 gate가 존재하지 않을 때만 쓴다. 환경이 없거나 아직
실행하지 않은 경우는 HOLD, 범위와 선행 결정이 아직 닫히지 않은 경우는
PARKED다. 과거 tree, 다른 artifact, 다른 로봇의 증거는 현재 gate를 GO로 만들지
않는다(D-79).

## 4. 공통 증거 레코드

각 실행은 Markdown이나 JSON으로 다음 필드를 남긴다.

| 필드 | 내용 |
|---|---|
| `run_id` | 중복되지 않는 시험 실행 ID |
| `module` / `scenario` | 판정할 모듈과 시나리오 이름 |
| `source` | commit SHA, dirty 여부와 관련 diff 식별자 |
| `environment` | OS, 아키텍처, ROS/RMW, 컨테이너 또는 호스트 버전 |
| `artifact` | release ID, manifest와 이미지 digest, 서명 key ID·검증 결과 |
| `device` | robot ID/number, 모델, 보드 revision, 장치 serial; secret 제외 |
| `profile` | runtime mode, capability/profile revision, map/calibration ID |
| `config_generation` | 적용된 config generation/revision과 readback hash; profile과 별도 기록 |
| `command` | 그대로 재실행 가능한 명령과 주요 입력 |
| `observation` | 기대값, 측정값, 허용 범위, 로그·rosbag·스크린샷 경로 |
| `fault_recovery` | 주입한 장애, 안전 상태, 복구·재시작·rollback 결과 |
| `result` | GO/HOLD/PARKED/N/A와 이유, 판정자, UTC 시각, 다음 gate |

측정 허용 범위가 필요한데 값이 비어 있으면 HOLD다. “문제 없어 보임”은 측정값이
아니다. 허용 범위, 최소 반복 횟수, sampling window와 승인자는 시험 전에 versioned
profile 또는 acceptance record로 고정한다. 결과를 본 뒤 기준을 완화하면 새
revision으로 다시 시험한다. credential, token, private key는 증거에 넣지 않는다.

판정의 기본 key는 `(module, scenario, source revision, profile revision,
config_generation, release manifest와 artifact digest, device/site)`다. 서로 다른
key의 성공률을 평균해 하나의 GO로 만들지 않는다. source, profile,
config_generation, artifact, hardware revision, map/calibration 또는 site 조건이
바뀌면 영향을 받는 판정을 HOLD로 되돌려 재검증한다. 시간 만료가 중요한
sensor·인증서·현장 점검은 profile에 최대 evidence age를 두며, 값이 없으면 오래된
증거로 새 배포를 승격할 수 없다.

## 5. 전 모듈 공통 불변식

아래 중 하나라도 위반되면 관련 모듈의 상위 gate는 HOLD다.

1. 외부 클라이언트의 로봇 진입점은 CORE REST/WS뿐이다. 외부 UI와 Fleet은
   ROS/DDS나 `cmd_vel`에 직접 붙지 않는다.
2. 최종 `cmd_vel` publisher는 CORE Command Manager 하나다. `control`, Fleet,
   Nav2, OMX는 최종 publisher가 될 수 없다.
3. 명령 접수(`accepted`)와 실제 실행 시작·완료·취소 결과를 구분한다.
4. identity에는 기본값이 없다. `ROSY_ROBOT_NUMBER`에서 파생된 robot ID,
   namespace와 DDS domain이 누락·충돌하면 기동을 거절한다.
5. stale, missing, non-finite, 역순 sequence, 잘못된 revision의 evidence는 새
   동작 허가가 아니다. 위험 동작은 HOLD 또는 zero output으로 닫힌다.
6. e-stop 해제, 재부팅, 프로세스 재시작은 이전 명령을 자동 재개하지 않는다.
   fresh evidence와 새 운영자 동작이 필요하다.
7. capability는 설치·활성화·검증된 기능만 광고한다. 미구현·PARKED 기능은
   `available`처럼 보이면 안 된다.
8. 소프트웨어 deadman은 물리 e-stop을 대체하지 않는다.
9. ROS-SIM, ARTIFACT, DEVICE, FIELD는 서로 대체할 수 없다.

### 5.1 최소 의존 gate

아래는 공통 최소치다. 실제 scenario가 추가 기능을 켜면 그 기능의 의존성을 더한다.
같은 행의 의존 모듈은 소비 모듈의 판정 key와 호환되는 source/profile/config여야
하며, 서로 다른 이미지·firmware는 동일 signed release manifest가 그 조합을
호환 대상으로 선언해야 한다. 표에 gate가 명시되어 있으면 그 gate를 요구한다.
gate가 생략된 실행 모듈은 소비 모듈과 같은 stage까지, 그 이후 stage가 N/A인
모듈은 자기 최종 목표 gate까지 GO여야 한다. 외부 toolchain·물리 장치는 소비
모듈의 목표-stage scenario 안에서 함께 검증한다.

| 실행 모듈 | 최소 필수 의존성과 gate | 목표 gate |
|---|---|---|
| `core_common` | 없음 | 자체 LOCAL + CORE 통합 ROS-SIM |
| `core_events` | `core_common` LOCAL | 자체 LOCAL + CORE 통합 ROS-SIM |
| `core_features` | `core_common`, `core_events` LOCAL | 자체 LOCAL + CORE 통합 ROS-SIM; 물리 capability는 DEVICE |
| `core_api_web` | `core_common`, `core_events`, `core_features` LOCAL | live ROS-SIM; Device UI는 DEVICE |
| `core` | 위 CORE libraries와 `interfaces` ROS-SIM; profile에 따라 `navigation`/`bringup` | DEVICE |
| `interfaces` | clean ROSIDL toolchain과 한 consumer/server | ROS-SIM round trip |
| `control` | ROS Jazzy graph; adapter 사용 시 `core`; 선택 calibration generation | ROS-SIM, camera/calibration은 DEVICE |
| `emotion` | `interfaces` ROS-SIM, physical LCD/profile | DEVICE |
| `games` | observation source와 참여 robot의 CORE API | ROS-SIM, 제품 사용은 FIELD |
| `omx_adapter` | selected vendor transport, ros2_control/MoveIt, power/mount/safety profile | DEVICE, 모바일 조작은 FIELD |
| `bringup` | selected hardware profile, `description`, motor/LiDAR 장치 | DEVICE |
| `led` | `interfaces` ROS-SIM, hardware helper와 LED | DEVICE |
| `imu_bno055` | selected I2C/profile과 BNO055 | DEVICE |
| `lamp_control` | `interfaces` ROS-SIM, ARM64 library와 lamp profile | DEVICE |
| `sensor_adc` | selected I2C/channel profile과 센서 fixture | DEVICE |
| `navigation` | map/profile, `description`, `bringup`, CORE readiness | DEVICE, site 사용은 FIELD |
| `description` | selected geometry/profile | ROS-SIM; 안전 geometry는 DEVICE |
| `gz_sim` | scenario에 쓰는 `description`, `navigation`, `core`, `fleet` | ROS-SIM |
| `fleet` | N대 CORE API, 공통 map/time/network 조건 | ROS-SIM, 실물 site는 FIELD |
| `deploy` | native ARM64 builder, signing trust, registry/storage, target Pi | DEVICE |
| `dock` | firmware, CORE docking/power, `navigation`, 물리 dock | DEVICE, 대표 접근 조건은 FIELD |
| `docs` | SRS/API/ADR, harness와 current tree | LOCAL |

## 6. 실행 모듈별 기준

### 6.1 CORE 도메인

#### `core_common`

역할은 protocol schema, identity, config, capability, profile과 공통 domain
모델이다. 단독 프로세스가 아니라 모든 상위 모듈이 의존하는 계약 라이브러리다.

**동작 GO 기준**

- 같은 payload를 직렬화·역직렬화해 protocol version, enum, evidence와 오류
  envelope가 보존된다.
- config가 기본값 → `~/.rosy/rosy.yaml` → `ROSY_CONFIG` 순으로 병합되며,
  잘못된 타입·경로·identity는 명시 오류로 실패한다.
- robot ID/name, profile, capability 검증이 모순된 조합과 미지원 기능을 거절한다.
- CORE ROS-SIM 기동에서 동일 schema/config/identity가 REST/WS와 내부 서비스에
  사용된다.

목표 gate는 라이브러리 자체 `LOCAL`과 CORE 통합 `ROS-SIM`이다. 제품 Device
판정은 동일 코드를 포함한 CORE artifact/readback에 종속된다.

#### `core_events`

역할은 in-process event bus와 append-only audit 기록이다.

**동작 GO 기준**

- event 순서와 sequence가 보존되고, 필터와 구독 해제가 예상대로 동작한다.
- 한 subscriber의 실패가 publisher나 다른 subscriber를 멈추지 않는다.
- audit는 재시작 뒤에도 조회 가능하고 보존 기간·크기 한계를 지키며, 손상된
  record를 성공으로 위장하지 않는다.
- API/WS에서 발생한 명령·거절·완료·안전 사건을 같은 correlation 정보로 찾을
  수 있고 secret이 기록되지 않는다.

목표 gate는 `LOCAL`과 CORE 통합 `ROS-SIM`이다. 파일시스템 장애와 재시작 복구가
없는 성공 경로만으로는 GO가 아니다.

#### `core_features`

역할은 command, safety, state, navigation, waypoints, power, docking,
diagnostics, swarm, fleet-agent의 로봇 로컬 정책이다.

**동작 GO 기준**

- 각 manager의 상태 전이, 중복/충돌 명령, timeout, cancel, restart가 명시된
  상태와 event를 만든다.
- safety와 navigation readiness가 stale/missing evidence를 만나면 새 명령을
  거절하고 최종 출력 후보를 zero/HOLD로 만든다.
- navigation은 API 접수, Nav2 action 수락, 진행, 결과, 취소 완료를 서로 다른
  상태로 기록한다.
- power·docking·swarm은 센서/peer 단절과 재접속 때 과거 동작을 자동 재개하지
  않는다.
- ROS-SIM에서 CORE bridge를 통해 실제 topic/service/action 효과와 readback이
  일치한다.

순수 정책의 목표 gate는 `LOCAL`+`ROS-SIM`이다. 모터, 배터리, 도크, swarm 등
물리 capability를 광고하려면 해당 하위 모듈의 DEVICE/FIELD gate도 필요하다.

#### `core_api_web`

역할은 FastAPI REST/WS, 인증/권한, Host Agent client와 정적 dashboard다.

**동작 GO 기준**

- viewer/operator/administrator별 allow와 deny를 모두 검증하고, direct route와
  기존 session revocation도 같은 정책을 따른다.
- REST/WS payload가 API Reference 및 `core_common` schema와 일치하며, 잘못된
  입력·권한·미지원 capability는 안정된 오류 code로 거절된다.
- live server에서 state/event WebSocket 재연결, sequence gap, stale 표시와
  REST 상태가 일치한다.
- dashboard는 `fresh`/`delayed`/`disconnected`/`unavailable`을 구분하고 stale
  값으로 위험 action을 활성화하지 않는다.
- Host Agent가 없거나 거절하면 임의 shell이나 성공 응답으로 우회하지 않는다.

서버 목표 gate는 `ROS-SIM`이다. 실제 운용 화면은 Pi의 지원 viewport에서
키보드·터치·재연결·권한을 검증해야 DEVICE GO다.

#### `core`

역할은 rclpy executor, ROS bridge, 서비스 조립과 uvicorn을 한 프로세스로 묶는
유일한 외부 gateway다.

**동작 GO 기준**

- 명시 identity와 config로 `ros2 run core core` 또는 공식 launch가 기동하고,
  ROS executor와 API가 함께 준비되며 한쪽 실패가 health에 드러난다.
- REST/WS 원자 명령이 내부 ROS topic/action/service로 변환되고 결과가 다시
  API 상태·event·audit에 반영된다.
- node graph에서 최종 `cmd_vel` publisher가 하나이고, lifecycle/readiness 또는
  sensor lease가 끊기면 출력이 zero가 된다.
- CORE 재시작, API thread 실패, ROS callback 지연, RMW mismatch에서 안전 상태와
  supervisor 복구가 관측된다.
- Pi에서 signed artifact, identity, health, graph, config generation과 publisher
  수가 `device-readback.sh --json`에 연결된다.

실제 로봇 runtime의 목표 gate는 `DEVICE`다. 바닥 주행과 업무 사용은 FIELD가
별도로 필요하다.

#### `interfaces`

역할은 `Emotion`, `SetLed`, `SetBrightness`, `SetLamp` ROS service IDL이다.

**동작 GO 기준**

- clean colcon build에서 Python/C++ type support가 생성되고 모든 consumer가
  같은 정의에 링크된다.
- 각 service는 한 개 이상의 실제 server/client 조합으로 request/response
  round trip을 통과하고, 범위 밖 입력은 consumer 계약대로 거절된다.
- IDL 변경 시 dependent packages를 rebuild하고 compatibility 또는 명시적
  breaking-change 결정을 기록한다.

목표 gate는 `ROS-SIM` service round trip이다. IDL 생성만으로 물리 장치 동작을
주장하지 않는다.

### 6.2 애플리케이션 도메인

#### `control`

역할은 absorbed sensing, camera/OpenCV, calibration, planning, safety-policy와
sensor evidence 생산이다.

**동작 GO 기준**

- required sensor, timestamp, sequence, revision과 calibration generation이
  immutable observation으로 전달된다.
- missing/stale/non-finite/역순 evidence와 calibration 불일치는 후보 동작을
  거절하고 이유를 남긴다.
- camera worker는 bounded queue, frame freshness, drop/latency와 restart 격리를
  측정하며 오래된 frame을 새 결과로 사용하지 않는다.
- 추론을 활성화하면 model hash/version, 입력 전처리, ground-truth fixture,
  false-positive/false-negative 또는 task success 기준, p95 latency와 uncertainty
  거절 조건을 사전 승인 record에 고정한다. 이 record가 없으면 inference
  capability는 unavailable이다.
- CORE sensor adapter는 명시 opt-in일 때만 활성화되고 선택 generation을
  readback한다.
- CORE와 함께 실행할 때 이 패키지는 최종 `cmd_vel`을 publish하지 않는다.

정책·노드 graph의 목표 gate는 `ROS-SIM`, 카메라·보정까지 포함한 실제 목표는
`DEVICE`다. 레거시 `robot.launch.py` 전체 스택을 CORE와 병행 기동한 결과는
유효 증거가 아니다.

#### `emotion`

역할은 LCD emotion service와 전원 상태에 따른 info screen이다.

**동작 GO 기준**

- `set_emotion` 요청이 선택한 asset을 실제 화면에 표시하고 성공/실패 응답과
  표시 결과가 일치한다.
- battery/info payload가 정해진 색·문구로 렌더되고 invalid 값은 오도하지 않는
  fallback으로 표시된다.
- `power/mode`에 따라 backlight가 active/idle/standby 정책을 따르고 재시작 뒤
  안전한 기본 화면으로 복구된다.
- 누락·손상 asset, LCD 단절, 빠른 연속 요청이 crash나 거짓 성공이 되지 않는다.

목표 gate는 물리 LCD에서의 `DEVICE`다. PIL render 시험이나 ROS service 생존은
그 이전 gate다.

#### `games`

역할은 노트북에서 실행하는 game host다. CORE mode가 아니며 ROS와 최종
`cmd_vel`을 소유하지 않는다.

**동작 GO 기준**

- field/overhead observation, game state, policy, robot transport의 한 tick이
  결정적으로 연결되고 20 Hz loop에서 정해진 제한을 지킨다.
- synthetic·stale·유실 observation은 기본 HOLD이며 robot action을 만들지 않는다.
- arm/start/stop/reset과 score 판정이 중복 입력과 재연결에서도 일관되고,
  정지 입력은 참여 로봇 모두의 CORE safety stop으로 전달된다.
- 실제 명령은 인증된 CORE 원자 API만 사용하며 ROS/DDS·`cmd_vel`에 접근하지
  않는다.
- FIELD GO는 실물 경기장, 실제 overhead camera와 2대 로봇의 반복 1v1 결과,
  충돌·유실·운영자 정지 증거를 요구한다.

host loop의 목표 gate는 `LOCAL` 통합 실행, 로봇 연계는 `ROS-SIM`, 제품 사용은
`FIELD`다.

#### `omx_adapter`

역할은 OMX profile과 향후 ros2_control/MoveIt 경계다. 현재 disabled profile
검증은 실물 arm 동작이 아니다.

**동작 GO 기준**

- disabled profile은 controller, joint state, transport를 만들지 않는다.
- 선택 모델은 serial/model, joint/gripper 이름, limit, controller와 MoveIt
  계약을 완전하게 검증하고 일부만 맞는 profile을 거절한다.
- 실제 vendor transport가 `FollowJointTrajectory`와 gripper action을 수행하고,
  feedback·완료·취소·통신 단절을 구분한다.
- joint limit, collision, e-stop, base-motion interlock, 전원 손실과 재시작에서
  재개가 아니라 안전 정지·재확인을 수행한다.
- 물리 mount, payload, centre of gravity, hand-eye, reach와 회복 절차를 측정한다.

목표 gate는 선택한 OMX를 연결한 `DEVICE`, 모바일 조작은 `FIELD`다. vendor
plugin과 MoveIt 경로가 없는 profile-only 상태는 SOURCE/LOCAL 이상으로 승격하지
않는다.

### 6.3 하드웨어 도메인

#### `bringup`

역할은 Dynamixel motor, odometry, joint state, LiDAR, battery와 motor-ready
lease다.

**동작 GO 기준**

- motor ID/baud/device와 wheel geometry가 지정 profile과 일치하고, probe는
  runtime이 확실히 내려간 상태에서만 실행된다.
- boot 시 torque-off/zero를 유지하고, 명령이 motion limit과 wheel RPM 한계를
  넘으면 제한 또는 거절 결과를 남긴다.
- `cmd_vel` timeout, CORE loss, UART loss, malformed command에서 측정된 시간 안에
  zero/stop하며 `motor/ready` lease가 만료된다.
- encoder 방향·scale·32-bit rollover와 odometry/TF가 실제 바퀴 이동과 맞는다.
- lifted-wheel bench에서 restart, power cycle, e-stop, driver error 뒤 과거 명령이
  재개되지 않는다.

목표 gate는 lifted-wheel 물리 `DEVICE`; 바닥 주행은 FIELD다.

#### `led`

역할은 `SetLed`와 `SetBrightness`를 실제 LED 장치에 적용하는 server다.

**동작 GO 기준**

- service request와 실제 색·밝기 결과가 일치하고 범위 밖 값은 명시적으로
  clamp 또는 reject된다.
- 빠른 연속 요청, 장치 초기화 실패, helper 예외가 node crash나 거짓 성공으로
  숨지 않는다.
- CORE battery/상태 정책이 service를 통해 적용되며 CORE가 장치를 직접 구동하지
  않는다.

목표 gate는 실물 LED를 관측한 `DEVICE`다.

#### `imu_bno055`

역할은 optional BNO055 IMU와 freshness health 발행이다.

**동작 GO 기준**

- 실제 I2C 장치에서 orientation/angular velocity/linear acceleration의 frame,
  단위, timestamp, rate와 covariance가 계약에 맞는다.
- short read, invalid quaternion, bus timeout, device reset을 유효 sample로
  publish하지 않고 health가 stale/fault로 전환된다.
- stationary bias, 온도 변화, 재시작 안정화 시간을 측정하고 선택 profile에
  허용 범위를 기록한다.
- `reset_on_start=false` 기본을 지키고, opt-in reset 뒤 quiet time을 지킨다.

목표 gate는 BNO055가 연결된 `DEVICE`; `robot_localization` 사용은 별도 FIELD
profile 검증이 필요하다.

#### `lamp_control`

역할은 WS2811 lamp의 `SetLamp` service와 색 command 적용이다.

**동작 GO 기준**

- selected board profile의 pixel count, GPIO, DMA, strip order가 실제 배선과
  일치하고 service 결과가 전 pixel의 관측 색과 맞는다.
- invalid RGB/length, `ws2811_init` 실패와 장치 재초기화가 명시 실패로 드러난다.
- 종료·재시작·전원 모드 전환에서 의도하지 않은 잔류 점등이 없다.

목표 gate는 native ARM64 artifact에 포함된 실물 lamp `DEVICE`다. Gazebo lamp
plugin은 ROS-SIM 증거일 뿐이다.

#### `sensor_adc`

역할은 I2C ADC의 IR, ultrasonic, battery channel을 표준 ROS message로 발행한다.

**동작 GO 기준**

- channel mapping, voltage/range 변환, 단위, frame, timestamp와 publish rate가
  실제 입력 fixture와 허용 오차 안에서 일치한다.
- active/idle/standby rate가 `power/mode`를 따르되 CORE 단절을 더 낮은 안전
  sample rate로 오인하지 않는다.
- short read, out-of-range, stuck value, I2C 단절을 정상 0으로 publish하지 않고
  stale/fault가 관측된다.
- battery 값은 독립 계측과 비교하고 low-battery 정책 입력으로 사용할 수 있는
  정확도와 지연을 만족한다.

목표 gate는 실제 ADC·센서를 연결한 `DEVICE`다.

### 6.4 Navigation, simulation과 site

#### `navigation`

역할은 Nav2/SLAM launch, map, params, footprint와 motion-limit guard다.

**동작 GO 기준**

- site map과 map ID, localization, planner/controller/costmap lifecycle이 준비된
  뒤에만 goal을 받는다. field profile에서 demo map fallback은 금지다.
- profile의 speed/acceleration/footprint 한계를 더 높은 launch override로
  우회할 수 없다.
- goal acceptance, progress, arrival pose/정지, cancel completion, timeout와
  bounded recovery를 별도 상태와 측정값으로 남긴다.
- stale localization, missing TF, blocked path, controller loss에서 HOLD/zero로
  전환하고 무한 recovery를 하지 않는다.
- stationary Pi → lifted-wheel → 측정 floor course 순서로 goal error, path length,
  minimum clearance, stop latency/distance, covariance, recovery count와 자원 사용을
  기록한다.

목표 gate는 측정 floor course의 `DEVICE`; 대표 site 운용은 FIELD다.

#### `description`

역할은 URDF/xacro, mesh, joint, collision/inertia와 TF 모델이다.

**동작 GO 기준**

- clean xacro render와 `robot_state_publisher`에서 TF tree가 단절·중복 없이
  생성되고 namespace/frame_prefix로 2대가 격리된다.
- wheel joint 이름과 축·방향이 `bringup` odometry 및 Gazebo model과 일치한다.
- visual/collision mesh, inertia와 footprint가 artifact에 실제 포함되고 선택한
  하드웨어 profile의 실측 치수·질량과 허용 범위 안에서 맞는다.
- 잘못된 joint, 누락 mesh, zero/비정상 inertia가 build 또는 launch에서
  실패한다.

모델 실행의 목표 gate는 `ROS-SIM`; 실제 geometry를 안전 판단에 사용할 때는
`DEVICE` 측정이 추가로 필요하다.

#### `gz_sim`

역할은 Gazebo world, robot spawn, ros_gz bridge와 multi-robot bench다.

**동작 GO 기준**

- 현재 tree의 colcon install에서 2대 이상을 띄우고 namespace, TF, sensors,
  bridge와 CORE가 서로 오염 없이 동작한다.
- spawn pose가 각 robot의 initial pose로 들어가며 odom 원점을 관제 pose로
  오인하지 않는다.
- navigation/follow/hold/cancel/e-stop 시나리오가 bounded time 안에 완료되고
  robot 하나의 실패가 다른 robot의 상태를 거짓 완료로 만들지 않는다.
- 동일 seed/profile 반복에서 주요 결과가 허용 범위 안에 있고 run별 world/map
  ID가 남는다.
- aarch64 robot artifact에는 Gazebo가 포함되지 않는다.

목표이자 최종 gate는 `ROS-SIM`; ARTIFACT/DEVICE/FIELD는 N/A다.

#### `fleet`

역할은 site PC의 formation, relay, SiteHub와 Fleet console이다. ROS를 import하지
않고 robot CORE 계약만 사용한다.

**동작 GO 기준**

- `robots.yaml`의 N대 identity/URL/token으로 상태를 모으고 robot별 goal/cancel과
  전체 e-stop을 올바른 대상 CORE에 전달한다.
- formation geometry와 slot assignment가 deterministic하고, arming 거절은
  실행 중 relay/session을 변경하지 않는다.
- relay는 leader pose frame을 byte-for-byte 전달하며 유실 frame을 반복하지
  않는다. stale/sequence gap/robot loss는 FOR-004 HOLD/ABORT로 전환된다.
- console의 접수 표시와 robot의 실제 결과가 구분되고, 일부 robot의 timeout이
  전체 성공으로 합쳐지지 않는다.
- UI/Hub/relay 어디에서도 ROS/DDS, `cmd_vel`, Image/twist scatter를 사용하지
  않는다.

목표 gate는 2대 이상 현재-tree `ROS-SIM`; 실제 여러 로봇과 site network에서
반복한 결과가 FIELD다.

## 7. 운영 지원 모듈

#### `deploy`

**동작 GO 기준**

- native ARM64 builder가 source revision과 locked input에서 core/io artifact를
  만들고 manifest, checksum, signature와 immutable registry digest를 발행한다.
- installer가 identity 없이 진행하지 않고 config/data를 보존하며 처음에는
  core-only 안전 상태로 설치한다.
- updater가 signature, target, downgrade와 digest mismatch를 거절하고 건강
  확인 실패·전원 중단 뒤 마지막 known-good signed manifest가 묶은 호환
  artifact digest들과 config generation의 tuple로 복구한다. artifact만 또는
  config만 따로 되돌린 상태는 복구 성공이 아니다.
- `verify-pi.sh`와 `device-readback.sh --json`이 activation, signature, image,
  identity, health, graph를 같은 release로 연결한다.

목표 gate는 install/update/rollback을 실행한 `DEVICE`; 이미지 빌드 성공만으로는
동작 GO가 아니다.

#### `dock`

**동작 GO 기준**

- ESP32 toolchain에서 firmware를 빌드·플래시하고 `/status` 필수 필드와 robot
  parser가 같은 계약을 사용한다.
- load를 감지하기 전에는 접점을 통전하지 않고 제거·오류 때 즉시 차단한다.
- 충전 판정은 dock current와 robot pack voltage 비하강을 함께 요구한다.
- staging, acquire, approach, settle, charge, undock, retry와 cancel을 실제
  costmap·센서와 실행하고 실패 시 collision exemption을 해제한다.
- 반복 접근 성공률, 접촉 저항/온도, 재시도와 전원 복구를 물리 bench에서
  측정한다.

목표 gate는 물리 dock `DEVICE`; 대표 바닥·정렬 조건의 반복 결과는 FIELD다.

#### `docs`

**동작 GO 기준**

- SRS/API/ADR/기준 문서 링크와 requirement ID가 유효하고 상호 모순이 없다.
- 각 harness 모듈이 자기 소유 기능 시험과 `progress.md`를 갖고 생성
  `index.md`/`STATUS.md`가 최신이다.
- `python tools/harness/rosy_harness.py lint`와 문서 계약 시험이 현재 tree에서
  통과한다.

목표 gate는 `LOCAL`; ROS-SIM/ARTIFACT/DEVICE/FIELD는 N/A다. 문서 GO는 제품
runtime GO를 승격하지 않는다.

## 8. M01–M14 추적표

이 표는 주 책임 실행 모듈을 찾기 위한 것이다. 나열되었다는 사실은 구현 완료나
GO를 뜻하지 않는다.

| 논리 모듈 | 주 실행 모듈 | 논리 모듈을 닫는 최종 관측 |
|---|---|---|
| M01 호스트·식별·전원 | `deploy`, `core_common`, `core_features`, `bringup`, `sensor_adc` | 반복 부팅, identity 보존, 전원/저전압 상태, 안전 복구 |
| M02 하드웨어 어댑터 | `bringup`, `interfaces`, `led`, `emotion`, `imu_bno055`, `sensor_adc`, `lamp_control`, `omx_adapter` | 실제 장치 식별·I/O·단절·재접속과 명시 오류 |
| M03 ROS 실행환경 | `core`, `navigation`, `description`, `gz_sim`, `deploy` | 현재 tree graph, lifecycle, namespace, DDS와 기능 freshness |
| M04 API·인증·capability | `core_common`, `core_api_web`, `core` | 역할별 allow/deny, schema, 정확한 capability, 명령 결과 |
| M05 영상·OpenCV·추론 | `control` | camera-only profile은 inference를 N/A로 선언하고 광고하지 않는다. 추론을 켜면 실제 camera freshness/지연/품질·stale 차단과 함께 승인된 model hash, ground-truth 품질, p95 latency, uncertainty 거절 record를 요구 |
| M06 보정·좌표·공간 | `control`, `description`, `navigation`, `imu_bno055`, `omx_adapter` | calibration/map/TF/hand-eye revision과 실측 위치 오차 |
| M07 베이스 이동 | `core_features`, `core`, `navigation`, `bringup`, `control`, `fleet` | 목표→주행→실제 정지 또는 명시 실패, 안전 복구 |
| M08 암·그리퍼 | `omx_adapter`, `interfaces` 및 향후 manipulation slice | 실물 trajectory/grasp feedback, payload, collision, recovery. 현재 profile 경계만으로는 미완료 |
| M09 작업 실행 앱 | 향후 Fleet workflow/manipulation mission; 현재 `core_features`의 원자 기능만 존재 | 이동→정지→재인식→집기→확인→배치의 durable 상태·취소·재시작. 현재 미완료 |
| M10 배치·적층 앱 | 구현 모듈 없음 | 지지·무게중심·접근·후퇴를 만족하는 계획과 실물 배치 결과. 현재 미완료 |
| M11 안전·명령 소유권 | `core_features`, `core`, `control`, `bringup`, `fleet`, `dock` | 동시 명령·통신 단절·e-stop·재기동에서 단일 권한과 측정 정지 |
| M12 웹 운영·정비 | `core_api_web`, `fleet`, `games`, `emotion` | 실제 브라우저/화면 권한, 연결 상실, 접수·완료 구분, 복구 안내 |
| M13 진단·증거 | `core_events`, `core_features`, `core_api_web`, `deploy` | 사건·명령·관측·artifact를 run ID로 추적하고 secret 없이 보존 |
| M14 릴리스·복구 | `deploy`와 변경 영향 모듈 owner | signed release 설치, 건강 확인, 실패·전원 중단 rollback. deploy owner가 release/readback을, 영향 모듈 owner가 같은 artifact의 기능 smoke를 승인하며 hardware/업무가 바뀌면 FIELD를 다시 인수 |

`docs`는 M01–M14 제품 기능을 구현하지 않는 governance 모듈이므로 표에 매핑하지
않는다. M08–M10은 표에 owner 후보가 있어도 현재 완료된 것으로 판정하지 않는다.

## 9. 실행 순서

새 모듈 또는 변경 모듈은 다음 순서로 승격한다.

1. 소유권, API, topic/service/action, fail-closed 상태와 목표 gate를 정한다.
2. 모듈 자체 기능 시험으로 SOURCE와 LOCAL을 닫는다
   ([D-73](ROSY%20ADR%20Log.md)).
3. Linux/ROS 2 Jazzy에서 clean colcon build 후 현재 tree의 ROS-SIM 시나리오를
   실행한다. 과거 install overlay를 재사용하지 않는다.
4. robot 배포 대상이면 native ARM64에서 서명·immutable artifact를 만든다.
5. Pi를 core-only로 설치하고 stationary graph/readback을 보존한다.
6. hardware power를 켜기 전에 probe, sensor freshness, publisher 수를 확인한다.
7. 모터는 lifted-wheel, 그 뒤 floor course 순서로 진행한다. 카메라, dock, OMX,
   payload는 각 모듈의 별도 DEVICE 기준을 닫은 뒤 결합한다.
8. 대표 환경에서 반복 FIELD 시나리오와 rollback을 수행한다.
9. 증거를 모듈 `logs.md`에 연결하고 `progress.md` gate를 갱신한 뒤 harness를
   생성·검증한다.

## 10. 기준 실행 명령

호스트 기능 표면:

```powershell
python tools/harness/run_functional.py
python -m pytest test/test_module_functional_surface.py test/test_harness_contracts.py -q
python tools/harness/rosy_harness.py lint
```

ROS 2 Jazzy 환경:

```bash
cd src
colcon build --symlink-install --event-handlers console_direct+
source install/setup.bash
colcon test --event-handlers console_direct+
```

Device 공통 readback:

```bash
sudo /opt/rosy/deploy/robot/verify-pi.sh
sudo /opt/rosy/deploy/robot/device-readback.sh --json
```

이 명령들은 공통 시작점이다. 각 모듈의 정상·장애·복구 시나리오와 물리 측정이
빠지면 해당 목표 gate는 GO가 아니다.

## 11. 변경 규칙

- 새 실행 모듈은 merge 전에 이 문서에 역할, 목표 gate, 관측 결과, 대표 장애를
  추가하고 harness `functional` 표면을 가져야 한다.
- 입력/출력이나 안전 소유권이 바뀌면 API Reference, schema, ADR, 이 기준과
  관련 시험을 같은 변경 단위로 갱신한다.
- 허용 오차와 현장 조건은 profile 또는 시험 기록에 수치로 둔다. 이 문서에
  특정 장치의 임시 측정값을 영구 기본값으로 박지 않는다.
- 이 기준을 만족하지 못하는 기능은 capability에서 숨기거나 명시적으로
  unavailable/HOLD로 광고한다. 데모 성공으로 승격하지 않는다.
- 현재 tree 재실행만 GO로 인정한다([D-79](ROSY%20ADR%20Log.md)). Fleet의
  formation 전체 HOLD/ABORT는 [FOR-004](../spec/ROSY%20FLEET%20SRS.md)의
  상태·증거 계약을 함께 따른다.

## 관련 문서

- [ROSY CORE SRS](../spec/ROSY%20CORE%20SRS.md)
- [ROSY FLEET SRS](../spec/ROSY%20FLEET%20SRS.md)
- [ROSY API & Protocol Reference](ROSY%20API%20%26%20Protocol%20Reference.md)
- [ROSY ADR Log](ROSY%20ADR%20Log.md)
- [모듈 평가·유지보수 설계](../plans/2026-09-12-rosy-os-module-evaluation-maintenance-design.md)
- [Device 검증 통합 구현 계획](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md)
- [Pi 5 인수 체크리스트](../deployment/pi5-acceptance-checklist.md)
