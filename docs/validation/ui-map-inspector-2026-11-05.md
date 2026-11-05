# 화면 지도: 현장 지도 검사 칸과 Learning 미리보기

기준: 화면 지도 아티팩트 `ER6vefvBnSjdAn3Pwx5iLW`. 현장 지도 선택 속성·초안 반영·저장·활성화는 하나의 검사 칸에 둔다. 95rem 이상은 지도 오른쪽, 그 아래는 지도 아래다. 지도 라벨 크기·클릭 좌표·명시적 활성화 계약을 보존한다. host/system 네트워크 패널은 기존 런타임 응답을 읽기만 한다.

## 착지 회귀와 수정

기존 `uiux/site-map-inspector`는 샘플 학습 입구를 위해 운영 정적 page registry에 `/console/learning`을 추가했다. 이 URL은 운영에서 보호된 호스트 설정으로 문서를 채우는 별도 동적 경로다. 기존 registry 계약 시험이 경로 목록의 변경을 검출했고 착지는 중단됐다. 개발 미리보기에도 템플릿 슬롯이 남고 `/model`·`/ai` 링크가 404였다.

운영 registry를 유지하고 개발 HTTP 호스트에서만 세 미리보기 주소를 처리한다. 운영 연결·계정·장치를 읽지 않으며 고정된 미등록 상태를 넣는다. 허브는 200, 미등록 호스트 문서는 503이고 복귀 링크를 유지한다. 독립 리뷰가 발견한 이동 중 한글 문구 손상도 복구했다.

## 검증 증거

- RED `851615c35d`: registry·sample server를 원격 현장 시험 호스트에서 실행. 기존 registry 불일치 1건과 새 미리보기 회귀 3건, 합계 4 failed/17 passed. `inspector-red/run-1.txt`.
- GREEN `f8b47be521`: AI 시험 호스트에서 registry·sample server·현장 지도 브라우저·운영 Learning 진입 회귀 151 passed, skipped 0, NEW 0. `inspector-green/run-1.txt`.
- 최종 제품/시험 `0b6f126525`: AI 시험 호스트에서 지도 배치·편집·활성화·좌표 선택 회귀 16 passed/84 deselected, skipped 0, NEW 0. `inspector-final-geometry/run-1.txt`. 배치는 1920·1520·1519·1440·390·320px × 두 테마, 실제 오른쪽/아래 위치·라벨 12px 이상·페이지 넘침 없음·비상정지 접근을 검사한다. 편집과 좌표 선택에는 1920px도 포함한다.
- 로그는 노트북 임시 `rosy-ui-map-20261105/` 아래 해당 묶음 이름으로 회수했다. 모든 pytest는 커밋 SHA를 `tools/remote/remote_pytest.py`로 실행하고 `test/known_failures.py`로 분류했다.
- 독립 리뷰는 최종 SHA와 남은 제한을 작업 공간의 화면 지도 마무리 기록에 보존한다. 공식 착지와 main ancestry는 아직 이 부분 회귀만으로 주장하지 않는다.

CE: 해당 없음 — 미리보기/운영 경로 분리의 이유와 회귀는 이 코드·시험·검증 기록으로 복원된다. 실제 호스트 연결·장치 동작·운영 배포·현장 수용은 검증하지 않았다.
