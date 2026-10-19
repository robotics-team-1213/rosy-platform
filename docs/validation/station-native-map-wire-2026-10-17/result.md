# 스테이션 복귀용 native 지도 확인 wire

전체 목표 ACTIVE. 이번 범위는 로봇 내부의 읽기 전용 ROS 서비스 정의와 실제 생성·직렬화다. 실제 AMCL/StaticLayer 채택 producer와 CORE의 admission/final writer 연결은 아직 없다.

## 구현

D-783과 [독립 검토를 통과한 R3 실행 계획](../../plans/2026-10-17-native-map-adoption.md)에 따라 기존 interfaces 패키지에 `MapAdoption.srv`를 추가했다. 요청은 고정 16-byte challenge뿐이다. 응답에는 version 1, bounded 원본 grid/native owner 식별 정보와 active/adopted 상태가 있다. 외부 REST/Fleet 계약이나 운행 권한을 추가하지 않는다.

실제 rosidl 목록에 등록하고, 기존 remote_sim의 승인 시험 PC에서 같은 SHA의 interfaces를 명시적으로 재생성하는 검증 경로를 추가했다. 설치 prefix·원본/설치 IDL 일치·generated header hash·Python import 경로·C++ compile include 경로를 확인한다. 테스트 fixture는 active=false/adopted=false인 응답만 직렬화한다. 성공/실패 exit code와 가능한 build/test artifact는 runner cleanup 전에 복사한다. 이 fixture를 실제 native 채택 ACK로 쓰지 않는다.

## 실행 증거

| Revision | 실행 | 결과와 범위 |
|---|---|---|
| `861c33caf` | AI 시험 PC remote_pytest, service surface RED | 기존 3 PASS/추가 3 FAIL/0 SKIP/NEW 3, exit 1. 두 실패는 IDL 부재, 하나는 rosidl 등록 부재이며 native 동작 반례는 아니다 |
| `f6ae71b14` | AI 시험 PC remote_pytest, service surface GREEN | 6 PASS/0 SKIP/NEW 0, exit 0 |
| `f6ae71b14` | AI 시험 PC remote_sim, same-SHA interfaces 재생성 | 생성·prefix/IDL/header/Python provenance와 Python round trips 뒤 fixture의 타입 표기 예상값에서 exit 1. generated metadata `string<64>`를 IDL 문법 `string<=64`로 잘못 예상했다. C++ 검사는 도달하지 않았다 |
| `8058c3676` | AI 시험 PC remote_sim, fixture 예상 표기만 수정 후 전체 재실행 | 같은 SHA interfaces 생성·provenance, Python request/closed-response round trips 및 7 bounded string metadata 검사 통과. 실제 C++ fixture compile/link와 CTest **1 PASS/0 FAIL/0 SKIP**, runner/보존 exit-code 모두 0 |

마지막 두 revision 사이 production IDL과 생성 목록은 동일하다. 서로 다른 SHA의 결과를 하나의 전체 실행 수치로 합산하지 않는다. native 시험은 Jazzy/rclcpp 28.1.22와 x86_64 C++ 실행이며 ARM64 payload나 현장 로봇 시험이 아니다. Gazebo 시나리오·DDS 서비스 요청/응답·native consumer·positive ACK도 이번 실행에 포함하지 않는다.

원본 로그는 저장소 밖 `C:/DevTemp/station-charge/` 아래 `native-map-contract-red/run-1.txt`, `native-map-contract-green/run-1.txt`, `native-map-wire-build/{run.txt,out/native-map-wire/}`, `native-map-wire-green/{run.txt,out/native-map-wire/}`에 있다. 마지막 artifact의 source SHA는 `8058c3676e63d10a16618a83c25b997b85b55f65`이며 CTest XML의 tests=1/failures=0/skipped=0과 Python success line, exit-code=0을 직접 확인했다. 실패 artifact에도 exit-code=1과 traceback이 남았다.

독립 review는 설계·RED, wire source/fixture, fixture 수정과 최종 기록 각각 scoped PASS다. 최종 generate와 lint는 0 errors/33 warnings이며 D430/size_range는 baseline `f1a2b0eff` 이후 구현 3 commit을 검사했다. interfaces 변경으로 selector는 FULL이다. 위 검증으로 전체 CI를 대체하지 않는다. 최종 기록 commit은 실행 source를 바꾸지 않는다.

## 남은 실행

R3의 canonical C++ helper와 실제 AMCL/global StaticLayer producer, SDK pin·startup/lock/lifecycle·native 적용 반례 시험이 다음이다. CORE는 두 consumer의 불변 instance/generation·원본 객체·config/build tuple을 parent에 묶고, 만료·변경 시 정확히 기존 parent를 소비해야 한다. 새 positive 응답이 만료된 운행이나 과거 writer receipt의 유효 시간을 늘리면 안 된다.

원본 energy와 SOC/SOH scheduling, 승인 Fleet 지도 revision/좌표 변환, geometry/localization과 frame-only loss의 진행 중 정지, 실제 HTTP/native ticket·폐쇄 factory, 세 번의 전체 복귀·충전·재투입과 스테이션 이동 검증을 계속 요구한다. 현장 담당자 확인은 나중에 가능하다. 상부 카메라 시야·현재 이동 로봇 위치·charger/BMS/contact/extrinsics·watchdog/물리 정지 수용은 미확인이다. 기존 현장 사실을 재탐색하거나 이동·토크·재시작·배포·landing·push를 수행하지 않았다.
