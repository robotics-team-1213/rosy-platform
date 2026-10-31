# Learning 저장 공간의 공용 버튼·폼 배치

2026-10-29, `fix/learning-storage-controls`, base `f05af50515`, 최종 source/시험 `06c40584b3`. 일반 동작 버튼 두 개를 공용 quiet 버튼으로 이행하고 폼 제목을 필드 위의 전용 행으로 배치했다. 새 CSS palette·토큰·공용 API는 추가하지 않았다.

재조회는 type=button, 공간 추정은 type=submit을 유지한다. storage.js의 submit caller도 ui-button으로 바꿨다. 공용 requestSubmit과 Enter 배선을 통해 native required/min/max 검증을 유지한다. 공간 추정은 기존 계산 API이며 실제 공간 예약·파일 전송이 아니다. 데이터/권한/epoch/busy와 인증 취소 처리도 보존했다.

## 실행과 관측

모든 pytest는 커밋된 SHA로 공식 원격 시험 PC에서 실행했다. 임시 ReviewStore·계정·폴더만 사용했다. 실제 HF·운영 라벨·실물 장치에 접근하지 않았다. 원본은 `C:/DevTemp/rosy-ui-standardization/`, 최종 로그4개의 hash는 reports.sha256에 있다.

| source | 로그 | 실제 결과 |
|---|---|---|
| `e1b1cdec6b` | storage-red/run-1.txt | 일반 버튼의 공용 역할 누락8 실패·HTTP1 통과 |
| `fd6803e3e7` | storage-heading-red/run-1.txt | 1440의 두 테마에서 제목이 필드보다 아래에 놓이는 geometry2 실패·7 deselected |
| `06c40584b3` | storage-layout-verified/run-1.txt | **9 passed, 0 skipped**. 320/390/768/1440 × dark/light의 실제 HTTP·Chromium8과 HTTP 권한1 |
| `06c40584b3` | storage-layout-affected/run-1.txt | **2880 passed, 358 skipped**, warnings51. selector affected, no escalation, 4 changed files, 1 invocation |

두 합격 로그 모두 known_failures 비교 NEW0/known0/flaky0이다. listed-but-not-failing 테마 항목은 이 범위에서 고쳤다는 증거가 아니므로 baseline을 지우지 않았다. skip358을 실행한 것으로 쓰지 않는다. 브라우저 전체 선택·FULL·CI 전체를 실행한 기록도 아니다.

실행 시 버튼의 공용 종류·48px 이상 표적, 최댓값을 넘은 입력의 native 제출 차단, Enter 제출, 공간 충족/보류/부족, 재조회503와 복구, 지연 응답 중 인증 취소, 가로 넘침, 제목이 필드보다 위에 놓임을 확인했다. 기존 실패/복구/원본 보존 assertion을 약하게 만들지 않았다.

최종 ready/form/error 각8장, **24PNG**는 source06의 동일 실행에서 생성해 `C:/DevTemp/rosy-ui-standardization/storage-layout-final/`에 보존했다. captures.sha256은 이 24장만 가리킨다. A(`/root/ui_design`)의 소스 검토와 독립 B(`/root/ui_evidence`)의 최종24/24장 직접 검토에서 해당 범위의 P1/P2가 없었다. Root도 1440 밝게 ready·320 어둡게 form을 직접 확인했다. 모바일 form 캡처에 설명과 제출 버튼이 모두 들어가며 두 테마의 제목·필드·버튼이 겹치지 않는다. 스크롤된 viewport라 일부 상단 제목/첫 라벨은 경계에 걸리며 ready/form이 서로 보완한다. 키보드·API 결과는 이미지가 아니라 실행 assertion의 증거다.

## 중간 실패와 증거 수명

첫 캡처는 remote_job.JOB가 종료 시 지우는 TEMP 아래에 생겨 보존되지 않았다. 그 실행의 통과를 시각 검토로 쓰지 않았다. test-only f4a8491182에서 명시 ROSY_UI_CAPTURE_DIR의 절대 경로를 helper에 넘겨 job scratch 밖에 보존했다. 이전16장(storage-captures-final)은 제목 개선 전 자료로 분리했고 최종24장과 합치지 않았다. 환경 옵션은 시험 증거 위치만 바꾸며 제품 설정이 아니다.

초기 단위9 passed, da208d82ba의 영향2880/358, f4의9 passed/캡처16 검토, 최초 RED와 제목 RED 원본은 덮어쓰지 않았다. 현재 표의 최종06 결과가 이 변경의 수용 근거다.

gate는 올리지 않았다. 전체 플랫폼 표준화·native 빌드·실제 HF·LeRobot reader·모델 품질·실물/현장 수용·설치·배포·착지·push/merge는 별도다. 이전 UI 후속·공용 기반·다른 앱 브랜치와의 최종 통합도 남아 있다.

CE: 해당 없음 — 부품의 type/submit 연결, 폼 제목 배치와 job scratch 수명의 판단은 최종 코드·실제 geometry/native 검증 회귀·이 기록으로 복구할 수 있다. 관련 교훈 검색에서 동일 캡처 문제의 기존 문서는 없었으며 단순 경로/배치 수정을 별도 교훈으로 중복하지 않았다.
