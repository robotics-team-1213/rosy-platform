# 웹 화면·영상 실행 위치 분리 Implementation Plan

> **For implementers:** Execute one task at a time in an isolated worktree. Preserve other worktrees and record each evidence tier separately.

**Goal:** D-275의 로봇 CORE, 사이트 Fleet/Vision, 관제 브라우저, 천장 폰, Control 진단 화면 경계를 실제 산출물과 실행 경로에서 확인하고, Vision을 향후 다른 입력·추론·학습에도 확장 가능한 책임으로 정의한다.

**Architecture:** 로봇의 화면과 REST/WS는 같은 CORE 프로세스와 origin에 둔다. 사이트 Fleet 콘솔과 현재 Vision ingress는 한 호스트의 분리된 서비스로 실행한다. Vision은 향후 edge·GPU·compute node로 배치할 수 있는 논리적 관측/추론 책임이며, Fleet은 검증된 파생 결과와 작업 정책을 소유한다. 학습 작업과 실시간 추론은 자원·배포·승인 수명 주기를 나눈다.

**Tech Stack:** ROS 2 Jazzy/native systemd, FastAPI, 정적 ES module·CSS, Android CameraX, Python/pytest, 사이트 Docker Compose/Caddy, 선택적 Playwright.

**Decision:** [D-275](../adr/D-275-web-surface-and-video-runtime-ownership.md). 통신 계약은 [D-269](../adr/D-269-device-server-contracts-and-ros-boundary.md), 영상 상한은 [D-152](../adr/D-152-core-1-preview.md), 제품 산출물 전환은 [D-197](../adr/D-197-docker-exits-the-product-chain.md)을 따른다.

---

## 시작 전 기준선

1. `Rosy OS`의 HEAD, `git status --short`, 관련 worktree와 변경 경로를 기록한다. 구현은 무관한 WIP가 없는 저장소 `.worktrees/<짧은이름>`에서 `git worktree add --relative-paths`로 시작한다. 임시 로그·캡처·빌드 찌꺼기는 `X:\DevTemp\`에 둔다.
2. 표면과 서버를 혼동하지 않도록 다음 표를 기준선으로 남긴다.

   | 화면·입력 | 코드 주인 | 실행 주인 | 첫 검증 경로 |
   |---|---|---|---|
   | 로봇 `/dashboard`, `/console`, `/setup`, `/device` | `src/hmi/dashboard`, `src/runtime/api_web` | Pi의 CORE | 같은 origin API/WS와 설치된 `share/dashboard` |
   | 사이트 `/console` | `src/site/fleet/fleet/server` | 사이트 Fleet | Caddy HTTPS → Fleet, 인증 및 작업 readback |
   | 전방 preview | `src/runtime/sensing`, `src/runtime/api_web` | 로봇 sensing → CORE | 최신 JPEG, 권한, stale, 속도·크기 제한 |
   | 천장 폰 영상 | `src/site/overhead/android`, `src/site/overhead` | 폰 → 사이트 Vision | WSS JPEG → sighting → Fleet SQLite |
   | Control 진단 화면 | `src/runtime/sensing/web` | 개발 전용 `web_node` | 운영 launch·배포에서 제외 |

3. 현재 제품 배포 기준은 native payload다. `deploy/robot/Dockerfile`의 옛 `core` 타깃이 새 패키지 경로를 담는지 여부는 D-197의 레거시 빌더 전환 항목으로만 기록한다. 그 Dockerfile을 고쳐 제품 수용을 대신하지 않는다.

## Task 1 — 로봇 화면의 소스·설치·실행 경로 고정

**Read:** `src/hmi/dashboard/CMakeLists.txt`, `src/runtime/api_web/core_api_web/api/app.py`, `src/runtime/gateway/core/main.py`, `deploy/image/build-native-payload.sh`, `deploy/robot/native/rosy-core.service`.

1. `src/hmi/dashboard/test`, `src/runtime/api_web/test/test_ui_route.py`, `test/test_dashboard_browser.py`의 기존 계약을 먼저 실행한다. 설치된 `share/dashboard`에서 정적 자산을 찾고 같은 CORE origin의 API/WS를 사용하는 시험이 빠졌으면 실패 시험을 추가한다.
2. native ARM64 payload의 `install/share/dashboard`와 `core_api_web` 포함 여부를 빌드 manifest·파일 목록·해시로 확인한다. 빠졌을 때만 해당 native 빌드 또는 설치 경로를 수정한다. 새 API나 별도 웹 서버는 추가하지 않는다.
3. 실제 Pi에서는 승인된 read-only 점검으로 systemd CORE PID, 설치 prefix·revision, loopback `/dashboard`와 LAN 브라우저 URL, 자산 200/404, 인증된 API/WS를 같은 장치에서 확인한다. HEAD와 실행 revision이 다르면 설치 판정은 HOLD다.

**Gate:** SOURCE/LOCAL은 계약 시험, ARTIFACT는 native ARM64 payload의 실제 파일·digest, DEVICE는 Pi 프로세스와 브라우저 readback이다. 호스트 브라우저 캡처만으로 DEVICE를 닫지 않는다.

## Task 2 — 사이트 Fleet 콘솔과 관제 PC의 역할 고정

**Read:** `src/site/fleet/fleet/server/app.py`, `src/site/fleet/fleet/server/web/`, `deploy/site/compose.yaml`, `deploy/site/Caddyfile`, `deploy/site/README.md`.

1. `/console`은 사이트 HTTPS origin에서 Fleet 정적 자산과 `/api/fleet/*`만 사용하는지 확인한다. 로봇 `/console`과 URL·토큰을 섞어도 권한이 생기지 않는 계약 시험을 추가한다. 관제 PC에는 브라우저 접속만 필요하다는 설치 표를 문서화한다.
2. 로컬 합성 환경에서 잘못된 운영자 토큰 거부, Fleet→가짜 CORE 요청 접수, SQLite task readback, Caddy 인증서 검증을 실행한다. 응답 `ACCEPTED`를 `COMPLETED`로 표시하지 않는지 확인한다.
3. 실제 Ubuntu 사이트 호스트에서는 이미지 digest·프로세스·포트·TLS/CA·volume·백업 위치를 readback한다. 실제 CORE와의 접속·명령 완료는 별도 장치 증거로 남긴다.

**Gate:** Docker Desktop LOCAL과 Ubuntu SITE 배포는 별도다. 사이트 호스트 정보가 없으면 SITE는 HOLD다.

## Task 3 — 두 영상 경로와 진단 화면의 경계 검증

**Read:** `src/runtime/api_web/core_api_web/api/v1/vision.py`, `src/hmi/dashboard/vision.js`, `src/site/overhead/overhead/`, `src/site/overhead/android/`, `src/site/fleet/test/test_no_video_relay.py`, `src/runtime/sensing/web/AGENTS.md`.

1. 전방 preview의 Viewer 인증, 최신 sequence, 404 stale, 409 advanced, 429 rate limit, JPEG 상한을 기존 시험에서 확인하고 빠진 경계만 실패 시험으로 추가한다. 상태 WS에 JPEG/base64를 싣지 않는다.
2. 합성 폰 JPEG→WSS→Vision→sighting→Fleet SQLite의 source/seq/map/calibration lineage와 stale·잘못된 token 거부를 확인한다. Fleet 서버의 영상 relay route/import 부재 시험을 유지한다. 사이트 콘솔은 원본 영상을 보여 주지 않는다.
3. 실제 폰과 현장 카메라는 페어링, 30분 연속 freshness·드롭·대역·열 상태, 현장 보정 오차를 측정해 DEVICE/FIELD로 따로 기록한다. 로봇 전방 카메라와 OMX 영상도 각각 별도 장치 증거가 필요하다.
4. `web_node` 포트·실행 파일이 운영 launch, native payload의 자동 기동 유닛, 사이트 Compose에 없는지 정적 시험과 장치 프로세스 목록으로 확인한다. 진단 화면이 있어도 운영 명령 권한은 CORE 경로만 허용한다.

## Task 4 — 장애 경계와 증거 인계

1. 사이트 Fleet/Vision 단절, CORE 단절, 카메라 stale, 토큰 폐기를 각각 독립적으로 주입한다. 로봇 로컬 CORE·정지 경로의 생존, Fleet의 `UNKNOWN/HOLD` 표시, 영상 stale 표시, 재연결 후 자동 재실행 부재를 관측한다. 물리 구동·E-Stop 시험은 현장 운영자 승인과 독립 정지 수단이 확보된 별도 DEVICE/FIELD 절차에서만 한다.
2. API 경로·envelope 수정이 필요해진 경우 먼저 API Reference와 `src/contracts/foundation/core_common/protocol/schemas.py`를 같은 변경에서 갱신한다(D-18). 이번 ADR 자체는 새 프로토콜을 승인하지 않는다.
3. 각 단위의 변경 파일만 스테이징하고 SOURCE, LOCAL, ROS-SIM, ARTIFACT, DEVICE/SITE, FIELD를 구분해 `docs/validation/<topic>-<date>/`와 모듈 `progress.md`에 기록한다. 실제 실행 revision·산출물 digest·설정 revision·접속 host·시각을 연결한다. 남은 gate가 HOLD이면 그대로 보고한다.

## Task 5 — Vision 확장 전 결정 게이트

1. 새 입력(로봇/OMX 카메라 또는 비영상 센서)마다 producer, 위치, 프레임·좌표계·시각, 보정, 원본 보존 여부, 지연·대역·자격 증명을 먼저 기록한다. 현재 `overhead`의 WSS·ArUco 계약을 범용 입력 계약으로 이름만 바꾸지 않는다.
2. 새 연산을 **표시용 관측**, **사람에게 제안하는 판단**, **자동 작업의 정책 적격 증거**, **장치 로컬 제어 입력**, **오프라인 학습**으로 분류한다. Fleet은 파생 결과를 표시하거나 검증된 정책을 평가할 수 있지만, 원본 영상/GPU 추론을 현행 Fleet 프로세스에 넣는 변경은 D-267/D-269 재검토와 장애·자원·권한 측정이 먼저다. 자동 작업은 D-268, 장치 제어는 CORE·D-55/D-273의 별도 수용이 필요하다.
3. 학습이 필요하면 데이터 출처·보존·라벨 품질·모델 revision·평가셋·롤백·GPU 예산을 별도 설계로 만든다. `docs/architecture/11_ROSY_AI_and_Physical_AI.md`와 `12_ROSY_Dataset_and_Learning_Pipeline.md`를 입력으로 사용한다. 학습 잡과 모델 배포는 실시간 Fleet/Vision/CORE의 정상 가동을 전제로 하지 않으며, 새 모델은 검증 전 운영 정책에 연결하지 않는다.
4. 실제 부하가 생긴 뒤 같은 사이트 호스트 유지, 별도 GPU 호스트, 로봇 edge 배치를 지연·대역·가용성·복구 비용으로 비교한다. 물리 배치 변경은 새 계약·배포·DEVICE/SITE 검증 계획을 기록하고 진행한다. 지금은 범용 AI 서비스나 GPU 예약을 선구현하지 않는다.

## 검증 명령과 완료 조건

```powershell
python -X utf8 -m pytest src/hmi/dashboard/test src/runtime/api_web/test src/site/fleet/test/test_no_video_relay.py src/site/overhead/test test/test_network_topology_contracts.py test/test_harness_contracts.py -q
python -X utf8 tools/harness/rosy_harness.py lint
```

- Windows에서는 ROS가 필요 없는 계약만 실행한다. 같은 이름의 ROS/pytest 테스트 디렉터리는 프로젝트 지침대로 분리 실행한다.
- SOURCE 완료는 라우트·소유 경계·금지 경로의 시험 통과다. ARTIFACT 완료는 native ARM64와 사이트 이미지 각각의 정확한 revision/digest다. DEVICE/SITE 완료는 실제 Pi·Ubuntu·폰의 프로세스와 네트워크 readback이다. FIELD 완료는 현장 장애·복구와 작업 결과까지 확인한 상태다.
- 단일 단계의 증거로 다른 단계를 승격하지 않는다. D-257/D-268 자동 실행과 D-273 OMX 카메라/집기는 이 계획의 완료 조건에 포함하지 않는다.
- Task 5는 후속 workload가 생길 때 수행하는 결정 게이트다. 현재 `overhead` 구현만으로 Vision의 학습·복잡한 추론·자동 판단이 완성됐다고 표기하지 않는다.


## Execution record - 2026-09-26

- Tasks 1-3 source/local checks completed. Task 4 local contract/error cases were covered by tests; device/site process failure injection remains open because no target host or device was available. Existing routes and ownership boundaries matched D-275; no implementation or protocol change was required.
- Task 5 remains a future workload decision gate. No training, GPU inference, or decision workload was added.
- SOURCE/LOCAL: GO for the checked contracts and tests. ARTIFACT: HOLD pending native aarch64 build and verified inputs. DEVICE/SITE/FIELD: HOLD pending actual host, device, and physical acceptance evidence.
- Detailed commands, results, and gate limits: [validation record](../validation/web-surface-role-boundaries-2026-09-26/README.md).
