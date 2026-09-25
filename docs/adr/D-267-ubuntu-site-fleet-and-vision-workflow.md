## D-267 Ubuntu 현장 서버가 Fleet과 영상 작업을 나눠 운영하고, 자동·수동 작업은 같은 검증 경로를 쓴다

**Status:** Proposed (2026-09-26). 현장 배치와 향후 작업 자동화의 설계 방향이다. 코드·Ubuntu 배포·GPU 실행·로봇암 DEVICE/FIELD 수용을 뜻하지 않는다.

잇는 결정: D-5, D-12, D-33, D-55, D-59, D-81, D-118, D-170, D-177(Proposed), D-199(Proposed), D-231, D-257(Proposed), D-261.
실행 계획: [2026-09-26-ubuntu-site-fleet-vision-workflow.md](../plans/2026-09-26-ubuntu-site-fleet-vision-workflow.md).

**Context:** 운영자는 RTX 5080 노트북을 현장에 상시 두고 Ubuntu에서 관제 서버, 데이터 처리, 영상 추론, 웹 접근을 운영하려 한다. 첫 영상 입력은 천장 스마트폰 카메라다. 이후 핑키 이동 로봇과 로봇암의 카메라를 추가한다. 검증된 인식 결과는 Fleet이 자동 작업을 시작하는 근거가 될 수 있고, 관제 PC에서도 같은 종류의 작업을 직접 요청할 수 있어야 한다.

이 문서 작성 당시 `fleet console`은 CORE REST 기반 관제였고 `SiteHub`, overhead frame adapter 및 site Compose는 운영 앱 경로에 연결되지 않았다. D-257 sighting과 자동 정책 입력도 Proposed였다. 아래 구현 현황은 이 초기 상태와 설계 승인을 구분한다.

**Decision:**

1. **현장 호스트와 책임.** Ubuntu RTX 노트북 한 대를 초기 사이트 호스트로 쓴다. Fleet API·웹, 영상 수신, GPU 추론, 작업·이벤트 저장은 별도 서비스로 배치하고 각 서비스의 재시작과 상태를 독립 관측한다. Docker Compose는 이 *사이트* 배포 수단이다. 로봇의 네이티브 안전·제어 런타임을 컨테이너로 바꾸는 결정이 아니다(D-246).
2. **통신 경계.** 로봇의 ROS 2/CycloneDDS는 로봇 내부에 머문다(D-33). CORE가 로봇 측 유일한 외부 관문이다. 사이트 Fleet은 CORE의 REST/WebSocket 계약으로 상태·이벤트를 모으고 원자 액션을 내린다(D-5, D-59). 사이트 서버가 로봇 DDS에 직접 참가하거나 `/cmd_vel`을 발행하지 않는다. 사이트용 ROS 주변장치가 생기더라도 별도 어댑터가 결과를 계약으로 바꾸며 로봇 도메인을 합치지 않는다.
3. **영상 경계.** 천장 폰은 D-261 `rosy-overhead/1`로 사이트 관측 서비스에 프레임을 보낸다. 관측 서비스는 최신 프레임만 처리하고, D-257이 수용되면 `map` 좌표의 sighting 등 작은 결과만 Fleet에 전달한다. Fleet API·명령 envelope·브라우저 데이터 경로에 원본 영상 또는 `sensor_msgs/Image`를 넣지 않는다(D-118). 핑키·로봇암 영상의 사이트 전송은 *후속 전용 미디어 계약*과 대역·지연 실측 후 추가한다. 기존 온보드 카메라 경로를 곧바로 노트북으로 전송하는 것으로 해석하지 않는다.
4. **출처와 신선도.** 결과에는 `source_id`, 대상 로봇/자산, 원본 프레임 순서와 촬영 시각, 수신 시각, 좌표계·`map_id`, 카메라 보정 revision, 처리기/모델 revision, 결과 종류·값·신뢰도·유효 기한을 기록한다. 구체 필드와 외부 경로는 API Ref·공유 schema 변경에서 고정한다(D-18). 출처·보정·지도·시간이 맞지 않거나 결과가 만료되면 표시에는 남길 수 있어도 자동 작업 입력으로 채택하지 않는다. D-257의 sighting 표시/판단 신선도와 관측 전용 경계를 우선한다.
5. **고수준 작업의 단일 입구.** 자동 경로는 운영자가 사전에 등록·활성화한 작업 조건과 유효한 인식 결과가 일치할 때만 Fleet 작업을 만든다. 수동 경로는 권한 있는 운영자의 웹/API 요청으로 같은 작업을 만든다. 두 경로는 같은 capability, 현장 구역, 로봇 상태, 지도·보정 revision, 중복/멱등성, 작업 충돌, 안전 정책 검사를 통과한다. 요청 출처(`automatic`/`operator`)와 결정 근거를 감사 기록에 남긴다. 수동 요청은 안전 검사를 우회하지 않는다.
6. **실행 소유권.** Fleet은 사이트 미션·자산 배정·작업 단계와 재시도 정책을 소유한다(D-12). 로봇 CORE는 이동·정지 원자 액션과 로컬 주행 안전을 소유한다. 향후 로봇 측 manipulation 액션은 접근·파지·운반·배치의 로컬 거래와 팔 안전을 소유한다(D-55). GPU 추론 결과는 제안/증거이며 모터 또는 관절 명령이 아니다. 인식 신뢰도 하나로 이동·집기를 허가하지 않는다.
7. **추적과 고장.** Fleet은 작업 ID와 멱등 키, 원인 evidence ID, 로봇 명령 correlation ID, 수락/실행/완료·실패 결과를 따로 저장한다. 응답 유실 후 재접수는 기존 작업을 반환해야 하며, 재기동 뒤 미확인 명령을 새 명령처럼 재송신하지 않는다. 영상 서비스·GPU가 죽으면 해당 자동 조건을 닫고 상태를 `DEGRADED`로 표시한다. Fleet 전체가 꺼지면 사이트 자동화만 멈추고 로봇의 로컬 정지·deadman은 유지한다. 복구 뒤 움직임 재개는 현재 상태·명령 결과를 재조회한 후에만 허용한다.
8. **단계적 활성화.** 1차는 천장 카메라 결과의 관측·대조와 기존 목표/취소 경로다. 자동 이동은 D-257 수용, 실제 카메라·지도 보정, 이벤트/명령 추적 및 현장 재현 시험 뒤 능력별로 활성화한다. 자동 집기는 D-55의 모델·장착·전원·hand-eye·충돌·payload·복구 장치 시험과 실제 파지/배치 검증 뒤 별도 정책으로 활성화한다. 핑키/팔 영상도 각각 전송 계약과 기기 실측을 거친다.

**Implementation status (2026-09-27, LOCAL):** the current source now wires the
CORE `FleetAgent` WebSocket and durable event audit into the site Fleet app,
accepts overhead frames through the separate vision service, stores sightings,
and exposes authenticated operator state/event/task readback. Operator
navigation uses a durable idempotent task path; interrupted `REQUESTED` work
recovers to `UNKNOWN`, while policy navigation remains `HOLD`. The Linux/amd64
Compose stack and synthetic TLS camera/Fleet smoke have been exercised on Docker
Desktop, including restart readback. No Ubuntu RTX host, NVIDIA container access,
physical phone/CORE stream, surveyed calibration, or per-user Fleet RBAC has been
accepted. D-177 command correlation/ACK reconciliation and D-268 policy evidence
gates remain open; this implementation record does not change the Proposed
status or authorize autonomous motion.

**Alternatives:**

- *Fleet 프로세스에 영상 처리와 GPU 모델을 합침* — 영상 장애가 명령·웹 경로에 전파되고 D-118/D-257 경계를 흐린다.
- *사이트 PC를 로봇 DDS 도메인에 참가시킴* — 로봇별 격리, 무선 대역과 CORE 외부 관문 계약을 깨며 현재 필요하지 않다.
- *인식 점수만 넘으면 즉시 자동 집기* — 지도·보정·파지 능력과 현재 로봇 상태를 증명하지 못한다.
- *처음부터 별도 서버와 GPU 노트북 두 대* — 초기 상시 RTX 호스트 한 대라는 현장 조건에 비해 운영 복잡성이 크다. 서비스 경계를 유지하면 나중에 분리할 수 있다.

**Validation / Transition:** 계획 문서의 SOURCE→LOCAL→ROS-SIM→ARTIFACT→DEVICE→FIELD 게이트를 각각 남긴다. Compose 기동과 호스트 GPU 인식은 사이트 배포 증거일 뿐 로봇 실기 집기 수용이 아니다. D-257·D-199의 Proposed 결정을 자동 실행의 승인으로 간주하지 않는다. 공개 저장소에는 실주소·토큰·영상 기록을 넣지 않는다(D-226).

**References:** [사이트 역할 설계](../plans/2026-09-14-site-middleware-role-fabric-design.md), [Fleet SRS](../spec/ROSY%20FLEET%20SRS.md), [CORE SRS](../spec/ROSY%20CORE%20SRS.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-118](D-118-image-fleet-gz-multi.md), [D-257](D-257-site-lane-map-and-overhead-sightings.md), [D-261](D-261-overhead-camera-app-skeleton.md), [D-269](D-269-device-server-contracts-and-ros-boundary.md).

---
