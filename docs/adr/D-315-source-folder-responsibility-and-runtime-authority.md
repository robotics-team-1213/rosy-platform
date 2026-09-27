## D-315 소스 폴더는 변경 책임을 나타내고 실행 권한을 대신하지 않는다

**Status:** Accepted (2026-09-28, 현재 소스 분류와 새 경로 판정 기준에 한정). 기존 ROS 패키지명, 장치 writer, 배포 위치, 설치 단위는 바꾸지 않는다.

**Context:** D-310은 Pinky Pro·OMX 전용 패키지를 `products/<model>`로, 제품 독립 IMU 패키지를 `drivers/`로 옮겼다. 뒤이어 실제 트리와 안내 문서를 대조하니 저장소 README는 삭제된 `src/devices/`를 현재 경로처럼 표시하고, `src/site/AGENTS.md`와 `src/hmi/AGENTS.md`는 새 하위 영역을 누락했다. 또 `runtime/sensing`은 ROS 패키지 `control`을 담지만 센서 외에 보정·계획·안전·진단도 포함한다. `products`, `runtime`, 물리 장치, 실행 프로세스와 배포 단위를 같은 개념처럼 읽지 않도록 규칙을 고정한다.

**Decision:**

1. **최상위 소스 폴더는 변경 이유와 코드 소유 영역을 나타낸다.** 현재 `src/`의 분류는 다음과 같다.

   | 폴더 | 현재 책임 |
   |---|---|
   | `contracts/` | `interfaces` ROS 계약과 `core_common` 타입·프로토콜 |
   | `runtime/` | 로봇 런타임 코드: `core`, `core_features`, `core_events`, `core_api_web`, `navigation`, `control` |
   | `products/<model>/` | 모델별 프로필과 제품 전용 패키지·주변장치 연결 |
   | `drivers/` | 특정 제품에 귀속되지 않는 칩 드라이버 소스. 현재 `imu_bno055`가 자리하며 다제품 재사용은 별도 입증 대상 |
   | `site/` | Fleet 사이트 서버, Overhead 관측 서비스, ROS가 없는 Games 호스트 |
   | `hmi/` | 로봇 대시보드 화면, 얼굴 LCD, 공용 웹 자산 |
   | `sim/` | 로봇 설명·메시, Gazebo 월드와 시뮬레이션 도구 |

2. **`products/<model>`은 명령 권한이나 배포 이미지를 뜻하지 않는다.** Pinky의 최종 주행 명령 소유자는 `runtime/gateway`의 CORE다. `products/omx/adapter`는 OMX 제품에 속한 현재 adapter 소스 위치이며, OMX 팔 운영 owner의 장치 수용을 뜻하지 않는다. 실제 물리 인스턴스는 설정·identity로 구분한다.

3. **`runtime/`은 모든 제품이 공유하는 범용 엔진이라는 주장이 아니다.** 현재 `runtime/gateway`의 ROS 패키지명은 `core`, `runtime/sensing`은 `control`이다. `control`은 센싱·관측 외에 보정, 계획, 안전 로직, 레거시 명령 제안 및 진단 경로를 함께 가진다. ROS 패키지명과 현재 소비자를 보존한다. CORE의 최종 `cmd_vel` 경계와 혼동하지 않으며, `cmd_vel_raw`나 진단 실행은 CORE writer를 대체하지 않는다.

4. **사이트 호스트와 관제 PC, 브라우저 위치는 `site/`와 `hmi/` 경로만으로 정하지 않는다.** Fleet은 사이트 요청과 Mission/Step 원장을 맡는다. Overhead는 원본 영상에서 파생 관측값을 만든다. 로봇 dashboard는 CORE API가 제공하고 사이트 console은 Fleet 서버가 제공한다. 관제 PC는 브라우저 단말일 수 있으며 Fleet/Vision 서비스가 그 PC에서 돈다는 뜻은 아니다. 전방 preview, 천장 카메라 관측, OMX 작업 카메라는 각각의 생산자·전송·신선도 경계를 따른다(D-275).

5. **새 최상위 폴더나 대규모 이동은 실제 경계가 생길 때만 결정한다.** 코드 소유자, ROS/package 이름과 의존, 실행 프로세스, 빌드·시험 단위, 이미지 package closure, 호스트 설치 위치, 기존 경로 소비자를 표로 확인한다. 새 경로가 이들 중 적어도 하나의 검증 가능한 경계를 표현하고 소비자·배포 변경을 감당할 근거가 있어야 한다. `devices/`, `device_control/`, `controllers/<model>` 같은 이름만의 병렬 구조나 빈 골격은 만들지 않는다.

6. **`runtime/sensing`은 현 단계에서 재명명하지 않는다.** 현재 `control` package의 import·launch·도구·시험·배포 참조와 writer 구성을 먼저 대조한다. 추후 내부 책임 분리가 별도 테스트·설치·실행 경계를 만든다는 증거가 생기면 그때 좁은 ADR과 이행 계획으로 디렉터리 재배치 여부를 판단한다. 이름을 바꾸기 위해 ROS 패키지명을 바꾸지 않는다.

7. **무시된 로컬 도구 상태는 소스 구조로 취급하지 않는다.** 이전 경로 아래 남은 `.omc`, `__pycache__`, `.pytest_cache`는 ignore 규칙으로 거르는 도구·캐시 상태다. 이 ADR은 이를 삭제하거나 이동하지 않는다. 추적되는 파일은 `git ls-files`와 현재 package/consumer 목록으로 판정한다.

**Consequences:** 이번 결정은 D-310의 제품별 소스 위치를 변경하지 않고 해석 규칙을 보완한다. 새 device-control root, 제품별 이미지, 새 실행 프로세스, 공통 Action schema, OMX/드론 운영 권한은 승인하지 않는다. 실행 위치·서명·설치·실물 결과는 `deploy/` 및 SOURCE/ARTIFACT/DEVICE/FIELD 게이트에서 별도로 증명한다.

**Validation:** 현재 `package.xml` 위치, `deploy/robot/Dockerfile`, API·화면·사이트 서비스 경로, 변경된 README/AGENTS를 대조했다. 문서 갱신 뒤 harness 색인·lint와 ADR/harness 문서 계약 시험을 실행한다. ROS-SIM·장치 동작은 변경하지 않는다.

**References:** [D-18](D-18-rosy-core.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md), [D-290](D-290-rosy-platform-naming-and-site-intent-boundaries.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-305](D-305-platform-boundary-outcome-invariants-and-independent-gates.md), [D-308](D-308-intent-and-device-action-interpretation-boundary.md), [D-310](D-310-product-specific-source-and-runtime-boundaries.md), [실행 계획](../plans/2026-09-28-source-folder-roles-and-runtime-audit.md).
