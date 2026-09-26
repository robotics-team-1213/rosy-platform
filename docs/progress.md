---
module: docs
logical_modules: []
owner: 거버넌스
last_verified: { commit: "uncommitted", date: 2026-09-23 }
gates:
  SOURCE:
    state: GO
    evidence: "D-61 Accepted, D-72/D-77/D-153/D-154 본문·색인 일치. SD 개인화 설계/실행 계획 정렬; focused ADR/network 계약 검증 (2026-09-21 Windows); D-169/D-170 추가 (2026-09-22); D-177/D-181 Proposed 추가 (2026-09-23, 구 D-176은 origin과 번호 충돌로 이명 — D-180은 perf/sd-single-verify 브랜치 선점); D-178 Accepted 승격 — 2차 회차 완료+기준선 갱신 (2026-09-23)"
    cmd: "python tools/harness/rosy_harness.py lint"
  LOCAL:
    state: GO
    evidence: "85 passed (2026-09-23 Windows). test_network_topology_contracts + test_harness_contracts + test_module_scorecard + test_module_structure"
    cmd: "python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py test/test_module_scorecard.py test/architecture/test_module_structure.py -q"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-17, D-18, D-45, D-61, D-72, D-75, D-77, D-78, D-79, D-80, D-81, D-82, D-83, D-84, D-85, D-86, D-87, D-88, D-89, D-90, D-91, D-92, D-93, D-94, D-95, D-96, D-97, D-98, D-99, D-100, D-101, D-102, D-103, D-104, D-105, D-106, D-107, D-108, D-109, D-110, D-111, D-112, D-113, D-114, D-115, D-116, D-117, D-118, D-119, D-120, D-121, D-122, D-123, D-124, D-129, D-130, D-131, D-132, D-133, D-141, D-144, D-145, D-151, D-152, D-153, D-154, D-155, D-156, D-157, D-158, D-159, D-163, D-164, D-165, D-166, D-167, D-169, D-170, D-172, D-177, D-178, D-181, D-182, D-183, D-184, D-186, D-246, D-256, D-263, D-265, D-271]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-17-interface-design-implementation-design.md
  - docs/plans/2026-09-17-remaining-gates-adr-plan.md
  - docs/plans/2026-09-17-remaining-runtime-adr-plan.md
  - docs/plans/2026-09-17-remaining-execution-adr-plan.md
  - docs/plans/2026-09-18-rosy-games-remaining-adr-plan.md
  - docs/plans/2026-09-20-ui-grammar-boundary-plan.md
  - docs/plans/2026-09-20-fleet-console-ops-plan.md
  - docs/plans/2026-09-21-hardware-mapping-g5-design.md
  - docs/plans/2026-09-21-hardware-mapping-g5.md
  - docs/plans/2026-09-21-semantic-road-control-design.md
  - docs/plans/2026-09-21-semantic-road-control.md
  - docs/plans/2026-09-21-camera-preview-dashboard-design.md
  - docs/plans/2026-09-21-camera-preview-dashboard.md
  - docs/plans/2026-09-21-rosy-sd-personalization-design.md
  - docs/plans/2026-09-21-rosy-sd-personalization.md
  - docs/plans/2026-09-21-module-coupling-consistency-plan.md
  - docs/plans/2026-09-22-pinky-pro-flashable-image-design.md
  - docs/plans/2026-09-22-pinky-pro-flashable-image.md
  - docs/plans/2026-09-26-role-menu-rollout.md
  - docs/plans/2026-09-26-site-task-scheduling-and-broker-design.md
  - docs/plans/2026-09-26-site-task-scheduling-and-broker-implementation.md
---
## 지금 상태

- ROS-SIM/ARTIFACT/DEVICE/FIELD는 docs가 문서 모듈이라 N/A다.
- D-61 Accepted. 모듈 progress/logs와 생성 index/STATUS가 계약 시험으로 산다.
- concept 16과 D-72 L1·증거·capability 계약이 live다. 운용자 콘솔은 CORE `/dashboard` 하나(D-77). G4 DEVICE는 HOLD (D-80).
- D-263은 메뉴 추가 판단과 탐색 원칙을 정한다. 역할별 화면 이관(D-204)은 별도 브랜치 작업이며 현재 `/dashboard`의 대체 구현 증거는 없다.
- D-265는 역할상 허용된 기반 화면을 패널 수와 분리하고 WEB-002의 기존 항목을 새 화면에 배치한다. 구현 순서는 `2026-09-26-role-menu-rollout.md`에 있다.
- UI/UX 평가 기준은 D-153(세 계층 G1/G2/G3, 판정 단위 표면)이다. 첫 회차(`docs/validation/uiux-surfaces-<date>/`) 전에는 표면 UI/UX 판정을 GO로 쓰지 않는다.
- 남은 게이트는 D-78–D-81이 가른다. ARTIFACT는 네이티브 Pi(D-78). 옛 ROS-SIM GO는 무효(D-79). Fleet 콘솔 v1 gather는 REST(D-81).
- D-154는 공통 Pinky 이미지와 장치별 identity/Wi-Fi/Fleet bootstrap을 분리한다. 현재 CORE `FleetAgent`와 Hub listen 경로는 미구현이므로 두 대 실기 등록·heartbeat·명령·재접속·단절 HOLD를 보기 전까지 FLEET은 HOLD다.
- D-164는 Pinky Pro 제품 파일을 ISO가 아닌 서명된 Raspberry Pi raw disk image
  `rosy-os-pinky-pro-<release-id>-arm64.img.xz`로 고정한다. `.img.xz` 생성, offline
  signature, read-only mount 검증과 full-media readback은 서로 다른 증거다.
- ADR 로그 분리(개별 `docs/adr/D-NNN-*.md`)는 보류한다.

## 다음 gate

1. ARTIFACT/DEVICE는 deploy·rosy_core gate가 소유한다. docs가 GO로 옮기지 않는다.
2. ADR 개별 파일 분리는 후속이며 이 Log 본문은 유지한다.

## 현재 유효한 금지사항

- ADR은 append-only다: 기존 D-n 본문을 고쳐 쓰지 않고 `Superseded`로 표시한 뒤 새 ID를 만든다. 어휘 정정(D-72 S7)은 예외로 기록했다.
- API 경로·envelope 변경은 `reference/ROSY API & Protocol Reference.md`와 `rosy_core/protocol/schemas.py`를 함께 바꾼다(D-18).
- `docs/`에 구현 코드를 두지 않는다.
- 모듈 `index.md`와 루트 `STATUS.md`는 생성물이다. `tools/harness/rosy_harness.py generate`로만 갱신한다.

## Site Fleet task scheduler (2026-09-26)

- Durable SQLite task acceptance, single-dispatcher claims, traffic-wait identity, expiry, queued cancellation, and console readback are implemented under D-271.
- Evidence: 485 Fleet tests passed, 5 skipped; 13 Chromium browser tests passed. Docker Compose config validated, Fleet image built, and a loopback container preserved a queued task across restart on its named volume.
- Broker decision: Gate A has no measured independent-worker/backlog requirement. Keep SQLite and defer RabbitMQ.
- Ubuntu/SITE/TLS, full Compose, real CORE, robot, GPU, DEVICE, and FIELD acceptance remain open. Automatic policy dispatch remains HOLD.
- Detailed record: `docs/validation/2026-09-26-site-task-scheduler-local.md`.
