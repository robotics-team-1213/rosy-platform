# Native map REQUIRED/CLOSED와 최종 명령 출력 검증

전체 스테이션 목표는 ACTIVE다. 이번 범위는 실제 CORE native manager와 기존 sole writer가 지도 채택 증거를 필요로 하도록 연결한 것이다. map readback·clock·pose·profile은 합성이다. 실제 native ACK와 운영 runtime factory·전체 충전 주기·ARM64/DEVICE/FIELD 수용을 완료한 것은 아니다.

## 변경

[R3 계획](../../plans/2026-10-17-native-map-adoption.md)·D-783과 [실제 DDS clients 검증](../station-native-map-clients-2026-10-17/result.md)을 잇는다. `install_native_execution`이 확보한 native-domain Fence는 지도 슬롯이 비어 있으면 REQUIRED/CLOSED다. trusted private NativeExecution의 `install_map_evidence`는 첫 writer cycle 전에 한 번만 시도할 수 있다. 실패한 claim·기존 설치·첫 ZERO cycle 이후 설치는 거절한다. native 운행에 기존 무검증 경로를 우회로로 남기지 않았다. 일반 non-native factory와 별도 declared-metadata 제한 시험 경로는 유지한다.

native entry·readiness·receipt 동기화와 docking staging은 현재 parent Budget와 지도 증거를 재확인한다. source는 owner의 getter를 신뢰하는 대신 실제 nav holder의 현재 _map_evidence pointer와 sample의 원본 MapObservation identity로 비교한다. owner.peek는 캐시 sample identity만 반환하며 lock·callback·clock을 호출하지 않는다. Fence는 먼저 sample을 보관한 뒤 fresh ledger clock을 읽는다. 그 사이 정상 poll이 더 새 sample을 발표해도 이미 잡은 unexpired sample을 잘못 clock fault로 소비하지 않는다.

selection Context는 선택한 정확한 sample을 보관하고 final submit에서도 같은 sample의 deadline을 검사한다. 이후 poll이 성공해도 옛 선택의 deadline은 늘어나지 않는다. final path는 owner/source lock·producer callback·hash·RMW wait를 호출하지 않는다. 누락·불일치·만료는 해당 parent에 STOP을 요청하고 기존 ledger 경계에서 소비한다. 교체 parent에 옛 callback의 STOP을 옮기지 않는다. 지원 runtime은 기존 CPython3.12/GIL이며 이 캐시 접근을 다른 runtime의 portable lock-free 보장으로 주장하지 않는다.

## 실제 원격 실행

| Revision | 실제 결과 |
|---|---|
| `d91751aa30` | 승인 AI 시험 PC 원격 RED **5 FAIL/8 ERROR**, exit1. 두 실제 navigation/dock admission은 지도 증거 없이 허용돼 DID NOT RAISE였다. 나머지는 install API 부재이며 writer 동작 반례로 합산하지 않는다 |
| `ab7d2c2f3c` | 독립 D-430 scoped source PASS 후 승인 AI 원격8대상 **232 PASS/1 FAIL/0 SKIP/NEW1**, exit1. 유일한 실패는 entry clock-race fixture가 lease_ttl_s의 필수 correlation_id를 누락한 VALIDATION_ERROR |
| `1144e9e4e08e41c9f3b469f5df56134e1b4f451b` | fixture identity만 수정하고 승인 AI 원격13대상 **296 PASS/0 FAIL/0 SKIP/NEW0**, exit0. production source는 ab7d2c2f3c와 동일 |

새 통합 회귀는 실제 NavigationManager/DockingManager·NativeExecution·Fence·cmd_vel_cycle/sole writer를 사용한다. 미설치/첫 한 role만 완료된 지도 증거의 native admission 거절, 일회성 pre-cycle 설치와 실패 비복구, callback 역할의 worker가 evidence lock을 보유한 동안 선택/출력의 비차단 만료, 새 poll 중 옛 selected deadline 만료, 정상 refresh의 Budget 비갱신, ledger clock capture 중 새 poll의 정상 경합(entry/selection), source owner 교체·높은 generation의 same-map 재적용·close, gap 뒤 같은 tuple의 비복구, 옛 query callback과 교체 native run 비간섭을 검사했다. producer source/parent/clock callback과 MapEvidence.snapshot을 금지해도 캐시 경로에서 출력할 수 있는지도 검사했다.

writer 만료 시험은 map expiry 외의 실패 원인을 배제하도록 기존 제한 안에서 synthetic original pose를 .2초 간격으로 갱신했다. lease와 command input도 아직 유효한 상태에서 지도 first-before+.5초를 넘긴다. original parent Budget의 start/duration은 유지하며 정상 poll 뒤 남은 시간 감소와 energy 상한 증가도 확인했다. 새 sampled 사실이 계속 들어와도 이미 소비된 Budget는 재개되지 않는다. 이 값들은 실제 pose/물리 정지 측정이 아니다.

기존 native-positive fixture는 합성 Consumer/profile과 두 readback을 명시적으로 설치한다. 원본 map callback 시험은 별도 unbound fixture를 사용해 첫 map 수신·기존 render·original-source 수명 검증을 보존한다. 순수 owner 정책은 services/test, 실제 CORE seam은 gateway/test의 정확한 D-184 경로에 둔다. scanner·baseline·threshold를 완화하지 않았다. 13대상에는 native composition, original odometry/map/bootstrap, 기존 writer Fence, async clients와 owner, ownership/safety/module structure·bridge 기본 등록·C6 검사가 포함됐다.

원본 로그는 저장소 밖 `C:/DevTemp/station-charge/native-map-writer-red/`, `native-map-writer-green/`, `native-map-writer-regression-green/`에 있다. 실제 summary와 exit를 확인했다. 앞선 wire/DDS/native producer 시험은 변경하지 않아 반복하지 않았으며 이296건에 합산하지 않는다.

## 남은 범위

actual generated clients와 required slot을 같은 supported private 운영 factory에 묶고 actual native readback/original odom·Fleet 승인 map revision/변환·geometry/localization·원본 pack energy와 reserve/SOC/SOH를 검증해야 한다. ongoing MAP→ODOM frame-only loss의 정지도 아직 별도 결함이다. 현재 owner의 parent64개/global nonce65,536개 한계(두 role4Hz이면8,192초)와 운영 failed-config cleanup은 장시간 수용 전에 해결해야 한다. owner나 parent Budget를 재생성해 우회하지 않는다.

실제 HTTP/native StationOwner·세 번의 복귀/충전/재투입·station relocation, watchdog/제동 측정·ARM64/DEVICE/FIELD도 남아 있다. manifest 변경의 FULL CI와 기존 branch ancestry guard도 미해결이다. 현장 담당자는 나중에 확인 가능하며 검은 상부 영상·오래된 mobile 위치·charger/BMS/contact/extrinsics 미정 상태를 반복 탐색하거나 장치 이동·토크·재시작·배포·landing·push를 하지 않았다.
