# 지도 검토 저장 완료 관측의 CI 후속 검사

[사이트 설치·계정 기록](../all-ui-deployed-2026-10-12/result.md)의 후속 시험이다. 설치 source commit `7a03bf1bf08e`의 전체·Android CI 성공과 실제 설치 확인은 그대로 유지한다. 문서 후속 commit `9076d86f28`의 [CI 38189986917](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38189986917)은 Fleet 한 묶음에서 1 failed / 1,716 passed / 5 skipped로 실패했다. 나머지 시험 matrix는 성공했지만 전체 CI 성공으로 계산하지 않는다.

## 원인과 최소 변경

실패는 `test_camera_road_review_without_survey_keeps_lineage_and_requires_recheck[390]`에서 검토 저장을 누른 뒤 서버의 이전 observed 초안을 읽은 것이다. `#draft-status`의 저장된 초안 문구는 기존 초안에도 있으므로 이번 PUT 완료의 증거가 아니었다. 실제 제품 저장 callback은 서버 응답을 await하며 제품 코드는 이 후속 변경에서 수정하지 않는다.

commit `e5f078ee02`는 첫 저장도 기존 두 번째 저장과 같이 `PUT /api/fleet/site-map/draft` 응답을 기다리고 성공 응답을 단언한다. 서버에서 다시 읽은 지도 출처·검토 상태·메모, 이후 수정의 observed 상태 복귀 및 활성화 거절, 실제 명령 없음 검사는 유지한다. 임의 sleep이나 재시도·기존 실패 목록 추가는 없다.

## 원격 증거

- 수정 전 commit `9076d86f28`: 실제 Chromium 같은 두 크기 시험에서 1 passed / 1 failed, 종료 1·NEW 1. 이번에는 1440px에서 같은 이전 초안 관측을 재현해 특정 화면 폭의 제품 결함으로 단정하지 않았다.
- 수정 후 commit `e5f078ee02`: 적정 AI PC에서 CI pytest 7.4.4/setuptools 68.1.2/wheel 0.42.0과 실제 Chromium으로 두 크기 **2 passed**, 종료 0·NEW 0.
- 독립 읽기 전용 검토: native_games_ui가 PUT transaction 완료 후 성공 응답 관측과 기존 출처·재검토·거절·무동작 단언 보존을 승인했다. 직접 시험 재실행을 한 검토로 계산하지 않는다.
- 공용 비공개 증거 루트 `X:/DevTemp/projects/rosy-platform/2026-10-12--015344--fleet-header-proof--958a02/`의 `logs/final-doc-ci-failed.txt`, `logs/map-save-observe/run-1.txt`, `logs/map-save-green/run-1.txt`에 원본을 보관한다.

이 선택 검사 자체는 후속 후보의 전체 CI 성공을 대신하지 않는다. 사용자 본인 계정 비밀번호 초기화 승인은 대기 중이며 팀원 네 계정과 기계 토큰은 보존한다. 외부 채널 설정은 보관·중지 상태이고 실제 주행·실물 기기 수용·TLS 신뢰는 이 시험 범위가 아니다.
