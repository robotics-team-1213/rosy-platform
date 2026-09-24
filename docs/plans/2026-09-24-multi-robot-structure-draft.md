# 다기종 로봇 구조 재편 — ADR 초안 (번호 미배정)

**Status:** Draft (2026-09-24). 사용자와 rosy-25 세션이 합의한 방향이다. 아직 ADR이 아니다.

**번호:** 이 ADR은 **D-196**이 될 예정이다. 로컬 `main`에만 있는 D-187(브라우저 조작 부품)과
D-188(치수·진단 팔레트)이 origin/main의 D-187·D-188(SD writer)과 번호가 겹친다. 두 건은 아직 push하지
않았으므로, 동기화(P0) 때 로컬 두 건을 D-194·D-195로 다시 매긴다. 그 뒤에 이 초안을 `docs/adr/`로 옮긴다.

**재평가 (2026-09-24, origin/main `208752ae` 기준):** 방향은 유지한다. 아래 표의 발견을 반영해 3절,
2절 2항, 진행 순서를 고쳤다.

| 발견 | 반영 |
|---|---|
| `fix/device-boot-runtime`이 origin에 머지되었다(PR #24) | 이동 선행 조건을 해제한다 |
| D-192 §4: 0x08을 읽는 코드는 모두 `flock`을 잡는다. 읽는 코드는 `rosylib.Battery`(hardware), `ir_adc_node`(apps), `sensor_adc`(벤치 전용)이다 | ADC를 읽는 코드를 모두 `devices/pinky_pro`로 모은다. `sensor_adc` 통합안은 철회한다(D-192가 벤치 전용과 동시 실행 금지를 이미 정했다) |
| US-010: `withhold_hardware_flags`가 CORE-only 모드에서 하드웨어 capability를 보류한다 | drive 게이팅은 두 층으로 둔다. 정적 층 = Profile v2의 장치 조합, 런타임 층 = US-010 보류(기존 코드 유지) |
| bringup에 `drive_enabled`(무동작 모드)와 `rosylib`이 들어왔다 | 둘 다 `devices/pinky_pro`로 옮긴다 |
| `apps/emotion/rosy_lcd.py`는 Pinky SPI LCD 드라이버다. D-190 부팅 표시가 이 LCD를 쓴다 | LCD 드라이버는 `devices/pinky_pro`로 옮기고, 감정·화면 로직은 `apps/emotion`에 남긴다(3절) |
| control 분할 설계 §3(D-171 트랙 3)이 `ir_adc_node`와 카메라 캡처를 `control_sensing`에 둔다 | 이 설계의 P4를 D-171 트랙 3과 합친다. `control_sensing`에는 알고리즘만 남긴다 |
| D-191: 이미지는 실기 평가표를 모두 통과해야 배포한다 | 이동(P3)은 이미지 릴리스 사이에 한다. 이동 뒤 첫 이미지는 평가표를 다시 통과해야 한다 |

**대체/보완:** D-147 §1·§2의 일부를 대체한다(장치 계열 이름 허용, 도메인 재편). D-168 P4 방향표에
행을 추가한다. D-11/HWA-003, D-57, D-44, D-163, D-169는 유지하고 확장한다. D-186(스크립트·수집 폴더)과는
범위가 겹치지 않는다. 다만 D-186의 `test/test_folder_layout.py`가 아래 적합성 시험을 담을 자리다.

---

## Context

Rosy OS는 Pinky Pro 전용이 아니다. 다음 세 형태를 같은 CORE API로 돌려야 한다.

- OMX를 Pinky 위에 얹은 형태(모바일 매니퓰레이터)
- 책상에 고정한 **단독 OMX**
- **다른 주행 베이스**(TurtleBot3, 메카넘 등)

지금의 `src/` 구조는 역할 기준 6개 도메인이다(D-147). 이 방향 자체는 맞다. 그런데 **"로봇"이라는
축이 없다.** 그래서 Pinky 지식이 6개 도메인 전체에 이름 없이 흩어져 있다.

| 위치 | Pinky에 묶인 부분 |
|---|---|
| `src/core/core/config/` | `profile.pinky_pro.yaml`이 core 안에 있다. `core/node.py:52`가 이 파일을 기본값으로 하드코딩한다 |
| `src/hardware/bringup` | 이름은 일반적인 bringup이지만 내용은 `PinkyProAdapter` 하나다 |
| `src/sim/description` | URDF가 Pinky 하나뿐이다. 그런데 sim 도메인에 있으면서 실기도 이걸 쓴다 |
| `src/navigation/.../nav2_params.yaml` | robot_radius와 inflation 값이 Pinky 풋프린트에 맞춰져 있다 |
| `src/apps/control/config/robot.yaml` | 파일이 스스로 "모든 Pinky 노드의 단일 원천"이라고 선언한다. sensing 코드 15개 파일 이상이 Pinky 기하 값을 쓴다 |
| `src/site/fleet/server/bays.py`, `traffic.py` | Pinky 외접 반지름이 상수로 박혀 있다 |
| `src/apps/omx_adapter` | **도메인이 틀렸다.** 하는 일은 장치 어댑터인데 apps에 있다 |
| `src/apps/control/control/camera_detect_node.py` | 앱 노드가 `Picamera2()`와 `cv2.VideoCapture`를 직접 열어 캡처하고, 같은 노드에서 검출까지 한다 |
| `deploy/` | `install-pinky-hardware-deps.sh`, `commission-pinky.py` |

HWA-001 Robot Profile은 D-11에 따라 capability의 원천이다. 그런데 실제로는 core 안의 yaml일 뿐이고
다른 패키지는 이 파일을 읽지 않는다. 그래서 두 번째 로봇을 붙이려면 6개 도메인 전부에 분기를 넣어야 한다.

## Decision

### 1. 도메인 재편 — `hardware/` → `devices/<계열>/`, 신규 `robots/`

```text
src/
  core/        로봇 무관. Profile 로더와 capability 파생만 소유한다
  apps/        로직만 둔다. 기하·한계 값은 선택된 로봇 프로필과 TF에서 읽는다
  devices/     재사용 가능한 장치. 종류가 아니라 계열로 묶는다
    pinky_pro/   base(현 bringup), description, adc, lamp, led — 보드에 딸린 것 일체
    omx/         adapter(apps/omx_adapter에서 이동), description, controllers, moveit_config
    common/      camera(아래 4절), imu_bno055 등 보드와 무관한 장치
  robots/      장치 조합. 코드 없이 설정·URDF 조립·launch만 둔다
    pinky_pro/  pinky_pro_omx/  omx_desk/
  navigation/  공통 launch와 기본값만 둔다. footprint·inflation은 robots/ 오버레이로 준다
  sim/         gz_sim(world·벤치)만 둔다. `robot:=` 인자로 로봇을 고른다. description은 장치별로 해체한다
  site/        fleet. 풋프린트는 로봇별 프로필에서 받는다
```

- **계열로 묶는 이유.** Pinky의 adc·lamp·led는 Pinky 보드에 딸린 부품이라 따로 떼면 의미가 없다.
  장치 종류(base/arm/sensor)는 manifest의 `device_type`이 이미 표현한다(concept 04 §3).
- **패키지 이름.** `devices/<계열>/` 안에서는 계열 접두(`pinky_pro_base`, `omx_adapter` 등)를 허용한다.
  이 점이 D-147 §2의 `pinky_*` 금지를 대체하는 부분이다. 그 밖의 도메인에서는 금지를 유지한다.
- **D-168 P4 추가 행.**

  | 출발 | 허용 대상 |
  |---|---|
  | `devices` | core 계약, 같은 계열 안, `devices/common` |
  | `robots` | core 계약, `devices` (조립 층) |
  | `navigation` | core 계약, `devices` (기존 `hardware` 행을 개명) |

  `sim`은 기존대로 모든 도메인을 쓸 수 있다.

### 2. 계약을 먼저 정한다

1. **베이스 경계는 `ros2_control`이다.** 베이스마다 hardware_interface 플러그인과 controller yaml
   (diff_drive, mecanum 등)을 둔다. 모든 베이스가 `cmd_vel`을 받아 `odom`과 TF를 낸다. 이것이 D-57이
   정한 방향이다. Pinky의 Python 드라이버는 **재편 뒤에** 교체한다. 그 전에 베이스 계약은 TurtleBot3
   sim으로 먼저 증명한다.
2. **core의 drive 전제를 capability로 게이팅한다.** "최종 `cmd_vel`의 유일한 발행자는 core"라는 규칙을
   "drive capability가 있을 때만"으로 좁힌다. 단독 OMX에는 `cmd_vel`이 없다. 게이팅은 두 층이다.
   정적 층은 Profile v2의 장치 조합이다(베이스가 없으면 drive capability가 false). 런타임 층은 US-010의
   `withhold_hardware_flags`이며 기존 코드를 그대로 쓴다.
3. **팔 명령 경로는 core가 MoveIt 액션을 대행하는 방식이다.** 안전을 우선한다. D-44의 interlock
   ("팔이 동작하는 동안 베이스 정지 확인")을 core의 중재가 소유한다. 팔 쪽이 직접 실행하고 core는
   허가 토큰만 주는 안은 기각했다.
4. **Robot Profile v2는 장치 조합이다.**
   ```yaml
   robot: pinky_pro_omx
   base: { device: pinky_pro }            # 단독 팔이면 base: null
   arms: [{ device: omx, mount: { parent: base_link, xyz: [0, 0, 0.1], rpy: [0, 0, 0] } }]
   cameras: [{ device: pi_camera, role: front_floor, mount: { parent: base_link, ... } }]
   sensors: [{ device: imu_bno055 }]
   ```
   capability(D-11), URDF, nav2 footprint, fleet 반지름, control 기하를 모두 이 파일에서 파생한다.
   로봇은 launch 인자 `robot:=<name>`(환경 변수 `ROSY_ROBOT`) 하나로 고른다.
5. **URDF는 조합으로 만든다.** 장치 패키지마다 자기 xacro 매크로를 가진다. `robots/<robot>`이 이
   매크로를 include해서 조립한다.

### 3. apps/control의 Pinky 센싱 코드 배치 규칙

> **로봇을 바꿨을 때 코드가 바뀌어야 하면 `devices`에 둔다. 숫자만 바뀌면 `apps`에 두고 값은
> 프로필/TF에서 읽는다.**

| 파일 | 배치 |
|---|---|
| `ir_adc_node.py`, `sensing/ir_adc.py` | `devices/pinky_pro`로 옮긴다. `/dev/i2c-1`을 ioctl로 직접 읽는 코드다. 이동하면 0x08을 읽는 코드(`rosylib.Battery`, `sensor_adc`)가 모두 한 계열에 모인다. D-192 §4의 `flock` 계약과 `test_adc_ownership`·`test_ir_source_exclusivity`는 그대로 둔다. D-169 장치 표면 시험의 경로도 함께 고친다 |
| `apps/emotion/emotion/rosy_lcd.py` | `devices/pinky_pro`로 옮긴다(SPI LCD 드라이버). GIF와 `info_screen` 같은 화면 로직은 `apps/emotion`에 남는다. D-190 부팅 표시 경로도 함께 고친다 |
| `sensing/camera_controls.py`와 `camera_detect_node.py`의 캡처부 | `devices/common/camera`로 옮긴다(4절) |
| `sensing/camera_ground.py` | apps에 남긴다. 카메라 외부 파라미터는 TF/프로필에서 읽는다 |
| `sensing/lidar.py` | apps에 남긴다. `lidar_yaw_offset`은 TF로 바꾼다. `pinky/` 프레임 판별은 sim 픽스처로 옮긴다 |
| `road.py`, `line_observer_node.py`, `road_observer_node.py` | apps에 남긴다. 소스 이름 `'PINKY'`는 중립 이름(예: `onboard_camera`)으로 바꾼다 |
| `safety/node.py` | apps에 남긴다. 외곽 치수는 프로필로 뺀다. `GZ_PARTITION == 'pinky_calmap227'` 분기는 삭제한다(D-182 위반) |
| `sensing/body.py` | 상수를 삭제한다. 값은 URDF/프로필에서 파생한다 |

### 4. 카메라는 로봇에서 독립된 공용 장치다

카메라는 Pinky, OMX AI, 그 밖의 장비에 붙는다. 그래서 **공용 부분은 코드로 공유하고, 장비마다 다른
부분은 설정이나 백엔드 플러그인 하나로만 표현한다.**

| 층 | 위치 | 책임 |
|---|---|---|
| 공용 드라이버 | `devices/common/camera` | 물리 카메라 1대당 캡처 노드 1개. `Image`와 `CameraInfo`를 표준 토픽 `camera/<role>/…`으로 발행한다. "AE/AWB가 안정되면 고정"하는 로직(현 `camera_controls`의 lock 로직)도 여기서 공유한다 |
| 백엔드 | 공용 백엔드(picamera2, v4l2/USB)는 `common/camera` 안에 둔다. 특정 장비에만 필요한 SDK가 있을 때만 `devices/<계열>/`에 플러그인으로 둔다 | 제어 읽기/쓰기와 프레임 획득 |
| 장착 | `robots/<robot>` | 카메라 선택, 역할(`front_floor`, `wrist` 등), TF, 캘리브레이션 파일 |
| 인식 | `apps/` | 역할 이름으로 이미지를 구독만 한다. 캡처 코드는 두지 않는다 |

D-163의 "프레임 소스 추상화(cv/file/picamera2)"와 "카메라 역할 분리"를 제품 카메라로 넓힌 것이다.
인식을 나중에 학습 모델로 바꿀 수 있게 하자는 방침(출력 계약 고정, 백엔드 교체 가능)과도 모양이 같다.
**Pi CPU(D-185)에 대한 대응:** 캡처 노드와 인식 노드를 ROS component로 만들어 같은 컨테이너에 올리고
intra-process 통신을 쓴다. 효과는 Pi에서 측정하기 전까지 가정이다.

## Alternatives

- **역할별 구조 유지 + `robots/`만 추가(최소 재편).** 변경 비용은 가장 작다. 하지만 OMX 단독과 다른
  베이스가 확정된 지금은 `hardware/`가 로봇별 장치를 담는 그릇 역할을 못 한다. 사용자가 전면 재편을
  택했다.
- **`devices/` 종류별 구분(bases/arms/sensors).** 역할은 잘 보인다. 하지만 Pinky 보드에 딸린 부품이
  흩어진다. 기각했다.
- **로봇별 최상위 폴더(`pinky/`, `omx/`).** OMX가 Pinky 위에 올라가는 조합을 표현하지 못한다. 기각했다.
- **camera_controls를 apps에 둔다.** 캡처 조건과 인식의 결합은 유지된다. 하지만 OMX AI 같은 다른
  장비에서 재사용할 수 없다. 기각했다.

## Consequences

- 도메인 이동이 크다. 여러 에이전트가 같은 트리에서 동시에 작업하므로, 이동은 단계 2에서
  **도메인당 1커밋**으로 하고 동작 변경을 섞지 않는다.
- D-169 장치 표면 시험, harness.yaml 모듈 경로, CI 경로, deploy의 이미지 입력(`required-ros-packages.txt`,
  `resolve-required-source-paths.py`), 각 AGENTS.md가 이동과 같은 변경에서 함께 바뀐다.
- origin/main의 D-192는 카메라를 **BLOCKED**로 두었다(센서 미열거). 4절의 공용 카메라 드라이버는 그
  결론을 바꾸지 않는다. 드라이버 구조만 정하고, 실기 활성화는 D-192/D-181 조건을 따른다.

## 진행 순서

P0–P3은 동작을 바꾸지 않으므로 바로 진행한다. P4는 D-171 트랙 3(control 분할)과 합쳐 한 번에 한다.
control 파일을 두 번 흔들지 않기 위해서다(사용자 결정, 2026-09-24).

| 단계 | 내용 | 완료 판정 |
|---|---|---|
| **P0 동기화** | origin/main을 로컬 `main`에 머지한다. 로컬 D-187·D-188 → D-194·D-195로 다시 매긴다(파일, ADR Log, 참조) | ADR 로그 시험 + host pytest 통과, push |
| **P1 ADR D-196 + 시험** | 이 초안을 `docs/adr/`로 승격한다. `test/test_module_structure.py`에서 `DOMAINS`에 `devices`·`robots`를 넣고, P4 방향표 행을 추가하고, src 안 `pinky` 리터럴을 `KNOWN_*` 집합 동일성으로 묶는다. control 분할 설계 §3도 개정한다 | 새 시험 녹색(현재 상태를 목록으로 인정) |
| **P2 프로필 (이동 없음)** | `robots/pinky_pro`를 만든다. `profile.pinky_pro.yaml`을 core 밖으로 옮기고, `robot:=`/`ROSY_ROBOT` 인자와 정적 capability 층을 추가한다 | core 시험 통과 + 모든 프로필이 capability 생성 |
| **P3 기계적 이동** | 그룹당 1커밋, 패키지 이름 유지: `hardware/{bringup,sensor_adc,lamp_control,led}` → `devices/pinky_pro/`, `hardware/imu_bno055` → `devices/common/`, `apps/omx_adapter` → `devices/omx/`, `sim/description` → `devices/pinky_pro/`(xacro 매크로) + `robots/pinky_pro/`(조립). 패키지 이름 변경은 별도 커밋. 이미지 릴리스 사이에 한다(D-191) | CI + 이미지 입력 시험 + WSL gz 벤치 결과가 이동 전과 같음 |
| **P4 앱에서 장치 코드 분리 + D-171 트랙 3** | 3·4절의 devices 이동(`ir_adc_node`, LCD 드라이버, 카메라 캡처 → `devices/common/camera`)과 control 3분할을 한 계획으로 묶는다. 보류된 `refactor/d171-track1`은 D-172 방식으로 재구현한다 | ADC 소유·IR 배타 시험 통과, `KNOWN_*` 감소 |
| **P5 Pinky 값 걷어내기** | safety, lidar, body, fleet, nav2 오버레이 | `KNOWN_*`가 빔 |
| **P6 sim 검증** | `pinky_pro_omx` → `omx_desk` → TurtleBot3 sim(베이스 계약) | 세 프로필이 같은 CORE API로 기동 |
| **P7 ros2_control** | Pinky 드라이버를 교체하고 실기 재검증(D-57 Validation) | 엔코더 부호·오도메트리·한계·deadman·torque-off·재시작 비교 |

## 열린 항목

- 공용 카메라 드라이버의 토픽·파라미터 이름을 `image_transport`/`camera_info_manager` 관례에 맞출지,
  아니면 관례를 그대로 쓸지.
- `robots/`를 ROS 패키지로 둘지(share 경로 해석이 편함), 순수 설정 폴더로 둘지. D-168 P1(a)의
  "별도 배포 단위" 조건은 로봇별 이미지 구성으로 충족한다.
- deploy 이미지를 로봇 프로필 단위로 만들지(`robot:=` 빌드 인자), 한 이미지에서 부팅 시 선택하게 할지.
