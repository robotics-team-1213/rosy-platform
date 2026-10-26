## D-890 Navigation intent epoch preservation

**Status:** Accepted (2026-10-26). Contract prelude; remote verification and device acceptance remain separate.

### Context

항법 intent에 호출자가 확보한 boot/generation을 추가할 때 문법만 열면 CORE Home 어댑터와 Fleet navigate 실행 경로가 해당 값을 버릴 수 있다. 받아들인 값을 최종 검사 전에 바꾸거나 버리는 계약은 허용하지 않는다.

### Decision

Foundation intent 문법은 navigate/home에만 optional `expected_boot_id`와 `expected_owner_generation`을 받는다. 주어진 값은 UUID 문자열과 bool을 제외한 비음수 정수로 검증하고 그대로 전달한다. 각 필드는 선택적이며 누락에 대한 최종 허용 여부는 기존 실행 owner가 결정한다. CORE `/api/v1/do` Home은 기존 `HomeRequest`로 본문을 전달해 실제 reservation/native 검사를 유지한다.

Fleet navigate의 기존 traffic/Task 인터페이스는 caller epoch를 보존하지 않는다. 따라서 직접 실행과 admission/Task 생성 진입 전에 어느 한 key라도 있으면 `COMMAND_REJECTED`와 `FLEET_NAVIGATION_CALLER_EPOCH_UNSUPPORTED`로 거절한다. 값 없는 기존 경로는 유지한다. Fleet Home의 기존 원본 본문 전달은 유지한다.

`NAVIGATION_ADMISSION_FENCE_VERSION = 1`은 기존 navigation-cancel 계약의 정본 상수이며 schemas에서 재수출한다. 상수 등록만으로 런타임이 해당 fence를 시행한다고 광고하지 않는다. envelope `PROTOCOL_VERSION`은 유지한다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 기존 Foundation·CORE API·Fleet owner 안에서 계약과 소비자만 보완한다. 새 배포 단위를 만들지 않는다. |
| D-429 | Foundation은 leaf를 유지하며 CORE router는 기존 서비스 경계로만 실행한다. |
| D-430 | CORE 최종 명령 권한과 기존 검사 순서를 유지한다. 거절 전 새 실행 효과를 만들지 않는다. |

### Consequences

공유 계약을 제품 변경보다 먼저 착지하면서 필드 유실 경로를 함께 닫는다. 이 결정은 idle cancel epoch 증가, public goal/home mandatory pair, readback marker 광고, managed Fleet/UI qualification이나 lease cleanup을 시행하지 않는다. 전체 항법 admission 개선은 후속 제품 단위로 별도 검증한다. NTP 정확도·네트워크 전달 성공·실제 정지·exactly-once를 보증하지 않는다.
