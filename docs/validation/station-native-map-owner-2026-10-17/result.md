# CORE native map evidence 소유자와 실제 generated 응답 소비

전체 스테이션 목표는 ACTIVE다. 이번 범위는 ROS-free 소유자/값 검증과 실제 생성된 ROS 응답의 domain 변환이다. 실제 ROS client wiring, final Fence/admission·writer 연결, 운영 실패 정리와 전체 충전 주기·DEVICE/FIELD는 완료하지 않았다. 일반 factory와 현장 장치 활성화는 바꾸지 않았다.

## 구현과 원본 수명

[R3 계획](../../plans/2026-10-17-native-map-adoption.md), D-783과 [실제 native producer 검증](../station-native-map-static-2026-10-17/result.md)을 잇는다. Drive navigation에 `NativeMapEvidence`, `Consumer`, `NativeReply`를 추가하고 기존 core_features distribution으로 소유한다. 별도 process·writer·public DTO/capability를 만들지 않았다.

소유자는 두 query 전에 정확한 MapEvidence owner와 현재 MapObservation 객체, parent를 캡처한다. 값이 같아도 owner/observation 객체가 바뀌면 거절한다. 첫 성공한 두 응답의 instance/generation/config/build tuple을 해당 parent에 고정한다. child admission 전에 고정하는 보수적 규칙이며, 후속 poll은 같은 tuple의 아직 만료되지 않은 sample만 갱신할 수 있다. higher generation의 reset→same-map 재적용도 기존 parent를 소비한다. gap/expiry 뒤 같은 tuple을 받아도 재생하지 않는다.

role별 발급 ticket의 동일 객체와 provider, fresh one-use16-byte nonce, 원본 metadata·digest, 실제 profile의 node/config/build를 검사한다. 두 query는 첫 before bracket부터 .25초 안에 끝나야 하며, sample은 그 first-before+.5초에 만료한다. 검증/source callback 뒤 최종 clock을 다시 읽는다. 지연·잘못된 clock·불일치는 캡처한 parent만 중지 대상으로 만든다. 늦은 옛 callback이 교체 parent를 중지시키지 않는다. parent/nonce/sample 보관량도 제한한다.

이 응답들은 동시 snapshot이나 native stability lease가 아니다. 소유자의 `valid`는 현재 raw source와 주입된 시각으로 보관된 sample identity/deadline을 읽는 predicate이며 source/owner 잠금·callback·clock·hash·RMW wait를 호출하지 않는다. 새 poll이 기존 selection sample의 deadline을 연장하지 못한다. 실제 writer에서의 사용과 STOP은 아직 연결하지 않았다. final Fence의 기존 supported CPython3.12/GIL 제약과 별도 clock 검증을 전제로 하며, 새 poll과 writer의 정상 경합도 이후 실제 연결에서 검증해야 한다.

## Revision과 원격 증거

| Revision | 실제 결과 |
|---|---|
| `249fa2ae41` | 시험 전용. 승인 model 시험 PC에서 모듈 부재로 collection/setup RED, pytest exit2. 실제 소유자 단위 동작0건 |
| `64accf7fe9` | 독립 source review 수정 후 소유자/ownership/safety/structure4대상 **109 PASS/1 FAIL/0 SKIP/NEW1**. 새 소유자 시험은 통과했고, 실패는 navigation1,339 lines의 기존 small 표시 졸업 요구 |
| `64accf7fe9` | 승인 AI 시험 PC remote_sim에서 같은 SHA interfaces 생성·IDL/header/Python/include provenance, 기존 Python/C++ wire 검증 및 실제 generated deserialize→domain capture PASS, exit0 |
| `a90891d712` | small 표시만 제거하고 동일4대상 재실행. **110 PASS/0 FAIL/0 SKIP/NEW0**, exit0. 소유자 production은 이전 revision과 동일 |

독립 검토는 초기 시각을 source/검증 뒤 재확인하지 않는 문제와 실제 fixed-array 타입 문제를 지적했다. source getter/응답 검증이 clock을 진행시키는 회귀와 최종 bracket을 추가했다. 발급되지 않은 ticket copy가 실제 round를 소비하지 못하도록 identity 검사를 맞추고 회귀를 추가했다. 순수 단위 시험은 services/test로 이동했고, 실제 generated ROS/domain helper만 D-184의 정확한 gateway seam 경로로 등록했다. scanner/threshold를 완화하지 않았다. 마지막 source·test·manifest 검토는 scoped PASS다.

Jazzy의 고정 numeric 배열은 numpy.ndarray로 생성된다. [공식 Python generator](https://raw.githubusercontent.com/ros2/rosidl_python/jazzy/rosidl_generator_py/resource/_msg.py.em)와 같은 SHA의 실제 deserialize 결과를 모두 확인했다. converter는 길이·1차원·연속 buffer·정확한 numeric format을 확인한 뒤 Python bytes/tuple로 복사한다. 실제 generated helper는 uint8[16]/float64[7] dtype/shape, serialize→deserialize, 복사 후 원본 배열 변경 비간섭, 두 synthetic 응답과 closed negative 응답을 검사했다. domain converter의 실제 로드 경로와 source hash도 확인했다. 설치 converter package나 실제 AMCL/static consumer ACK를 검증한 것은 아니다.

소유자 단위 시험은 두 독립 응답이 필요한 점, first-before 기준 수명, 같은 값의 새 원본 객체, 잘못된 role/provider/nonce/profile/metadata, ticket replay, reset의 높은 generation/instance 변경, gap 비복구, old selection 만료, old callback/new parent 비간섭, clock 지연/역행/비정상 값, bounded capture, source-lock 없는 predicate를 실행했다. synthetic reply/parent를 쓴 단위 경로이며 실제 manager/writer 동작으로 합산하지 않는다.

원본 로그는 저장소 밖 `C:/DevTemp/station-charge/native-map-owner-red/`, `native-map-owner-green/`, `native-map-owner-structure-green/`, `native-map-capture-sdk-64accf7fe9-attempt-1/`에 있다. native-map-capture의 정확한 source SHA는 `64accf7fe99ce5a93af1a8e143f8ec60d11b462b`, exit0과 실제 Python 성공 메시지를 직접 확인했다. wire CTest1건과 두 generated response/negative 검사를 pytest110건 또는 이전 native producer30건에 중복 합산하지 않는다.

## 남은 연결과 수용

실제 ROS clients의 nonce 발급·async query/brackets/timeout과 정확한 captured parent를 연결해야 한다. required/CLOSED native-map slot은 단 한 번 pre-cycle 설치하고, 실제 native admission·selection·final writer에서 expiry/source/context를 비차단 검사해야 한다. callback thread가 멈춘 동안 deadline을 넘긴 실제 writer의 거절, reset/reapply between polls와 normal refresh race, 원본 parent budget/선택 receipt deadline 비연장도 실제 manager와 sole writer에서 검증해야 한다. 현재 owner의 기본 보관 한계는 parent64개·발급 nonce65,536개이며 소진 시 닫힌다. 두 role을4Hz로 계속 질의하면 nonce 한계는8,192초이므로 장시간 운영 profile/발급 수명 방안도 실제 factory 수용 전에 다뤄야 한다.

manifest 변경은 FULL selection이며 FULL CI는 아직 남아 있다. 이전 branch exception ancestry guard 실패도 해결하지 않았다. 이110건을 전체 source/CI GREEN으로 확대하지 않는다. 승인 map revision/좌표 변환·geometry/localization과 ongoing frame loss 정지, 원본 pack energy/SOC/SOH·reserve, 실제 HTTP/StationOwner/CLOSED factory·운영 failed-config 정리, 전체3회 복귀·충전·재투입과 station relocation·ARM64/DEVICE/FIELD도 남아 있다. 현장 담당자는 나중에 확인 가능하며 장치 재탐색·이동·토크·재시작·배포·landing·push는 하지 않았다.
