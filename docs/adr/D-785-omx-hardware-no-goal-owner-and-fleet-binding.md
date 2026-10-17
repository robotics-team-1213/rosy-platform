## D-785 OMX 실물 no-goal owner와 Fleet 연결: 정지·상태 읽기부터 열고, 동작은 열지 않는다

**Status:** Proposed

## Context

2026-10-17 사용자 지시: "fleet PC를 통해서 로봇암 자체를 구동하고 학습까지 완성". 같은 날 플랫폼 연결 점검(비공개 `platform-control-verification-20261017.md`)에서 현장 Fleet PC의 실물 OMX 제어 연결이 없다는 사실을 확인했다.

| 항목 | 현재 |
|---|---|
| Fleet 진입점 | `fleet.cli console`이 `create_app`에 `omx_instances`를 넘기지 않음 |
| Fleet 컨테이너 | `/run/rosy/omx` mount 없음 |
| 실물 owner | 없음. `run_cell_owner.py`는 simulation 전용이고 serial·video grant를 거부함 |
| 수집 | `collection_ros.RosBackend`가 수집 세션 동안만 자체 owner를 만듦 |

D-246은 workcell마다 native systemd 인스턴스 하나로 실물을 제어한다고 정했다. 계획 G4.4는 실물 owner를 no-goal 기동부터 검증하라고 정했다. 측정 profile과 정지 증거(G3)는 아직 없다.

같은 날 사용자는 현장 Fleet PC의 ROS 2 Lyrical(Python 3.14) native runtime을 승인했다("Lyrical 도 괜찮아"). 이 승인으로 G2의 runtime 선택이 정해진다. 고정 벤더 source와 lock은 바뀌지 않는다. 실물 lifecycle·구동 시험은 G3 이후에 따로 한다.

## Decision

### 1. 실물 owner는 no-goal 조립 하나다

`rosy_agent.omx_hardware_owner.build_hardware_owner`가 한 프로세스 안에 다음을 묶는다.

- `ArmCommandOwner` 하나: steady clock, `allowed_owners=("rule_based",)`
- `ActionStore`
- `LocalStopController`
- `OwnerRecoveryApi`
- D-336 UDS

Action runner는 `enabled=False`이고 phase runner가 없다. 그래서 `SubmitAction`은 journal row를 만들기 전에 거부된다. HTTP·Pilot 표면도 없다.

identity는 `simulation: false`, `profile: omx-hardware-no-goal`, `goals_enabled: false`로 보고한다. Fleet Cell·step dispatcher는 원래 simulation identity가 아닌 owner를 거부한다. 따라서 이 owner는 Fleet 쪽 설정 실수가 있어도 동작 목표를 받지 않는다.

조립은 아래 경우를 거부한다.

- 비활성 policy
- workcell·instance·보정 revision 불일치
- `rule_based` 외 owner 허용
- sim·gazebo·isaac 표지나 `<...>` 자리표시가 남은 보정 revision
- sim clock runtime
- root Fleet UID

### 2. 실행기는 장치 권한을 갖지 않는다

`deploy/robot/omx/run_hardware_owner.py`의 동작 조건은 다음과 같다.

- 설정: `rosy.omx-hardware-owner.v1` 비공개 JSON만 받는다. 이 사용자 소유여야 하고, group·world 쓰기가 없어야 하며, 자리표시가 없어야 한다.
- ROS 환경: 명시 `ROS_DOMAIN_ID`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`, 설정과 같은 `ROSY_OMX_ROS_NAMESPACE`를 요구한다.
- 하지 않는 일: serial을 열지 않고, torque를 켜지 않으며, controller configure·activate도 하지 않는다.
- 하는 일: native controller graph를 관측만 한다.

수집 backend와 같은 per-Action flock(`collection_ros.resource_key`)을 잡는다. 그래서 수집 세션과 owner가 한 trajectory action을 동시에 소유할 수 없다. 수집이 이 owner의 명령·사건을 소비하는 조립(점검 기준 3)은 후속이다.

`cell_sim_tools.refuse_second_owner`는 `run_hardware_owner`를 같은 graph의 arm owner로 센다.

배치:

- user unit: `rosy-omx-owner@.service`
- 소켓 디렉터리: tmpfiles 예시로 만든다. `/run/rosy/omx/<instance>`는 2750이고 그룹은 Fleet 실행 GID 10001이다.
- 소켓 권한: setgid로 그룹을 상속받은 0660 `control.sock`에는 Fleet 컨테이너 UID 10001만 연결된다.
- 재시작: 정지 래치가 닫힌 상태로 돌아온다. 오래된 소켓이 남아 있으면 운영자 검토 전까지 시작하지 않는다.

이 정지 래치는 owner의 소프트웨어 fence다. 모터 전원을 끊지 않고, 비상정지도 아니다.

### 3. Fleet 연결은 명시 설정과 overlay로만 켠다

`fleet.cli console`은 `ROSY_FLEET_OMX_INSTANCES`(`WORKCELL=INSTANCE`를 쉼표로 구분, 중복 없음)로만 연결 대상을 받는다. 비어 있으면 지금과 같이 OMX를 구성하지 않는다. 소켓 루트는 컨테이너 안 `/run/rosy/omx`(`create_app` 기본값)다. CLI 플래그를 두지 않은 이유는 `fleet` 크기 단위(D-766)가 고정이기 때문이다. 같은 커밋에서 줄 배치만 바꿔 순증가를 0으로 맞췄다.

연결이 열어 주는 것은 기존 local stop fanout, RearmLocal, owner HOLD 복구, owner 상태 읽기다. `enable_mission_dispatcher`는 CLI가 여전히 넘기지 않는다.

`deploy/site/compose.omx.yaml`의 구성과 규칙은 다음과 같다.

- 넣는 것: env와 읽기 전용 `/run/rosy/omx` bind만 넣는다. `create_host_path: false`라서 디렉터리가 없으면 스택이 거부된다.
- 넣지 않는 것: image·command·port는 바꾸지 않으므로 pairing overlay와 함께 쓸 수 있다.
- 배포: 후보 산출물에 포함된다.
- 자동 업데이트: 단독 또는 pairing 뒤 조합만 허용한다.

### 4. 현장에서 overlay를 켜기 전 막힌 점

Fleet이 OMX를 구성하면 `/api/fleet/dispatch/rearm`은 모든 OMX owner의 RearmLocal이 OPEN일 때만 성공한다. 하나라도 실패하면 Fleet dispatch를 다시 닫는다. 이 동작은 Pinky dispatch에도 적용된다.

owner의 RearmLocal·복구는 `rosy_agent.fleet_fence`로 Fleet fence를 다시 읽는데, 이 경로는 loopback 평문 HTTP만 허용한다. 현장 Fleet은 TLS로만 열려 있고 proxy 뒤에 있어서 그 endpoint가 없다. 그대로 켜면 비상정지 뒤 현장 전체 dispatch 재개가 막힌다.

따라서 현장 overlay 활성화는 다음 둘 중 하나를 별도 결정·safety 리뷰로 정한 뒤에만 한다.

- (a) Fleet 컨테이너가 host loopback에 읽기 전용 평문 dispatch-control endpoint를 따로 연다.
- (b) fence readback이 site CA를 고정한 HTTPS loopback을 지원한다.

이번 변경은 이 결정을 내리지 않는다.

## Alternatives

- **`run_cell_owner.py` 재사용**: SIM gripper·sim clock·SIM profile이 묶여 있어 기각했다.
- **수집 backend를 상시 owner로 승격**: 120 s 세션 한도·teacher 입력과 결합되어 있어 기각했다.
- **base compose의 command에 플래그 추가**: pairing overlay가 command 전체를 반복하므로 두 overlay가 충돌한다. 그래서 env로 넘긴다.

## Consequences

| 단계 | 상태 |
|---|---|
| SOURCE | 위 조립·실행기·CLI·overlay와 host 시험 |
| ROS-SIM | 미실행. native Gazebo에서 no-goal owner 기동·readback은 후속 |
| DEVICE | 미실행. Fleet PC에서 소켓 권한·peer UID 실측, 실물 joint state 수신은 후속 |
| 동작 | 열지 않음. 측정 profile·정지 증거(G3)와 별도 ADR 없이는 열지 않는다 |

## Validation

- `test/test_omx_hardware_owner.py`
- `operations/fleet/test/test_cli_omx_instances.py`
- `test/test_site_autoupdate.py::test_omx_overlay_from_the_candidate_is_allowed`
- `test/test_site_candidate.py`

## References

D-246, D-336, D-390 §5, D-403 §7, D-540 9, D-770, D-778, `docs/plans/2026-10-15-omx-hardware-control.md` G2·G4·G5.
