# Native map 비동기 CORE clients 검증

전체 스테이션 목표는 ACTIVE다. 이번 결과는 실제 generated MapAdoption client의 비동기 DDS 통신과 ROS-free Future orchestration, evidence의 영구 종료를 검증한다. 서버의 map/consumer 응답·parent·clock은 합성이다. 실제 AMCL/StaticLayer ACK, required/CLOSED runtime factory·native admission·Fence selection/final writer와 장치/현장 수용은 아직 남아 있다.

## 변경과 수명

[R3 계획](../../plans/2026-10-17-native-map-adoption.md)·D-783과 [기존 owner 검증](../station-native-map-owner-2026-10-17/result.md)을 따른다. `core.bridge.native_map_adoption.NativeMapClients.create`는 명시적 호출에서만 generated ROS service type으로 두 client를 생성하고 각 Consumer.provider를 실제 client identity에 묶는다. 기본 RosBridge 생성자·timer·factory는 바꾸지 않았다. ROS-free constructor의 시험은 실제 concurrent.futures.Future를 사용하며 rclpy를 가짜 모듈로 대체하지 않는다.

poll은 parent/원본 source를 먼저 캡처한 owner round에 fresh16-byte nonce를 발급하고 비동기 query를 보낸다. service 부재·발급/전송/응답/변환 실패·취소·overlap은 캡처한 ticket/parent를 소비한다. 완료 callback에서만 result를 읽고 bounded immutable response를 캡처한다. outstanding pair를 먼저 분리한 뒤 pending request를 제거하고 local Future를 취소하므로 늦은 callback은 교체 pair를 정리하거나 교체 parent로 STOP을 옮기지 못한다. local 취소는 remote cancellation ACK가 아니다. transport.close는 완성된 owner sample도 영구 무효화하며 이후 parent에서도 재시작하지 않는다.

첫 before+.25초 completion과 first-before+.5초 sample lifetime은 기존 owner가 검사한다. poll 실행 스케줄과 final writer의 독립 만료 검사까지 연결한 것은 아니다. 새 poll은 기존 selected sample의 deadline을 늘리지 않는다. 기본 parent64개/global nonce65,536개 보관 한계는 그대로이며 두 role4Hz 지속 질의의8,192초 한계는 실제 장시간 운영 factory 수용 전에 해결해야 한다. owner를 재생성해 수명을 우회하지 않는다.

## 실제 실행

| Revision | 결과와 범위 |
|---|---|
| `d0d536545ae5ed9246b7cc598fe50e0e03695593` | 승인 AI remote_sim. 6회 placement 거절 뒤7번째 실제 실행. 같은 SHA interfaces 생성/provenance·Python/C++ wire CTest1 PASS 뒤 adapter 모듈 부재 import RED, exit1. transport 동작0건 |
| `7ebb9615f3` | 승인 model 원격 pytest transport 모듈 부재 collection RED, exit2/동작0건. 별도 owner 실행은 close 부재 **61 PASS/1 FAIL**, exit1 |
| `2fd55d947bd4f39602c6f0ccd757619f0f1c5128` | 독립 D-430 scoped PASS 후 source. 승인 model 원격7대상 **134 PASS/1 FAIL/0 SKIP/NEW1**, exit1. sole failure는 이전 map_pose getattr 의존성의 C6 guard |
| `2fd55d947bd4f39602c6f0ccd757619f0f1c5128` | 승인 AI remote_sim. 1회 placement 거절 뒤2번째 실제 실행, 같은 SHA interfaces 생성/IDL/header/Python/include provenance와 wire CTest1, 실제 typed DDS transport 검증 **PASS/exit0** |
| `cd53393a09` | C6 원인 수정 후 승인 model 원격9대상 **198 PASS/0 FAIL/0 SKIP/NEW0**, exit0. transport/owner production은 이전 source와 동일 |

DDS 시험은 실제 generated service server/client와 executor를 사용한다. 성공 pair, nonce4개 비중복, 만료 전 refresh, 기존 selected sample 만료, explicit close, 첫 query timeout 뒤 pending detach와 실제 old/new DDS 응답, replacement-parent 비간섭, negative response의 영구 소비, 없는 service의 비대기 거절을 실행했다. native 소비자와 physical time/parent를 쓴 end-to-end 운행 시험은 아니다.

ROS-free Future 시험은 위 orchestration 외 send/response exception·cancel·malformed capture·entropy 실패·취소할 수 없는 RUNNING Future의 늦은 완료를 검사했다. 회귀9대상에는 owner, behavior ownership, safety separation, module structure, 기본 bridge 등록, C6 criteria, 원본 map observation과 map-pose TF 수명 검사가 포함됐다. C6 수정은 실제 bridge가 이미 선언한 _map_pose_lease를 직접 읽고 TF 없는4개 fixture가 None을 명시한 것이다. scanner/allowlist 완화는 없다. 이 수정도 독립 scoped PASS 후 커밋했다.

원본 로그는 저장소 밖 `C:/DevTemp/station-charge/native-map-clients-red/`, `native-map-close-red/`, `native-map-clients-green/`, `native-map-clients-structure-green/`, `native-map-clients-sdk-d0d536545a-attempt-7/`, `native-map-clients-sdk-2fd55d947b-attempt-2/`에 있다. 실제 DDS 실행의 source-sha·exit-code0·각 PASS 메시지를 직접 확인했다. wire CTest1과 DDS scenario assertions를 pytest198건 또는 이전 native producer30건에 중복 합산하지 않는다.

## 다음 수용

실제 NativeExecution/private factory에 unique required/CLOSED source를 첫 cycle 전에 설치해야 한다. native admission과 Fence selection/final writer는 정확한 raw source·captured parent·retained sample deadline을 비차단으로 검사해야 한다. callback thread 정지 중 만료, reset→same-map 재적용, gap 뒤 같은 tuple, 새 poll 중 옛 selection 제출, 원본 교체와 옛 callback을 실제 manager/sole writer에서 검증해야 한다. 기존 parent Budget를 초기화하거나 default path를 우회로로 남기지 않는다.

ongoing MAP→ODOM frame loss 정지, 승인 Fleet map revision/변환·geometry/localization, 원본 pack energy/SOC/SOH·reserve, 실제 HTTP/native StationOwner·운영 failed-config 정리, 장시간 nonce/parent 수명, 전체3회 복귀·충전·재투입과 station relocation·ARM64/DEVICE/FIELD도 남아 있다. manifest 변경은 FULL selection이며 FULL CI와 이전 branch ancestry guard 문제도 미해결이다. 현장 담당자는 나중에 확인 가능하다. 장치 재탐색·이동·토크·재시작·배포·landing·push는 하지 않았다.
