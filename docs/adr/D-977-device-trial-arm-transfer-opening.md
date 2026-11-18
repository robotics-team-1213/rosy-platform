## D-977 `device_trial`에서 승인된 ARM 이송을 단일 팔 하달로 잇는다

**Status:** 부분 Accepted (2026-11-04). 사용자 결정(2026-11-04): "ROSY 실물 ARM 경로를 지금 열기 시작"(구현·원격 시험·착지 승인, 첫 실물 동작은 사용자 입회), "업무 완료 근거는 자동 생산자 전까지 기명 현장 운영자 확인".

- **Accepted (Fleet 쪽 개방, v1.362):** Decision 1~3(같은 경로 재사용, `device_trial` 단일 팔 한정과 `production` 닫힘, 모듈 수준 owner identity 함수 `fleet/server/device_identity.py`)과 Decision 5의 `operator_attested` 수신(아래 wire). 설정의 `commissioning_revision`은 `omx_cell_grant_revisions`에서 가져오고 grant에 넣지 않는다. `device_trial`에서는 무인 정책 승인 worker를 켜지 않는다(기명 운영자 승인만). owner가 거절하면 작업은 `HOLD`(`PHYSICAL_PREPARATION_UNAVAILABLE`)로 남고 자동 재시도는 없다.
- **Accepted (2026-11-17, 사용자 결정):** Decision 4(owner의 ARM 목표 수락), Decision 5의 하달 전 확인 대체, Decision 8의 첫 실물 절차. 값은 모두 저장소 상수·기존 세션 상한에서 가져온 제안값이며 측정값이 아니다(아래 각 항). 구현은 단계별로 들어오고 이 ADR이 Accepted라는 사실이 실물 수용을 뜻하지 않는다.
- **Proposed (사람 결정 필요):** Decision 6 위임 종류 추가(D-855 후속), 하달 뒤 확인이 없을 때 HOLD까지의 시간.
- **구현 범위:** `operator_attested` 레코드는 처음엔 Fleet 기록용이었다. 2026-11-17 결정(Decision 5)으로 `device_trial`의 PRE_DISPATCH는 `SOURCE_CLEAR` 확인을 필수 조건으로 한다(`production`·`simulation` 불변).

**독립 안전 검토(2026-11-04, 읽기 전용 별도 에이전트): PASS with notes.** 실물 동작 경로 없음, `production`·시뮬레이션 불변, identity 판정 단일 함수, 무인 정책 승인 worker는 `device_trial`에서 꺼짐. 메모: `operator_attested`의 만료는 기록만 하며 소비자가 생기면 그쪽에서 강제해야 한다.

### `operator_attested` wire (v1.362)

`POST /api/fleet/arm-transfers/jobs/{mission_id}/operator-attestations`, `GET` 같은 경로(목록). `device_trial`에서만 설치. 본문 `{kind: SOURCE_CLEAR|TARGET_PLACED, expected_request_digest, expected_proposal_digest}`; 서버가 시각을 찍고 45초(60초 미만) 유효 시간을 붙인다. 확인자는 기명 operator이고 제안자·승인자와 달라야 한다. (작업, kind)당 1건이고 반복은 409다. 응답 `evidence_source: "operator_attested"`, `goal_confirmed: false`. 작업 상태·claim·receipt는 바뀌지 않으므로 `GOAL_CONFIRMED`가 되지 않는다. Harbor 쪽 사람 확인(ADR 0023)은 Harbor 업무 장부 안에서 소비되고, 이 경로는 Fleet 기록용이며 둘은 서로를 대신하지 않는다.

### Context

- Harbor는 중립 경로 `arm-transfers`(`operations/fleet/fleet/server/work/arm_transfer_job_routes.py`)로 팔 이송을 제안하고, 승인된 작업이 `ARM_TRANSFER` Action으로 나간다. 이 경로는 `deployment_profile != "simulation"`이면 설치를 거절하고(`install_arm_transfer_job_routes`), `PhysicalTransferDispatcher`·`PhysicalTransferStore`도 같은 이유로 `simulation`만 받는다. 디스패처는 owner가 `simulation: true`를 보고해야 한다(`_capabilities`).
- D-797 §2·§3(S4)은 셀 장부 경로(`StepJobDispatcher`, `CELL_TRANSFER`)만 `device_trial`에서 열었다. 두 경로는 별개다. 셀 경로는 공정 digest·장부 단계를 쓰고, `arm-transfers`는 `FleetArmTransferGrant`와 owner SDK(`transfer_capability`·`submit`·`get`·`cancel`)를 쓴다. 현재 실물 하드웨어 owner(`omx_hardware_owner.py`)는 SDK 없이 `goals_enabled: false`다.
- D-965: 외부 앱은 관제 꼭대기(R) 하나로 들어오고, 셀 소유 workcell의 팔 작업은 D-855 위임으로 셀에 넘어간다. 승인·admission은 셀 화면의 기명 운영자가 한다(D-960 §2). 위임 종류가 생기기 전에는 R이 팔 제안을 실행 경로처럼 접수하지 않는다. 구현은 `DelegatedArmJobs`와 `arm_transfer_relay_routes`에 일부 있다.
- Harbor 사용자 결정: 자동 근거 생산자가 생기기 전까지는 **기명 현장 운영자의 확인**을 근거로 허용한다.
- D-328 §1·§4와 D-797 §5: 운영자 확인은 성공 증거가 아니다. D-856 §3: 동작 성공과 업무 완료는 별도 정본이고 Harbor가 판단한다.

### Decision

1. **새 하달 경로를 만들지 않는다.** `arm-transfers`의 제안·승인·원장(`PhysicalTransferStore`)·디스패처를 `device_trial`에서도 쓴다. 셀 장부(`CELL_TRANSFER`)로 번역하지 않는다. 번역하면 공정 어휘(pallet·layer)가 중립 경로로 새고 D-856 §1을 어긴다.
2. **프로필 허용은 두 곳이고 `production`은 닫힌 채다.** `install_arm_transfer_job_routes`, `PhysicalTransferStore`, `PhysicalTransferDispatcher`가 `{"simulation", "device_trial"}`을 받는다. `device_trial`은 설치 정책의 참가 팔이 정확히 하나일 때만 설치된다. 둘 이상이면 설치를 거절한다(다팔은 D-778/D-779 몫, D-797 「일부러 하지 않는 것」).
3. **owner identity는 D-797 §3 한 함수로 판정한다.** `StepJobDispatcher._device_trial_identity`의 조건(`device: true`, `simulation` 아님, `instance_id`·`workcell_id` 일치, 설정의 `commissioning_revision`과 같음)을 모듈 수준 함수로 꺼내 두 하달기가 같이 쓴다. `PhysicalTransferDispatcher._capabilities`는 프로필에 따라 `simulation: true` 또는 이 함수를 요구하고, 그 외에 journal·capability 대조는 지금 그대로다. 설정의 `commissioning_revision`은 grant에 넣지 않는다.
4. **owner의 ARM 목표 수락 (Accepted 2026-11-17, 사용자 결정).**
   - 동작 세션은 owner cgroup 밖의 별도 systemd unit에서 돌고 버스의 유일한 writer다. owner는 serial을 열지 않는다. 신원은 새 캐시를 만들지 않는다(ARM 경로는 제출마다 owner identity를 읽는다).
   - owner는 현장 운반 순서(`FOLDED`, `cell_transfer.py:157`)를 세션에 단계별로 보내고, 단계(approach·grasp·transfer·release)는 그 단계의 결과를 받은 뒤에만 기록한다.
   - 취소·정지는 언제나 접기(fold)로 끝낸다. 세션에 SIGINT·SIGKILL을 보내지 않고, 팔을 뻗은 채 토크를 끊지 않는다(D-911).
   - fence·링크 watchdog은 0.25초마다 폴링하고, 실패가 3초 이어지면 접고 HOLD한다. 전체 시한 300초이되 접기는 끊지 않는다. 토크·전류는 기존 세션 상한을 그대로 쓴다.
   - 위 값(0.25 s, 3 s, 300 s)은 저장소 상수(Fleet 주기, `FifoCell` timeout)에서 따온 제안값이고 측정이 아니다.
   - 이 경로가 구현되기 전에는 `device_trial`의 ARM 이송이 준비 단계(`PHYSICAL_OWNER_UNAVAILABLE`)에서 HOLD이고 아무것도 움직이지 않는다.
5. **사람 확인을 근거로 받는다. 단 이름과 용도를 구분한다.**
   - 새 근거 출처 `operator_attested`. 기명 셀 운영자가 셀 화면에서 입력한다. 서비스 토큰이나 관측기 토큰으로는 만들 수 없다(관측기 토큰은 확인을 만들 수 없다).
   - **하달 전 확인 (2026-11-17 결정, `device_trial` 한정):** 기명 운영자의 `SOURCE_CLEAR`(1회용, 유효 45초, 요청·proposal digest 결속, 제안자 ≠ 승인자 ≠ 확인자)가 있어야 별도 생산자 id `operator-attested-producer`가 PRE_DISPATCH 관측을 올릴 수 있다. 물체 자세는 정책 source 자세이고, 팔 구역·링크 여유는 owner가 읽은 실측 관절 값의 FK로 계산한다. 기록과 콘솔은 이것이 독립 자동 관측이 아니라 운영자 확인에 기댄 것임을 보여 주어야 한다. Fleet은 이 확인을 하달 전에 한 번만 소비한다. 확인이 없으면 작업은 하달되지 않는다. `production`·`simulation`은 변하지 않는다.
   - **하달 뒤 확인:** "물체가 `target`에 놓였다"는 `operator_attested`로 기록해 Harbor가 읽는다. 작업 상태는 `ACTION_SUCCEEDED`까지만 가고 `GOAL_CONFIRMED`는 자동 근거 생산자나 별도 결정이 있어야 한다. 사람 확인이 Fleet의 목표 확인을 대신하지 않으므로 D-328 §1·§4와 충돌하지 않는다. 업무 완료 판단은 Harbor 몫이다(D-856 §3).
   - 근거 레코드는 확인자 principal·시각·근거 출처를 남기고, 자동 근거와 한 화면에서 같은 신뢰로 보이지 않게 구분 표시한다. 자동 생산자가 등록되면 `operator_attested` 허용은 설정에서 끈다.
6. **위임(D-965).** 현장 R은 `ARM_TRANSFER` 제안을 D-855 위임으로 셀에 넘긴다. 위임 종류 추가(`ControlNavigationCandidate`에 팔 작업)는 후속 구현이고, 그 전에는 R이 접수하지 않고 앱은 HOLD로 다룬다. 한 Fleet이 팔과 Pinky를 함께 소유하는 개발 구성에서는 그 Fleet이 직접 접수한다.
7. **정지·rearm.** 정지 해제와 rearm은 셀 화면의 사람만 한다(D-430, D-965). 앱과 R은 해제 경로가 아니다. owner 정지 래치와 Fleet 펜스(`authority_epoch`·`dispatch_generation`)는 지금 규칙 그대로다.
8. **첫 실물 동작은 사용자 입회.** 토크 ON, 첫 `SubmitAction`은 S5 실물 수용 절차(D-797 §8, D-403 §7)에서 사용자가 보는 앞에서 한다. 이 결정은 그 절차를 대신하지 않는다. 2026-11-17 결정: 첫 실동작은 arm_s 바닥→벨트 한 번, 사용자 입회. `--commissioning`은 사용자가 셀에서 만든 단기·1회용 로컬 입회 토큰이 있을 때만 켜고 wire 메시지로는 켜지 않으며, 새로 발급한 기명 운영자 토큰으로 admit한다. Gate의 비전 재계획 훅(wrist·pinch·feel)과 `finish_attempt`가 아직 연결되지 않았으므로, 그 전까지 `device_trial`의 모든 운반은 이 입회 토큰이 필요하다(없거나 낡으면 `CarryRefused`로 명령 전에 거절). 훅이 연결되면 완화한다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-797 | §2·§3 위에 선다. §4·§5(자동 인계 장벽·카메라 근거)는 건드리지 않고, 이 결정의 사람 확인은 그 자동 근거가 생길 때까지의 대안이다 |
| D-856 | 중립 경로 유지. 번역·공정 어휘 없음. 성공과 업무 완료 분리 |
| D-965, D-960, D-855 | 진입점·위임·셀 승인은 그대로. 팔 작업 위임 종류 추가는 후속 |
| D-858 | S4 이후 단계. 위 4항의 owner 목표 수용은 S1 port 위의 별도 안전 결정 |
| D-328, D-403 | 운영자 확인을 성공 증거로 쓰지 않음. `simulation` 경로·시험 불변 |
| D-336, D-299, D-330, D-430 | 같은 호스트 owner 하나, 시리얼 owner 하나, 정지 경계 유지 |

### Alternatives

| 대안 | 판단 |
|---|---|
| `arm-transfers` 제안을 셀 장부 `CELL_TRANSFER` 작업으로 번역 | S4 코드를 그대로 쓴다. 공정 어휘가 중립 경로로 번져 D-856 §1 위반. 채택하지 않음 |
| 사람 확인을 목표 확인(`GOAL_CONFIRMED`)으로 인정 | 가장 짧다. D-328의 "운영자 확인은 성공 증거가 아니다"를 깬다. 채택하지 않음 |
| 확인 없이 하달(근거 생산자 대기) | 실물 팔이 물체 유무를 모른 채 움직인다. 채택하지 않음 |
| **같은 경로 + `device_trial` 한정 + 사람 확인은 `operator_attested`로 구분** | 채택 |

### Consequences

- 구현 단위는 (a) identity 함수 추출과 프로필 허용, (b) `operator_attested` 근거 입력·검증·표시, (c) owner의 ARM 이송 수용 경로, (d) 위임 종류 추가로 나뉜다. (c)와 (d)는 각자 안전 결정이다.
- `simulation`과 `production` 동작은 변하지 않는다.

### Validation

- SOURCE(구현 때): `device_trial`에서 참가 팔 둘 이상이면 설치 거절, `production` 거절, 시뮬레이션 owner를 `device_trial`이 거절·실물 owner를 `simulation`이 거절, `operator_attested`의 1회용·만료·역할 분리, 서비스 토큰이 근거를 만들 수 없음.
- DEVICE: S5(D-797 §8). 이 초안은 장치 수용을 주장하지 않는다.

### 열린 항목

- `operator_attested`의 wire 모양과 유효 시간 기본값(D-18에 따라 API Reference·schema·시험과 같이 확정).
- 하달 뒤 사람 확인이 없을 때 작업을 얼마 뒤 HOLD할지.
- 위임 종류 추가의 wire(D-855 후속).

**References:** D-328, D-403, D-430, D-797, D-855, D-856, D-858, D-960, D-965.
