## D-310 제품 전용 소스와 장치 로컬 실행 소스를 구분한다

**Status:** Proposed (2026-09-27, 소스 배치 목표). 이 문서만으로 D-231·D-305의 Accepted 위치 규칙을 변경하거나 폴더 이동, OMX 운영, 제품별 이미지, 장치 수용을 승인하지 않는다. [이행 계획](../plans/2026-09-27-product-source-layout-migration.md)의 기준선과 검증을 확인한 뒤 상태를 다시 판정한다.

**Context:** 현 `src/devices/pinky_pro`에는 Pinky 전용 bringup·ADC·조명이, `src/products/pinky_pro`에는 설정 ROS 패키지가 따로 있다. OMX도 `devices/omx/adapter`와 `products/omx`에 나뉜다. `devices`와 별도 `device_control`을 병렬로 만들면 같은 제품이 두 곳에 반복된다. 반대로 `core`·`core_features`·`navigation`·`control`을 통째로 Pinky 아래에 넣으면 프로필 기반 실행, 현장 지도·시뮬레이션, 관측·레거시 writer까지 Pinky 전용 제어기라고 오인시킨다. `core_common`은 CORE뿐 아니라 Fleet·Overhead가 사용한다. D-303은 이 혼합과 이미지 경로를 무시한 일괄 제품 이동을 기각했다.

**판정 기준:** 소스 폴더는 현재 코드의 변경 이유와 소비 경계를 나타낸다. 최종 명령 권한은 실행 인스턴스와 단일 writer 시험으로, 설치 단위는 이미지 package closure·설치 readback으로 따로 판정한다. 이름이 같아도 `products/pinky_pro`는 제품 소스·구성이고 `robot_id`는 물리 장치 인스턴스다. 한 호스트의 Pinky+OMX는 제품 참조 둘과 최종 명령 owner 둘을 유지한다.

**제안 목표:**

```text
src/
├─ products/
│  ├─ pinky_pro/
│  │  ├─ profile/         # 현 ROS package pinky_pro
│  │  ├─ bringup/         # 현 ROS package bringup
│  │  ├─ adc/             # 현 ROS package sensor_adc
│  │  ├─ lamp/            # 현 ROS package lamp_control
│  │  └─ led/             # 현 ROS package led
│  └─ omx/
│     ├─ profile/         # 현 ROS package omx
│     └─ adapter/         # 현 ROS package omx_adapter; 운영 owner 후보/HOLD
├─ runtime/{gateway,services,events,api_web,navigation,sensing}/
├─ drivers/imu_bno055/    # 제품 독립 칩 드라이버
├─ contracts/{foundation,interfaces}/
├─ site/{fleet,overhead,games}/
├─ hmi/{dashboard,face,web}/
└─ sim/{description,gz_sim}/
```

1. **`products/<모델>`은 제품 전용 코드와 구성의 자리다.** 기존 설정 패키지는 각 `profile/`에 놓는다. 부모 `products/pinky_pro`와 `products/omx` 자체를 ROS 패키지로 남겨 하위 ROS 패키지를 중첩하지 않는다. Pinky 보드 패키지 넷과 OMX adapter 하나만 기존 패키지 이름·import·ROS 실행 이름을 보존하며 옮기는 후보로 둔다. `omx_adapter`의 위치는 제품 귀속을 나타낼 뿐 운영 가능한 팔 owner나 드라이버 선정의 증거가 아니다.
2. **`runtime/`은 현재 로컬 실행 코드의 자리다.** `gateway(core)`는 Pinky 배포에서 단일 최종 `cmd_vel` 경계지만 `robot.model`로 프로필을 선택한다. `services(core_features)`, `events(core_events)`, `api_web(core_api_web)`, `navigation`, `sensing(control)`을 이번 소스 이동에서 통째로 제품 아래로 옮기지 않는다. 이들을 모든 장치에 재사용 가능한 공용 엔진이라고 승인하는 뜻도 아니다. `navigation`의 Pinky bringup 의존·현장 지도·Gazebo 자산, `control`의 관측·레거시 명령 경로는 내부 분할 후보로 기록한다.
3. **`drivers/`는 제품 독립 칩 구현에 한정한다.** 현재 `devices/common/imu_bno055`의 독립 드라이버를 옮기는 후보로 둔다. 다른 제품에 실제로 설치됐다는 주장은 하지 않는다. `description`·로봇 얼굴·영상·사이트 지도는 설치/소비자 감사 없이 제품 아래로 옮기지 않는다.
4. **제품별 로컬 연결은 실제 코드가 생길 때만 연다.** Pinky 센서·주변장치 결합이 CORE의 port/adapter 경계로 분리되면 `products/pinky_pro/runtime_adapter/`를 후속 목표로 검토한다. 이 자리는 현재 존재하지 않으며 이번 소스 이동에서 빈 골격이나 새 ROS 패키지를 만들지 않는다. 새 adapter는 최종 `cmd_vel` publisher가 0개여야 하고 CORE의 단일 프로세스·최종 writer는 유지한다. `core`가 직접 새 패키지를 import하거나 설치 경로가 바뀌면 SOURCE/ROS-SIM뿐 아니라 이미지 closure와 실제 장치 동작을 별도로 검증한다.
5. **공유 계약과 사이트 책임을 제품 폴더로 끌어오지 않는다.** `core_common`의 wire 값, 사이트 값, `intent`·`succession` 실행 규칙은 D-305의 생산자·소비자 감사를 따른다. Fleet Mission/Step 원장, Overhead 관측, HMI·영상 표시는 각각 현 소유 경계에 둔다. OMX의 고정형·탑재형은 같은 소스를 재사용하되 인스턴스·프로필·설치로 구분한다. 드론은 비행 스택과 최종 actuator authority 확인 전 폴더나 공통 action API를 예약하지 않는다.

**이행과 기존 결정:** 이 Proposed 문서는 D-231의 층별 현 위치 및 `products=config only`와 D-305 결정 5의 현 위치 유지보다 우선하지 않는다. 목표를 Accepted로 올릴 때에는 D-231의 `products/`·`devices/` 위치와 설정 전용 조항, D-305의 해당 소스 위치 유보 조항을 **범위를 적어 부분 대체**한다. D-231의 패키지명 유지, 한 경로 묶음의 경로 참조 갱신과 host pytest·harness·colcon·이미지 빌드, D-305의 장치/아티팩트 독립 게이트는 유지한다. D-303의 `core_common`·화면·IMU 일괄 Pinky 이동 및 `deploy/robot` 개명은 되살리지 않는다.

**검증:** 이동 전후 `colcon list --base-paths src`의 패키지 이름 집합, CORE/IO/native 이미지의 선택·설치 패키지와 import 경로, `core` 단일 최종 publisher, 외부 JSON/API 의미를 비교한다. `deploy/robot/Dockerfile`의 CORE 빌드는 이동 후 `products/pinky_pro` 전체 대신 `profile`만 복사해야 한다. IO 이미지와 native payload의 `omx_adapter` 포함 이유·필수 목록은 소스 폴더 이동과 별도로 감사한다. 기존 패키지 집합/서비스/설치 경로가 달라지면 단순 소스 이동으로 완료 처리하지 않는다. 서명·digest·대상 설치/readback은 실제 산출물 변경의 별도 게이트다.

**Alternatives:** `device_control/<제품>`과 `devices/<제품>`의 병렬 루트는 같은 제품 구현을 중복 분류한다. CORE·지원 코드 전체를 `controllers/pinky_pro` 또는 `devices/pinky_pro/control`로 옮기면 프로필 기반 실행과 공유 소비를 제품 전용으로 오인시킨다. `runtime/mobile_base` 일괄 이동은 `navigation`의 Pinky 의존과 사이트·시뮬레이션 자산 혼합을 해결하지 않는다. 현 트리만 유지하면 제품 전용 패키지와 제품 프로필이 갈라진 상태가 남는다.

**References:** [D-18](D-18-rosy-core.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-231](D-231-layered-source-roots-keep-package-names.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-303](D-303-controller-owned-source-layout.md), [D-305](D-305-platform-boundary-outcome-invariants-and-independent-gates.md), [D-308](D-308-intent-and-device-action-interpretation-boundary.md), [이행 계획](../plans/2026-09-27-product-source-layout-migration.md).
