# 구조 판정

**Status:** 초안 (2026-09-24). 주인 지도의 결정은 [D-207](../adr/D-207-one-owner-per-product-and-device-kind.md)이다. 그 ADR이 Accepted 되기 전에는 폴더가 `src/AGENTS.md`를 따른다.

**기준:** `docs/plans/2026-09-06-module-split-criteria.md`. 크다는 이유로는 나누지 않는다. 새 모듈은 아래 셋이 모두 성립할 때만 올린다.

- **B1.** 요구 가족이 있고, 기존 `AGENTS.md`가 그 가족을 주장하지 않는다.
- **B2.** 역할이 다른 파일이 둘 이상이거나, 두 번째 파일을 강제하는 요구 ID가 있다. ID를 대지 못하면 B2는 거짓이다.
- **B3.** 서로 다른 패키지 둘이 그 코드를 import 한다.

파일 하나짜리 역할은 모듈로 남는다. 호스트 시험이 못 보는 판단은 ROS 없는 형제로 빼낸다. 그게 C1이다.

## 1. 판정

`core_common.equipment`는 제거했다. 바퀴 매핑의 주인은 `devices/bringup`의 `PinkyProAdapter`다. 신호등의 주인은 `site/fleet`의 `signals.yaml`과 ROSY-SIGNAL-001이다. 램프 핀의 주인은 `devices/lamp_control`이다. 그 파일들을 읽지 않는 목록은 두 번째 주인이고, 생산 코드가 import 하지 않으므로 B3이 성립하지 않는다.

`src/apps`가 어색한 것은 사실이다. `control`은 감지이고 `games`만 응용에 가깝다. 어색함만으로 새 패키지를 만들지는 않는다. `src/robots/pinky_pro`를 강제하는 요구 ID가 없다. 칩 이름을 종류 이름으로 합치는 일과 새 패키지는 1대 readback과 요구 ID가 생기기 전에는 하지 않는다.

ESP 패키지도 만들지 않는다. 버스, 요구 ID, 그 코드를 부를 두 번째 패키지가 없다. B2와 B3이 거짓이다.

## 2. 지금 트리는 이름마다 패키지가 는다

`devices/` 아래 패키지는 장치 종류가 아니라 칩과 브랜드로 갈라져 있다. 같은 종류가 하나 더 생기면 패키지가 하나 더 생긴다.

| 지금 패키지 | 이름에 박힌 것 | 하나 더 생기면 |
|---|---|---|
| `imu_bno055` | BNO055라는 칩 | `imu_<다른칩>` 패키지 |
| `sensor_adc` | 그 ADC 보드 | 다른 ADC 패키지 |
| `lamp_control` | WS2811 스트립 | 다른 램프 패키지 |
| `led` | 그 LED 서비스 | 또 하나의 LED 패키지 |
| `omx_adapter` | OMX라는 브랜드 | 다른 팔마다 어댑터 패키지 |

매니페스트는 이미 종류로 적는다. `bringup/config/adapter.manifest.yaml`은 `device_type: mobile_base`이고 `drive`, `battery`, `lidar`, `local_safety`를 제공한다. `omx_adapter/config/adapter.manifest.yaml`은 `device_type: manipulator`이고 아직 `provides`가 비어 있다. 개념 13은 Pinky와 OMX를 패키지 이동이 아니라 이 매니페스트로 두라고 했고, Pinky 위에 팔을 얹은 복합 자산은 D-55 증거가 나오기 전에는 켜지 말라고 했다. 개념 6은 안전 정지를 칩이 아니라 장치 종류로 나눈다. 모바일 베이스는 멈추고 위치와 감지를 유지한다. 팔은 궤적을 멈추고 관절 한계를 지킨다. 개념 12의 학습 원천은 OMX-AI 하나가 아니다. OMX-L 원격 조작, OMX-F 관절, 그리퍼, Pinky 자세가 따로 있다.

그래서 확장되는 폴더는 브랜드나 칩이 아니다.

```text
src/core/                 공유 런타임. 모드, 안전, cmd_vel 하나, /api/v1, /do
src/devices/              버스와 장치 종류. i2c, uart, gpio, ros2_control 하드웨어 인터페이스
src/products/             매니페스트와 URDF만. pinky_pro(mobile_base), 팔 제품들(manipulator)
src/site/                 관제, 신호등, 현장에 붙는 ESP
learning/                 src 밖. 기록만 읽고 승인된 모델 파일만 돌려 준다
```

`imu_bno055`의 디코더와 고장 주입은 장치 종류 `imu` 아래의 한 구현이다. BNO055가 패키지 이름이 되면 다음 IMU는 형제가 아니라 새 패키지다. `omx_adapter`도 같다. `omx_ai`, `omx_f`, `openmanipulator_x`는 매니퓰레이터의 프로필이다. 다른 회사 팔이 오면 프로필이 늘지, `apps/`에 어댑터 패키지가 늘지 않는다. 팔이 여러 개여도 몸통으로 들어가는 문은 개념 11의 한 줄이다. 원하는 동작, 런타임 검증, `ros2_control`, 구동기. 브랜드 SDK는 그 하드웨어 인터페이스 안에 남는다.

비디오도 같은 규칙이다. `control`의 `road_observer_node`가 `camera/front`를 받아 도로 판단을 하고, 화면용 JPEG만 `camera/preview/compressed`로 낸다. Core는 `core_features.vision.transport`의 `standard_ros_image`로 그 JPEG만 저장한다. `intra_process`, `shared_memory`, `nitros`는 이름이 있으나 이 프로세스에 연결되어 있지 않다. `core`의 `package.xml`에 NITROS가 없다. 인지 사실은 `road/observation`이고, 관제는 이미지를 받지 않는다.

디렉터리는 이 지도의 첫 걸음만 옮겼다. 패키지 이름은 그대로다.

```text
src/devices/     bringup, imu_bno055, sensor_adc, lamp_control, led
src/products/    omx_adapter
src/face/        emotion
src/site/games   노트북 경기
src/core/control 감지. 카메라, 보정, 계획
```

칩 이름을 종류 이름으로 합치는 일과 `learning/` 생성은 아직 하지 않는다. `src/AGENTS.md`가 이 디렉터리를 따른다.

## 3. 학습

학습은 이 대화에서 계속 나온 자리다. 기준에 대면 지금은 패키지가 아니다. 요구 ID가 없고, 몸통이 남기는 기록 파일을 읽는 두 번째 패키지가 없다. B2와 B3이 거짓이다. 그래서 `learning/`을 만들지 않는다. 빈 폴더는 구조를 증명하지 못한다.

기준이 성립한 뒤에 둘 자리는 미리 고정한다. 성립해도 `src/core`나 `src/apps` 안이 아니다. `src/` 안에 두면 colcon이 로봇 이미지에 넣을 수 있다. 자리는 저장소 루트의 `learning/`이고, 로봇 빌드 목록 밖이다.

그때 학습이 하는 일은 셋으로 닫는다.

- 몸통이 쓴 기록만 읽는다. 기록의 후보는 MCAP 에피소드다. 몸통은 파일을 쓰고 학습을 import 하지 않는다.
- 승인된 모델 파일 하나만 몸통이 읽는 자리에 둔다. 로봇이 챔피언을 고르지 않는다.
- Pi에서 학습 프로세스를 켜지 않는다. v0.4의 Learning, Registry, GPU는 이 자리다. Perception과 Safety는 몸통으로 남는다.

이 세 줄은 폴더를 만들라는 허가가 아니다. 나중에 B2의 요구 ID를 쓸 때 몸통 안에 패키지를 만들지 못하게 막는 제약이다.

## 4. 관제와 역할

관제의 주인은 `src/site/fleet`다. 새 관제 패키지를 만들지 않는다.

역할은 장비의 신분이 아니다. `formation_start`의 `leader`는 그 세션의 로봇 ID다. 코드의 말은 leader/follower다. 대형이 이미 있으면 `FORMATION_ACTIVE`로 거절한다. 리더만 조용히 바꾸면 이전 팔로워가 무장된 채로 남기 때문이다.

죽는 장비마다 하는 일은 그 거절과 같은 절차다. 리더가 죽으면 관제 스냅샷이 대형을 풀고 `next_leader`로 다시 연다. 팔로워도 같은 함수로 한 명을 고른 뒤 끊긴 참조는 따라가지 않는다. 팔로워끼리 다른 리더를 뽑지는 않는다. 대기 관제가 죽은 세션을 이어 받는 일은 여전히 없다.

| 죽은 것 | 관제가 할 일 |
|---|---|
| 팔로워 | 그 멤버만 뺀다. 리더는 유지한다 |
| 리더 | 대형을 푼다. `FOLLOW`를 취소한다. `robots.yaml` 순서 가운데 심박이 살아 있는 다음 로봇으로 다시 `formation_start` 한다. 그 순서는 후보지 신분이 아니다 |
| 관제 PC | 로봇이 새 리더를 뽑지 않는다. 몸통과 얼굴은 산다. 끊긴 참조는 따라가지 않고 선다. 대기 관제가 있어도 죽은 세션을 이어 받지 않고, `HELLO`를 본 뒤 새 `formation_start`로만 연다 |

`source: peer`는 흩뿌리지 않는다. 서버가 없을 때의 임시 리더 임대는, 서버가 돌아오면 내려놓고 리더가 둘인 시간이 없다는 제약이 문서에 생기기 전에는 만들지 않는다.

신호등은 로봇 첨부가 아니다. fleet의 신호 계약이다. ESP는 그 계약의 버스가 측정되기 전에는 패키지가 아니다.

## 5. 지금 하지 않는 것

- 실행되지 않는 장비 목록을 다시 만든다.
- `src/robots/`, `learning/`, ESP 패키지를 만든다.
- 칩 패키지를 종류 폴더로 합친다.
- 리더가 죽었을 때 팔로워가 서로 다른 리더를 뽑는다. 고르는 함수는 하나다.
- 학습을 `core`의 의존성에 넣거나 Pi에서 학습 프로세스를 켠다.
- 미들웨어가 카메라 원본, 바퀴 속도, 관절 스트림을 중계한다.
