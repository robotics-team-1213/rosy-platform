# Pilot 녹화 브라우저 시험 분리

2026-10-29 · `refactor/pilot-recording-browser-tests` · base `1d1f5c4bf5` · 최종 소스 `da361c0aa0`.

Pilot 녹화 초점 수정을 검증하기 전에2827줄의 기존 browser 파일에서 녹화 workflow11개를 `test_recordings_browser.py`로 분리했다. 기존 파일은2554줄로 줄였고 size_ratchet도2827→2554로 낮췄다. 새 파일286줄은 기존 conftest와 공용 helper/기본 controls fixture를 재사용한다. 제품 runtime·API·명령·기하·권한은 변경하지 않았다.

기존81개 test 함수 중11개 이동·70개 유지이며 누락/중복은 없다. Native AST 비교는 이동11개와 유지89개 함수(유지 helper 포함)의 body/decorator가 모두 같음을 확인했다. 독립 A도 test 함수 AST·fixture·누락/중복을 확인했다.

browser_scope의 Pilot 및 공용 자산 소비자에 새 파일을 등록했다. 첫 등록이 기존 `PILOT[2:]`의 순서 가정을 깨뜨리는 것을 실제 기존 회귀가 잡았다. 명시적인 OMX_PILOT 목록을 재사용해 기존 OMX 선택 범위를 유지했고 검사 기대값을 완화하지 않았다.

## 원격 검증

로그 원본은 외부 scratch `C:/DevTemp/rosy-ui-standardization/`에 있고 reports.sha256으로 확인한다. 모든 pytest는 승인된 시험 PC의 커밋 SHA 실행이다.

| SHA / 로그 | 결과 | 설명 |
|---|---|---|
| `db77769388`, pilot-recording-split/run-1.txt | 1 failed, 32 passed | 새 등록으로 인한 OMX 선택 확대를 기존 회귀가 검출 |
| `0681bf5fce`, pilot-recording-split-green/run-1.txt | 33 passed, 0 skipped | 이동한 실제 Chromium workflow16건과 browser scope17건, NEW0/known0/flaky0 |
| `0681bf5fce`, pilot-split-affected/run-1.txt | 1 failed, 625 passed, 137 skipped, 44 warnings | 줄어든 기존 파일의 ratchet row 갱신 누락 검출 |
| `da361c0aa0`, pilot-split-ratchet-affected/run-1.txt | 635 passed, 137 skipped, 44 warnings | 실제 측정2554로 ratchet을 낮춘 뒤 공식 affected 재검증, NEW0/known0/flaky0 |

선택 mode=full의 공식 remote_pytest affected 사전 검증이며 CI FULL/전체 lab full_invocations 수용은 아니다.137개의 optional browser skip은 실행 통과가 아니며 실제 browser는 위33건 중16건이다. 반복 결과를 고유 건수로 합산하지 않는다.

단순 시험 이동으로 UI 캡처는 추가하지 않았다. 이후 제품 초점/시트 수명 변경은 별도 `fix/pilot-recording-focus` 브랜치·검증 기록이 소유한다. 기존 파일은 여전히 한도 이상이므로 앞으로 그 파일에 더할 때도 분리 절차를 따른다.

CE: 해당 없음 — 선택/ratchet 실패와 해결이 기존 guard 및 최종 등록·회귀·측정값으로 설명된다. 설치·장치·FIELD·배포·착지·공개 push/merge는 수행하지 않았다.
