# OMX native 관절 freshness HOLD 진단

> Historical record recovered on 2026-10-19 from preserved work. Results below describe the cited source/run; this recovery does not rerun or extend that simulation evidence.

2026-10-17. [첫 실행 기록](../omx-native-runtime-2026-10-17/result.md)의 후속이다.
AI 역할의 승인된 격리 호스트에서 Docker 없이 실행했다. 실물 팔은 구동하지 않았다.

## 실제 실행에서 확인한 범위

| 실행 source / nonce | 관측 | 판정의 한계 |
|---|---|---|
| `cdcdf9b9f5` / `2a6de6100cd0` | startup `action_submission_failed`, Gazebo goal 수신 없음 | 당시 submit 예외의 원문·분류가 없어 DDS discovery를 유일 원인으로 확정할 수 없다. |
| `9115a6d45a` / `224d5f6db936` | startup goal 수락 후 cancel, `WATCHDOG_DECISION: joint_state_stale`, terminal UNKNOWN | owner가 유효한 관절 상태를 제때 반영하지 못한 것은 확인했으나 메시지 미도착과 intake 거절을 아직 구분하지 못했다. |

두 실행 모두 task prepare/admit 전 startup에서 HOLD했다. 각 run을 한 번만 시작했고
ACK 이후 재시작하지 않았다. cleanup_verified=true, remaining_groups=[], cgroup 부재와
MainPID=0을 확인했다. 해당 run의 실제 budget 파일도 없어졌다.

두 번째 실행의 진단 snapshot에서 SIM clock은 6.192초, 마지막 runtime 관절 상태의
received_at은 5.610초였다. 차이 **0.582초**는 설정된 **0.5초** 한계를 넘었다.
관절 source stamp는 5610000000ns였다. 이 기록은 stale 판정의 근거이며, upstream
센서·DDS·executor·owner 중 어느 구간이 지연됐는지 자체로 입증하지 않는다.

## 수정과 검증

- 실제 owner action client의 server_is_ready도 startup 준비 조건에 포함했다. 기존
  별도 probe의 성공만으로 새 client discovery가 끝났다고 판단하지 않는다.
- workflow timer에 별도 mutually-exclusive callback group을 배정했다. Jazzy의
  TimeSource 기본 callback group과 분리하고 executor slot을 5개로 맞췄다.
  AI 서비스 CPU 상한은 4개로 유지한다. 이 변경이 위 stale의 유일 원인이라는 주장은 하지 않는다.
- terminal 진단은 기존 이벤트 전달 후 bounded queue에 기록한다. 별도 writer가
  파일을 쓰며 callback에서 owner/handle lock, 파일 I/O, stderr를 기다리지 않는다.
  강제 종료 시 마지막 기록의 영속성을 보장하지 않는다.
- `a160ba66d8`은 intake 시도·수락·거절 횟수, 원본 stamp와 검사 시각, monotonic 수신 시각,
  allowlist 거절 코드만 추가했다. 원래 검증 함수를 정확히 한 번 호출하며 결과 객체와
  예외를 그대로 전달한다. 거절된 메시지는 accepted stamp·sequence·owner freshness를 갱신하지 않는다.
  owner가 반영한 snapshot과 runtime 최신 snapshot도 따로 남긴다. 관측은 비원자적이다.

원격 집중 검증은 `a160ba66d8`에서 intake/진단/startup **38개**, workflow clock/task client
**25개**로 합계 **63 passed, skip 0**이다. known_failures 비교는 NEW/known/flaky 모두 0이다.
기존 Starlette/AnyIO deprecation 경고 2개가 있었다. 독립 코드 리뷰 material finding은 0개다.
freshness·future-stamp·timeout·HOLD 기준과 명령 권한은 완화하지 않았다.

## 증거 위치와 남은 확인

private 운영 scratch의 `native-auto-deployment-6/fetches/20261017T104135-4a3e17b103fb`에
원본 archive, 추출 대조표와 receipt를 보존했다. host/account/IP는 공개 기록에서 제외한다.

```text
archive_sha256 = f85e6ffb08f45b280d262c111f2faeddf926c502df3e3335fee7ec08cd818cf9
extraction_map_sha256 = d7f723065a79499ae0f88f02b35798235a21557b805b5b513fbbcc784cb05cc0
```

원격 시험 로그는 외부 scratch `native-intake-observation-green/run-1.txt`와
`native-intake-composition-green/run-1.txt`다. 새 관측을 포함한 실행의 결과는 별도 후속
기록으로 남긴다. 본 기록은 task 완료·전체 G2 fault matrix·실물 수용을 입증하지 않는다.
실제 적격 episode는 0개이며 실제 ACT 학습은 시작하지 않았다. 중단된 병합 검사는
최종 병합 증거로 사용하지 않는다.
