## D-154 공통 OS 이미지와 장치별 SD 개인화를 분리한다

**Status:** Accepted (2026-09-21). D-15의 `robot_id=rosy_NN`,
`hostname=rosy-NN` 명명 결정 중 사람이 보는 장치명과 hostname 부분을 대체한다.
D-88의 FleetAgent 로봇 이미지 제외/PARKED 결정도 대체한다. 플랫폼명 Rosy 결정,
D-33의 내부 DDS 신원 계약과 D-88의 Site Hub 관제 PC 소유권은 유지한다.

**Context:** D-15는 플랫폼명과 함께 공개 장치명까지 순번에 결합했고, D-33은
`ROSY_ROBOT_NUMBER`에서 ROS domain과 namespace를 파생한다. 이 구성을 SD에 그대로
넣으면 카드 복제 시 여러 장치가 같은 이름과 DDS 신원을 가지며, Pi 또는 SD 교체와
로봇 재번호를 같은 사건으로 오인한다. 반대로 로봇마다 전체 OS 이미지를 다시 만들면
동일 release의 artifact가 장치 수만큼 갈라지고 서명·checksum·rollback 증거를
재사용할 수 없다. 현장 Wi-Fi를 자동 설정해야 하지만 site passphrase를 공통 이미지,
Git, 명령행 또는 감사 로그에 넣을 수도 없다. 마지막으로 Windows에서 drive letter만
보고 SD를 쓰는 절차는 시스템 디스크 오선택을 막지 못한다.

**Decision:**

1. **서명된 기본 이미지는 기종별 공통 artifact다.** Pinky Pro용 Rosy OS 이미지는
   Robot ID, hostname, 현장 Wi-Fi, API token, SSH private key를 포함하지 않는다.
   장치별 값은 이미지 검증과 기록이 끝난 뒤 별도 personalization bundle로만 넣는다.
2. **공개 장치 신원은 세 층으로 분리한다.** 불변 `device_uid`는 UUIDv4,
   사람이 입력하는 `device_name`과 hostname은 `rosy-pinky-<4자리>`, 실제 보드
   결속은 첫 부팅에서 읽은 Raspberry Pi hardware serial이다. 네 글자는 소문자
   영숫자에서 `0`, `o`, `1`, `i`, `l`을 제외한 alphabet으로 생성하고, 등록부와
   현재 네트워크에서 충돌하면 다시 만든다. 짧은 이름은 전역 신원의 대체물이 아니다.
3. **DDS 신원은 공개 이름과 분리해 D-33을 유지한다.** 명시적
   `ROSY_ROBOT_NUMBER=N`이 `ROS_DOMAIN_ID=40+N`, `ROSY_NAMESPACE=rosy_NN`을
   파생한다. 번호에는 기본값이 없고, hostname 또는 4자리 code에서 domain이나
   namespace를 추측·파생하지 않는다.
4. **Windows personalizer는 physical disk를 두 번 확인한다.** disk number,
   bus type, model, serial, size, boot/system/read-only/offline 상태를 계획 시점과
   기록 직전에 비교한다. 사용자가 `ERASE DISK <n> <device_name>`을 정확히 입력한
   뒤에만 signed checksum을 통과한 이미지를 write verification과 함께 기록한다.
   drive letter만으로 대상을 선택하거나 verification을 끄는 경로는 만들지 않는다.
5. **Wi-Fi 자동 주입은 비밀정보 경계를 유지한다.** 운영자 PC의 passphrase는
   저장소 밖 DPAPI 보호 credential에서 읽고 명령행에 넣지 않는다. 카드에는
   PBKDF2-HMAC-SHA1로 파생한 raw WPA PSK만 일회성 bundle에 넣는다. 이 값도
   비밀로 취급하며 readback·receipt·로그에 내보내지 않는다. 첫 부팅은 검증 후
   NetworkManager profile을 mode `0600`으로 설치하고 boot bundle을 소비한다.
6. **첫 부팅은 항상 `core`로 제한한다.** 요청 preset은 의도로만 기록한다.
   최초 bundle 또는 Wi-Fi 후보가 실패하면 후보를 폐기하고 `PROVISIONING_AP`로
   돌아가며 motor/hardware를 시작하지 않는다. 이미 provisioned인 장치의 일반
   WLAN 장애는 D-26대로 `NETWORK_HOLD`이고 자동 recovery AP를 열지 않는다.
   (2026-09-24: 첫 부팅 Wi-Fi 후보는 재시도 예산 뒤에도 폐기하지 않는다 — D-176의 "첫 부팅 현장 Wi-Fi 보완" 노트.)
7. **개인화는 Fleet 가입 준비까지 포함하되 군집 운용 완료로 간주하지 않는다.**
   bundle은 site별 `fleet_endpoint`, trust profile과 pairing 필요 여부를 장치 신원에
   결속한다. 일회용 pairing credential이 필요하면 Wi-Fi PSK와 같은 transient secret
   경계에서만 전달하고 적용 후 제거한다. 공통 Pinky 이미지는 비활성 FleetAgent
   코드를 포함하고, 유효한 장치별 bootstrap과 pairing이 있을 때만 outbound 연결을
   연다. 로봇은 Fleet에 WebSocket으로 heartbeat/event를 보내고 인증된 REST API
   명령을 받는다. 로봇 간 DDS 통신은 요구하거나 열지 않으며 DDS는 로봇 내부로
   격리한다. Fleet 등록 성공만으로 motor, mission, formation을 자동 활성화하지 않는다.
8. **증거는 SOURCE, ARTIFACT, MEDIA, BOOT, DEVICE, FLEET로 분리한다.** 호스트 테스트,
   native ARM64 image, SD write/readback, Pi 부팅, Pinky Pro G0–G5, 두 대 이상 Fleet
   연동 중 어느 하나도 다른 단계를 대신하지 않는다. FLEET은 서로 다른 신원의 Pinky
   두 대 이상에 대해 등록, heartbeat, 상관 ID가 있는 명령 응답, 재접속, 통신 단절
   안전 정지와 군집 시나리오를 확인해야 GO다.

**Alternatives:** 장치별 완성 이미지는 artifact와 서명 단위를 불필요하게 분기해
기각한다. `rosy_01`을 공개 hostname으로 계속 쓰는 안은 재번호와 하드웨어 교체를
장치 정체성과 결합해 기각한다. 4자리 이름을 ROS namespace/domain으로 사용하는
안은 충돌과 운용 진단을 어렵게 하고 D-33을 깨므로 기각한다. 평문 passphrase를
boot 파티션이나 PowerShell 인자에 쓰는 안은 복구 가능한 비밀을 로그·shell history와
이동식 매체에 남겨 기각한다.

**Consequences:** 장치 목록은 `rosy-pinky-k7m4`처럼 플랫폼→기종→개체 순서로
정렬되고, 향후 다른 Rosy 기종도 같은 taxonomy를 쓸 수 있다. 짧은 이름 충돌을
전역 UUID, 등록부, 첫 부팅 serial binding으로 보완해야 한다. raw WPA PSK는 평문
passphrase보다 노출을 줄이지만 약한 비밀번호의 오프라인 추측 위험을 제거하지
않는다. D-15의 플랫폼명 Rosy와 D-33의 내부 번호 계약은 계속 유효하다.
장치별 Fleet bootstrap은 향후 endpoint나 인증서를 교체할 수 있어야 하며,
`device_uid`를 바꾸는 수단으로 사용하지 않는다. SD 개인화 완료는 Fleet 페어링이나
군집제어 인수 완료를 뜻하지 않는다.

**Validation / Transition:** `test_sd_personalization.py`는 이름 alphabet, UUID,
등록 충돌, manifest와 secret redaction을 고정한다. `test_sd_writer_contract.py`는
비파괴 `-PlanOnly`, disk drift와 erase 확인을 검증한다.
`test_first_boot_provisioning.py`는 원자 적용, mode `0600`, one-shot 소비,
serial binding과 네트워크 fallback을 검증한다. native ARM64 image와 현재 연결된
SD/Pi 실행 증거가 생기기 전에는 ARTIFACT, MEDIA, BOOT, DEVICE를 GO로 쓰지 않는다.
`test_fleet_enrollment_contracts.py`는 endpoint/trust binding, outbound-only 가입,
secret redaction과 DDS 격리를 고정한다. 서로 다른 Pinky 두 대의 Fleet FAT/MAT 증거가
생기기 전에는 FLEET을 GO로 쓰지 않는다.

**References:** D-5, D-6, D-15, D-20, D-22, D-26, D-30, D-33, D-36, D-46, D-53,
D-59, D-66, D-78, D-81, D-83, D-88,
`docs/spec/ROSY FLEET SRS.md`,
`docs/plans/2026-09-21-rosy-sd-personalization-design.md`,
`docs/plans/2026-09-21-rosy-sd-personalization.md`.

---

## [ADR-999] Interface Philosophy Refinements: Core State Abstraction & Fallback Patterns

**Date:** 2026-09-21
**Status:** Accepted
**Context:** 16_ROSY_Interface_Design_Principles.md lacks headless state abstraction to prevent duplicate logic across surfaces, missing degraded AI fallback capabilities, and lacks cross-surface HITL handoff standards.
**Decision:** 
1. Introduce Headless State Primitives (L1.5 Layer) for Law 0 logic without forcing shared visual components.
2. Add `degraded_fallback` capability state.
3. Standardize HITL escalation across all four UI surfaces.
**References:** docs/plans/2026-09-21-interface-philosophy-refinement-design.md, [concept 16](../concept/16_ROSY_Interface_Design_Principles.md).

---

## [ADR-1000] Fleet Orchestration for Module Degraded & HITL States

**Date:** 2026-09-21
**Status:** Accepted
**Context:** The degraded_fallback and hitl_requested states defined in ADR-999 need explicit handling in the Fleet SRS to prevent the Fleet from mistakenly treating them as standard OFFLINE errors, and to utilize them for mission re-routing.
**Decision:** 
1. **Exceptional Teleop Handoff (PRT-1.2):** Allow Fleet to unlock WebRTC teleop control only when hitl_requested is true (overriding the strict no-motor-control rule).
2. **State Queues (MON-002):** Implement a 'Degraded' warning queue and a 'Requiring Assistance' critical popup queue.
3. **Mission Re-routing (MSN-004):** Fleet dynamically re-assigns tasks if a robot's capability degrades.
4. **Formation Speed Adjustment (FOR-004):** Down-sync swarm speed to the slowest degraded robot.
**References:** ROSY FLEET SRS.md (PRT-1.2, MON-002, MSN-004, FOR-004).
## [ADR-1001] Fleet UI/UX Exception-Based Queue Adherence & Token System Convergence

**Date:** 2026-09-21
**Status:** Accepted
**Context:** During the implementation of the Degraded and HITL Monitoring Queues in the Fleet Console, an initial design showed empty alarm boxes during normal operation. This violated ROSY's 'Management by Exception' principles (Law 8) and zero-alarm-color normal state rule (Law 1, g3-checklist.md). Additionally, the queues used hardcoded colors instead of the central /ui/tokens.css.
**Decision:**
1. **DOM Display Toggling:** The Monitoring Queues container sets `display: none`
   dynamically when no robot has `hitl_requested` or degraded capabilities.
   This enforces zero alarm colours in the Fleet Console during nominal states.
2. **Token Compliance:** CSS uses only variables mapped from `tokens.css`
   (for example `--status-warn`, `--status-crit`, `--ground-card`,
   `--ground-raise`, and `--paper`).
**References:** docs/validation/uiux-surfaces-2026-09-21/g3-checklist.md, ADR-1000.
