# 충전 주기의 CORE 운행 한계 설계

2026-10-17. 기존 [충전 설계](2026-10-16-station-charge-lifecycle-design.md), [실행 계획](2026-10-16-station-charge-lifecycle.md), D-776의 운영 조립을 위한 작업 설계다. API 필드·version·capability를 발행한 문서는 아니다. 한 로봇·한 스테이션의 자동 작업→복귀→접안과 실제 착좌/정지 이후 후속 작업이라는 기존 범위를 유지한다. 설치 프로필의 실측 수용은 별도다.

## 확인한 현재 경로

기준 source는 9ee0965bd다. NavigationManager의 목표 임대는 만료 뒤 갱신을 거절하지만 살아 있는 임대는 계속 갱신할 수 있다. 만료 timer가 비동기 Nav2 cancel을 요청하는 것만으로 최종 출력이나 물리 정지의 시간 상한을 증명할 수 없다. StationReturnAuthority는 RETURNING을 제한하며 WORK_AVAILABLE의 일반 NAV 작업은 그 경계 밖이다.

RosBridge._on_nav_cmd_vel은 원본 Twist를 CommandManager.set_nav_twist로 넘긴다. _AutonomousInput에는 수신 monotonic 시각·mode epoch·속도·곡률 보존 여부가 있지만 native run ID가 없다. 수신 시점의 현재 run을 붙여 과거 메시지의 실제 실행 출처를 증명한 것으로 표시하면 안 된다. 관측된 native 완료·transport quiescence와 입력 속도의 논리 출처는 다른 근거다.

기존 private BoundedTrial은 전체 승인에 걸친 총 0.20m와 재개 금지 ledger다. 이 객체나 제한을 반복 운행용으로 바꾸지 않는다. 재사용할 방식은 최종 검사와 실제 PinkyTwistPort 제출을 같은 fence 안에서 처리하는 것이다. 새 50Hz 경로에는 SQLite·파일·네트워크 I/O와 blocking lock을 넣지 않는다.

## 제한이 증명할 성질

새 parent는 작업과 귀환 동안 선택된 모든 자동 속도 후보의 시간·누적 이동량·허용 공간을 제한한다. 기존 CORE admission·안전·mode·readiness가 운동 권한을 부여한다. parent는 출력 허용 조건을 추가할 뿐이다. 늦거나 실행 출처를 모르는 Twist도 물리 예산에서 빠지지 않는다. 이 제한을 통과했다는 사실은 명령이 특정 child에서 생성됐거나 작업이 완료됐다는 증거가 아니다.

Nav2 입력의 논리 출처를 증명하는 producer가 설치되면 별도 수용한다. 그 전에는 출처를 UNATTRIBUTED로 명시하고 원본이 없는 run ID를 생성하지 않는다. 작업 완료와 충전 인계에는 기존 정확한 native outcome/transport 확인, 실제 도착 위치와 원본 정지 계측, 상대 카메라·착좌 확인을 계속 요구한다. 예산 제한의 통과를 completion receipt로 사용하지 않는다.

## parent와 native child

parent의 불변 값은 robot/boot, 승인한 writer와 policy/profile/cost revision, 원본 facts의 수락 기한, map ID/실제 활성 version/revision, odom frame/epoch, 허용 공간, 누적 경로·회전·시간 한계와 정지 reserve다. Fleet은 실제 Task/request digest와 원장 소유권에 이 값을 결속한다. CORE는 최초 수락 기한과 현재 boot/원본 odom/실행 한계를 검증한 뒤 자기 monotonic 시작점과 deadline을 정한다. 검증·승인 중 지연으로 수명을 다시 시작하지 않는다.

parent는 초기 저SOC의 return→dock 또는 충전 완료 이후 departure→work→return→dock 전체 자동 이동을 포괄한다. 착좌만으로 끝내지 않고 원본 정지·충전 확인 경계까지 대기/정지 tail을 계산한다. 긴 CHARGING은 자동 출력 금지 상태이며 다음 CHARGED_HOLD의 새 에너지 admission 이전 parent를 부활시키지 않는다.

child identity는 `(owner-domain, boot, native run, owner generation)`이다. NavigationManager는 NAV child를, DockingManager는 dock/undock child를 각자의 기존 native ledger 잠금 아래 결속한다. CommandManager가 소유한 공통 제한 fence에 연결하되 Nav owner가 DockingManager receipt를 채택하지 않는다. child 교체·구간 도착·재시도·임대 갱신은 parent의 최초 deadline, 누적 경로, 회전량, 오차 예산을 초기화하지 않는다. 작업 완료 뒤 귀환에도 같은 남은 예산을 사용한다. 새 parent는 기존 parent의 정지/종료 경계와 새 원본 에너지 admission을 거쳐 만든다. 재시작은 이전 parent나 미확정 제출을 자동 재개하지 않는다.

설치된 제한이 REQUIRED_WAIT 또는 소모 상태이면 parent 없는 자동 출력은 차단한다. ordinary/unleased goal이나 mode 변경으로 제한을 벗어나지 못한다. 수동 인계는 기존 CORE 규칙으로 parent를 소모하며 자동 모드로 돌아와도 새 검증 없이 출력이 복원되지 않는다. 기본 미설치 경로와 설치 후 소모 상태를 구분해, parent 삭제를 unrestricted fallback으로 해석하지 않는다.

내부 원장은 parent ID와 `(domain, boot, native run)`의 소비 키를 부트 전체에 보존한다. 실제 native phase 갱신으로 generation만 증가하면 현재 attach된 exact run의 전진으로 처리하고, revoke한 run을 새 generation이나 새 parent에 재결속하지 않는다. 선언 identity/digest와 메타데이터 STOP·retire는 실제 native 수용, 현재 지도/에너지 검증이나 물리 정지의 증거가 아니다. 단일 CORE owner에 한 번 설치해 전체 부트에 보존하는 경계는 runtime 조립 시 따로 검증한다.

늦은 cleanup은 캡처한 parent/boot/run만 정지한다. parent가 바뀌었으면 새 실행을 취소하지 않는다. 만료·소모한 parent ID는 같은 boot에서 재사용하지 않는다. 보존 한도를 넘으면 새 admission을 거절하며 오래된 ID를 지워 재사용 가능하게 만들지 않는다. 새 CORE boot는 이전 요청을 거절한다.

## 원본 계측과 물리 reserve

기존 odometry callback의 원본 header/source clock/frame/body frame와 StateManager의 실제 odom epoch를 보존한다. 첫 구현은 검증된 최대 물리 속도×parent 전체 경과 시간과 최대 각속도×전체 경과 시간을 경로·회전 상한으로 쓴다. ZERO/대기 중에도 한계를 소비하므로 보수적이지만 동일 endpoint의 왕복·닫힌 경로·표본 사이의 완전 회전을 누락하지 않는다. chord에 고정 배수를 곱하거나 wrapped yaw 차이를 합산한 값으로 이 상한을 대체하지 않는다. 원본 pose는 공간 여유·현재성·물리 속도와 모순되는 위치 점프를 검사한다. 원본 반복은 첫 capture의 수명을 연장하지 않으며 역행·epoch 변경·불량 frame·gap·비유한 값·clock 역행은 해당 parent의 운동 허용을 영구 소모한다. 새 정상 sample로 소모를 되돌리지 않는다.

허용 공간은 odom frame에 결속하며 World의 승인 변환과 실제 활성 map version/revision에 대응해야 한다. 매 제출 전에 footprint·전체 측정 불확실성·최대 속도×원본 나이/출력 지연·최소 실측 감속도에 따른 제동 거리를 보수적으로 남긴다. 공간 여유·총 거리·총 시간의 한계와 같아도 정지한다. 제자리 회전의 전력과 angular 한계도 포함한다. 전류/전력·제동·latency·source gap의 장치 수용 근거가 없으면 finite energy나 DEVICE 수용을 주장하지 않는다.

## 최종 선택과 제출

CommandManager가 선택한 후보의 값·input epoch·mode epoch와 parent/child 세대를 불변 선택 receipt에 결속한다. clip 뒤의 실제 출력과 receipt가 달라지면 재검증하거나 ZERO를 선택한다. 다른 후보의 receipt를 재사용하지 않는다. 이미 선택된 옛 candidate를 다음 parent/child에 재결속하지 않는다. 수신한 raw Twist의 논리 출처가 생겼다고 추정하지 않는다.

기존 cmd_vel_cycle과 PinkyTwistPort가 실제 writer를 유지한다. bound 확인과 같은 cycle의 정확한 writer 호출을 비차단 fence로 묶는다. 다른 guard나 느린 작업 뒤에 실행되는 가장 안쪽 검사가 deadline과 원본 계측을 다시 확인한다. 거절·lock 경합·writer 예외/미확정 전달은 ZERO와 재개 금지 latch로 처리한다. 이벤트 기록·DB·network cancel은 50Hz fence 밖에서 수행한다. latch 상태의 확인과 출력 사이를 원자적으로 보존하는 lock 순서도 계약의 일부다.

잠금 순서는 기존 native owner lock → ModeMachine input/mode lock → 공통 제한 fence다. 최종 writer는 mode lock과 제한 fence만 비차단으로 획득하며 native owner lock으로 역진입하지 않는다. odom 관측은 제한 fence만 사용하고 mode/native owner를 호출하지 않는다. 제한 fence 아래에서는 backend 요청·이벤트 sink·mode transition을 실행하지 않는다. 각 admission owner의 attach/revoke는 native 쓰기와 이 순서 안에서 연결한다. backend 요청 전에는 gate를 먼저 닫고, 검증된 child 수락 후에만 해당 phase를 연다.

경합 시 50Hz 경로는 ZERO를 선택하고 그 parent 객체의 단방향 fault-request를 남긴다. 이 요청을 STOP commit과 혼동하지 않는다. 공통 fence를 다음으로 얻는 진입점은 새 허용 판정보다 먼저 요청을 STOP latch로 합친다. parent 객체에서 요청을 false로 되돌리는 길은 없다. STOP commit은 fence 안에서 직렬화하며 이미 같은 fence 안에서 진행 중이던 제출과의 순서를 보존한다. 실제 구현은 대상 Python runtime에서 요청이 유실되지 않는 원자적 단방향 저장과 단일 직렬화 publisher를 검증해야 한다. 이를 증명하기 전 운영 capability를 광고하지 않는다.

`threading.Event.set()`의 내부 Condition 잠금을 비차단 요청 저장으로 간주하지 않는다. 최종 검사와 writer의 직렬화에는 NAV/DOCKING의 None 입력과 manual clear 등 모든 입력/epoch 무효화 경로도 포함한다. 기존 clear가 경계 밖에 남아 있으면 mode→fence 잠금만으로 최종 제출을 증명할 수 없다. 이 변경은 기존 manual/native 잠금 순서를 추적해 검증한다.

출력 ZERO는 정지 요청이다. 접안/충전/다음 작업의 인계는 기존 원본 motion·native transport·착좌 증거를 따로 확인한다. 출력 제한이 물리 정지 측정을 대신하지 않는다.

CORE process/executor stall로 50Hz 자체가 멎는 경우도 장치 수용에 포함한다. downstream watchdog·마지막 비제로 명령 유지 시간·transport/actuator 지연·제동/coasting 상한이 없으면 software fence만으로 물리 정지 시간/거리나 에너지 ceiling을 주장하지 않는다. 프로필의 latency 근거는 이 전체 경로를 포함해야 한다.

## Fleet 예산과 설치

Fleet은 실제 READY Task 선택·World proof·활성 graph·station pose revision과 지원하는 실행 한계를 함께 확인한다. 작업의 중간 위치에서 귀환하는 비용도 parent가 보장하는 허용 공간/시간 안에서 계산한다. lane graph 길이나 ETA만으로 ordinary NAV 상한을 선언하지 않는다. 공급할 수 있는 유한 비용은 승인한 전력·거리·회전·대기·접안·재시도·정지 tail 및 reserve를 포함한다. 시간×전력 모델의 전력은 ZERO/대기 중 보조 부하까지 포함한 전체 관련 소비의 상한이어야 한다. 지원하지 않는 작업/공간/장치 profile은 WAIT다. 한계 소진의 안전 정지는 작업/귀환 성공을 보장하지 않으므로, 허용 공간에서의 실제 귀환 경로 가능성도 별도 검증한다.

운영 factory와 CLI는 동일 TaskStore/TripRunner/World reader/CORE client를 사용한다. 해당 실행 제한을 실제로 구현·수용한 backend의 capability/profile만 사용하며 설정 문자열을 capability 증거로 취급하지 않는다. API/DTO/capability가 필요하면 계약을 예약하고 SRS·API reference·producer/consumer 시험을 함께 변경한다. 기존 20cm trial, 실제 장치 수용 및 배포 승인을 새 설정으로 대체하지 않는다.

## 검증과 남은 설계 결정

필수 RED는 늦은 최초 수락, parent 갱신/child 교체의 deadline 연장, 예산 reset, 같은 ID 재사용, 옛 선택 receipt의 새 child 재결속, 원본 gap/역행/epoch 변경, 제자리 회전·왕복, reserve 경계, source/최종 시각 읽기 도중 만료, STOP과 제출 경합, writer 전달 불명, 늦은 exact cleanup 및 새 boot 재생이다. 그 뒤 실제 CORE HTTP→native admission→CommandManager→같은 최종 writer→measured stop과 Fleet 작업/귀환/접안 3회 사이클을 검증한다. 합성 profile과 실측 profile을 구분한다.

`a9efc3800`의 private 연결은 CommandManager sidecar의 불변 단일 receipt와 부트 scope Ledger/Budget claim, 최초 cycle 전 설치 및 같은 Port의 비차단 최종 경계를 구현했다. 원격 관련 572 PASS/0 skip/NEW 0이며 구체 RED와 한계는 실행 계획에 기록했다. fault request의 지원 대상은 traditional CPython 3.12의 단방향 slotted bool로 제한하고, Ledger의 software STOP commit과 물리 정지를 구분한다. runtime factory는 아직 설치하지 않는다.

native owner의 모든 변경 경로에 대한 actual run attach/revoke, 단일 CORE runtime 조립·boot 수명 보존, 실제 설치 profile/원본 clock·정지 지연의 수용 식별자는 여전히 검증 대상이다. 논리 command provenance를 필수로 요구하는 작업은 별도 producer 수용 전까지 미지원이다. 이 private host 검증은 운영 capability 활성화·장치/현장 수용이나 전체 충전 목표 완료를 증명하지 않는다.

추가 `4a82303e4`는 복사한 parent handle이 공유하는 mutable STOP flag를 바꾸지 못하게 현재 객체 identity를 먼저 검사한다. 복사 handle RED 4건 후 결합 원격은 576 PASS/0 skip/NEW 0이다. 실제 native owner와 운영/장치 수용의 미완료 범위는 그대로다.

후속 `f9c05107a`는 정상 input/선언 child generation 갱신을 고장과 분리한다. 원래 선택의 TTL·parent STOP/clock/예산·receipt 무결성과 물리 제한을 먼저 확인하고, 정상 교체만 이전 출력을 ZERO로 버려 같은 parent의 누적 소비와 원래 기간을 보존한다. 갱신은 새 출력 허가가 아니며 기존 receipt는 소비한다. `61e95e784`의 관련 원격 745 PASS/0 skip/NEW 0은 actual writer와 guard 보강 근거다. 실제 native owner binding·runtime 설치·장치/현장 수용은 별도다. 다음 구현의 소유 경계와 완료 조건은 [실행 계획](2026-10-17-bounded-station-execution.md#3-core-admissionnative-ownersource-조립)을 따른다.

private native 조립 `cfa8ab1ad`는 실제 CoreServices의 Nav/Dock owner에서 BOOT/run/generation을 읽고 변경 전 pause와 실제 receipt 확인 후 재결속을 수행한다. full-invocation ticket을 admit 및 Dock mode 인계 전에 재검증하며, 성공 종료·최초 활성화의 입력 정리와 첫 입력 WAIT를 구분한다. Dock phase 변경 전 Nav 잠금 아래 STAGING token을 폐기한다. 관련 host 회귀 363 PASS/0 skip/NEW 0과 실제 native callback 재생 23건의 범위다. 확장 영향 검사·기본 runtime 설치·원본 odometry/clock·실측 profile·운영 API와 물리 수용은 이 결과로 대체하지 않는다.

후속 private 원본 adapter `a67abda37`은 실제 ROS callback의 변환 전에 정확한 parent와 Ledger clock을 캡처하고, 같은 StateManager 쓰기 잠금의 wall/epoch receipt를 원본 ROS stamp/frame/source clock·검증한 planar pose와 함께 Budget으로 전달한다. 느린 읽기는 원래 시작 하한을 보존하며 교체된 parent에 귀속하지 않는다. 관련 host 352 PASS/0 SKIP/NEW 0에는 새 source adapter 회귀 17건이 포함된다. 기본 factory 설치·실기 clock/profile·StationMotionFeed 자체의 epoch 원자성·map/에너지 admission·운영 HTTP 및 물리 수용은 계속 남는다.

이후 `2b1991f85`는 같은 쓰기의 receipt를 StationMotionFeed에도 전달한다. 원래 feed와 read 하한을 변환 전에 캡처하고 mono→UTC→mono bracket의 양끝으로 read 지연·최종 만료를 검사한다. 후속 state scope의 epoch로 재표기하지 않으며 원본 pose/twist가 불명하거나 cache 만료를 관측하면 새 원본 전까지 정지 증거가 없다. 실제 owner admission의 odom freshness 거절을 포함한 RED를 구분해 실행 계획에 기록했다. 실기 clock/profile·원본 에너지 admission·runtime 설치·HTTP ticket 통합과 DEVICE/FIELD는 계속 남는다.

test-only import 수정 `49564de0e`의 관련 원격은 516 PASS/0 SKIP/NEW 0이다. source/owner 경계 회귀와 continuous JPEG/HTTP SIM의 충전 세션 3개·이안/작업 3회·복귀/재충전 2회 및 station relocation을 포함한다. SIM의 contact/BMS·odom·clearance·energy는 합성이며 실제 bridge 원본 연결 시험과 같은 장치 수용으로 합치지 않는다.

parent 이전 원본 보관 `165c317e5`는 실제 bridge에서 시작한 불변 관측을 같은 StateManager 쓰기의 opaque token과 원래 header/frame/twist/read 구간에 결속한다. snapshot pose나 나중 wall 시각으로 최초 Budget을 만들지 않는다. 반복·실패한 header는 원래 수명을 늘리거나 수정된 원본으로 복구하지 못한다. 역사적 read-start/end와 최신 seal/accessor clock을 분리하고, 최종 writer에는 source lock을 추가하지 않는다. test-only clock fixture 수정 `bd3aebe7f` 뒤 관련 원격 540 PASS/0 SKIP/NEW 0이며 신규 bootstrap은 21건이다. 해당 receipt는 운동 허가나 활성 지도 내용의 인증이 아니다.

후속 admission은 실제 지도 전체 내용 digest·활성 generation과 승인된 map revision/변환을 결속해야 한다. 원래 계측한 battery energy의 pack/source/epoch/capacity revision·수명을 확인하고 parent 사이에도 같은 측정의 소비를 이어 센다. Fleet의 작업/귀환 추정치를 실제 usable Wh로 승격하지 않는다. 이후 HTTP 최초 reserve와 native ticket/StationOwner를 연결한 뒤 단일 폐쇄 factory를 최초 cycle 전에 설치한다. 기존 SIM·host 통과를 기본 factory 활성화 또는 실기 수용으로 해석하지 않는다.

원본 지도 조립 `78b095ec8`는 실제 bridge callback의 full grid를 Drive의 별도 evidence owner에 전달한다. CORE local observation generation·lifecycle epoch와 전체 digest를 유지하며 render cache를 권한으로 올리지 않는다. 원본 hash 중에는 snapshot이 닫히고, 모든 지도 수신/lifecycle 변경은 파싱 전 캡처한 parent에 STOP을 요청한다. 동일 grid 재수신에도 STOP하는 진행성 한계를 남긴다. 원래 header/load time의 역행·소모된 header 수정·늦은 hash와 lifecycle 경합을 검사하며 static map에는 odom TTL을 적용하지 않는다. 관련 32대상 host 651 PASS/0 SKIP/NEW 0이며 새 지도 회귀는 37건이다.

지도 수신과 실제 backend 채택은 별도다. 현재 source receipt에는 AMCL/global costmap의 adopted-map digest나 backend instance ACK가 없다. consumer 확인 및 승인된 Fleet revision/변환 결속이 갖춰질 때까지 운영 admission/factory는 닫아 둔다. 실제 map/energy·HTTP 연결과 실기 수용을 local observation generation으로 대체하지 않는다.

## 복귀 위치의 원본 TF 수명과 확인 한계

기존 map pose의 receipt 시각 재갱신을 원본 TF 수명으로 바꿨다. ROS-free reader는 원본 header/frame/planar geometry와 line→ROS→line bracket을 검사하고 시작 시각에서 source age를 보수적으로 뺀다. 같은 header는 기존 capture를 연장하지 않는다. State lock 대기 전 state clocks를 확보하고 commit 직전에 원본 lease를 다시 확인한다. 같은 source의 state 유효 시각은 갱신하지 않으며 만료 시 map freshness를 제거한다. 지도/lifecycle은 기존 exact-parent STOP과 source ticket/epoch를 먼저 갱신한 뒤 TF read를 무효화한다. lock rank는 lease→state→clock이며 최종 writer에는 새 잠금이 없다.

source `d3c1017f8`의 관련 검사는 705 PASS와 기존 형식 guard 1 FAIL이다. test-only `d261d4698`의 해당 guard 및 위치/localization/state 관련 5대상은 98 PASS/0 SKIP/NEW 0이다. [기록](../validation/station-map-pose-freshness-2026-10-17/result.md)은 두 revision을 구분한다. TF latest-common time은 원본 AMCL 측정 시각이나 위치 수렴·native 지도 채택 ACK가 아니다. LOCALIZED enum 유지 중 frame-only 상실에 대한 ongoing stop도 이 검증에 포함되지 않는다.

native adopted-map R1은 독립 검토에서 REVISE다. 실제 graph의 AMCL과 전역 StaticLayer에 대해 실제 처리 commit·원본 입력 identity·변경 경로/instance 수명·안정성/무효화·잠금·native 시험을 확정한 R2가 필요하다. model PC SDK 읽기 확인과 host TF 시험은 robot 설치나 native compile/test를 대신하지 않는다. 전체 충전·재투입·relocation 목표와 실기 수용은 유지한다.

## 외부 source 대조

2026-10-17 조회한 [rclpy Jazzy subscription 구현](https://github.com/ros2/rclpy/blob/jazzy/rclpy/src/rclpy/subscription.cpp)은 take_message metadata에 source/received timestamp와 지원되는 sequence 값을 싣는다. 이것을 native run 증명으로 간주하지 않는다. 조사한 branch와 실제 설치 binary의 지원은 별도 확인 대상이다.

[Nav2 Jazzy controller 구현](https://github.com/ros-navigation/navigation2/blob/jazzy/nav2_controller/src/controller_server.cpp)은 controller 취소 결과를 기다리는 경로가 있다. API cancel 요청 성공만으로 모든 controller/transport가 정지했다고 판정하지 않는다. 이 외부 source 대조는 현재 ROSY backend의 DEVICE 수용 증거가 아니다.

[Nav2 Jazzy map server 구현](https://github.com/ros-navigation/navigation2/blob/jazzy/nav2_map_server/src/map_server/map_server.cpp#L166-L179)은 ACTIVE에서 GetMap에 보관한 grid를 반환한다. 이는 server의 원본 대조에 쓸 수 있지만, 현재 ROSY에 없는 AMCL/global costmap의 지도 채택 확인 경로를 대신하는 것으로 해석하지 않는다.
