## D-269 장비는 역할별 계약으로 사이트 서버에 접속하고 DDS는 CORE 안에 둔다

**Status:** Proposed (2026-09-26). 코드와 문서의 계약 경계를 대조한 제안이다. 한 ASGI 앱의 로컬 왕복 시험, 비밀 분리, 현장 장비 시험이 끝나기 전에는 서버 연동이나 DEVICE/FIELD 수용으로 간주하지 않는다.

잇는 결정: D-18, D-30, D-59, D-81, D-118, D-136, D-170, D-177, D-193, D-246, D-257, D-261, D-267, D-268.

**Context (현재 코드 확인):**

1. 천장 스마트폰 앱은 JPEG 프레임을 `rosy-overhead/1` WebSocket `/overhead/v1/frames`로 보낸다. `src/site/overhead/overhead/ingest.py`는 단일 설정 Bearer 토큰, `source`별 최신 프레임 1장과 수신 통계만 관리한다. 마커 인식과 Fleet 전송은 없다.
2. 사이트 `fleet console`은 브라우저 요청을 `/api/fleet/*`로 받고 `robots.yaml`의 `RobotEndpoint`별 HTTP Bearer 토큰으로 CORE REST 상태·원자 명령을 호출한다. 콘솔 명령은 Fleet 서버가 중계하지만 최종 제어와 안전은 CORE가 소유한다.
3. CORE의 `FleetAgent`와 사이트 `SiteHub`에는 PRT Envelope의 `hello`, `heartbeat`, `event` 코드가 있다. 그러나 `fleet console` 앱은 Hub WebSocket 라우트를 포함하지 않고, Agent는 `fleet.hub_url`과 `fleet.pairing_token`이 없으면 시작하지 않는다. 두 프로세스가 같은 운영 앱에서 만나는 통합 시험도 없다.
4. `SiteHub`는 현재 `RobotEndpoint.token`을 `HelloPayload.pairing_token`과 대조한다. 따라서 별도 설정이 없으면 로봇 REST 호출용 자격 증명과 Agent 페어링 자격 증명이 같은 값으로 맞춰져야 한다. 이 결합은 장비 연결을 운영으로 열기 전에 분리해야 한다.
5. 로봇 내부 DDS는 CORE와 로봇 런타임의 경계다. Fleet/브라우저가 DDS에 참여하지 않는다. D-118은 원본 `Image`가 Fleet 계약·브라우저 경로로 들어오는 것을 막는다.
6. 로봇 전면 카메라의 CORE 로컬 preview, Pinky 카메라의 사이트 업링크, OMX 팔 영상·집기 명령은 서로 다른 기능이다. 현재 Fleet 서버가 이들을 사이트 영상 입력이나 원격 조작으로 연결하지 않는다.

**Decision (제안):**

1. **단일 전송 규약을 만들지 않는다.** 같은 Ubuntu 사이트 호스트에 여러 서비스가 배치되어도 장비 연결은 목적에 맞는 버전 계약을 유지한다.

   | 연결 | 계약·흐름 | 현재 상태 | 수용 전 필수 조건 |
   |---|---|---|---|
   | 브라우저 → Fleet 서버 | same-origin HTTPS, `/api/fleet/*`, console Bearer token | 앱·수동 REST 명령 구현, 현장 TLS 미수용 | 역할·CSRF/인증·TLS·명령 readback 시험 |
   | Fleet 서버 → CORE | `/api/v1/*` HTTPS REST, 장비별 로봇 토큰 | `HttpRobotClient` 구현, 현재 gather는 REST 폴링 | 실제 CORE, 인증·timeout·stale·명령 상태 시험 |
   | CORE Agent → Fleet 서버 | WSS `/ws/robots`, API Ref PRT Envelope, hello/heartbeat/event | 양 끝 구현, 운영 앱 미결합·기본 비활성 | ASGI 통합, 분리된 페어링 비밀, reconnect·seq 시험 |
   | 천장 폰 → 사이트 수신기 | WSS `/overhead/v1/frames`, `rosy-overhead/1`, JPEG | 프로토콜·수신기·Android 앱 LOCAL 구현 | source별 자격 증명, 실제 폰/LAN/연속 신선도 시험 |
   | 사이트 영상 작업자 → Fleet | D-257 sighting JSON 및 후속 D-268 정책 증거 | 인식·publish endpoint 없음, D-257/D-268 Proposed | API Ref와 shared schema 동시 변경, quality·freshness·거절 시험 |
   | 로봇 내부 | ROS 2 DDS → CORE → 로컬 기능·장치 | 로봇 런타임 소유 | 장치별 DEVICE 절차; 사이트 서버는 DDS 참가자가 아님 |
   | Pinky 카메라·로봇암 | 미정인 전용 media/action 계약 | 사이트 연결 없음 | 대역·지연·권한·로컬 안전 계약을 별도 ADR로 수용 |

2. **자격 증명을 목적과 장치별로 분리한다.** 브라우저 console 토큰, 로봇 CORE REST 제어 토큰, CORE Agent 페어링 토큰, 천장 카메라 source 토큰은 서로 바꾸어 쓸 수 없다. 배포 설정은 읽기 권한을 제한하고, 회수·교체를 지원하며, 토큰을 URL·로그·영상 payload에 넣지 않는다. 전송 자격 증명을 실제 네트워크에서 쓸 때는 TLS가 필수다.
3. **Robot Fleet Agent는 상태·이벤트 업링크다.** 이 경로를 CORE DDS 제어 또는 임의의 로봇 명령 채널로 사용하지 않는다. 사용자 명령은 기존 Fleet → CORE REST 계약을 따라가며 수락 응답과 실제 완료 이벤트를 구분한다. D-177의 correlation/ACK 계약을 구현하기 전에는 응답을 완료로 표시하지 않는다.
4. **영상은 사이트의 제한된 입력이다.** 폰 영상은 사이트 관측 worker에서 처리하고 Fleet에는 D-257이 수용된 뒤 작은 파생 결과만 보낸다. raw JPEG, 영상 URL, `sensor_msgs/Image`는 Fleet/Hub/API/브라우저에 전달하지 않는다. ROS robot camera preview를 사이트 입력으로 재사용하지 않는다.
5. **자동 실행은 계속 차단한다.** D-257 sighting은 표시·대조 자료다. 자동 작업은 D-268이 요구하는 별도 수용 정책 증거와 작업별 freshness/false-trigger 수용 뒤에만 허용한다. 미확인·stale·출처 불일치는 `HOLD`이며 운전자 명령 또한 같은 task 검증·감사 경로를 쓴다.
6. **장비별 연결 증거를 따로 기록한다.** 계약 벡터/단위시험은 SOURCE, 실제 localhost 서비스 간 왕복은 LOCAL, 합성 또는 로봇 시뮬은 ROS-SIM, 고정 이미지와 호스트 드라이버 시험은 ARTIFACT/SITE, 실제 폰·CORE·팔·Pinky 측정은 각각 DEVICE/FIELD 증거다. 한 연결의 통과를 다른 장비나 배포의 통과로 승격하지 않는다.

**Alternatives:**

- *모든 장비를 DDS domain에 직접 붙임* — 웹·스마트폰 경계와 장치 인증을 복잡하게 만들고 CORE 단일 gateway와 충돌하므로 기각한다.
- *모든 장비에 하나의 WebSocket schema를 적용* — 영상 크기·센서 주기·제어 권한이 뒤섞이고 D-118 경계를 약화하므로 기각한다.
- *Agent 페어링에 CORE REST 관리자/운영 토큰 재사용* — 토큰 하나의 누출이 telemetry와 로봇 명령 권한을 함께 노출하므로 기각한다.
- *수신·인식·Fleet·자동 정책을 한 프로세스로 결합* — 장애·자원·권한 경계가 사라져 관측 실패가 명령 경로에 영향을 줄 수 있으므로 기각한다.

**Consequences:** 현장 호스트는 서비스 프로세스를 한 대에서 운영할 수 있지만, 폰 ingress·vision worker·Fleet API·CORE 연결·저장소는 분리된 설정과 상태로 관찰한다. 로컬 Hub 연결을 여는 첫 구현은 credential separation과 동일 앱 통합 시험을 포함한다. Pinky 카메라 및 로봇암은 이 결정만으로 활성화되지 않는다.

**Validation / Transition:** [장비-서버 계약 감사 및 연동 계획](../plans/2026-09-26-middleware-device-server-contract-integration.md)을 실행한다. 첫 수용은 실제 `FleetAgent`가 동일한 `fleet console` ASGI 앱의 `/ws/robots`에 연결해 hello/heartbeat/event/reconnect를 왕복하고, 틀린 토큰·로봇 신원·프로토콜·stale 입력을 거절하는 localhost 시험이다. 별도 다음 수용은 phone→receiver→vision→Fleet 파생 결과의 같은 source/seq/map lineage를 검증한다. 실물 장비·TLS·현장 네트워크 시험 전까지 DEVICE/FIELD 및 자동 실행은 HOLD다.

**References:** [D-118](D-118-image-fleet-gz-multi.md), [D-257](D-257-site-lane-map-and-overhead-sightings.md), [D-261](D-261-overhead-camera-app-skeleton.md), [D-267](D-267-ubuntu-site-fleet-and-vision-workflow.md), [D-268](D-268-policy-eligible-vision-evidence-for-fleet-tasks.md), [ROSY API & Protocol Reference](../reference/ROSY%20API%20%26%20Protocol%20Reference.md).
