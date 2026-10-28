# Native 지도 클라이언트 정리와 수명 경계

2026-10-21 · 기존 파이프라인 C1의 정리·용량·복구 경계를 보완했다.
SOURCE 및 아래 명시한 native 시험 범위이며 운영 factory·장시간 운행·장치 수용은 HOLD다.

## 결함과 수정

`NativeMapClients.close()`와 `create()`의 실패 정리는 client를 순서대로 해제했다.
첫 해제 예외가 다음 해제를 건너뛰고 구성 실패의 원래 예외까지 덮었다.
`destroy_client`가 false를 반환해도 성공으로 처리했다.
공통 해제 경로는 모든 client의 정리를 시도하고 첫 실패를 보고한다.
구성 실패에서는 원래 예외를 유지하고 정리 예외를 cause로 연결한다.
close는 기존과 같이 먼저 evidence를 영구 폐쇄하고 pending 요청을 분리한다.

실패를 보고했다는 것은 해당 client가 실제로 파괴됐다는 보증이 아니다.
외부 node 생명주기에서 잔여 resource를 정리해야 하며, 이 수정은 실패한 owner를 재개하거나
같은 실행에 새 owner를 자동 설치하지 않는다. operational factory·poll timer·admission·CORE writer는 추가하지 않았다.

## 검증

| 정확한 source | 실행 | 결과 |
|---|---|---|
| `53c7d91367` | native pytest transport RED | 2FAIL/11PASS. 첫 해제의 예외 후 다른 client 미시도, false 미보고 |
| `53c7d91367` | 실제 generated Jazzy types/DDS RED | exit1. 구성 ValueError를 해제 RuntimeError가 덮는 경로 확인 |
| `baaef16433` | 기본 용량 경계 | 64PASS/0SKIP/NEW0, exit0 |
| `403f4a6162` | 새 복구 회귀 초안 | 1FAIL/20PASS. 복구·새 실행 이후 잘못 쓴 navigate API에서 AttributeError; 제품 결함 RED로 쓰지 않음 |
| source commit `ed405d1ecf93aa6b460c19dfc6ba15e82f89613f` | transport/native execution/actual binding/evidence 4 suites | 137PASS/0SKIP/NEW0, exit0 |
| 같은 `ed405d1ecf` | 실제 generated Jazzy/DDS client probe | exit0. failed config 양쪽 정리 시도·원래 오류 보존, 정상 pair/refresh, pending timeout/late callback, negative reply, missing service 검사 |

표의 pytest는 공식 remote_pytest, DDS probe는 공식 remote_sim의 AI 시험 역할에서 실행했다.
현장 PC와 실제 장치는 사용하지 않았다. 반복 실행을 합산하지 않는다.
DDS의 server 응답과 parent/clock은 합성이다. native AMCL/StaticLayer의 실제 ACK와
운영 final writer까지 연결한 proof로 확대하지 않는다.

기본 65,536개 nonce를 두 role 4Hz로 소진하는 8,192초는 **빠른 합성 clock 경계 시험**이다.
실제로 8,192초 연속 운행한 시험이 아니다. 새 parent가 global nonce 기록을 초기화하지 않고,
64개 parent 이후 과거 소비 이력을 버려 다시 허용하지 않는 것을 확인했다.
실제 native manager/sole writer의 frame 상실→ZERO/STOPPED→frame 복구 후 비재개→새 Budget/parent→
새 map ACK→명시적 새 navigation의 성공과 이전 parent 거절도 확인했다.
지도/odom/시계 입력은 합성이며 승인된 운영 지도 복구 수용은 별도다.

## 독립 검토와 남은 관문

`native_map_cleanup_review`가 producer/consumer/NativeMapEvidence/private binding/final Fence를
추적해 Critical/Important/Minor 지적 없이 독립 안전 검토를 승인했다.
최종 source SHA256은 `51fed553d2bc6c4d1444bf99ed35acf9c92ddde745bab12dfc3f7a3e27db2471`,
검토 diff의 Git-object fingerprint는 `ec5ca999c9bc5c8f49cf252af4b730e26cdec9e3`다.
수정 커밋에 Safety-Review trailer를 남겼다. 리뷰 자체가 시험 재실행이나 실기 안전 인증은 아니다.

실제 운영 factory/profile·map/clock/pose 원본 결속, 장시간 수명, native node 잔여 resource를 포함한
운영 failed-config cleanup/재설치와 같은 승인 지도 복구 뒤 새 admission 수용이 남아 있다.
CORE final writer·OMX owner의 권한과 기존 제한을 유지한다. 푸시·배포·실물 이동은 하지 않았다.
