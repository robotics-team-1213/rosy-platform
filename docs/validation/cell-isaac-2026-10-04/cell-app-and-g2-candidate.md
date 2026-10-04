---
module: deploy
tags: [cell, palletizing, G1, G2, D-450]
---

# Cell 편집·운전석·G2 후보 검증

2026-10-04 후보 소스의 검증 범위다. 로컬 커밋이나 호스트 테스트를 이미지·실제 장치 수용으로 승격하지 않는다.

| 범위 | 확인된 증거 | 남은 항목 |
|---|---|---|
| 구조 편집 | 실제 Chromium와 Cell API/store/job 23 passed, 독립 UI 검토 | TCP capture와 owner 티칭 수락 |
| Pilot/Cell 배타 | 257 passed·기존 2 skips, 독립 경합 repro 및 22 tests | 실제 ROS 경합과 재시작 exact-goal 복구 계약 |
| G2 실행기 | host preflight의 16 box transfers/marker8·16, 독립 15 tests | 실제 SDK import·16회 배치·fault matrix |
| 통합 | affected 42 passed, fast462 passed·기존2 skips, NEW0 | 로컬 main 착지와 원격 CI·배포·현장 수용 |
| 수동 슬립시트 | recipe/2의 box16 및 checkpoint5·13, 기존 recipe/1 호환; 통합 guard/store/API/schema/replay101 passed, Chromium9 passed | owner-exclusive 접근 계약·작업자 확인 API·실행 검증 |

G2는 실제 Fleet 발급 grant만 사용하며 세계 staging은 durable intent 이후 한 번만 실행한다. pose·gripper·clock은 별도 프로세스가 측정하고 이전 모든 배치를 매 transfer와 마지막에 다시 검증한다. Python source origin을 확인하고 설치 wheel ARTIFACT closure는 NOT_RUN으로 유지한다. 결과는 실제 happy path 통과 때도 full_g2=false이며 fault matrix 미수행을 명시한다.

SIM AID의 detachable joint와 SIM GRIPPER 측정은 실제 파지나 작업자 안전 접근의 증거가 아니다. 수동 sheet 확인은 단순 owner ready·StopLocal ACK·caller boolean으로 다음 층을 열 수 없다.

수동 처리 선택은 간지 두께를 보존하며 별도 로봇 집기 위치를 만들지 않는다. 관제는 간지 삽입 대기 사유를 표시하고 일반 재승인으로 이를 통과시키지 않는다. owner 접근 허용 계약과 확인 경로가 아직 없어 실제 작업은 `OPERATOR_SHEET_ACCESS_UNAVAILABLE`로 보류된다. 체크포인트는 같은 Fleet SQLite 트랜잭션에서 Job·다음 단계와 함께 보류하며, 누락·부분 투영은 저장 자체를 롤백한다. HTTP 확인 기능과 물리 작업자 접근 수용은 NOT_RUN이다.

모델 PC 직접 SSH 접속은 확인했으나 비밀번호 없는 sudo와 Docker 접근은 거부되었다. 사용자가 실행한 G2 준비 명령의 이미지 빌드는 성공했지만 cap-drop 컨테이너가 소스 마운트를 읽지 못해 import 검사가 실패했다. 실패 결과와 검증 컨테이너 부재 확인을 보존했고 소스 읽기 권한을 고친 별도 재시도 폴더를 준비했다. 이미지 preflight와 시뮬레이터 수용은 아직 HOLD/NOT_RUN이다. Isaac A07은 정상 프로세스 종료를 확인했지만 전진 거리와 입력 만료 후 실제 정지 조건을 만족하지 못했으므로 주행 수용은 HOLD다.

최신 main 통합 후 PROCESS·G2·Isaac source 68 tests가 통과했다. fast 실행은 462 passed·기존 2 skips였으며, 나머지 1건은 검증 문서의 공개 SHA-256 표기에 대한 secret-scan 오탐이었다. 해당 네 값에 명시적인 `sha256:` 표기를 추가한 뒤 release-boundary 전체 79 tests가 통과했다. scanner나 예외 목록은 변경하지 않았다. 문서 병합의 충돌 표시는 별도 수정했으며 양쪽 부모의 모든 journal entry가 보존됐다는 독립 검토와 lint 오류 0을 확인했다.

교훈: cap-drop 컨테이너의 root는 다른 UID가 소유한 0700 마운트에 대한 읽기 권한을 우회하지 못한다. 정제된 소스에만 읽기 권한을 부여하고 evidence는 실제 고정 image UID와 일치시키며, rootless/userns 설정은 별도 소유권 검증 전 거절한다. 호스트 SSH 성공·Docker 이미지 빌드 성공·컨테이너 import 성공을 각각 검증해야 한다.

## G2 startup 통합 후속: 자동 home은 HOLD

2026-10-04 `4941cfb4f995e894ba33717306ad9c790483ae06` startup 추가안을 별도로
검토했다. 측정 home helper의 10개 검증은 통과했으나 초기 UNKNOWN LocalStop을
거치지 않는 자동 제출과 homing 중 StopLocal IPC 부재가 확인됐다. 이는 앞의
Gazebo 단일 generation-change 결과를 폐기하거나 전체 G2 완료로 바꾸는 기록이
아니다. 자동 startup 경로의 별도 안전 차단 사유다.

통합 fallback은 home을 제출하지 않고 기존 Action 제출 기능을 비활성화한 뒤
StopLocal·상태 조회 IPC만 제공한다. Pilot HTTP 제어와 pending Action 진행을
시작하지 않으며 기존 stop latch 초기화·자동 rearm도 하지 않는다. runner는
`STARTUP_AUTHORIZATION_REQUIRED` HOLD 기록을 발견하면 rearm·admit 전에 종료해
기존 소유 프로세스 cleanup을 수행한다. owner의 관절 수신 준비 상태는 측정된
home READY나 작업 승인과 같지 않다.

명시적인 startup 승인, 기존 열린 세대의 최종 `run_if_open` 제출 fence, 정확한
startup goal의 StopLocal 취소 연결을 마련하기 전에는 자동 home을 실행하지
않는다. 그 후에도 ROS 결과 이후 신선한 관절 측정과 지속 안정성 검증이 필요하다.
fallback의 독립 SPEC·Quality·Safety 소스 검토는 PASS이고 교정된 gate-noop
회귀 2 FAIL 뒤 적용본 G2 12 PASS로 기존 측정 검증 10개를 유지했다.

통합 worktree의 G2·카메라 boot guard·native systemd 전체 세 파일은 206 PASS,
기존 Windows POSIX signal 1 SKIP, NEW 0이었다. 카메라 독립 9개·11개 검증과
중복 합산하지 않는다. 실제 ROS startup·16회 배치·fault matrix·실제 카메라 boot·
물리 장치 수용은 확인하지 않았으며 G2 실행 수용은 HOLD다. 상세 통합 소스 기준과
로그는 [main 통합 기록](../network-peer-discovery-2026-10-04/main-integration-checkpoint.md)에
기록했다.
