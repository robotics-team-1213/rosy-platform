## D-938 팔 이송 정책 승인 — D-865 승인 범위를 ARM_TRANSFER로 확장

**Status:** Accepted (2026-10-31, 사용자 결정 "팔 자동 승인 범위 확장을 처리해").
- 구현 범위: 서버 판정·admit 경로·계약·시험이다.
- 활성화 조건: 범위를 설정하고 첫 자동 admit의 원장을 대조하는 일은 현장 수용으로 따로 기록한다.
- profile: simulation 전용 팔 이송 HTTP(`/api/fleet/arm-transfers/jobs`)에서만 동작한다.

**관련:** D-865 · D-856 · D-763 7항 · D-678 · D-430 §5 · Harbor ADR 0017(화물 재배치 자동 실행)

### Context

- D-865는 정책 승인을 `one_person`(drive-only)으로 열었다. 팔 단계는 "별도 승인과 safety 검토를 받아 확장한다"고 남겼다(결정 5).
- Harbor ADR 0017은 화물 재배치(R2)를 사용자가 정한 허용 범위 안에서 자동 실행하기로 했다. Harbor의 팔 이동은 `ARM_TRANSFER` 작업(`PhysicalTransferStore`)으로 제안된다.
- 이 작업의 사람 admit은 다음 순서로 진행된다.
  1. 제안자와 다른 기명 operator(`two_person`)가 승인한다.
  2. 참여 팔 capability를 새로 읽는다.
  3. snapshot·정지 세대·capability 신선도(전후 두 번)·자원 claim·원장을 한 트랜잭션에서 검사하고 기록한다.
- D-865 자동 admit worker는 Mission 제안만 보므로, 팔 이송은 사람 클릭 없이는 멈춘다.
- 조사 중 D-865 core가 `valid_until`을 읽기만 하고 판정에 쓰지 않는 것을 확인했다. 만료된 범위도 계속 승인할 수 있었다.

### Decision

1. **범위 종류:** `step_approval_kinds`에 `arm_transfer`를 더한다.
   - `arm_transfer`는 `PhysicalTransferStore`의 `ARM_TRANSFER` 작업만 뜻한다.
   - `two_person`인 `CELL_TRANSFER`와 legacy `proposer_only`는 계속 열지 않는다.
2. **필수 범위 항목:** `arm_transfer`를 담은 범위는 다음을 모두 가져야 한다. 하나라도 없으면 설정 오류로 fail-closed다.
   - `robots`: 참여 팔 instance ID
   - `proposers`: 자동 승인을 받을 수 있는 제안 principal
   - `valid_until`: timezone이 있는 시각
   - `max_admits`
   
   작업의 모든 참여 팔이 `robots`에 있어야 한다.
3. **두 번째 사람:** `two_person`의 두 번째 사람은 그 Fleet 프로세스에서 범위를 켠 기명 operator다.
   - 사이트 설정의 기본 활성만으로는 팔 작업을 승인하지 않는다(`SCOPE_NOT_ACKNOWLEDGED`). 실행 중에 기명 operator가 `POST /api/fleet/policy-admission`으로 켜야 한다.
   - 켠 operator는 readback `enabled_by`로 보인다.
   - 제안자는 `proposers`에 있어야 하고(`PROPOSER_OUT_OF_SCOPE`), 켠 operator와 같을 수 없다(`PROPOSER_IS_ENABLER`).
   - 사람 operator의 제안은 범위에 없는 한 자동 승인하지 않는다.
4. **같은 검사:** 자동 admit은 사람 admit과 같은 `PhysicalTransferStore._admit`을 탄다.
   - 차이는 두 가지뿐이다. 신원은 정책 principal(`fleet-policy-admission`)이고, 기대 digest·세대는 같은 트랜잭션 안의 현재 값이다.
   - capability는 사람 route와 같은 함수로 매번 새로 읽는다.
   - 성공하면 사람 admit처럼 dispatcher를 준비한다.
   - 원장 이벤트에는 `policy_scope_revision`과 `policy_enabled_by`가 붙는다.
5. **팔 단계의 보수성:**
   - 한 틱에 팔 작업 1건만 admit한다.
   - 다른 작업이 참여 팔 자원을 쥐고 있으면 claim 거절로 HELD가 되고 다음 틱에 다시 판정한다.
   - 같은 HELD 사유는 바뀔 때만 감사에 남긴다.
   - 범위 판정(스위치·만료·켠 운영자·상한)은 admit 트랜잭션 안에서 commit 직전에 한 번 더 한다. 사유가 생기면 승인 전체를 되돌린다.
   - 한계: 상한은 commit 뒤 감사 기록으로 센다. commit과 감사 기록 사이에 프로세스가 죽으면 그 1건이 세어지지 않아 `max_admits`를 1 넘을 수 있다. 원장 이벤트에는 남으므로 현장 수용 대조에서 확인한다.
   - 범위를 끄면 새 승인만 막는다. 진행 중인 팔 동작은 기존 정지·복구 경로를 따른다(팔을 뻗은 채 토크를 끊지 않는다).
6. **만료:** `valid_until`이 지나면 모든 종류가 `EXPIRED`로 닫힌다. readback도 `reason=EXPIRED`, `admits_remaining=0`이다. 이것은 D-865의 drive-only 범위에도 적용하는 수정이다.
7. **우회 불가:** 규칙집 law(FL-*)·E-stop·정지 세대·사람 점유·UNKNOWN 인계는 D-865 결정 4대로 범위로 해제할 수 없다.

### Consequences

- 계약은 API v1.335다. `PolicyAdmissionScope.step_approval_kinds`에 `arm_transfer`, `PolicyAdmissionScope.proposers`, `PolicyAdmissionStatus.enabled_by`를 추가한다.
- 새 판정 모듈 `operations/fleet/fleet/server/work/arm_transfer_policy_admission.py`는 safety 모듈로 등록한다. 이 변경 커밋은 `Safety-Review:` trailer와 독립 리뷰를 받는다(D-430 §5).
- 실물 profile은 이 결정으로 열리지 않는다. 팔 이송 HTTP가 실물 profile에서 열릴 때, 정책 승인도 그 profile의 현장 수용(범위 readback, 첫 자동 admit 원장 대조)을 따로 기록한 뒤에만 켠다.
- Harbor는 자기 제안을 승인하지 않는다. Harbor ADR 0017의 자동 실행은 이 범위 안에서 Fleet이 승인할 때만 진행된다.

### 검증

다음 경우를 원격 회귀로 확인한다(`operations/fleet/test/test_arm_transfer_policy_admission.py` 등).
- 범위 밖 제안자, 켠 operator와 같은 제안자, 정지 세대 닫힘, capability 만료, 팔 자원 점유, 이미 승인된 작업을 각각 거절한다.
- 정책 principal이 아닌 actor는 기명 operator 확인을 건너뛸 수 없다.
- 사람이 켜지 않은 범위에서는 승인하지 않는다.
- 만료된 범위는 모든 종류에서 막힌다.
- 한 틱에 1건만 승인하고 상한을 지킨다.
- 사람 admit 경로에 회귀가 없다.
