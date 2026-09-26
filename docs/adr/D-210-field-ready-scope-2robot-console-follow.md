## D-210 실사용 1차 범위 — 2대 관제+군집을 실물 1대+시뮬 1대로 닫는다

**Status:** Proposed (2026-09-25).

**Context:**

1. "실사용 가능"의 범위가 정해지지 않으면 게이트 판정이 흔들린다. `STATUS.md`는 SOURCE/LOCAL GO, ROS-SIM/ARTIFACT/DEVICE HOLD, FIELD PARKED이며, 중앙 Fleet `:8081`(미션·페어링·추적)은 미구현이다.
2. 사용자 결정(2026-09-25): 1차 목표는 **2대 관제+군집**, 충전도크·신호등은 제외, 빌드 호스트는 **Pi 5 1대 네이티브**다.
3. 물리 장비는 Pi 5 1대뿐이므로 실물 2대 FIELD는 지금 증명할 수 없다. 2대 묶음은 **실물 1대 + 시뮬 1대**로 먼저 닫아야 한다.

**Decision:**

1. 1차 `FIELD READY`의 범위를 `(fleet console 관제 + formation 2대, 실내 단일 맵, 실물 1대 + sim 1대)`로 고정한다. 범위를 생략한 전역 `FIELD READY`는 만들지 않는다(수용 기준 §2.2).
2. 포함: CORE 게이트웨이, Nav2 goal/cancel/home, teleop, e-stop, Fleet console gather/scatter(goal/cancel/전체정지), formation relay + FOR-004 HOLD/ABORT, 배터리 실측.
3. 제외(1차): 충전도크 실물(`DOCK_GO`), 신호등 실물 수용, OMX 암, 중앙 Fleet `:8081` 미션/페어링/PRT-004 추적, emotion/lamp/led/imu 제품 편입(D-169 유지).
4. 제외 항목은 capability 미광고 + disabled 프로파일로 두며, 데모 성공으로 승격하지 않는다.
5. 실물 2대 반복 FIELD는 2호기 확보 후 D-210 후속 ADR로만 연다. 그 전까지 해당 판정은 PARKED다.

**Consequences:** D-211~D-213의 모든 게이트는 이 범위를 기준으로 판정한다. 범위를 넓히는 변경은 D-210을 `Superseded`로 바꾸고 새 ADR을 추가한다(기존 문서 수정 금지).

**Validation:** 문서 결정이다. `docs/reference/ROSY Module Operational Acceptance Criteria.md` §8 M07/M11/M12/M14의 1차 추적표가 이 범위를 가리키면 충족이다.

**References:** D-169(장치 표면), D-170(PRT-004 연기), D-81(console gather), D-31(릴레이), 수용 기준 §2.2/§8.
