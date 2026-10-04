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
