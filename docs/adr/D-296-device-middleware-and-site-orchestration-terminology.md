## D-296 장치 미들웨어와 사이트 조정 계층의 이름과 책임을 구분한다

**Status:** Accepted (2026-09-27, 명명과 책임 경계). 이 결정은 OMX 원격 API, 복합 로봇 조정자, 범용 런타임 또는 실물 제어를 구현·수용하지 않는다.

**Context:** CORE SRS는 Pinky CORE를 로봇의 미들웨어라고 부르고, D-167의 미들웨어 목표에는 사이트 계약까지 들어 있다. 목표 구조 문서의 `ROSY Runtime`은 모든 호스트에 같은 실행기를 설치하는 이름처럼 읽힐 수 있다. D-290은 전체 제품을 `ROSY Platform`으로, 현장 미션 원장을 Fleet 한 곳으로 정했다. D-282는 장치별 하드웨어·최종 명령 소유권을 제안했고, 이 논의에서는 Pinky 주행의 최종 명령은 CORE, OMX 팔의 최종 명령은 OMX 로컬 제어기에 유지하기로 했다. 용어가 실행 권한을 흐리지 않도록 범위를 고정한다.

**Decision:**

1. **`ROSY Platform`은 전체 제품이다.** 장치 로컬 실행, 사이트 Fleet, 관측, Console, AI·데이터·배포 등 목표 역할의 우산 이름이다. 이 역할들이 하나의 프로세스, ROS graph, 공통 서버 또는 모든 호스트에 설치되는 패키지라는 뜻은 아니다. `ROSY OS`는 기존 저장소·파일·배포의 이력 이름으로 남긴다(D-290).
2. **`장치 미들웨어`는 장치 로컬의 계약·제어 경계다.** 외부 요청을 장치가 검증·수용 가능한 로컬 작업으로 바꾸고, 관측한 상태·capability·수락·실행 결과를 계약으로 돌려준다. 장치 identity와 현재 설정, 요청의 권한·한계·모드, 상태 신선도, 단일 최종 명령 소유권, 연결 상실·재시작 시 HOLD/정지를 책임진다. 내부 ROS 2·드라이버 구조는 외부 API 뒤에 둔다. Pinky에서 이 책임의 구현은 CORE다. OMX는 장치별 로컬 제어기가 같은 종류의 책임을 가져야 하지만, 현재 adapter/development 코드가 운영 제어기 수용을 뜻하지는 않는다.
3. **최종 물리 명령은 장치 로컬에 남는다.** Pinky 주행의 최종 `cmd_vel`은 CORE만 발행한다(D-2, D-38). OMX 팔 trajectory의 최종 제출은 장치 수용을 마친 OMX 로컬 제어기 하나가 소유한다(D-282의 구현·장치 게이트 유지). Fleet, Console, Vision, AI 및 네트워크 연결은 이 권한을 넘겨받지 않는다. Pinky에 OMX를 장착해도 팔의 최종 명령 소유자는 OMX 로컬 제어기다. 장치 간 순서와 복합 로봇의 로컬 상태기계는 별도 계약·수용 전까지 활성화하지 않는다(D-55).
4. **`Fleet`은 사이트 미션 조정 계층이다.** 요청자·대상·capability와 현장 상태를 검증하고, 작업 순서·장치 간 인계·우선순위·미션 이력의 정본을 맡는다. 장치에 수용된 API로 유한한 작업을 요청하며, 장치의 수락 응답과 실제 완료 증거를 구분한다. Fleet의 작업 원장은 로컬 안전 판단, 모터·팔 제어, 장치 상태의 정본을 대체하지 않는다(D-12, D-290, D-293).
5. **공통 계약과 공통 실행 코드는 다른 판단이다.** 장치·사이트가 공유해야 할 식별, 요청, 상태·결과의 의미는 API Reference와 typed schema에서 함께 버전 관리한다(D-18). OMX에 Pinky 전용 `core_common` 전체를 의무화하지 않는다. 두 장치에서 같은 실행 규칙과 검증 필요가 실제로 확인될 때만 작은 공용 라이브러리 추출을 별도로 결정한다. `src/runtime/`은 소스 분류이며 단일 프로세스·공통 배포·하드웨어 소유권의 이름이 아니다.
6. **`ROSY Runtime`은 목표 아키텍처의 역할명이다.** 현행 Pinky CORE, 제안 단계의 OMX 로컬 제어기, 사이트 서비스가 모두 동일한 `rosy-runtime-base`를 설치하거나 같은 ROS graph에 참여한다는 뜻이 아니다. 현재 실행 단위와 장기 목표를 문서에서 구분한다. 기존 API 경로, ROS 패키지 이름, 소스 폴더 이름은 이 ADR만으로 바꾸지 않는다.

**Consequences:** `미들웨어`를 단독으로 써서 장치 CORE와 Fleet을 한 실행기로 묶지 않는다. 전체를 말할 때는 `ROSY Platform`, 장치 내부 경계는 `장치 미들웨어`, 사이트 작업 소유자는 `Fleet`이라고 쓴다. D-167의 평가표는 플랫폼 전반의 미들웨어 목표를 기록한 역사적 기준선이며, 그 표의 사이트 축이 Fleet을 장치 미들웨어로 만들지는 않는다. Vision의 관측과 AI의 후보, 배포·학습 서비스는 플랫폼 역할이지만 장치의 최종 명령 권한은 없다.

**Validation / Transition:** 제품 정의·용어집·목표 Runtime 문서·README·CORE SRS의 범위 표현을 정렬한다. 문서/계약 검증은 이름의 정합성만 확인한다. OMX 실행 인스턴스, 원격 작업 API, Pinky+OMX 복합 운용은 D-281/D-282/D-55의 별도 ROS-SIM·DEVICE·FIELD 증거를 요구한다.

**References:** [CORE SRS](../spec/ROSY%20CORE%20SRS.md), [D-12](D-12-mission-fleet.md), [D-18](D-18-rosy-core.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-167](D-167-middleware-goal-scorecard.md), [D-231](D-231-layered-source-roots-keep-package-names.md), [D-281](D-281-site-host-placement-and-omx-instance-isolation.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-290](D-290-rosy-platform-naming-and-site-intent-boundaries.md), [D-293](D-293-site-fleet-intent-api-contracts.md).
