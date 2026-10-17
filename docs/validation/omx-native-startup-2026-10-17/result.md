# OMX native task 시작·정지 연결 검증

2026-10-17. 검증 소스 commit `9108fd4d8e82aad8a1f31437bf1e30c83baa38aa`.

## 소프트웨어 결과

시뮬레이션 시작은 기본 HOLD다. 이름 있는 시뮬레이션 운영자의 별도 시작 허가가
현재 owner session·nonce·profile·목표 hash·Fleet epoch/generation에 맞아야 한다.
기존 Fleet 재무장 API가 실제 local rearm을 완료한 뒤에만 시작 요청을 한 번 게시한다.
이 허가는 실물 profile을 활성화하지 않는다.

UDS StopLocal 서버를 먼저 열고, 시작 명령 ID와 영속 intent를 최종 stop fence 전에
등록한다. ROS 수락 전 정지도 기존 runtime.cancel의 정확한 command ID로 전달한다.
기록 저장이 멈춰도 시작 취소와 기존 Fleet 취소 시도를 먼저 수행한다. terminal 성공과
새로운 안정 관측을 확인한 뒤 같은 fence 안에서 seat를 해제하며, runner enable도
다시 같은 fence를 통과한다. 정지 소켓 상실·세대 변경·불명 결과는 HOLD다.

기존 owner workflow timer를 G2 composition에도 연결했다. callback 수신만으로
다음 phase가 자동 실행됐다고 간주하지 않는다. 기존 G2 격리 검사는 유지했다.

## 원격 테스트와 독립 리뷰

AI/모델 시험 PC의 커밋 기반 remote_pytest로 검증했으며 노트북 pytest는 실행하지 않았다.
외부 scratch의 run-1.txt를 원본으로 보존했다.

| 범위 | 수정 전 | 수정 후 |
|---|---:|---:|
| 명시적 시작·세대·정확한 취소 gate | 13 failed | 기존 owner/phase 포함 58 passed |
| UDS 서버를 먼저 여는 startup session | 2 failed | startup 묶음 27 passed |
| startup 중 UDS 상실 | 1 failed, 2 passed | 최종 묶음 포함 |
| 별도 허가·one-shot Fleet rearm 요청 | 4 failed | 최종 묶음 포함 |
| 진단 기록 callback을 실제로 막은 정지 취소 | 1 failed | 최종 묶음 포함 |
| 최종 session/request/gate/기존 startup/owner workflow/phase | — | **66 passed**, skip 없음 |

원본 묶음: `startup-gate-red`, `startup-gate-green`, `startup-session-red-ai`,
`startup-session-green`, `startup-uds-loss-red`, `startup-request-red`,
`startup-cancel-io-red`, `startup-integration-green`.

독립 reviewer `/root/review_native_cycle`가 `a8141132fb..9108fd4d8e`를 검토했다.
취소 앞의 동기 기록 P2를 수정했고, 최종 검토에서 material finding은 없었다.
안전 태그 파일의 8줄 listener 상태 조회 변경은 [별도 Safety-Review](safety-review.md)를 받았다.

## 실행 준비와 남은 제약

이전 native Gazebo discovery 실행은 `a8141132fb`에서 별도로 통과했다. 이번 소스의
G2 SDK imports·실제 box-only16 compile·module origin 검사는 AI PC에서 통과했다.
기존 시험 venv를 수정하지 않고 시스템 Python과 해당 dependency site 경로를 조합하여
Gazebo protobuf import 누락을 해소했다.

현재 사용자 계정의 native 격리 시험은 systemd `218/CAPABILITIES`와
`unshare`의 uid_map 거절로 끝났다. `sudo -n`도 관리자 인증을 요구한다.
따라서 기존 G2의 network-none·장치 배제·read-only root 검사를 통과한 것으로
기록하지 않는다. 관리자 namespace 생성 후 일반 사용자로 실행하는 bounded systemd
명령과 PowerShell 실행·상태 조회 파일을 private 준비 묶음에 만들었다. Docker는 필요 없다.
준비 중에는 팔 Goal이나 시뮬레이션 task를 실행하지 않았다.

**미검증:** 이 변경의 isolated G2 runtime, 실제 task GOAL_CONFIRMED,
관제 PC의 실물 owner 활성화, 물리 변위·정지 수용, 실제 모방학습 시연·학습.
실제 학습 대상 episode는 0개다. SIM AID·SIM GRIPPER 시나리오는 실물 시연을 대신하지 않는다.
