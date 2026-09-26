## D-274 로컬 브라우저 검토는 실제 CORE 경로를 쓰고 장치 수용은 분리한다

**Status:** Accepted (2026-09-26). 로컬 화면/API 통합 검토의 결정이며 ROS-SIM, ARTIFACT, DEVICE 또는 FIELD 수용을 대신하지 않는다.

**Context:** 역할 메뉴와 패널은 `src/hmi/dashboard/panels.yaml` 및 `src/runtime/api_web`의 인증된 `/api/v1/ui/surfaces/{surface}` 계약으로 연결된다(D-243, D-263, D-265). 화면만 띄우는 API 목업은 배치와 빈 상태를 보는 데 쓸 수 있지만, 실제 인증·권한·CORE 상태·명령 차단을 확인하지 못한다. 특히 브라우저 캡처를 실제 로봇 동작 증거로 혼동하면 안 된다.

**Decision:**

1. `/console`, `/setup`, `/device`의 통합 브라우저 검토는 실제 `create_app()` 라우터와 `CoreServices`를 사용한다. 화면 목록은 실제 role manifest에서 읽고, 해당 검토의 완료 증거에는 요청 가로채기 기반 API 목업을 사용하지 않는다. 컴포넌트 단위 상태 시험은 별도 테스트에서 목업을 쓸 수 있다.
2. 로봇이 연결되지 않은 개발 PC에서는 `runtime.mode=core`로만 로컬 검토한다. Fleet 연결을 끄고, 수명이 짧은 수동 검토 자격 증명은 메모리에서만 만들며, 서버는 loopback에만 연다. 상태 파일은 작업 임시 경로에 둔다.
3. CORE capability gate가 이동·위치화 기능을 차단하고 화면은 그 차단 이유를 표시한다. 이 환경에서 E-Stop API가 요청을 받더라도 그것은 API 수신 증거일 뿐 물리 정지 증거가 아니다. 실제 동작은 ROS-SIM 및 장치별 관측, 설치 버전·이미지 digest와 물리 정지 readback을 각 gate에서 따로 입증한다.
4. 로컬 브라우저 캡처는 인증, 역할별 메뉴, 패널 mount, API readback, 레이아웃만 증명한다. 어떤 운용 동작이 실제 장치에서 완료되었다고 기록하지 않는다.

**Consequences:** UI 표면과 API 권한의 소유 경계는 D-243 및 D-263/D-265 그대로다. 이 ADR은 새 메뉴나 병렬 API를 만들지 않고, 통합 검토의 입력 경로와 증거 범위만 고정한다. 미연결 상태는 실제 CORE의 `available/stale/blocked` 응답으로 표현하며, 편의상 성공 응답을 반환하는 가짜 backend를 완료 증거로 쓰지 않는다.

**Validation:** 2026-09-26 Windows 로컬 검토에서 실제 FastAPI + `CoreServices.build()` CORE 경로를 loopback으로 실행했다. `/api/v1/ui/surfaces/console`, `/api/v1/auth/whoami`, `/api/v1/system/info`, `/api/v1/robot/state`가 모두 HTTP 200을 반환했고, 실제 Playwright Chromium에서 세 표면을 mount했다. 이 검토는 ROS graph·Pi 이미지·실물 정지를 실행하지 않았다.

**References:** [D-243](D-243-operator-screens-live-in-hmi.md), [D-263](D-263-role-based-menu-extension.md), [D-265](D-265-base-surfaces-and-stop-access.md), [역할별 메뉴 구현 계획](../plans/2026-09-26-role-menu-rollout.md).
