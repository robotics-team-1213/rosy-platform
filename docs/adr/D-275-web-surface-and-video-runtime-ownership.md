## D-275 웹 화면과 영상 처리는 실행 위치와 권한별로 나눈다

**Status:** Accepted (2026-09-26). 소스와 배포 경계의 결정이다. 실제 Pi 설치, Ubuntu 현장 서버, 카메라 및 물리 동작의 DEVICE/FIELD 수용을 뜻하지 않는다.

잇는 결정: D-23, D-75, D-77, D-118, D-150, D-152, D-161, D-197, D-243, D-246, D-257, D-261, D-267, D-269, D-271, D-273, D-274.

**Context:** 현재 소스에는 로봇 CORE가 제공하는 정적 대시보드와 역할별 화면, 사이트 Fleet 콘솔, Control 진단용 `web_node`가 있다. 로봇 전방 카메라 preview와 천장 폰 영상은 생산자·소비자·용도가 다르다. 같은 관제 PC 브라우저에서 화면을 열 수 있다는 사실만으로 웹 서버나 영상 처리가 그 PC에 설치된 것은 아니다. 사이트 Fleet/Vision/프록시는 Compose 후보로 구현되어 있으나 로봇 제품 런타임은 native systemd다(D-161/D-197). 현재 사이트 Vision은 천장 영상의 CPU ArUco 처리 하나지만, 장기적으로 다른 카메라·센서의 추론과 학습 작업도 필요할 수 있다. 이 확장 가능성을 현재 Fleet 명령 서버에 원본 영상과 GPU 작업을 합치는 이유로 삼지 않는다.

**Decision:**

1. **로봇 화면과 명령의 소유자는 로봇 CORE다.** `src/hmi/dashboard`의 정적 HTML·JS·CSS는 설치된 `share/dashboard`에서 `src/runtime/api_web` FastAPI가 CORE 프로세스 안에서 제공한다. `/dashboard`와 역할별 `/console`, `/setup`, `/device`는 같은 로봇 origin의 `/api/v1/*` 및 `/ws/*`를 사용한다. 브라우저는 ROS/DDS나 장치 드라이버에 직접 접속하지 않는다. 인증·역할·capability·최종 명령 판정은 CORE에 남는다. 별도 Node 서버나 로봇 운용 웹 서버를 만들지 않는다.
2. **사이트 관제 화면과 작업 순서의 소유자는 Fleet이다.** `src/site/fleet/fleet/server/web`의 `/console`은 사이트 호스트의 Fleet FastAPI가 제공하고 Caddy가 HTTPS로 노출한다. 사이트의 `/console`과 로봇의 `/console`은 같은 경로 이름이어도 다른 origin·인증·책임을 가진다. Fleet은 여러 로봇의 상태, 작업 요청·취소·이력과 사이트 관측값을 다루고, 로봇별 원자 명령은 CORE REST 계약으로 제출한다. 접수 응답을 동작 완료로 표시하지 않는다. 관제 PC는 이 화면을 여는 브라우저 단말이며 Fleet 설치 위치로 가정하지 않는다.
3. **Vision은 천장 카메라의 별칭이 아니라 관측·연산 책임이다.** 현재 첫 구현인 `src/site/overhead`는 천장 폰 JPEG를 받아 CPU ArUco 관측값을 만든다. 향후 Vision/AI 연산은 입력 종류와 지연·자원 요구에 따라 로봇 edge, 사이트 GPU 또는 별도 compute node에 배치할 수 있다. 같은 사이트 호스트에 Fleet과 나란히 두는 것은 허용하지만, 현재 운영 경로에서 원본 프레임 처리나 GPU 모델을 Fleet API/작업 프로세스 안에 넣지는 않는다. Fleet은 Vision의 작은 파생 관측값을 대조·저장·표시하고 작업 정책을 평가할 수 있다. 배치 변경은 입력 출처, 출력 계약, 인증, 자원 격리, 장애 영향을 확인한 뒤 별도로 결정한다.
4. **영상 출력의 권한은 용도마다 다르다.** 로봇 전방 영상은 로봇 내부에서 관측·압축하고 CORE가 인증된 최신 JPEG 한 장만 저주기 preview API로 제공한다(D-152). 천장 폰 영상은 사이트 Vision이 처리하고 현재는 표시 전용 sighting만 Fleet에 보낸다. Fleet/Hub/브라우저에 원본 영상·영상 URL·DDS `Image`를 중계하지 않는다(D-118/D-269). OMX 작업 카메라와 고속 제어용 영상은 D-273의 별도 미구현 계약으로 남긴다. 복잡한 모델이 내는 분류·추천·행동 후보도 곧바로 명령이 되지 않는다. 자동 작업 입력은 D-268의 별도 정책 적격 증거와 Fleet 검증을 거쳐야 하고, 최종 이동·팔 동작 및 안전은 로봇 CORE/로컬 action이 판정한다.
5. **학습은 운영 추론과 별도 수명 주기를 가진다.** 데이터 수집·보존·라벨·학습·모델 검증·배포는 `docs/architecture/12_ROSY_Dataset_and_Learning_Pipeline.md`의 장기 경로로 취급한다. 학습 작업이 실시간 Fleet API나 로봇 정지 경로의 CPU/GPU·저장 자원을 잠식하지 않도록 별도 작업/자원 예산을 요구한다. 모델 revision과 현장 성능이 검증되기 전에는 학습 산출물을 운영 추론·자동 결정에 승격하지 않는다. 이 ADR은 새 학습 서비스나 데이터 수집을 승인하지 않는다.
6. **Control `web_node`는 개발·진단 화면이다.** `src/runtime/sensing/web`의 별도 포트와 명령 경로는 운영 launch·제품 배포·Fleet 콘솔에 포함하지 않는다(D-150). 화면 스타일 자산을 공유할 수 있어도 서버, 자격 증명, 명령 권한은 공유하지 않는다.
7. **배포와 장애 경계는 독립적으로 검증한다.** 로봇 제품의 CORE/제어/안전은 native systemd로 기동하고, 사이트 Fleet·Vision·Caddy는 사이트 호스트의 서비스 경계로 운영한다. 사이트나 Vision이 끊기면 로봇의 로컬 CORE·정지 경로는 유지되어야 한다. 로봇 CORE가 끊기면 Fleet은 해당 로봇 명령을 성공으로 표시하거나 자동 재개하지 않는다. 영상이 stale이면 미리보기를 숨기거나 관측을 stale로 표시하고 과거 프레임을 현재 상태로 반복하지 않는다. 자격 증명은 로봇 브라우저, 사이트 운영자, CORE REST, Agent pairing, 폰 source, Vision 게시 권한별로 분리한다(D-269).
8. **소스, 산출물, 설치, 현장 증거를 각각 기록한다.** 라우트·계약 시험은 SOURCE/LOCAL이고, 설치된 `share/dashboard`와 native ARM64 payload 및 사이트 이미지 digest는 ARTIFACT, 실제 Pi·사이트 호스트·폰의 프로세스/URL/영상 readback은 DEVICE/SITE, 장애·복구 및 운용 결과는 FIELD다. 한 화면의 로컬 브라우저 캡처나 합성 영상 시험으로 다른 단계의 수용을 주장하지 않는다.

**Alternatives:**

- 모든 화면을 관제 PC의 단일 웹 서버로 이전: 사이트 단절 시 로봇 로컬 화면과 인증 경로가 사라지고 CORE 단일 관문을 약화한다.
- 로봇마다 Fleet/Vision 전체를 설치: 영상 처리·다중 로봇 작업·사이트 저장소를 Pi 자원과 안전 경로에 결합한다.
- 첫 천장 카메라는 Fleet 프로세스가 직접 처리하고 나중에 분리: 지금도 OpenCV/JPEG의 CPU·메모리·재시작·인증 장애가 작업 서버에 전파된다. 이미 분리된 사이트 Vision 서비스가 있으므로 같은 호스트에서 운영하며 계약을 유지한다. Fleet의 파생 데이터 처리까지 분리할 필요는 없다.
- Fleet이 로봇/폰 원본 영상을 중계: D-118/D-152의 크기·신선도·권한 경계와 충돌한다.
- Control 진단 화면을 운영 화면으로 승격: 인증·명령의 두 번째 소유자를 만들어 D-77/D-150과 충돌한다.

**Consequences:** 화면 소스는 서비스별 패키지에 남고 `src/hmi/web`의 공통 토큰·컴포넌트만 공유한다. 두 `/console`의 호스트·인증·목적을 문서와 시험에서 명시해야 한다. Vision의 논리적 소유권은 배치 호스트와 무관하고 현재 `overhead` 구현을 범용 Vision 서비스 완성으로 부르지 않는다. 사이트 호스트의 서비스 분리는 로봇 제품에 Docker 의존을 추가하지 않는다. `deploy/robot/Dockerfile`은 D-197의 전환 중인 레거시 빌더 경로이며, 그 내용만으로 현행 native 제품 payload의 웹 포함 여부를 판정하지 않는다.

**Validation / Transition:** [실행 위치·화면·영상 경계 계획](../plans/2026-09-26-web-surface-video-role-boundaries.md)을 따른다. 현재 소스의 `core_api_web.api.app`, `fleet.server.app`, `deploy/site/compose.yaml`, `overhead`, `web_node`와 D-152/D-197을 대조했다. 이번 ADR에는 API 경로·스키마·제품 런타임 변경이 없다. native payload의 설치 파일, 실제 Pi·사이트·폰의 프로세스 및 네트워크 경로는 계획의 별도 게이트에서 확인한다.

**References:** [CORE SRS](../spec/ROSY%20CORE%20SRS.md), [API Reference](../reference/ROSY%20API%20%26%20Protocol%20Reference.md), [D-243](D-243-operator-screens-live-in-hmi.md), [D-267](D-267-ubuntu-site-fleet-and-vision-workflow.md), [D-268](D-268-policy-eligible-vision-evidence-for-fleet-tasks.md), [D-269](D-269-device-server-contracts-and-ros-boundary.md), [AI 경계](../architecture/11_ROSY_AI_and_Physical_AI.md), [학습 경로](../architecture/12_ROSY_Dataset_and_Learning_Pipeline.md), [사이트 배포 설명](../../deploy/site/README.md).
