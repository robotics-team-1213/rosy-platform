# OMX native 결정 시점의 시계·intake 관측

> Historical record recovered on 2026-10-19 from preserved work. Results below describe the cited source/run; this recovery does not rerun or extend that simulation evidence.

2026-10-17. 실행 source `3ab4dd9874`, nonce `11f524e3823e`.
[응답 snapshot 수정](../omx-native-receipt-snapshot-2026-10-17/result.md)의 후속이다.

startup과 topic prepare/admit 뒤 첫 approach에서 `joint_state_stale`로 HOLD했다.
독립 목표 확인은 0/16이다. frozen watchdog record의 command 일치가 true이며
취소 전 결정 표본과 intake를 다음처럼 보존했다.

| 관측 | 값 |
|---|---:|
| intake callback 진입 steady | 22820.596800710 |
| intake 검사 steady | 22820.596833890 |
| intake 관측 저장 steady | 22820.596848176 |
| packet source stamp | 16.780 s |
| intake local source clock / received_at | 16.140 s |
| intake 결과 | STAMP_REJECTED |
| 마지막 수락 sequence / owner received_at | 1100 / 16.108 s |
| watchdog owner_now / source_age | 16.828 / 0.720 s |
| watchdog 관측 steady | 22820.596976388 |
| 기존 source-age 상한 | 0.500 s |

callback 진입부터 관측 저장까지 약 47µs다. packet은 local clock보다 0.640초
앞서 거절됐고, watchdog은 기존 나이 상한을 초과해 HOLD했다. 그러나 기존
owner_now 읽기에는 steady bracket이 없다. 따라서 약 128µs 뒤 저장된 watchdog
관측을 owner_now의 실제 읽기 시각으로 취급하거나, 이 구간의 시계 점프를 확정하지 않는다.
나중 diagnostic의 시계·sequence도 이 결정 표본과 구분한다.

고정 SDK 기동 소스와 실제 로그에서는 Gazebo 하나, 고유 partition과 단방향
GZ→ROS `/clock` bridge 하나를 확인했다. 실행 당시 실제 DDS publisher GID/count,
offered QoS, clock callback의 역행 기록은 없으므로 중복 발행·역행 부재를 증명하지 않는다.
설치된 TimeSource는 depth 1 BEST_EFFORT로 기본 callback group에서 수신하고
frame을 backward filter 없이 ROSClock에 적용한다.

후속 [D-788](../../adr/D-788-omx-sim-dedicated-clock-executor.md)은 같은 owner clock의
수신 실행기를 분리하는 실험이다. `52d8fadce8`은 기존 owner_now provider 읽기
전후의 best-effort steady bracket만 추가했다. 원격 owner/intake 회귀 **102 passed**,
skip/NEW 0, 독립 D-430 Safety-Review APPROVE다. `2e06275a1`은 이 두 표본을
terminal evidence로 내보낸다. 원격 RED 2 expected failures 후 GREEN **15 passed**다.
두 수정은 위 실행에 없었으며, 전용 시계 구성의 실제 수용도 별도 확인이 필요하다.

정리는 cleanup_verified=true, remaining_groups=[], cgroup 부재, MainPID=0 / 빈
ControlGroup과 실제 budget 파일 부재를 확인했다. ACK 뒤 같은 run·불명 Goal을 재전송하지 않았다.
private 운영 scratch `native-auto-deployment-11/fetches/20261017T113110-6332ae4aba33`에
원본·추출 대조표·receipt를 보존했다.

```text
archive_sha256 = 9a4542cdcbea07c27c2adb8ee0c64c34de6d4c732aa8521034b8e81eff295f00
extraction_map_sha256 = 295396e2a17fb73f4d91a57f26679423b55fa44c92867845c3bd6b7198d396de
clock_topology_sha256 = edf5953b9d832251a1d95ff06592183959545cc09d7cb8558ec3cf106b4e92c2
clock_closure_sha256 = 8ce21335efbf6fb5143ec1743fdbc36d5745f8de458dd5516fa79c4315b3bba7
clock_api_sha256 = 78837480d3c435bfca1b4fbace6e2b98e1f54606796e2f6d96e33d6a6eef0d23
```

전체 native task와 full G2 fault matrix는 HOLD다. 적격 실제 episode는 0개이며
실물 수용·수집·ACT 학습 완료로 표시하지 않는다.
