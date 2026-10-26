# D-856 물리 종료 관측과 중립 job producer

**Status:** ralplan 독립 architecture/critic는 frozen commit `5dad5fd6c4`의1차, object pose 기준점 보완 `ebba429c4c`의2차, pre-dispatch occupancy 보완 `b241ef1cc5`의3차를 모두 approve했다. 이견/필수 보완 없음으로 이미 승인된 execution을 진행한다. 계획 승인은 구현·안전 수용 증거가 아니다. 공개 route/DTO 이름은 제안이며 실제 API ref 예약·반영 전 제공 API로 취급하지 않는다.

단계1의 World raw-facts는 source commit `037c29121f`에서 구현하고 `0849ce4825`에서 미측정 속도를 None으로 보존했다. 해당 소스의 World28 passed/skip0·affected764 passed/2 skipped·각0 NEW와 고정 SHA 독립 검토를 확인했다. [검증과 한계](../validation/harbor-physical-observations-2026-10-24/result.md)를 따른다. 당시에는 producer 인증·freshness/coverage evaluator·claim 해제가 없었다. 후속 구현과 현재 미완료 범위는 아래에 기록한다.

고정 OMX 형상 descriptor는 source `b045ed0050`에서 실제 URDF·8개 mesh 내용 검증과 visual/collision 전체9개 필수 링크를 구현했다. World 전체36 passed/skip0·affected753 passed/2 skipped·각0 NEW, 동일 SHA 독립 검토 finding 없음이다. descriptor는 측정 bounds·부착물·실제 구역 이탈의 검증을 대신하지 않는다. 이후 source205에서는 직접 생성하는 descriptor에도 정확한 고정 profile과 전체 링크 invariant를 적용했다.

두 표본 정책 소비자는 source `205cd08767`에서 구현했다. [검증 기록](../validation/harbor-physical-evaluator-2026-10-24/result.md)의 집중67 passed/skip0, affected 두 묶음4587 passed/189 skipped와6312 passed/336 skipped·각0 NEW와 독립 재검토를 확인했다. 최초 소스에서 발견한 quaternion norm/축소 descriptor 누락은 RED 재현 뒤 보완했다. 이 첫 profile은 모든 참가자의 gripper가 열려 있고 비어 있어야 한다. credential ingress·현재 원장 context/fence·atomic claim 종료는 후속이며 validator 성공을 그 권한으로 사용하지 않는다.

단계2의 내부 physical create/read/two-person approval·공통 claims/schema version6은 source `3c95937a56`에서 구현했다. 자원 키도 정책 digest에 결속하고 legacy owner workcell을 함께 잠근다. source76에서는 자원 키를 공용 contracts leaf로 옮겨 safety/decision 의존 방향을 지켰다. [검증 기록](../validation/harbor-physical-proposals-2026-10-24/result.md)의 최신 집중1292 passed/skip0·최종FULL23개 모두0 NEW·동일source G1 timing4 passed/skip0와 독립 안전 검토를 확인했다. 원본9d FULL의 구조/G1 실패는 따로 보존하며 G1 원인은 미확정이다. 공개 HTTP/DTO·live capability 수집·prepared action/attempt·관측 credential ingress·dispatcher·physical receipt/claim 종료는 아직 연결되지 않았다. READY는 장치 제출을 뜻하지 않는다.

## 목표와 소유권

첫 독립 HTTP 팔 흐름에서 Harbor는 CargoMove를 물리 참조로 변환하고 업무 완료를 판단한다. ROSY는 설치된 정책, 두 사람 승인, 실행·점유, 물리 관측의 검증과 receipt를 소유한다. 물체가 목표에 놓이고 전체 로봇 링크가 공유 구역 밖에서 정지했다는 근거가 없으면 동작 성공 뒤에도 점유를 보존한다. 새 broker/DB/장치 writer를 만들지 않는다.

첫 profile은 격리 simulation workcell의 한 executing OMX owner와 설치된 유한 shared-zone 참가자 집합이다. 참가자는 모두 v1.306 managed capability를 제공해야 한다. Base·conveyor·사람 등 통제되지 않는 다른 진입자가 있는 구역은 이 profile로 열지 않는다. 실제 Harbor 전체 현장/모든 actuator의 수용으로 확대하지 않는다.

World는 원본 물리 관측과 projection을 소유한다. Fleet가 해당 action/attempt·설치 policy·fence와 대조하고 자신의 원장/claim을 같은 transaction에서 변경한다. World producer와 Harbor 앱에는 claim 쓰기나 물리 완료 verdict를 주지 않는다. CORE/OMX 최종 writer 경계를 유지한다.

## 현재 코드의 제약

- `operations/world/.../state/projections/arm_state.py`는 표시용 정규화 관절값만 받으며 object_state를 unobserved로 강제한다. object pose·radian FK·전체 link clearance 근거로 변환하지 않는다.
- `CellGoalEvidenceService/Registry`는 recipe/cell/job/item predicate와 sim_model_pose에 결속된다. 중립 자료를 Cell hash로 위장하거나 기존 legacy producer 자격을 그대로 승격하지 않는다.
- `CellJobStore.admit/start_step/read`는 provenance_kind=legacy를 필터링한다. physical row를 이 경로로 통과시키지 않는다. 공통 dispatch control·resource reserve/release·idempotency transaction은 재사용한다.
- `fleet_cell_jobs` physical provenance와 v1.306 owner-target/receipt 경계는 구현됐다. Fleet kind registry/HTTP physical creator/claim closure는 아직 닫혀 있다. release phase는 그리퍼를 풀고 같은 home joint vector로 돌아오지만 home/TCP 성공은 전체 링크 관측을 대신하지 않는다.

## 선택과 대안

**선택:** 설치 정책 + 별도 trusted 물리 관측 + Fleet의 atomic 완료/해제. 기존 원장과 최종 owner를 재사용한다. 관측 producer의 자격/수명/순서 검증은 기존 evidence 경계의 패턴과 공통 helper를 재사용하되 recipe/cell에 의존하는 형식은 새 물리 계약으로 분리한다.

owner success만으로 해제하는 대안은 물체 배치·전체 link 이탈을 증명하지 못한다. Harbor가 outside/satisfied를 보내는 대안은 앱이 공유 점유를 해제하게 된다. 기존 Cell evidence의 필드 이름만 바꾸는 대안은 공정 hash와 승인 의미를 남긴다. 관측/claim을 다른 DB에 두는 대안은 완료 receipt와 해제의 원자성을 잃는다. 선택안은 producer·정책 구성과 관측 보존 비용이 늘지만 이 네 경계를 직접 닫는다.

## 설치된 물리 정책

server 설정이 owner별 object/catalog/bindings·resource-policy digest, arm/zone claim key, 허용 source/target, 각 zone의 보수적 경계와 required participant/link 집합을 고정한다. 앱은 resources·경계·producer·허용 오차를 고르거나 줄이지 못한다. 정책의 canonical digest는 owner factory의 resource_policy_digest와 일치해야 한다.

정책은 참조 frame/calibration/kinematics/collision-model/evaluator revision, target object pose 허용 오차, 최대 관측 age와 정지 속도/최소 관측 간격을 포함한다. required links는 pinned collision model의 전체 coverage로 검증하며 누락/unknown model은 비활성화한다. home 위치나 부분 joint map으로 링크를 보충하지 않는다.

object pose의 기준점/방향은 관측 model·frame에 명시적으로 결속한다. catalog의 TransferPose는 grasp motion 기준이며 object 중심/관측 model origin과 같다고 가정하지 않는다. 설치된 object goal/reference 또는 검토된 geometry/calibration 변환으로 목표 object pose를 고정하고, 높이·grasp depth·origin offset·tilt가 다른 fixture에서 이 결속을 검증한다. 명령 EE pose를 관측 object pose로 복사하지 않는다.

모든 참가자의 작업이 진입 가능한 zone을 보수적으로 claim하게 한다. 이 첫 profile에서는 zone 밖 동작이어도 해당 zone을 생략해 병렬로 움직이는 최적화를 하지 않는다. 따라서 이전 job의 미확정 점유가 있으면 다음 참가자 action도 시작하지 못한다. 참가자 일부가 unmanaged/unknown이면 접수·dispatch를 닫는다.

## World 관측 계약과 Fleet 판정

제안하는 관측은 물리 object_ref/목표 frame의 object pose, 각 required participant의 전체 collision-link 보수적 bounds와 측정 속도, 그리퍼 열림/held-object 없음의 센서 관측을 담는다. capture 시각·producer sample 순서·action/attempt·owner journal/session·설치 revision을 결속한다. boolean satisfied/outside_zone/claim_released와 CargoMove·cargo arrival·하역 완료 같은 업무 필드는 입력으로 받지 않는다.

producer 자격은 설치 scope/model/policy/evaluator에 한정하고 proposer/operator와 분리한다. 만료된 자격·다른 scope·future/replayed timestamp·같은 sample ID의 다른 payload는 거절한다. Fleet 수신 시각은 server clock을 사용한다. 원본 사실과 producer 식별자를 보존하며 token은 보존하지 않는다. simulation에서는 별도 observer가 독립 simulated state를 제공하고 action 성공/명령 목표로 관측값을 채우지 않는다. 주입 관측 시험과 Gazebo/실물 관측 수용은 따로 기록한다.

Fleet는 동일 grant의 durable action success 뒤에 잡힌 두 순서 있는 신선한 표본으로 목표 object pose·열린 gripper/held 없음·모든 required link의 zone 이탈/정지 조건을 판정한다. bounds가 zone에 닿거나 coverage·frame·revision·시각·참가자 identity가 하나라도 불명확하면 해제하지 않는다. 표본 간 최소 간격은 policy에 고정하며 단일 순간의 0 속도를 정지로 추정하지 않는다.

관측만으로 움직임 권한이 생기지 않는다. 모든 참가자의 managed/session/journal 결속과 Fleet claim 직렬화가 관측 이후의 미조정 움직임을 배제해야 한다. receipt는 관측 시점의 물리 결과이며 다음 동작의 허가가 아니다. 다음 요청은 자신의 현재 resource claim·fence·fresh state 검사를 다시 통과해야 한다.

## 중립 producer·승인·원자적 종료

제안 API는 arm-transfer job의 create, read-by-ID/key, named-operator admit, evidence ingress와 physical receipt read다. 실제 path·closed DTO·권한/Origin/audit·코드/버전은 구현 직전 정본 계약에 고정한다. create body는 request key와 물리 object/source/target·scope만 받고 서버가 설치 snapshot과 resource 목록을 해석한다. 앱의 업무 metadata를 공통 실행 원장에 저장하지 않는다.

create는 proposer/service의 principal-scoped idempotency로 PROPOSED physical row를 만든다. 같은 key/다른 요청은409다. creator는 자기 job만 읽고, 다른 named human operator는 기존 site 권한 범위의 승인 자료를 읽을 수 있어야 한다. 일반 viewer/service가 남의 job을 읽거나 self-approval하지 못하게 한다. 승인자는 proposer와 다르고 검토한 정확한 proposal digest/revision을 제출한다.

admit 전 현재 설치/capability/참가자 identity를 읽고, 같은 SQLite write transaction 안에서 snapshot digest/CAS·현재 dispatch control·미확정 점유를 다시 대조한 뒤 claims와 READY를 함께 기록한다. network/DB 조회를 최종 command lock 안에 넣지 않는다. 승인 뒤 owner 교체는 v1.306 target binding으로 device 접수 전 거절/HOLD돼야 한다. stale proposal의 값을 조용히 갱신해 승인하거나 새 request key로 자동 재접수하지 않는다.

**실행 전 물리 점유 확인:** managed 활성화의 ready 상태와 capability 조회는 실제 구역이 비었음을 증명하지 않는다. 다른 참가자가 기존 claim 없이 zone 안에 정지해 있을 수도 있다. READY claim을 확보해 이후 다른 참가자의 진입을 막은 뒤, 그 시점 이후의 신선한 두 표본으로 모든 required participant/link의 구역 이탈·정지와 primary gripper의 열림/빈 상태, 대상 object의 등록 source pose를 확인하기 전에는 전송하지 않는다. READY에서 action/attempt/grant identity를 먼저 영속 준비하되 이는 제출/실행을 뜻하지 않는다. 관측은 이 준비 context에 결속하고, 최초 send 직전 transaction에서 해당 precondition proof·claim·fence·identity·freshness/CAS를 다시 검사한다. 변경/누락/재시작이면 HOLD이며 관측 후 resource 직렬화를 건너뛰지 않는다. 이 첫 isolated profile의 초기 배치가 조건을 만족하지 않으면 자동 homing/manual fallback으로 보충하지 않는다. object source/target 판정 모두 검토된 object-origin 기준을 쓴다.

새 physical store/projection을 만들고 legacy Cell resolver/recipe/checkpoint/arm-success release에는 등록하지 않는다. 공통 parent/step/event·claim SQL을 재사용하되 nullable legacy provenance를 채우지 않는다. schema를 추가하면 기존 initializer가 가진 atomic migration transaction에 넣고, old host가 새 physical journal을 잘못 복구하지 않도록 schema version을 올린다. legacy row/claim/FK/mirror/UNKNOWN을 보존한다.

2026-10-24 코드 대조 결과, 최초 physical step은 공통 parent/event/claim 아래 `fleet_physical_transfer_attempts`에 둔다. 기존 `fleet_cell_steps` CHECK는 `_KINDS`로 생성되고 Cell dispatcher에는 sheet checkpoint·Cell grant·전송 전 release 규칙이 결합돼 있다. ARM 등록만으로 physical 경로가 생기지 않으면서 legacy dispatcher의 kind 범위가 넓어지므로 이 첫 slice에서는 `_KINDS`를 확장하지 않는다. 공통 atomic migration version7 안에서 job당 하나의 준비 attempt를 만들고 고정 step/action/attempt·canonical grant/digest·owner journal/session·approval/fence·준비 시각을 영속화한다. 별도 DB나 범용 attempt framework는 만들지 않는다. 독립 계약 검토가 실제 producer/consumer 경로를 대조한 구현 선택이며 위 승인 계획의 소유권을 바꾸지 않는다.

Action SUCCEEDED는 공통 ACTION_SUCCEEDED 상태로 저장하되 claims를 유지한다. World 관측 ingress와 immutable physical receipt 저장, 동일 action/attempt·generation의 claim 해제를 같은 DB transaction에서 판정·commit한다. 내부 GOAL_CONFIRMED는 물리 object-at-target/정지/전체 link 근거를 뜻하며 Harbor 업무 완료로 내보내지 않는다. 표본 중복은 같은 receipt, 다른 attempt/revision/fence나 부분 근거는 해제0이다. CANCEL/UNKNOWN/HOLD도 같은 물리 종료 경계 없이 해제하거나 다른 팔에 재배정하지 않는다.

## 실행 순서와 확인 기준

1. policy/World 물리 사실·producer identity/freshness의 순수 contract와 RED. 고정 model의 link 누락, 경계 접촉, pose 오차, 그리퍼 held/unknown, 단일/역순/오래된 표본을 거절한다.
2. 같은 DB의 physical create/read/two-person approval·claims migration RED. 동시 중복·다른 principal·self-approval·stale CAS/capability/fence·실패 rollback·legacy 전체 보존을 검증한다.
3. physical step/grant/dispatcher를 installed simulation에만 연결한다. owner journal/session 교체·응답 유실·늦은 응답·재시작을 HOLD/UNKNOWN으로 보존하고 GET만으로 자동 재전송하지 않는다.
4. World fact→Fleet physical receipt/claim transaction을 연결한다. action success만 있음/근거 일부/다른 zone participant/재시작/중간 SQL 실패/다음 admit와 경합에서 claim이 잘못 사라지지 않는지 확인한다. global stop과 cancel/resume도 검증한다.
5. Harbor의 Cell ProcessBinding/compile 입구에 중립 action binding을 병행 연결한다. 기존 장부·PlacementEvidence·ArmRetreat와 업무 완료 조건은 보존하고 동작 성공만으로 업무가 진행되지 않는 회귀를 유지한다.
6. 고정 두 repo SHA의 실제 loopback Fleet HTTP/임시 DB/분리된 proposer·approver·observer 자격으로 한 흐름과 중복·busy·권한·유실·restart를 실행한다. Harbor runtime에 ROSY import/DB/UDS/ROS가 없고 두 번째 최소 HTTP 소비자도 같은 계약을 소비하는지 확인한다. 기존 Cell HTTP도 별도 실행한다.

플랫폼은 공식 remote_pytest와 selector의 FULL/affected 전체, 각 run known_failures·skip 분류, size/safety·독립 계약 검토를 따른다. Harbor는 CONTRIBUTING의 unittest와 opt-in 실제 HTTP integration을 수행한다. 모든 실제 명령/소스 SHA/결과는 validation에 기록한다. 현재 문서는 이 검사들을 실행한 증거가 아니다.

실패 복구는 dispatch 비활성화와 권한/장부/점유 보존 HOLD다. schema 다운그레이드·journal 삭제·unmanaged 자동 복귀·request key 초기화·관측 위조는 복구가 아니다. 실물·배포·push·병합은 기존 사용자 승인 경계를 유지한다.
