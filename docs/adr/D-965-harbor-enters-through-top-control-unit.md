## D-965 외부 업무 앱은 관제 계층의 꼭대기 하나로 들어오고, 팔 작업은 셀로 위임된다

**Status:** Accepted (2026-11-03, 사용자 결정 "권장으로 처리"). 연결 대상과 책임 결정이다. 팔 작업 위임 wire는 미구현이다(아래 「수용 조건」).

잇는 결정: [D-850](D-850-composable-control-units.md) · [D-855](D-855-control-unit-wire-and-scoped-cancel.md) · [D-856](D-856-application-action-boundary.md) · [D-960](D-960-control-unit-per-arm-set-under-integrated-r.md) · [D-963](D-963-usb-camera-role-approval-in-fleet.md). Harbor 쪽 정본은 harborlogi ADR 0018.

### Context

D-960으로 팔은 셀 관제(CELL-A), Pinky는 통합관제 R이 소유한다. Harbor는 Fleet origin을 하나만 가진다. 이송(TRIP)과 팔 작업(cell-app·ARM)의 주인이 달라졌는데, 외부 앱이 어느 관제로 들어오는지 정한 결정이 없었다.

D-855 위임 wire(`ControlNavigationCandidate`)는 `robot_id`·`goal` 주행 후보만 싣는다. 위임을 받은 쪽은 CORE 주행 경로로만 잇는다.

### Decision

1. **외부 업무 앱은 관제 계층의 꼭대기 하나에만 연결한다.**
   - 현장에서는 R이다. 앱의 서비스 principal은 R이 발급한다.
   - 셀 관제는 외부 앱의 직접 연결 대상이 아니다.
   - 한 Fleet이 팔과 Pinky를 함께 소유하는 개발·시뮬레이션 구성에서는 그 Fleet이 꼭대기다.
2. **R은 요청의 주인에 따라 나눈다.**
   - 자기가 소유한 장치(Pinky)의 요청은 직접 접수한다.
   - 셀이 소유한 workcell의 팔 작업은 D-855 위임으로 셀에 넘긴다.
   - 승인·admission·정지 해제는 셀 화면에서 셀의 기명 운영자가 한다(D-960 §2).
3. **장치 식별은 장치 쪽에서 끝난다.**
   - USB에 꽂힌 위치는 owner가 도는 호스트를 정한다. 정지(StopLocal)가 같은 호스트의 local UDS를 쓰기 때문이다.
   - 보드·카메라의 역할은 host inventory와 셀 Fleet의 기명 승인(D-963)이 정한다. 꽂혔다는 사실만으로 역할을 주지 않는다(D-943).
   - 외부 앱과 R은 장치 경로·역할을 받지 않는다.
4. **위임 종류가 생기기 전에는 R이 셀 소유 workcell의 팔 제안을 실행 경로처럼 접수하지 않는다.** 앱은 HOLD로 다룬다.

### 역할 정리

| 층 | Pinky | OMX 암 세트 |
|---|---|---|
| 장치 실행자(최종 명령 하나) | CORE (`/cmd_vel`) | OMX owner (관절·Action) |
| 장치를 묶는 관제(원장·승인·admission) | R이 직접 | 셀 관제(CELL-A), owner와 같은 PC |
| 조정 | R | R (요약·위임·정지 요청만) |
| 업무 | Harbor (R 하나로 연결) | Harbor (R 하나로 연결) |

OMX owner가 Pinky CORE에 해당한다. 같은 PC의 셀 관제는 팔 여러 대의 공유 원장·admission을 맡는 별도 역할이다. CORE에 합치지 않는다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | 새 폴더·파트를 만들지 않는다 |
| D-429 | 셀이 팔 원장·admission을, OMX owner가 관절을, CORE가 `/cmd_vel`을 계속 소유한다 |
| D-430 | 안전은 셀·장치에 남는다. R과 앱은 정지 해제 경로가 아니다 |
| D-855 | 위임 identity·취소 규칙을 그대로 쓴다. 후보 종류에 팔 작업을 더하는 것은 후속 구현이다 |
| D-856 | 앱은 장치를 직접 제어하지 않는다. 진입점만 정한다 |
| D-960 | 계층 구조를 외부 앱 진입까지 이어 적용한다 |

### Alternatives

| 대안 | 판단 |
|---|---|
| 앱이 R과 각 셀에 따로 연결 | 플랫폼 변경 없이 된다. 대신 앱이 셀 구성을 알아야 하고 셀마다 신원이 는다. 채택하지 않는다 |
| 앱이 셀 하나에만 연결 | Pinky 이송의 주인 R을 잃는다. 채택하지 않는다 |
| **꼭대기 하나 + 위임** | D-960 계층과 맞고 앱 설정이 고정된다. 위임 경로 전까지 팔 작업은 HOLD다. **채택** |

### 수용 조건

1. `core_common.protocol.control_units`에 팔 작업 후보 종류가 있고, 계약 시험이 주행 후보와 함께 돈다.
2. 고정 양 끝 Fleet HTTP에서 R 제안 → CELL-A inbox → CELL-A 기명 승인 → CELL-A admission → R 조회가 확인된다.
3. R이 멈춰도 CELL-A는 받은 팔 작업을 정지·조회한다(D-960 수용 조건 5).
4. Harbor 통합 시험이 R origin 하나로 이송과 팔 작업을 모두 낸다.

구현 계획은 `Rosy/docs/superpowers/plans/2026-11-03-harbor-entry-via-r-platform.md` 3절(Git 밖 작업 기록)이다.
