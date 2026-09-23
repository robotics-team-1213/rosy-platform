## D-46 Device 설치 후 readback 증거 계약

**Status:** Accepted (2026-09-13). 소프트웨어 증거 형식의 결정이며 실제 Pi와
Pinky Pro 현장 인수 상태와 구분한다.

**Context:** Pi에 Rosy OS를 설치한 뒤 SSH 성공, HTTP 200, 컨테이너 실행만으로는
어떤 OS·identity·release·image가 실제로 부팅되었는지 재현할 수 없다. 환경 파일에는
API credential이 있어 그대로 수집할 수 없다.

**Decision:** `deploy/robot/verify/device-readback.sh`가 표준 JSON readback을 만든다.
readback은 OS/model/architecture, 로봇 번호·DDS domain·namespace, activation record,
서명된 manifest의 git revision·immutable container digest, systemd/core health,
ROS node와 최종 `cmd_vel` publisher 수를 포함한다. `.env` 전체와 credential은 포함하지
않는다. `device_runtime`은 ARM64 identity·manifest·healthy core·graph가 모두 확인될
때만 GO이고, 물리 주행 `field` gate는 별도로 HOLD로 남긴다.

**Alternatives:** 설치 로그만 보관하거나 dashboard 상태만 캡처하는 안은 재부팅 후
동일 release와 graph를 확인할 수 없고 secret 경계를 보장하지 못하므로 채택하지 않는다.

**Consequences:** installer는 readback 도구를 `/opt/rosy/deploy/robot`에 설치하고
`verify-pi.sh`가 명령을 안내한다. readback 성공은 ARM64 artifact publication이나
Pinky Pro/OMX 물리 인수를 대신하지 않는다.

**Validation / Transition:** fake Device filesystem을 이용한 단위 계약과 AMD64
container package smoke를 CI에서 실행한다. 실제 Pi에서는 설치·재부팅·rollback 뒤
JSON을 release evidence와 함께 보관하고, graph/publisher·모터·카메라·OMX는 D-39와
D-44의 별도 commissioning gate로 승격한다.

**References:** [Device 검증 실행 계획](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md), [Pi runtime](../deployment/raspberry-pi-runtime.md), [ARM64 빌드 메모](../deployment/arm64-build-notes.md).

---
