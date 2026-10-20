# OMX native 응답 불확실성과 일관된 journal snapshot

> Historical record recovered on 2026-10-19 from preserved work. Results below describe the cited source/run; this recovery does not rerun or extend that simulation evidence.

2026-10-17. 실행 source `eacdc5af1a`, nonce `0f8d817d1979`.
[명목 finger 배치 수정](../omx-sim-finger-envelope-2026-10-17/result.md)의 후속이다.

## 실제 실행의 결과

실제 SDK의 STL과 URDF/xacro 세 파일을 대조한 preflight가 RUNTIME_SDK_MATCHED,
명목 finger 경계 밖 최소 여유 4.879 mm를 기록했다. startup READY와 topic
prepare/admit를 통과했지만 첫 action에서 Fleet가 LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN으로
HOLD했다. owner에는 approach RUNNING이 기록됐으며 목표 확인은 0/16이다.
이 결과로 배치 간섭 해결이나 전체 작업 성공을 주장하지 않는다.

UTC 11:16의 저장된 시각은 다음과 같다. 전송된 응답 원문은 보존되지 않았다.

| 사건 | 초 |
|---|---:|
| Fleet STEP_SUBMITTING | 53.858040 |
| staging initial 관측 | 54.137197 |
| owner PREPARED / submission 시작 | 54.184336 / 54.206890 |
| approach submission 시작 | 54.461876 |
| Gazebo goal 수락 / owner 수락 기록 | 54.530797 / 54.545404 |
| phase RUNNING 기록 | 54.645042 |
| Fleet submit outcome UNKNOWN | 54.784831 |
| owner action RUNNING 기록 | 54.873889 |
| Fleet device receipt 기록 | 55.060518 |

Fleet 제출부터 UNKNOWN까지는 staging을 포함해 약 0.927초다. 기존 UDS timeout은
2초이므로 이 자료는 단순 timeout 증가의 근거가 아니다. ACK 이후 같은 run이나
불명 action을 재전송하지 않았다. 정리 결과는 cleanup_verified=true,
remaining_groups=[], cgroup 부재, MainPID=0 / 빈 ControlGroup, 실제 budget 파일 부재다.

## 별도로 재현한 producer 경쟁 조건과 수정

기존 ActionRunner 응답은 cached action의 journal watermark와 뒤에 읽은 phase 상태를
합쳤다. 그 사이 다른 SQLite 연결에서 phase RUNNING을 commit하면 phase event 번호가
응답의 journal watermark보다 커질 수 있다. 엄격한 DeviceActionReceipt validator는
이를 거절하고 transport는 UNKNOWN으로 내린다. 이 source 버그는 동시 writer를
끼워 넣는 원격 회귀로 재현했다. 위 실제 실행의 특정 응답이 이 형태였는지는 원문이
없어 확정하지 않는다.

`c6f9e8b263`은 이미 있는 attempt_snapshot의 단일 SQLite read transaction을 사용한다.
parent의 binding/state/time/goal, 동일 attempt의 phase/event와 watermark를 같은
snapshot에서 만들며, pure projection만 재사용한다. PREPARED/attempt 없음, 기존
v1/v2 응답, 만료 후 인증된 read-only reconciliation을 유지한다. action/attempt가
사라지거나 달라지면 거절한다. validator·timeout·재전송 금지·명령 권한은 바꾸지 않았다.
독립 리뷰 material finding 0, 원격 producer/consumer/G2 회귀 **166 passed, skip/NEW 0**이다.

## 다음 실행의 watchdog 관측 보강

`c71f008047`은 intake 직후 owner lock을 기다리기 전에 원래 stamp/source clock,
검사 시각과 세 steady 시각, intake 수락 여부·sequence·고정 거절 코드만 frozen record로
발행한다. owner의 취소 전 watchdog record가 이 immutable 객체를 보존한다. 거절된
packet에는 freshness를 주지 않으며 기존 provider 시각 읽기와 guard를 유지한다.
독립 D-430 Safety-Review APPROVE 후 원격 **98 passed, skip/NEW 0**이다.

`3ab4dd9874`의 G2 내보내기는 결정 순간의 intake와 나중의 최신 snapshot을 구분한다.
두 수정·형상 검사·trace·clock·startup을 합친 원격 집중 검증은 **64 passed, skip/NEW 0**이다.
이는 최신 관측을 묶는 진단이다. callback 발행과 guard 시각 표본 자체가 비원자적이므로
intake가 guard의 직접 원인이었다고 자동 판정하지 않는다. 이 수정들은 위 실행에 없었다.

## 증거와 한계

private 운영 scratch `native-auto-deployment-10/fetches/20261017T111749-b3990a02a307`에
원본·대조표·receipt를 보존했다.

```text
archive_sha256 = 52ec03f0820dd0af6965e7c469de8d7921d7b7006237b494609019dcce2954b7
extraction_map_sha256 = ed1a09d81edfebde4236cd44f8802a08272b773323ca6b2ef0d9332dba2f24e6
receipt_test_log_sha256 = 074294c9697eeb239c6402a4a8805794aabc9dd070556f39fe3b7e9999e30923
```

전체 native 작업의 성공·전체 G2 fault matrix·실물 수용·수집·학습은 별도 확인이 필요하다.
적격 실제 episode는 0개이며 실제 ACT 학습은 시작하지 않았다.
