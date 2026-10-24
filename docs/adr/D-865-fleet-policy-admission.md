## D-865 Fleet 정책 승인 — 사람이 정한 승인 범위 안 작업 자동 승인

**Status:** Proposed (2026-10-25). 방향을 확정한다(사용자 2026-10-25: 자동 승인의 주체는 Fleet 정책이고 업무 앱은 제안만 한다). 구현·게이트 활성화·현장 수용은 별도 단계이며 이 문서가 `FleetTaskService.POLICY_DISPATCH_ENABLED=False` 기본값이나 MSN-006 승인 등록부의 현재 동작을 바꾸지 않는다.

**관련:** D-674 · D-678 · D-685 · D-836 · D-856 · Harbor ADR 0004 A11 (MSN-006 · MSN-007 · SEC-204 · UI-WORK-001)

### Context

- 사용자 요구(2026-10-25): 매 작업마다 사람이 승인 버튼을 누르지 않아도 되는 자동 승인이 있어야 한다. 자동 승인의 주체는 Fleet 정책이고, 업무 앱(Harbor)은 제안만 한다(사용자 확정, Harbor ADR 0004 A11 같은 날).
- 현재 상태: Mission/Cell Job의 admit은 사람 operator가 승인 등록부 규칙(MSN-006)에 따라 누른다. 정책 Task 경로는 `FleetTaskService.POLICY_DISPATCH_ENABLED=False`로 닫혀 있고(D-678 14항), D-685의 `fleet.stuck_resolver.autonomous_robots` 승인 범위는 복구 경로에만 적용된다. 규칙집의 자율 운영 목표("사람이 목표와 승인 범위를 정하면 Fleet이 일상 관측·판단·실행")가 이미 이 방향을 서술한다.
- 빈 곳: "사람이 정한 승인 범위"가 복구가 아닌 **작업 접수(admit) 단계**에 성립하는 계약이 없다. 업무 앱의 제안이 사람 클릭 없이 실행되려면 이 범위 계약이 먼저여야 한다.

### Decision

#### 1. 승인 권한 소유

승인(admit) 권한은 Fleet이 소유한다. 업무 앱은 자기 제안을 스스로 승인하지 않고 승인 범위 정의·정책 설정 화면을 갖지 않는다. 자동 승인은 "앱이 승인한다"가 아니라 "사람이 정한 범위의 Fleet 정책이 사람과 같은 admission 검사를 통과한 제안을 승인한다"이다.

#### 2. 승인 범위(scope)

사람(named operator 이상)이 승인 범위를 정하고 Fleet이 보관·readback한다. 범위는 최소한 다음을 담는다(정확한 스키마는 실행 계획에서 정한다).

- 대상: 로봇·셀, 작업 종류(1차는 이송 등 drive-only 한 종류씩)
- 조건: 근거 신선도, 관측·계획 revision 일치, 자원·통행 admission 통과
- 상한: 작업 수·기간(소진 시 자동 대기, 초기화 없음 — D-685 예산 규칙과 같은 원칙)
- 존속: 사람이 언제든 해제. 해제는 stop generation으로 새 작업만 막고 진행 중 작업을 소급 무효화하지 않는다.

보관은 `fleet.stuck_resolver.autonomous_robots`와 같은 사이트 설정 형식에서 시작하고, 콘솔 readback을 함께 둔다. 범위 변경은 감사 기록으로 남는다.

#### 3. 자동 admit의 조건

자동 admit은 사람 admit과 **같은 검사를 전부** 통과한 뒤에만 일어난다: 승인 등록부의 종류 규칙, generation·재해석 검사(MSN-006), trip lease·claim·ttl 순서(MSN-007), 자원·stop fence admission(FL-RESOURCE·FL-FENCE), 전송 직전 재검사(D-678). 자동 승인은 검사를 줄이지 않고 사람 클릭을 대체할 뿐이다.

#### 4. 우회 불가

규칙집의 law(FL-ESTOP·FL-HUMAN·FL-UNKNOWN·FL-ONLINE·FL-CALIBRATION·FL-TRIP·FL-CASE)는 승인 범위로 해제할 수 없다. 사람 점유·E-stop·UNKNOWN은 자동 admit 이후에도 기존 인계·정지 경로로 사람에게 돌아간다.

#### 5. 단계적 범위

- 1차: 승인 등록부 `one_person`(drive-only) 종류의 Mission/Cell Job. 업무 앱 제안이 사람 resolve를 거친 뒤 승인 대기인 것을 범위 안에서 자동 admit한다.
- 제외 유지: `two_person`(팔 단계)과 legacy `proposer_only`의 자동 승인은 이 문서가 열지 않는다. 팔 단계 자동 승인은 별도 승인과 safety 검토를 받아 확장한다.
- Task 정책 경로(`POLICY_DISPATCH`)의 활성화는 이 문서와 별도로 D-678의 기본 게이트 규칙을 따른다.

#### 6. 기록·감리

자동 admit은 사람 admit과 같은 원장에 actor가 정책 principal(범위 근거·범위 revision 포함)로 기록된다. 화면 표시는 `auto_hold:<reason>`과 같은 접두 방식으로 자동 승인 사실을 구분해 보여 준다.

### Consequences

- MSN-006·MSN-007·UI-WORK-001의 보완이 필요하다: 승인 등록부에 "정책 범위 승인" 경로, 범위 설정·해제 API, 감사 표시. SRS와 API reference·`core_common.protocol` 스키마는 실행 계획에서 한 세트로 바꾼다(D-18).
- 구현이 `dispatch_admission.py`, `task_dispatch_routes.py`, `console.py`, `cancel_all.py`, `goal_lease.py` 등 safety 태그 파일을 만지는 커밋은 `Safety-Review:` trailer와 독립 리뷰가 필요하다(D-430 §5). 이 문서 자체는 docs 변경이므로 해당하지 않는다.
- 업무 앱 문서(`application-contract-support.md`)의 "승인·거절" 행 의미가 "operator 사람"에서 "사람 또는 사람이 정한 승인 범위의 Fleet 정책"으로 보강된다. 앱의 자기 승인 금지는 유지된다.
- 구현·원격 회귀·착지는 현장 활성화 증거가 아니다. 활성화는 범위 설정 readback과 첫 실제 자동 admit의 원장 대조로 별도 수용한다.

### 구현 순서

1. 실행 계획 수립(범위 스키마, 승인 등록표 연결, 설정·readback, 감사 표시, 회귀 목록) — [실행 계획](../plans/2026-10-25-fleet-policy-admission-design.md)
2. SRS·API reference·스키마 보완(버전 선점 포함)
3. 서버 구현과 콘솔 readback, 회귀 시험(safety 태그 경로는 독립 리뷰)
4. 시험 PC 원격 회귀 후 착지, 현장 범위 설정·수용 기록
