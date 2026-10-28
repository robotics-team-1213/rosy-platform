# OMX native 격리 실행과 첫 task HOLD

> Historical record recovered on 2026-10-19 from preserved work. Results below describe the cited source/run; this recovery does not rerun or extend that simulation evidence.

2026-10-17. 실행 commit `9b760dce01`, run nonce `ca3197f8dc35`.
[설치 후 기록](../omx-native-installed-2026-10-17/result.md)의 후속 실제 실행이다.

## 확인한 실행 범위

자원 예약을 반영한 6 CPU / 8 GiB 여유 검사를 통과한 뒤, 기존 SSH 배포 CLI와
좁은 root helper로 한 번만 시작했다. 시작 ACK 이후에는 같은 run을 재전송하지 않았다.
일반 계정으로 조회한 실제 systemd unit은 다음 설정을 보였다.

| 항목 | 관측 |
|---|---|
| 실행 계정 | 설정된 일반 계정, uid/gid 1000 |
| namespace | PrivateNetwork=yes, PrivateDevices=yes, PrivateTmp=yes |
| 파일 권한 | ProtectSystem=strict, ProtectHome=read-only, 고정 state root만 ReadWritePaths |
| 권한·종료 | NoNewPrivileges=yes, KillMode=control-group |
| 상한 | CPUQuotaPerSecUSec=4s, MemoryMax=4294967296, MemorySwapMax=0, RuntimeMaxUSec=2h5min |

실제 G2 isolation guard를 통과했다. Gazebo의 arm controller와 joint-state broadcaster가
활성화됐고 7개 관절, 시뮬레이션 clock 진행, trajectory action server를 확인했다.
ROSY의 별도 startup 허가 경로로 home 이동이 `READY`가 됐다. ROS terminal status 4,
result code 0, seat_reconciled=true이며 10.61초 SIM / 10.62초 wall이 걸렸다.
최종 관절 상태도 요청한 목표 근처에 도달했다.

## task 결과

기존 Fleet compile → proposal → admit → UDS → OMX owner 경로의 box-only16 작업을
시작했다. 첫 작업의 approach와 grasp는 ROS SUCCEEDED였다. transfer는 승인·RUNNING
이후 `UNKNOWN`이 됐고, canonical Cell Job은 `LOCAL_ACTION_HOLD`로 종료됐다.
device reason은 `ROS_TERMINAL_RESULT_UNKNOWN`, 독립 목표 확인은 **0/16**이다.

Gazebo cancel 요청은 UNKNOWN 기록 직전에 보였다. freshness watchdog과 result future
예외 등 여러 producer가 같은 UNKNOWN을 내며 현재 영수증은 원인을 구별하지 않는다.
watchdog가 유력하더라도 확인된 원인으로 단정하지 않는다. timeout·freshness·HOLD를
완화하지 않았고, 원인 관측을 보강한 새 버전만 새 run으로 실행해야 한다.

`g2/result.json`은 HOLD, cleanup_verified=true다. process-cleanup은
verified_absent=true / remaining_groups=[]였다. terminal unit의 MainPID=0,
ControlGroup은 비었으며 해당 cgroup 디렉터리도 없었다. 이 run의 실제 budget.lock와
budget.resv는 제거됐고, 고정 state를 가리키는 원래 예산 심볼릭 링크만 남았다.
이 결과를 task 성공이나 전체 G2 fault matrix 통과로 표시하지 않는다.

## Windows 증거 회수 수정

최초 실제 회수는 Gazebo ISO timestamp 디렉터리의 콜론 때문에 Windows WinError 123으로
실패했다. 원본 archive는 보존됐다. commit `de27676753`은 regular file만 bounded하게
추출하고, Windows에 부적합한 이름·대소문자 충돌·예약어·끝의 점·긴 경로를 변환한다.
원본 이름 대조표와 그 SHA-256을 별도 receipt에 결속하며 파일을 덮어쓰지 않는다.
절대/상위 경로·링크·중복 경로는 거절한다. 추출 실패도 원본과 hash receipt를 보존한다.

새 원격 회귀는 수정 전 3 failed / 1 passed였다. 수정 후 helper/runtime/CLI/release
집중 검증은 **155 passed, skip 없음**이다. 독립 리뷰 material finding은 0개다.
이어서 Windows 개발 PC에서 실제 SSH fetch가 exit 0으로 끝났다.

원본은 private 운영 scratch `native-auto-deployment-3/fetches/20261017T101227-b093c6192d23`의
archive·추출 파일·대조표·receipt와 `agent-observations`의 unit/journal 관측이다.

```text
archive_sha256 = 5d39dd64e27846f2d6c046b677172563b9636591c8828dbac0724ebca066c0b5
extraction_map_sha256 = 69b116cd3aedbd3996e0b2f706b41940b06c4f15cbb3f7f4127bf9cc2caaef7c
```

## 남은 범위

시뮬레이션 aid와 가상 그리퍼 센서를 쓴 실행이다. 실제 물체 파지나 실물 동작 수용의
증거가 아니다. task 완료, 전체 fault matrix, 실제 시연 수집, ACT 학습은 확인하지 않았다.
실제 적격 episode는 0개다. 중단된 병합 검사나 이전 후보의 통과를 최종 병합 증거로
재사용하지 않는다. 신규 진단·수정은 별도 커밋 검증과 새 실행 기록이 필요하다.
