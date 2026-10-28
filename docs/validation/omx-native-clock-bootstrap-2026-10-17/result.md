# OMX native 전용 시계 구성의 초기화 거절

> Historical record recovered on 2026-10-19 from preserved work. Results below describe the cited source/run; this recovery does not rerun or extend that simulation evidence.

2026-10-17. 실행 source `0c90086539`, nonce `b9ca544ad998`.
[D-788](../../adr/D-788-omx-sim-dedicated-clock-executor.md)의 첫 실제 SDK 실행이다.

전용 시계 handoff 구현 `4d932c53b`은 원격 집중 64 passed, skip/NEW 0과 독립
리뷰 material finding 0 후 배포했다. 실제 SDK source hash 검사는 통과했으나
`Node.set_descriptor`가 기존 BOOL 파라미터와 descriptor 기본 타입 NOT_SET의
불일치를 거절했다. `use_sim_time` 고정이 완료되기 전 실패했다.

이 실행은 owner runtime·startup·topic 승인·업무 Goal 전에 끝났다.
목표 확인은 0/16이며 전체 task나 시계 scheduling 개선의 수용 근거가 아니다.
SDK 소스 hash 일치는 API 사용의 정확성까지 보장하지 않는다. 실제 타입 거절을
검사하지 않던 test double도 보완해야 한다.

ACK 뒤 같은 run을 재실행하지 않았다. 실제 격리는 4 CPU, 4 GiB, swap 0과
7,500초 상한을 유지했다. cleanup_verified=true, remaining_groups=[], cgroup 부재,
MainPID=0 / 빈 ControlGroup, 실제 budget 파일 부재를 확인했다.

private 운영 scratch `native-auto-deployment-12/fetches/20261017T114647-ff2007fca72f`에
원본·추출 대조표·receipt를 보존했다.

```text
archive_sha256 = 0836e12b5a8429e1f465efd64045cebff3ef2b5cec2c64af0f2209bd4ab9afd9
extraction_map_sha256 = 8e0b7aca2782f9af335cd49e4accbe9fe67783a09c33198864ed8bc258fb0109
clock_test_log_sha256 = 6e88d7552c7d0f69ef9dd94f2f03455134c26c337f91efc46162eecf0ee3a909
```

후속 수정은 BOOL 타입을 명시하고 기존 read_only 고정을 유지하는 범위다.
원격 재현·회귀와 별도 native 실행이 필요하다. 적격 실제 episode는 0개이며
실물 수집·ACT 학습은 시작하지 않았다.
