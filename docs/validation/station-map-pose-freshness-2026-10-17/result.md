# 스테이션 복귀 위치의 원본 TF 유효 시간

상태: 아래 범위의 host 검증을 확인했다. 전체 스테이션 목표는 ACTIVE다.

## 변경과 판단 범위

기존 `_tick_state`는 cached TF 조회 성공마다 현재 시각으로 위치 수명을 갱신했다. source `d3c1017f8`는 원래 dynamic TF header와 요청/반환 frame, planar geometry를 검사하고 원본 나이를 기존 line clock에 보수적으로 투영한다. 같은 header 재조회와 멈춘 ROS clock은 수명을 늘리지 않는다. clock 역행/비정상 값은 bridge 수명 동안 거절한다. 정상 만료 뒤에는 새 원본 TF로 회복할 수 있다.

조회·clock accessor·State lock 대기까지 포함해 commit 직전에 만료를 다시 검사한다. StateManager는 잠금 대기 전 자신의 clock을 잡고 같은 원본의 유효 시각을 보존한다. 만료 후 odom이 도착하지 않아도 map pose의 freshness를 제거한다. 마지막 표시 좌표는 남지만 현재 좌표의 근거로 사용하지 않는다. odom 상태의 freshness는 map 거절로 제거하지 않는다.

지도 callback/lifecycle은 exact parent STOP 요청과 원본 map ticket/epoch 갱신을 먼저 수행하고 TF read를 무효화한다. 이후에는 지도 사건 이전의 cached TF를 다시 수용하지 않는다. 새 수신 지도에 대한 실제 소비자 채택을 이 과정으로 추정하지 않는다.

잠금 순서는 TF lease → State → clock이다. State 안의 동기 age reader는 clock만 읽고 다른 manager나 State로 진입하지 않는다. 최종 command writer에는 새 잠금을 추가하지 않았다. bridge 크기는 881→874줄로 ratchet을 낮췄고 새 source는 safety module/anchor에 등록했다. 독립 검토의 clock bracket·State lock 대기 지적 두 건을 고친 뒤 최종 scoped PASS를 받았다.

## 검증 기록

- test RED `2f3a419bd`: 원격 `map-pose-red-2/run-1.txt`, exit 1, **2 PASS/4 FAIL/22 ERROR/NEW 26**. 22 ERROR는 새 module 부재다. 기존 odom ownership의 NaN/미래 시각 3건과 없는 callback delegation 1건이 FAIL이다. 원본 cached-TF 동작의 22건 반례가 실행됐다고 계산하지 않는다.
- 최초 요청 `map-pose-red`는 host 목록 구분자 오기로 중단했다. 테스트는 실행되지 않았다. 이후 승인된 두 host를 공백으로 구분해 기존 runner로 실행했다.
- source `d3c1017f8`: 원격 30대상 `map-pose-green/run-1.txt`는 **705 PASS/1 FAIL/0 SKIP/NEW 1/exit 1**이다. 유일한 실패는 기존 cross-lane AST guard가 제거된 inline receipt 갱신을 기대한 것이다. clock·위치·station source와 구조/안전/harness 검사가 포함된다.
- test-only 보정 `d261d4698`: 기존 guard의 initializer만 남기고 두 ownership 검사에 line clock을 쓰는 검증은 유지했다. 이 revision과 source의 차이는 해당 테스트 파일 하나다. 새 TF·cross-lane·localization API·state odom·ownership 5대상 `map-pose-guard-green/run-1.txt`는 **98 PASS/0 SKIP/NEW 0/exit 0**이다. 앞선 706건 전체를 이 revision에서 재실행한 것으로 합산하지 않는다. source와 이 테스트 보정은 각각 독립 scoped PASS다.
- 새 회귀는 실제 CoreServices/StateManager의 original age·반복/정상 만료/시계 고장·늦은 조회·지도 변경·실제 thread의 State lock 대기를 검사한다. ROS semantic stub은 사용하지 않는다. 기존 timer 구조 검사는 등록 구성만 검사한다.
- local AST/diff check, generate, lint는 통과했고 lint는 0 errors/33 warnings다. D430/size_range `86cdffa42..d3c1017f8`는 각각 두 commit을 검사했다. harness manifest 변경으로 selector는 FULL이며 관련 원격 검사로 FULL CI를 대체하지 않는다.

## 남은 수용

TF의 latest-common timestamp는 AMCL 원본 측정 시각·위치 수렴·지도 소비자 ACK가 아니다. 이번 변경은 위치 ownership과 후속 localization admission 거절의 근거다. 기존 LocalizationAssist는 state enum이 LOCALIZED인 채 frame만 ODOM으로 바뀌면 on_lost를 호출하지 않으므로, 진행 중인 모든 명령의 자동 정지를 이 시험으로 주장하지 않는다.

native adopted-map 설계 R1은 독립 검토에서 REVISE다. 실제 기본 graph의 확인 대상은 AMCL과 전역 StaticLayer이며 로컬 plugin 목록은 voxel/inflation이다. model PC 설치 SDK 읽기 확인은 native compile/test나 robot 설치 증거가 아니다. R2에서 실제 채택 commit·변경 경로·instance/수명·잠금·native 시험을 확정해야 한다.

후속: R3 설계가 두 독립 검토에서 승인됐으며 D-783으로 기록됐다. [내부 wire 생성 검증](../station-native-map-wire-2026-10-17/result.md)까지 진행했지만 실제 consumer producer/CORE admission은 아직 없다. 위 R1 판정은 당시 기록으로 남긴다.

원본 pack energy/잔여·예약, 승인 Fleet 지도 revision/좌표 변환, 실제 HTTP/native ticket·단일 폐쇄 factory, 지원 profile을 쓰는 전체 3회 복귀·충전·재투입·스테이션 이동 검증은 남아 있다. 카메라 시야, 로봇 현재 위치, 착좌·BMS·물리 정지 수용도 남아 있다. 사용자는 현장 담당자가 나중에 확인 가능하다고 답했다. 기존 현장 사실을 반복 재탐색하거나 이 host 시험을 실기 완료로 취급하지 않았다. 장치 이동·토크·재시작·배포·landing·push는 수행하지 않았다.
