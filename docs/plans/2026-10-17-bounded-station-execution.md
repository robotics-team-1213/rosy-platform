# 충전 운행 한계 구현 계획

대상 설계: [CORE 운행 한계](2026-10-17-bounded-station-execution-design.md). 기존 충전 주기 계획 Task 18의 후속 단계이며 한 로봇·한 스테이션의 전체 자동 주기를 유지한다. 현재는 3단계의 실제 source·admission 조립을 진행한다. 내부 계산·private writer/native 연결과 원본 관측의 host 검증을 운영 factory 활성화나 장치 수용으로 대체하지 않는다.

## 1. 공통 parent 제한과 원본 관측

CommandManager 소유의 기존 command holder에 독립된 제한 모듈을 둔다. 미설치와 REQUIRED_WAIT/ACTIVE/소모 상태를 구분하고, parent 객체의 최초 deadline·누적 경로/회전·허용 공간·STOP 요청과 commit을 보존한다. bound는 운동 권한을 생성하지 않는다. profile과 parent identity는 frozen 값으로 만들고 현재 parent가 바뀌어도 옛 객체의 fault가 새 parent에 적용되지 않게 한다.

원본 stamp/source clock/frame/epoch와 finite pose/yaw를 검증한다. 첫 baseline부터 왕복·회전·coasting을 계산하며 원본 반복/역행/gap과 clock fault는 소모 상태로 남긴다. profile은 path/angle 과소추정·측정 오차·전체 전력·정지 tail·downstream watchdog 수용 근거를 요구한다. 원본 단위·시계 도메인을 섞지 않는다.

먼저 RED로 새 모듈 부재와 안전 반례를 확인하고 내부 상태/수명/측정 회귀를 통과시킨다. 이 단계만으로 runtime에 주입하거나 capability를 광고하지 않는다.

진행: `_execution_budget.py`는 최초 window의 시간×최대 물리 속도/각속도, 현재 공간 여유와 지금 정지할 tail, 원본 위치 수명·gap·epoch·불가능한 위치 변화, 비유한 값과 overflow를 검사한다. 이 초기 primitive 단계에서는 실제 writer/부트별 parent ID 소모 원장·수락 소유권·native child를 연결하지 않았다. 후속 private 연결은 아래 a9efc3800 절에 기록했다. `energy_upper_j`는 현재까지 경과 시간과 지금 정지할 tail의 전체 부하 상한이며 미래 작업 전체의 에너지 예산이 아니다. 합성 profile 검증은 실제 감속도·watchdog·원본 시계·전체 전력의 수용 근거가 아니다.

진행 추가: `194826e8a`의 `_execution_ledger.py`는 선언된 boot/robot/profile/odom scope와 원래 adoption 기한을 대조하는 내부 메타데이터 원장이다. 부트 전체 parent ID와 `(domain, boot, native run)` 소비 키를 유한 용량 안에서 유지하고 용량이 차면 거절한다. revoke한 run은 generation을 높여도 재사용할 수 없다. 실제 `NativeReceipts.update()`는 같은 run의 phase 갱신에도 owner generation을 증가시키므로, 현재 attach된 exact child에만 별도 `advance()`를 허용한다. 이는 기존 Budget과 소비한 run 수를 유지하고 readback epoch만 전진한다. 늦은 parent handle/child cleanup은 현재 parent를 바꾸지 못한다. `STOP` 후 `retire`는 메타데이터 정리이며 실제 정지 확인은 아니다. 194826e8a 단계에서는 단일 CORE owner의 부트 전체 유일 설치, 실제 native receipt/에너지/정지 검증과 writer 연결이 없었다. 후속 private writer 연결과 남은 runtime 조건은 아래 절에 구분한다.

원격 `execution-ledger-green`은 `194826e8a`에서 새 원장/계산·기존 station owner/착좌/충전 완료·구조/안전 분리/harness 268 PASS, skip 0, NEW 0으로 종료했다. 독립 scoped 안전 검토와 source trailer 검사를 통과했다. 이 시험은 실제 카메라 입력·전체 HTTP 주기·실기 수용을 새로 검증한 것이 아니다.

## 2. 선택 receipt와 실제 writer fence

CommandManager의 기존 선택 경로를 사용해 실제 출력 값·input epoch·mode epoch·parent/typed-child epoch를 불변 receipt에 결속한다. 기존 API의 Twist 값 반환은 호환하며 receipt는 허가받은 최종 경로에서만 사용한다. 다른 후보·옛 선택·값 변경·다른 parent/child·중복 제출의 receipt는 거절한다. raw Nav2 입력의 논리 출처는 UNATTRIBUTED로 유지한다.

cmd_vel_cycle의 동일 PinkyTwistPort 제출을 최종 fence에서 실행한다. 기존 trial이 설치돼 있으면 그 검사가 바깥에서 끝난 뒤 안쪽 공통 fence가 다시 clock/원본/STOP을 확인한다. 반대 순서의 느린 검증으로 deadline을 넘긴 출력을 허용하지 않는다. mode lock→제한 fence를 비차단 획득하고 writer에서 native owner lock으로 들어가지 않는다. 새 50Hz 경로에서 DB/network/event/mode transition을 호출하지 않는다.

경합의 fault-request와 STOP commit, 이미 진행 중인 단일 직렬 writer의 순서를 시험한다. fault-request를 유실하지 않는 원자적 단방향 저장을 대상 Python runtime에서 확인한다. 같은 fence 안에서 STOP과 writer를 직렬화하고, 실제 writer 전달 불명은 parent를 소모한다. ZERO 제출/관측과 물리 정지를 구분한다.

`threading.Event.set()`은 내부 Condition 잠금 때문에 비차단 STOP 저장으로 채택하지 않았다. 검토 당시 `set_nav_twist(None)`, `set_docking_twist(None)`, `clear_manual()`의 입력/epoch 변경은 모두 mode lock 아래 있지 않았다. 선택·최종 검사만 잠그고 이 clear 경로를 남기면 검사와 writer 사이에 입력 무효화가 끼어든다.

`ce12776c6`은 입력 clear를 mode lock 아래의 순수 필드 갱신으로 직렬화했다. manual/watchdog/input epoch와 policy/E-stop listener의 전체 입력 무효화를 먼저 처리하고, native receipt 정리와 이벤트는 outer mode lock 밖에서 실행한다. 실제 mode listener도 같은 helper를 쓴다. 캡처한 native session만 닫아 늦은 정리가 새 수동 pulse를 종료하지 못하게 한다. source는 507 lines이며 크기 한도를 높이지 않았다.

입력 race·직접 clear/모드 이탈의 native 경합·지연 close의 RED 6건을 확인했다. 정책 clear의 첫 시험은 활성 MANUAL→NAV 전환이 거절되는 준비 단계에서 실패했으므로 그 실패를 동작 증거로 쓰지 않는다. 정상 IDLE 인계를 추가한 시험만 수정 전 source에 대조한 `672e8bf212`에서, 기존 실제 cmd_vel_cycle이 ZERO 대신 `(0.1, 0.0)`을 전달하는 RED를 확인했다. 이 대조 커밋은 `18d74cefc`와 시험의 IDLE 인계 한 줄만 다르며 command source는 동일하다. 수정 source와 정상 시험을 합친 `f3503ce86`의 원격 `command-input-fence-green-corrected`는 251 PASS, skip 0, NEW 0이다. 독립 scoped 검토와 source trailer 검사도 통과했다.

이 ce12776c6 수정은 입력 clear의 경계를 정렬한 것이다. 당시에는 새 budget/parent/child의 sealed selection, 비차단 STOP store, 동일 최종 writer fence와 실제 native/장치 수용을 연결하지 않았다. ZERO 전달의 host 회귀를 실제 물리 정지나 접안 정밀도 수용으로 해석하지 않는다.

### 최종 writer 내부의 관측 분리

실제 ROSBridge._send_twist에는 ROS 발행 뒤 D-422 차선 추종 메모리 갱신과 경고 로그가 함께 있었다. 이 함수를 새 Mode/Ledger fence 안에서 그대로 호출하면 후처리 잠금과 이벤트가 출력 잠금 안으로 들어갈 수 있다. `1fc85c6f9`은 동일 publisher를 유지하면서 raw 발행과 `_note_wheels`를 분리했다. `cmd_vel_cycle`은 Port close·기존 trial transaction 해제 뒤에만 `notify_written`을 호출하고, 그 다음 power/events를 처리한다. 정상 반환한 host write와 ZERO fallback만 해당 값을 관측하며 물리 수신·정지 ACK로 해석하지 않는다. 관측 예외는 성공한 발행을 전달 불명으로 바꾸거나 비제로 재전송·trial 소모로 이어지지 않는다. 전송 불명인 비제로에는 성공 관측을 보내지 않는다.

원격 RED `a93774889`는 미구현 keyword/배선 16 FAIL/NEW 16이다. 최초 GREEN 요청은 잘못된 구조 시험 경로로 exit 4였고 시험을 실행하지 못했다. 경로를 교정한 `1fc85c6f9`는 319 PASS/0 skip/1 FAIL이며, 실패는 기존 bridge 시험 fixture에 새 `_note_wheels`가 없는 경우였다. `7d5eadfd3`은 fixture에 callback을 넣고 성공한 출력과 관측 목록의 일치 assertion을 추가했다. 독립 scoped source·fixture 검토는 PASS이고 최종 원격 결과는 후속 기록으로 확정한다. 이 단계는 실제 실행 fence의 설치·권한·장치 수용이 아니다.

이후 설치 경계에서는 IDLE만 확인하지 않는다. 이미 fence 없이 선택 중인 cycle이 나중에 설치한 제한을 우회할 수 있으므로, 동일 writer의 모든 cycle과 설치를 직렬화하고 최초 cycle 시작 후 설치를 거절하는 조건을 검증한다. 원래 parent/child와 입력·모드 epoch에 봉인한 receipt, 기존 느린 trial 검사 뒤의 최종 재검사, 경합·재진입에서 중복 ZERO나 비제로 재전송 방지와 old-parent fault의 새 parent 격리는 아래 a9efc3800 단계에서 private 경로로 구현·시험했다. 운영 runtime 설치와 실제 native 수용은 계속 남아 있다. 기본 GIL이 있는 지원 CPython 판별만으로 STOP 저장/제출의 race가 해결됐다고 주장하지 않는다.

최종 원격 `writer-observation-green-final`은 `7d5eadfd3`에서 320 PASS/0 skip/NEW 0/exit 0으로 종료했다. 새 관측 시험·기존 cmd_vel/Port/trial·D-422 line follow·bridge observation/등록·watchdog/core logic·모듈 경계/구조·안전 분리를 포함한다. `ros_bridge.py`는 888 lines로 기존 ratchet을 유지하며 한도를 높이지 않았다. 실제 ROS 배포나 장치 동작 검증은 실행하지 않았다.

### private 선택 receipt와 최종 writer 연결 검증

`a9efc3800`은 실제 CommandManager에 부트 scope 원장의 1회 private 설치, 정책 전후의 원래 parent/typed child/mode/input epoch 봉인, 같은 Port의 최종 제출 검사를 연결했다. 실제 cycle이 한 번이라도 시작되면 legacy ZERO였어도 설치를 거절한다. 설치와 모든 실제 cycle/ZERO/예외 경로는 같은 cycle lock을 사용하고 중복·재진입은 두 번째 발행 없이 STOP request만 남긴다. 최종 Mode→Ledger→Budget 획득은 비차단이며, 관측·로그·native bookkeeping은 그 경계 안에 넣지 않는다.

기존 참조의 Budget operation과 claim 전체를 같은 비차단 잠금으로 직렬화한다. 센서 읽기의 원래 시작/종료 구간은 writer가 그 사이 확인한 monotonic 시각과 분리하고, 원래 capture lower bound를 앞으로 옮기지 않는다. budget과 입력 TTL은 같은 최종 sampled clock으로 검사한다. STOP request는 지원 대상 GIL runtime의 plain slotted 단방향 bool이며, software STOP은 Ledger 경계에서 별도로 확정한다. Budget 경합 중에는 `STOP_REQUESTED`이고 확정 전 `STOPPED`로 표시하거나 다음 tick에서 ACTIVE로 복구하지 않는다. MANUAL/EMERGENCY 인계는 중간 writer tick 없이 복귀하더라도 원래 parent를 소모하며, 정지한 자동 예산이 기존 수동 권한을 막지 않는다.

초기 기능 RED `01a901f3a`는 미구현 설치 경로 19 FAIL/NEW 19다. 독립 검토의 claim 경합·정상 read span·최종 clock 불일치는 별도 defective witness `4aec2deb43`에서 19 PASS/3 FAIL/NEW 3으로 재현했다. 추가 witness `a3411b42ee`는 29 PASS/4 FAIL/NEW 4로 hardware/device/trial 오류의 parent 미소모와 Budget 경합의 잘못된 STOP readback을 확인했다. 두 witness는 외부 임시 index로 만든 소유 test ref이며 제품 branch HEAD/index를 되돌리지 않았다. 이 witness를 accepted source로 사용하지 않는다. 수정 후 원래 receipt parent를 대상으로 요청해 callback 중 교체된 새 parent는 소모하지 않는다. raw writer 진입 전에 receipt를 소모해 중복 제출·전달 불명에서 비제로를 재시도하지 않는다.

원격 `execution-writer-green`은 `a9efc3800`에서 572 PASS/0 skip/NEW 0/exit 0으로 종료했다. 새 38개 writer restriction case와 기존 최종 출력/관측·Port/trial·D-422·bridge·watchdog/CORE·Budget/Ledger/input clear/shadow/manual·구조/안전 분리/harness를 결합했다. 독립 scoped source/추가 회귀 검토와 D-430 trailer 검사도 통과했다. 최초 지원 조건은 traditional CPython 3.12이며 실제 로봇 interpreter·물리 watchdog/제동·source clock/profile 수용을 이 host 시험으로 대체하지 않는다.

이 단계의 private 최종 출력 연결은 검증됐다. 운영 factory 설치·capability·actual native owner admission/취소·활성 map/에너지 proof는 아직 없다. raw Nav2 입력의 논리 출처는 계속 UNATTRIBUTED다. 일반 Python lock-free, hard real-time, 실제 이동·물리 정지·접안 정밀도나 전체 충전 운용 완료를 주장하지 않는다. 다음 단계는 선언한 child를 실제 native run에 결속하는 아래 조립이다.

추가 exact-handle 점검에서는 `copy.copy`/`dataclasses.replace`가 parent의 mutable STOP flag를 공유하는 경우를 발견했다. 기존 원장은 복사 handle을 거절했지만 새 wrapper가 먼저 flag를 바꾸는 결함이다. `7b857ab56`의 네 가지 stop/request 회귀는 실제 cycle이 ZERO를 발행하는 RED 4 FAIL/NEW 4로 확인했다. `4a82303e4`는 flag 저장 전에 현재 parent 객체 identity를 확인한다. 이미 retire된 parent의 요청은 무시하며 새 parent로 대상을 바꾸지 않는다. 수정 후 `execution-writer-green-final` 원격은 576 PASS/0 skip/NEW 0/exit 0이며 신규 writer 회귀는 총 42개다. exact diff의 독립 scoped 검토도 PASS다. 최초 572건을 복사 handle 검증의 근거로 사용하지 않는다.

### 정상 갱신과 실행 고장의 분리

`f9c05107a`는 유효한 기존 선택의 input/child generation이 바뀌었을 때 이전 출력만 ZERO로 버리고 같은 parent/Budget을 유지한다. 원래 입력 timestamp의 TTL, 원래 parent의 STOP·clock·예산과 receipt 1회성·값 무결성·물리 속도 제한을 먼저 검사한다. 갱신이 이 고장과 겹치면 parent를 소모한다. 정상 교체도 receipt는 소비하며 gateway는 private sentinel을 거절 결과로 바꿔 같은 writer에서 ZERO를 발행한다.

`7d28c28c8` RED는 정상 갱신 네 경우 4 FAIL/NEW 4와 다른 49 PASS다. 첫 확장 시험은 702 PASS/2 FAIL/NEW 2로 끝나 기존 symbol 추적과 공개 진단 도구 hash 등록 누락을 드러냈다. `61e95e784`는 단일 허용 생성 symbol을 실제 `_cmd_vel_cycle`로 교체하고 두 공개 hash를 정확한 path/line hash/value에만 등록했다. frozen 현장 결과와 scanner는 변경하지 않았다. 최종 원격 `execution-refresh-green-final`은 745 PASS/0 skip/NEW 0/exit 0이다. 새 writer 회귀는 총 53개이며 실제 native lease가 아닌 선언 child generation 갱신을 포함한다. 동일 parent/Budget의 원래 시작·duration과 경과 시간/경로/회전/에너지 소비 보존을 확인했다. 운영 factory·native hooks·실기 수용은 계속 남아 있다.

## 3. CORE admission·native owner·source 조립

실제 manager에는 Drive 소유의 작은 helper와 주입된 binding을 사용한다. `middleware/drive/behaviors`가 CORE-private mixin을 import하거나 상속하지 않는다. 기존 `NativeReceipts` foundation은 유지한다. 설치 시 소유자 잠금 순서는 기존 docking→navigation 호출 방향에 맞춰 Dock→Nav이며, final writer는 Mode→Ledger만 획득한다.

`cfa8ab1ad`의 명시적 private 설치는 실제 CoreServices의 robot/BOOT와 빈 owner를 확인하고 최초 cycle 전에 단 한 번 연결한다. fence가 보이기 전 native domain을 닫아 두고, 설치 중 cycle이 시작되면 닫힌 제한을 남긴 채 거절한다. 기존 mode owner가 NAVIGATION을 준비하며 binding은 새 mode 권한을 갖지 않는다. 기본 runtime factory는 이 installer를 호출하지 않는다.

private 경로는 native generation 변경 전에 child를 pause하고 실제 owner의 receipt 객체와 generation 증가를 확인한 뒤 전진시킨다. 최초 NAV는 scoped RUNNING 수락까지 닫고, Dock은 `_take_mode` 전 재검증과 실제 DOCKING/UNDOCKING 상태 후 활성화를 사용한다. Dock의 public SUBMITTED phase를 임의로 바꾸지 않는다. 전체 호출 인자·원래 spec·native snapshot에 결속한 1회 ticket을 entry와 admit 전에 확인한다. cancel은 필터와 no-op 판정 뒤 backend 호출 전에 parent를 닫는다. 완전히 unscoped 일반 cancel만 reservation-only admission을 폐기하며 옛 terminal run의 scoped cancel은 새 reservation을 건드리지 않는다.

성공 종료와 최초 활성화는 해당 입력 slot을 clear한다. 첫 입력이 없으면 budget을 계속 검사하면서 ZERO로 기다리고, 원래 선택했던 입력의 TTL 만료·변조·STOP은 별도로 소모한다. STAGING token은 Dock이 phase를 바꾸기 전에 Dock→Nav 잠금으로 폐기한다. 선언 child를 직접 attach/advance/revoke하는 경로는 native owner claim 뒤 거절한다. 이는 trusted-process의 private 경계이며 적대적 Python reflection에 대한 보안 경계가 아니다.

최초 `cd279381e` RED는 미구현 module 때문에 12 ERROR/1 FAIL, 별도 foreign-cancel 결함 1 FAIL로 NEW 14다. 독립 검토의 defective witness `c2122fe5b1`은 15 PASS/7 FAIL/NEW 7, 첫 입력 WAIT 회귀를 추가한 `e333d3fcd3`은 15 PASS/8 FAIL/NEW 8이다. 두 tree는 별도 owned ref의 진단 근거이며 accepted source가 아니다. 수정 `cfa8ab1ad` 관련 원격은 363 PASS/0 skip/NEW 0/exit 0으로 종료했고 actual CoreServices·native callback 재생·같은 final writer 회귀 23개를 포함한다. 같은 source의 lab mapped 확장은 7065 PASS/217 SKIP/1 FAIL/NEW 1이다. 기존 handover 이벤트의 boot_id/run_id 문서 누락을 API-002 Corrective로 수정하고 별도 재검증한다. ROS/Gazebo 실행이나 장치 수용, FULL CI 통과로 확대하지 않는다.

공통 fence는 CommandManager가 소유한다. NavigationManager와 DockingManager는 각각 NAV와 dock/undock의 `(domain,boot,run,generation)`을 자기 ledger 잠금 아래 attach/revoke한다. native owner lock→mode lock→공통 fence 순서와 기존 mode listener의 lock 밖 실행 규칙을 보존한다. 새 backend 호출 전에는 gate를 닫고 검증된 child 수락 후 해당 phase만 연다. 모든 native owner 변경 경로와 늦은 결과/cleanup을 추적한다.

`a67abda37`은 실제 `_on_odom`이 변환 전에 private 실행 parent를 캡처하도록 연결했다. 읽기 전후는 Ledger와 같은 monotonic clock을 쓰며 원래 ROS source clock·header stamp·frame·body frame·유효한 planar quaternion과 원래 위치를 검증한다. StateManager는 같은 쓰기 잠금 안에서 wall/epoch tuple을 반환하고 기존 `set_odom_pose`의 wall 반환은 유지한다. Budget 관측은 legacy station/trial/lane observer 전에 전달한다. 실패는 원래 parent에만 STOP request를 남기며 읽는 도중 교체된 parent에 관측·정지를 재귀속하지 않는다. state 파일과 실제 adapter/receipt anchor를 safety로 등록하고 기존 CORE DI의 StateManager class import만 공개 anchor로 유지했다.

원격 `4a26d78dd` RED는 미구현 adapter/receipt와 callback 배선 17 FAIL/NEW 17이다. 최초 source `8d3da8488`은 351 PASS/1 FAIL/NEW 1로, 실패는 bridge가 888→887줄로 줄어든 크기 기록 누락이다. 이 tree는 별도 owned ref `test/execution-odom-ratchet-red-8d3`로 보존하고 자체 미공개 source commit에 887 row를 함께 넣어 `a67abda37`로 교정했다. 최종 관련 원격 `execution-odom-green-final`은 352 PASS/0 SKIP/NEW 0/exit 0이다. 새 17건은 같은 final writer의 성공/실패, 원본 재생·읽기 지연, 다른 legacy/state clock, 실제 callback 배선, atomic epoch receipt와 읽기 중 parent 교체를 포함한다. 독립 scoped source 검토·D-430와 두 commit의 size-range 검사도 통과했다. selector는 FULL이며 lab mapped 51대상 종료 결과와 수정은 아래에 구분한다. FULL CI·ROS/실기 source clock 수용으로 확대하지 않는다.

다음은 실제 clock/profile·활성 map/에너지 admission과 runtime의 유일 설치를 연결하는 단계다. 기존 StationDockingOwner/HTTP 경로도 같은 실제 context와 ticket을 사용하도록 통합해야 한다. private fixture 설치만으로 운영 charging API나 capability를 활성화하지 않는다. Manual 인계/안전 정지는 기존 우선권을 유지하면서 parent를 소모하며 새 boot는 이전 parent를 재개하지 않는다.

### 실제 station 정지 관측의 원본 귀속

`a67abda37`의 lab mapped 51대상은 7367 PASS/217 SKIP/1 FAIL/NEW 1로 종료했다. 실패는 실제 CORE/bridge/final writer 통합 시험 다섯 파일의 D-184 소유권 등록 누락이다. 독립 검토 뒤 정확한 다섯 경로와 통합 사유만 등록했고 scanner·집합 동일성·기존 실패 기준은 바꾸지 않았다. FULL CI 통과나 217 SKIP의 실행을 주장하지 않는다.

`2b1991f85`는 별도로 남아 있던 StationMotionFeed의 이후 state scope 조회를 제거하고 같은 메시지의 wall/epoch receipt를 사용한다. bridge는 원래 feed와 읽기 하한을 변환 전에 고정한다. Feed의 mono→UTC→mono bracket은 UTC를 원래 시작 하한으로 투영하며, 원본 stamp의 age와 전체 adapter 지연을 차감한다. 유효한 원래 planar pose/body twist만 받으며 잘못된 입력·변환 실패·범위 없는 직접 호출은 캡처한 feed를 비운다. Budget의 원래 parent 귀속은 유지한다.

observe와 snapshot은 같은 bracket의 마지막 mono·보수적인 UTC 상한으로 수명을 확인한다. 반환식에서 clock을 다시 읽지 않고 두 수명의 작은 값으로 TTL을 제한한다. 실패·만료를 확인한 cache는 새 원본 관측 전까지 되살아나지 않는다. 이 계산은 설치 profile의 실제 clock 의미·물리 정지 증명을 대신하지 않는다.

최초 `b810cde9a` 원격 RED는 12 PASS/17 FAIL/NEW 17이며, 추가 clock 경합을 고정한 `ba0ba9070`은 12 PASS/21 FAIL/NEW 21이다. 실제 StateManager·motion feed·owner admission에서 옛 속도의 새 epoch 재표기와 읽기 지연 freshening, 원본 pose 오류, unscoped 호출, 변환 실패, 관측한 만료의 부활과 최종 clock 조회 경합을 재현했다. `2b1991f85` 첫 관련 확장은 515 PASS/1 FAIL/NEW 1로, 연속 camera HTTP SIM 시작 과정에서 CORE/Fleet 동명 `test_trip_lease` 모듈이 충돌했다. `49564de0e`는 CORE 상수 import만 정확한 namespace로 고정했고 생산 Python은 같다. 같은 23대상의 최종 `station-motion-read-green-final`은 516 PASS/0 SKIP/NEW 0/exit 0이다. 신규 motion 21건과 기존 12건, 원본 execution/native/writer·seating/sensors·ownership/structure/safety/harness/network 및 continuous camera HTTP SIM을 포함한다.

continuous SIM은 렌더한 JPEG 상대 인식과 실제 Fleet/CORE HTTP·native/final writer를 사용한다. 검증한 반복 수는 충전 세션 `charge-1`~`charge-3`, 이안·선택 작업 3회, 복귀·재충전 2회이며 station pose revision 2의 이동 복귀를 포함한다. 마지막 세 번째 작업 완료 뒤에는 시험이 끝난다. contact/BMS·거리계·rear space/isolation·energy는 명시적 합성 source이며 원본 bridge adapter 회귀와 별도다. 실제 ROS 원본·charger·물리 착좌·제동·운영 factory 전체 수용은 남는다. 독립 scoped source/import 검토 PASS, 관련 네 commit의 D-430·size-range도 통과했다. 전체 목표는 ACTIVE다.

late initial admission, stop과 admission 경합, parent 갱신/child 교체의 예산 reset, 옛 결과가 새 실행을 바꾸는 경로를 먼저 RED로 고정한다. 실제 CoreServices와 final writer를 함께 사용하는 SIM에서 검증한다. private 구성만 통과한 단계를 운영 API 지원으로 표시하지 않는다.

후속 `605ba2c17`의 모델 PC 원격 `native-owner-catalogue-green`은 256 PASS/0 SKIP/NEW 0/exit 0이다. API-002 Corrective 이벤트 표와 단일 handover 이벤트, native binding 24건, protocol schema·harness/network를 검증했다. 추가 이안 회귀는 접안 완료·release를 주입한 뒤 실제 Undock과 첫 ZERO WAIT·역방향 candidate를 같은 parent/Budget/final writer로 연결한다. 주입은 물리 착좌·충전·출발 수용이 아니다. 기존 확장 검사의 217 SKIP과 FULL CI 미실행은 그대로 남는다.

### parent 이전 원본 관측 확보

`165c317e5`는 private native 설치에 exact Limits/profile을 요구하고, parent가 없는 동안에도 실제 `receive_odom`의 원본을 frozen receipt로 보관한다. raw header·source clock·전체 planar body twist·같은 StateManager 쓰기의 robot/map/epoch token과 원래 read 구간을 함께 검증한다. 다른 state 쓰기, map ID 왕복, 실패한 원본 header의 수정 재입력은 관측을 되살리지 못한다. 반복 header는 최초 수명을 연장하지 않는다. monotonic fault는 부트 수명 동안 유지하며 역사적 read-start/end와 현재 seal/accessor clock을 구분한다. 최종 writer는 이 source lock을 읽거나 획득하지 않는다. receipt는 관측 근거이며 운동 허가가 아니다.

미구현 RED `0b723aad5`는 1 PASS/17 ERROR/NEW 17, 추가 경계 RED `c0487276a`는 1 PASS/21 ERROR/NEW 21이다. 모두 없는 `source_limits` installer API에서 setup이 차단된 결과이며 개별 반례 실행 성공을 뜻하지 않는다. 최초 GREEN 요청은 bridge timer 시험 경로 오기로 수집 전 exit 4였다. 경로 교정 후 `165c317e5`의 24대상은 538 PASS/2 FAIL/NEW 2였다. 두 신규 clock fixture가 lane observer의 두 번째 clock 읽기에도 최초 interposition을 반복했다. source 변경 없이 `bd3aebe7f`에서 해당 fixture만 고친 동일 24대상 최종 원격은 **540 PASS/0 SKIP/NEW 0/exit 0**이다. 신규 bootstrap 21건과 원본 execution/native/writer·station motion/seating/sensor·CORE/bridge/lane·Budget/Ledger·구조/소유권/안전/harness/network를 포함한다. source와 fixture 수정은 각각 독립 scoped 검토를 통과했다. FULL selector의 GitHub 전체 검사와 기존 continuous SIM은 이 실행의 검증 범위에 포함되지 않는다.

다음 연결 순서는 실제 map 내용 전체의 digest와 활성 generation → 승인 profile/변환 → 원래 실측 energy source와 parent 사이 소비 원장 → HTTP reserve_goal/native ticket와 StationOwner → 최초 cycle 전 단일 폐쇄 factory다. 이 receipt의 map ID와 표시용 occupancy ID를 승인 map revision으로 쓰지 않는다. usable Wh를 매 parent마다 다시 배정하지 않고 대기/ZERO·parent 사이 부하도 센다. 전체 허용 window의 부하와 reserve는 Budget의 현재까지 소비/정지 tail 상한과 별도로 비교한다. source가 부족한 factory는 REQUIRED_WAIT를 유지해야 한다. 기본 factory 설치, 실제 admission/운영 HTTP 연결, 전체 3회 복귀 주기와 DEVICE/FIELD 수용은 계속 미완료다.

### 원본 지도 관측과 정지 요청

`78b095ec8`는 Drive 소유 `navigation/map_evidence.py`를 기존 private NativeExecution에서 NavigationManager의 선언된 evidence slot에 조립한다. 새 NAV-005 mapping session 상태나 mapping package를 만들지 않는다. 실제 `_on_map`은 ROS-free adapter로 원본을 전달하고 map-server/SLAM lifecycle callback은 같은 owner의 ticket/관측을 폐기한다. 표시용 MapSnapshotStore를 역으로 읽어 증거를 만들지 않는다.

관측 receipt는 robot/boot, 전체 SHA256, frame·width/height·resolution·origin의 위치/회전 7값, 원래 header/load time, local observation generation/lifecycle epoch를 보존한다. digest 형식은 `ROSY-GRID-v1\0` prefix, little-endian uint32 UTF8 frame 길이와 frame, `<II8d` 크기·해상도·origin, 순서 그대로의 signed int8 cell bytes다. header 시각은 내용 digest와 별도 메타데이터다. 최대 4,194,304 cells를 순회 전에 검사하고 원본 범위·planar quaternion·finite 값과 occupancy -1~100을 검증한다. 이 메모리 상한은 실측 주행 profile이 아니다. 큰 복사/hash는 owner lock 밖에서 수행하며 같은 ticket인지 완료 시 재검증한다.

검증 동안 관측 snapshot은 닫힌다. 모든 원본 지도 수신과 lifecycle 변경은 파싱/hash 전에 캡처한 parent에 STOP을 요청한다. **같은 지도 재수신도 기존 parent를 멈추는 보수적인 진행성 한계**가 있으며 정상 재수신 최적화는 별도다. STOP 요청·Ledger의 software STOP commit·물리 정지를 구분한다. 실패/소모된 header, 역행, A→B→A와 옛 callback은 새 관측 또는 replacement parent의 수명을 재표기하지 못한다. static latched map의 오래된 header에 odom TTL을 적용하지 않으며 lifecycle 이후 옛 latched 전달도 새 epoch의 관측일 뿐 backend ACK가 아니다.

`d5d3d4ebc` RED는 1 PASS/29 FAIL/8 ERROR/NEW 37이며 새 adapter/evidence module 부재로 실패했다. source `78b095ec8`의 관련 원격 32대상은 **651 PASS/0 SKIP/NEW 0/exit 0**이다. 신규 지도 37건, 이전 bootstrap/odom/native/writer/station source와 지도 표시·readiness·MANUAL/SLAM·CORE/구조/안전/harness를 포함한다. 별도 thread가 hash 완료 전에 lifecycle을 끝내는지, STOP commit 뒤 parent 교체, 데이터 길이가 맞는 oversized 입력의 비순회 거절도 검증한다. 독립 scoped source 검토 PASS이며 bridge는 887→881줄로 줄여 ratchet을 낮췄다. selector FULL의 CI 전체 및 이번 continuous SIM/장치 실행은 이 시험에 포함되지 않는다.

이 관측의 generation은 **CORE local observation generation**이다. 실제 backend instance/generation 또는 AMCL/global costmap이 채택한 지도 revision으로 간주하지 않는다. 소비자 측 채택 확인, 승인 Fleet revision/좌표 변환↔전체 digest 결속, 원래 energy 계측/소비, HTTP ticket·단일 폐쇄 factory, 전체 3회 복귀와 DEVICE/FIELD는 계속 남아 있다. 기본 runtime 설치와 운영 admission을 이 source 결과로 열지 않는다.

### 복귀 좌표의 원본 TF 수명

`d3c1017f8`는 cached map→base TF를 매 tick 최신 시각으로 갱신하던 동작을 제거했다. 원래 dynamic header·resolved frame·planar geometry, line/ROS/line bracket과 전체 조회·State lock 대기를 검사한다. 같은 header와 멈춘 source clock은 수명을 늘리지 않고 clock fault는 같은 bridge에서 재생으로 회복하지 않는다. StateManager도 원본 유효 시각을 보존해 odom이 없어도 만료된 map 위치를 fresh로 내보내지 않는다. 지도/epoch 변경은 늦은 TF를 버린다.

관련 30대상은 705 PASS/1 FAIL/0 SKIP이며 실패는 제거한 inline 갱신을 기대하던 기존 AST guard 하나다. test-only `d261d4698`에서 그 기대값을 보정하고 원본 TF·cross-lane·localization API·state odom·ownership 5대상을 재검증해 98 PASS/0 SKIP/NEW 0으로 종료했다. 두 revision의 범위와 미실행 항목은 [검증 기록](../validation/station-map-pose-freshness-2026-10-17/result.md)에 분리했다. 최신 revision에서 전체 706건을 다시 통과했다고 합산하지 않는다.

이 변경은 후속 localization admission의 거절까지 검증한다. 진행 중 명령의 frame-only 상실 정지, 실제 native adopted-map ACK/승인 좌표 변환, 원본 energy·HTTP/factory·전체 3회 복귀와 DEVICE/FIELD는 계속 남아 있다. 실제 Nav2 소비자 설계 R1은 REVISE이며 실행 graph의 대상은 AMCL과 전역 StaticLayer다. 로컬 costmap의 미활성 static parameter block을 소비자로 추가하지 않는다.

## 4. 공개 계약과 설치 프로필

필요한 parent 생성/참조·admission 기한·readback/소모 사유·실제 지원 capability를 source producer/consumer에 맞춰 확정한다. ADR/API reservation 도구로 번호를 확보한 뒤 SRS/API reference/shared schema·CORE/Fleet producer-consumer를 같은 변경으로 갱신한다. 현재 계획의 용어를 이미 공개된 필드명으로 취급하지 않는다.

설치 profile은 물리 수용 evidence의 identity/revision과 허용 한계를 포함하며 nominal 설정값을 실측으로 만들지 않는다. parent ID는 같은 boot에서 재사용하지 않고 보존 한도 초과는 거절한다. 실제 지원하지 않는 backend/profile은 charging admission에서 WAIT한다. 기존 20cm private trial을 public arming 경로로 바꾸지 않는다.

## 5. Fleet 예산·factory·전체 주기

기존 ChargeFactSource, ChargeWorldPoseSource, ChargeWorkSelector와 활성 지도/경로 원장을 사용한다. profile의 실행 한계와 원본 facts·work digest·station pose/cost revision을 결속해 departure→work→모든 return segment→dock의 전체 시간·거리·회전·ZERO/대기 부하·정지 tail과 reserve를 계산한다. parent의 허용 공간 안에 있는 임의 중간 위치의 귀환 가능성도 검사한다. 지원하지 않는 작업·변환·경로는 WAIT한다.

기존 app factory/CLI가 같은 TaskStore·TripRunner·World·CORE client를 조립하게 한다. 기존 session은 실제 ingress scope를 사용하고 새 bootstrap은 실제 session/profile/original facts에만 결속한다. 새 parent는 실제 정지/종료 경계와 새 에너지 admission을 요구한다. work→return 전환이나 station relocation을 단순한 예산 reset으로 처리하지 않는다.

실제 HTTP와 승인 파일 source를 통한 3회 SIM을 실행한다. 카메라 상대 접안·착좌/정지·BMS 완료·departure·선택 작업·복귀·station relocation과 parent 한계 소진을 포함한다. 지연/재생/재시작/수동 인계/출력 경합/원본 유실에서 ZERO·HOLD·claims와 exact cleanup을 확인한다. SIM profile 근거는 DEVICE/FIELD와 별도로 기록한다.

## 6. 장치 실습 수용

현장 담당자의 렌즈 가림·방향·조명 확인은 사용자 답변에 따라 이후 가능한 일정으로 남긴다. 확인 전에는 기존 상부 영상의 과소노출이나 오래된 이동 로봇 위치를 정상 시야·현재 위치로 수용하지 않는다. 현장 확인이 가능해지면 새 영상과 원본 위치를 다시 관측해 아래 수용 절차를 진행한다.

기존 Fleet PC·OMX·카메라·지도 경로를 사용한다. 이동 로봇의 현재 연결/원본 위치·실제 charger/BMS/contact와 장치 profile, 전체 출력→watchdog→물리 정지의 상한을 확인한다. source가 없으면 설치 지원/건강도/완료를 추정하지 않는다. 실제 사람의 현장 확인이 필요한 단계에는 응답을 받고 진행한다.

한 스테이션·한 이동 로봇의 실제 상대 위치 오차, 관측 유실 정지, 착좌와 정지 후 후속 처리, 충전 완료/이안·재투입과 station 이동 복귀를 수용 기준으로 대조한다. 미확인 정밀도·BMS/제동·실제 운행을 소프트웨어 시험으로 완료 처리하지 않는다. 이 단계가 남으면 전체 목표는 ACTIVE다.
