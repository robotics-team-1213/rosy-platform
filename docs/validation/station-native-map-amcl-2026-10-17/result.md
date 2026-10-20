# 실제 AMCL의 원본 지도 채택 확인

전체 스테이션 목표는 ACTIVE다. 이번 범위는 원본 지도 canonical identity와 실제 AMCL owner의 내부 readback이다. 전역 StaticLayer, 두 consumer의 CORE admission/final writer 연결, 전체 충전 주기와 DEVICE/FIELD는 남아 있다.

## 구현과 검토

[승인된 R3 계획](../../plans/2026-10-17-native-map-adoption.md)과 D-783을 따른다. 기존 navigation 패키지의 native opt-in은 기본 OFF다. 일반 standalone/composable launch는 바꾸지 않고 verified component를 등록하지 않는다. 첫 지원은 고정 SDK에서 한 process에 한 verified AMCL instance다. upstream의 process-global free-space 상태 때문에 임의 composition을 지원한다고 주장하지 않는다.

C++ helper는 Python의 `ROSY-GRID-v1` 원본 byte 계약을 구현한다. OccupancyGrid float32 resolution을 double로 승격하고 little endian·signed zero·원본 int8를 보존하며 최대 4194304 cells, exact shape, finite axis-aligned map origin과 두 원본 시각을 검증한다. content digest와 두 timestamp를 함께 original identity로 다룬다. helper 자체는 native 채택이나 운행 허가가 아니다.

AMCL subclass는 최초 subscription부터 private callback group을 소유한다. base `on_configure/initPubSub`를 호출하지 않고 보호된 초기화 helper와 별도 pub/sub wiring을 사용해 startup의 latched map도 우회 callback으로 처리되지 않게 한다. 원본을 별도 immutable copy로 캡처·검증·hash한 뒤 실제 native mutex 안에서 upstream `handleMapMessage`를 한 번 호출하고 native geometry/cells가 해당 원본의 해석과 맞는지 검사한다. 원본과 실제 호출의 연결이 증거이며, 변환된 cells의 일치만으로 서로 다른 raw 지도를 같다고 보지 않는다.

정확한 반복은 native 처리와 generation을 갱신하지 않는다. raw bytes나 header/load time이 바뀌면 기존 instance를 native 변경 전에 폐기하며 first_map_only의 두 값 모두 동일하다. 비활성화는 먼저 폐기하고 readback executor를 유지해 거절 상태를 응답한다. 정리·종료·파괴는 폐기 후 native mutex 밖에서 private executor를 종료·join한다. 재활성화/재설정은 같은 instance를 되살리지 않는다. destructor도 derived callback 상태보다 executor를 먼저 정리한다.

pre-set parameter callback이 전체 transaction을 거절하므로 inherited map_topic 재구독 등의 부분 부작용을 막는다. config digest는 표시 문자열 대신 type tag, 정확한 int64/double bit, length-prefixed string/array를 hash한다. 독립 검토에서 `.2`와 `.20000001`을 같은 표시 문자열로 만들던 문제와 진행 중 callback을 보장하지 않던 cleanup 테스트를 발견해 첫 source commit 전에 고쳤다. cleanup 회귀는 실제 private group의 DDS callback이 barrier에 진입한 것을 확인하고, 별도 cleanup thread가 callback 해제 전 완료되지 않으며 해제 후 실제 map을 정리하는지 검사한다. 이는 test-only endpoint이고 실제 map/readback consumer를 대체하지 않는다.

서비스는 실제 owner mutex 안에서 version·challenge·instance/generation·active/adopted 상태와 원본 metadata, build/config를 반환한다. hash/네트워크 대기를 final writer에 옮기지 않았다. 아직 CORE가 이 서비스로 운행을 허가하는 경로는 없다. 서로 다른 두 consumer의 동시 상태나 native lease를 증명하지도 않는다.

각색한 wiring의 원본은 [고정 Nav2 AMCL source](https://raw.githubusercontent.com/ros-navigation/navigation2/f4108e5b1c2bce804a1aa0c7be6673a8eb4a1501/nav2_amcl/src/amcl_node.cpp)다. 알고리즘은 upstream library를 호출하며 LGPL 고지·원문과 package license를 보존했다. native C++ 폴더는 독립 검토가 필요한 safety root로 등록했다.

## Revision별 실행 증거

| Revision | 실제 실행과 결과 |
|---|---|
| `a22e7c5fb` | 승인 AI 시험 PC remote_sim. Python golden 7개/SDK/gtest 확인 뒤 grid.cpp 부재로 setup RED exit 1. 실제 gtest 0건 |
| `8f749b1f9` | 같은 standalone canonical fixture compile/link 및 실제 gtest **6 PASS/0 FAIL/0 SKIP**, exit 0. Python golden parity·raw equal-conversion 차이·두 시간·shape/geometry/셀 제한 검사 |
| `5d4b074a0` | 실제 interfaces 생성/직렬화 뒤 navigation opt-in 부재로 setup RED exit 1. AMCL 동작 0건 |
| `834d6bd02` | 첫 native 요청은 headroom 부족으로 미실행. 이후 실제 요청은 interfaces/wire 뒤 costmap header 탐색에서 실패. AMCL compile/gtest 미도달 |
| `6c918813c` | 실제 exported core target include 경로를 사용해 기존 5개 SDK pin 통과. 추가 lifecycle pin에서 실패. 로컬 CRLF 캐시를 hash한 오류였으며 Linux 원본과 줄끝 정규화 후 동일함을 확인 |
| `834ba0a9d` | model/AI Linux 원본에서 확인한 lifecycle pin으로 교정. 6개 SDK pin·same-SHA interfaces→navigation build/provenance·compile/link 통과. native gtest 16건 중 **7 PASS/9 FAIL/0 SKIP**, exit 1. grid 6과 typed config 1 PASS, Harness 9는 executor 생성 전에 ROS context를 초기화하지 않은 fixture 오류 |
| `1f2b0f1e8` | fixture 초기화 순서만 수정. production source는 이전 revision과 동일하다. 승인 AI 시험 PC remote_sim은 **grid 6 + AMCL 10 = 실제 gtest 16 PASS/0 FAIL/0 SKIP**, exit 0 |
| `0034827d2` | 설치된 standalone binary의 실제 초기 graph 검사를 추가하고 전체 경로 재실행. **실제 gtest 16 PASS/0 FAIL/0 SKIP**, 설치 executable의 GetState/namespace·초기 UNCONFIGURED·해당 node의 velocity publisher 부재 및 정상 종료 확인, exit 0 |

`1f2b0f1e890d53b9caf876e393fb415bde2a6d02`의 회수된 source-sha/exit-code와 두 gtest XML을 직접 확인했다. AMCL suite 중 9건은 실제 AMCL class/DDS grid/readback을 사용하고 1건은 실제 LifecycleNode typed parameters의 config digest를 검사한다. map 미수신 거절·latched 첫 원본의 실제 cells/호출 수·정확한 반복·동일하게 변환되는 다른 raw의 두 first_map_only 모드 거절·원본 시각 변경·mixed parameter 부작용 거절·비활성/정리/재생성·진행 중 callback 정리·동시 verified instance 거절·typed config 정밀도를 포함한다. 위치 측정·laser localization 수렴이나 precision docking을 시험한 것으로 계산하지 않는다.

native runner는 같은 SHA의 interfaces를 먼저 명시적으로 재생성하고 원본/설치 IDL·header hash·Python import·C++ include 경로를 확인한 뒤 navigation을 opt-in 빌드·설치하고 `colcon test`/`test-result` 및 정확한 XML case 수를 검사했다. SDK는 Nav2 1.3.13/rclcpp 28.1.22이며 original 5개 header pin과 실제 Linux lifecycle header pin을 모두 검사한다. build ID는 own source/IDL/SDK·compiler/flags를, config ID는 실제 typed parameters와 resolved map topic을 포함한다. 실패와 성공의 build/test/XML/fingerprint artifact를 cleanup 전에 보존했다. C++ API deprecation 경고는 남아 있으며 실패나 skip으로 숨기지 않았다.

원본 로그는 저장소 밖 `C:/DevTemp/station-charge/`의 `native-map-grid-{red,green}/`, `native-map-amcl-red/`, `native-map-amcl-green-retry/`, `native-map-amcl-sdk-attempt-2/`, `native-map-amcl-sdk-834ba0a9de-attempt-2/`, `native-map-amcl-sdk-1f2b0f1e89-attempt-3/`, `native-map-amcl-sdk-0034827d27-attempt-1/` 아래에 있다. placement가 거절한 요청은 실제 실행 수에 넣지 않았다. bounded wrapper는 실제 작업이 시작돼 terminal이 되면 성공/실패와 무관하게 멈추며 live job을 다시 시작하지 않았다.

## 남은 검증과 실패

설치된 standalone executable의 실제 초기 lifecycle graph 검사는 `0034827d2`에서 별도 Python fixture로 실행됐으며 gtest 16건에 합산하지 않는다. 설치 경로·실제 service 응답·성공 메시지와 정상 process 종료를 확인했다. 활성화·laser localization 수렴이나 로봇 동작 검사는 아니다.

source guard `834d6bd02`의 원격 9대상은 **207 PASS/1 FAIL/0 SKIP/NEW 1**이다. 실패는 safety exception 표의 commit들이 현재 branch HEAD의 ancestor인지 확인하는 검사다. 수정하지 않은 main `8b60af26b`에서 해당 검사는 1 PASS, 이번 변경 이전 branch baseline `cb19bf69f`에서 1 FAIL이다. 검사·예외 표·검증기는 이번 native 변경에서 바꾸지 않았다. 기존 branch 이력 문제로 분리하고 전체 guard GREEN이나 main의 기존 실패라고 주장하지 않는다. 착지 전 해결이 남아 있다. manifest/package 변경의 FULL CI도 미실행이다.

전역 StaticLayer의 실제 full application·reset/resize/cleanup, CORE의 원본 객체/nonce/불변 parent tuple·expiry와 실제 final writer 거절, 승인 Fleet map revision/좌표 변환, 원본 pack energy/SOC/SOH·충전 완료/재배치 scheduling, 실제 HTTP/native ticket·폐쇄 factory, 세 번의 전체 복귀·충전·재투입·station relocation이 남아 있다. ongoing LOCALIZED MAP→ODOM frame-only loss의 정지도 별도로 확인해야 한다.

카메라 시야/extrinsics·현재 이동 로봇 위치·접점/착좌·충전기/BMS·watchdog/제동 지연의 현장 수용은 미확인이다. 현장 담당자는 나중에 확인 가능하다. 이 x86_64 시험 PC 실행은 ARM64 payload·로봇 설치·현장 동작 증거가 아니다. 현장 장치 재탐색·이동·토크·재시작·배포·landing·push는 수행하지 않았다.
