# 녹화 인계 UI 후속 개선 검증

2026-10-28 KST. 브랜치 `fix/recording-learning-handoff`. 후속 변경 기준 commit은 `2631515ea7`, 최종 제품 소스 commit은 `95b205573f`다. 최종 시험 보강 commit `030c2fb110`까지 제품 디렉터리 diff는 0이다. 아래 기록·색인은 문서 변경이다.

이전 기록은 [녹화·검수·변환·보관 연결](../recording-learning-handoff-2026-10-28/result.md)이다. 그 뒤 별도의 main 통합 commit `2631515ea7`이 작업 브랜치에 있었으며, 이번 수정은 그 트리를 기준으로 검증했다. 그 통합 전후 이번 UI 대상의 diff는 없었다. 앞선 FULL26 결과를 새 통합 소스의 전체 수용으로 재사용하지 않는다.

## 결과

남은 녹화·검수·변환·보관 UI의 구체적인 결함을 수정하고 실제 HTTP/Chromium과 영향 회귀로 검증했다. 독립 소스 리뷰에 남은 P1/P2 지적은 없다.

- 전체 도구에서는 전체 보기임을 명시하고 거짓 현재 단계 강조를 없앴다. 단계별 보기는 기존 선택 표시를 유지한다. 중첩 anchor는 실제 초점 대상을 상단바 아래로 이동시키며, view 전환은 다른 query와 hash·뒤로가기 문맥을 보존한다.
- 변환 목록은 동일 결과에서 DOM을 유지한다. 결과 변경 시 같은 작업·동작으로 키보드 초점을 복구하고, 동작이 사라지면 해당 작업 제목 또는 변환 영역으로 복귀한다.
- 진행 중 변환 중지 요청과 거절 메시지는 폴링으로 목록이 바뀌어도 유지된다. 중지 대기 중 새 버튼이 활성화되어 중복 요청하지 못한다.
- 실행기 조회 상태/오류는 숨긴 6단계 밖의 공통 영역에 표시한다. 읽기 오류는 기존 목록이 오래된 결과일 수 있음을 알리며 재조회 성공 후 지운다. 작업 제출 오류와 별도 상태다.
- 저장 검수 선택과 설명을 `aria-describedby`로 연결하고 변경 설명은 status로 노출한다. 시도별 결과·물체 결과·분할은 보이는 한국어 열 제목과 같은 접근성 이름을 쓴다.
- 완료 자료에서 Enter로 보관에 들어가면 고정 자료 ID/revision을 유지하고 준비 영역 제목에 한 번 초점을 준다. 이후 목록 새로고침은 초점과 동의를 빼앗지 않는다. 누락된 revision을 다른 자료로 바꾸지 않고 복구 설명을 제공한다.
- 저장 검수 ID/원본 revision/체크 상태/변환 동작을 함께 캡처했다. 폴더·실물 자료·진짜 검수 결정·API/권한·HF provider 경계는 변경하지 않았다.

## 검증과 원본 위치

모든 pytest는 공식 원격 runner로 커밋을 전송해 승인된 AI/모델/site TEST 호스트에서 수행했다. 노트북 pytest는 실행하지 않았다. 브라우저는 격리 fixture 서버와 실제 Chromium, 보관 쓰기는 fake HF transport다. 각 GREEN 로그를 `python test/known_failures.py <log>`로 비교했으며 NEW0 / known0 / flaky0이다. “listed but not failing”으로 표시되는 기존 theme 항목은 해당 시험 실행 증거가 아니다.

로그 표의 루트는 `C:/DevTemp/`다. 실행 범위는 서로 겹치므로 행별 건수를 합치지 않는다.

| 범위 | commit | 실제 결과 | 로그 |
|---|---|---|---|
| 탐색·조회 오류·poll 초점 RED | 2b9e047d8d | 7 failed / 9 deselected | recording-handoff-ui-followup-red/run-1.txt |
| 설명/접근성·보관 초점 RED | 6ab8eae558 | 4 failed / 1 deselected | recording-handoff-ui-accessibility-red/run-1.txt |
| 중지 대기 상태 RED | 309ada1c40 | 1 failed | recording-handoff-ui-stop-red/run-1.txt |
| 1차 탐색·초점 전체 | 098e014f73 | 16 passed / skip0 | recording-handoff-ui-followup-green/run-1.txt |
| 검수·변환·보관 전체 | 1cf5d24e99 | 19 passed / skip0 | recording-handoff-ui-accessibility-green/run-1.txt |
| 중지 상태 포함 전체 | 95b205573f | 17 passed / skip0 | recording-handoff-ui-stop-green/run-1.txt |
| 공식 브라우저 선택 17파일 | 147e97ab70 | 최초 262 passed / 1 failed / skip0 | recording-handoff-ui-followup-browser-final/run-1.txt~run-8.txt |
| 실패한 두 파일 전체 보강 후 | 6f7fff249c | 19 passed / skip0 | recording-handoff-ui-rail-green/run-1.txt |
| 저장 검수 최종 캡처 | 54fa5d9e7c | 2 passed / skip0 | recording-handoff-ui-saved-capture-final/run-1.txt |
| 오류 최종 캡처·좌표·회복 | 030c2fb110 | 1 passed / skip0 | recording-handoff-ui-alert-capture-final/run-1.txt |
| Git 근거 표기·릴리스/비밀값/배치 | 88a2963129 | 108 passed / skip0 | recording-handoff-ui-provenance-green/run-1.txt |
| 최종 공식 영향 선택 27대상 | 030c2fb110 | 3059 passed / 352 skipped | recording-handoff-ui-followup-affected-final/run-1.txt |

공식 영향 명령은 `python tools/harness/rosy_harness.py affected --base 2631515ea7 --json`이다. [선택 원본](evidence/affected-selection.json)은 affected/no escalation이다. 이를 `remote_pytest.py --sha 030c2fb110 --affected-json <selection> --log-dir <external-dir>`로 실행했다. 352 skip은 Chromium opt-in·SDK/학습 환경 등에 의존하는 시험이며 통과/실행으로 세지 않는다.

별도 Chromium은 `browser_scope.targets(changed)`가 선정한17파일 전부를 `land_browser.chunks()`의 공식8묶음으로 만들고 `remote_pytest.run()`에 전달했다. 모든 묶음에 `ROSY_RUN_BROWSER_TESTS=1`을 넣었으며 제외 파일은 없다. 최초 종료 코드는 `[0,0,0,1,0,0,0,0]`이다. 실패를 없었던 것으로 바꾸지 않고 원본별 결과/SHA를 [manifest](evidence/manifest.md)에 남겼다. 뒤의 보강·재실행으로 남은 NEW 실패는 없다.

## 실패 원인과 후속 확인

- 브라우저 run-4의 기존 메뉴 시험은 `/`로 이동한 뒤 load 이벤트만 기다렸다. 비동기 workspace가 아직 로딩 중인 39글자 문구를 즉시 `>40` 검사해 실패했다. 빈 fixture 검수 화면의 로딩 제목이 바뀔 때까지 기다리도록 보강하고 기존 링크·본문·계정·도착 URL·오류 검사를 유지했다. 두 파일 전체19건을 재실행해 확인했다. 제품 로딩 동작이나 assertion을 약화하지 않았다.
- 최초 영향 선택은 3034 passed / 352 skipped / 1 failed였다(`recording-handoff-ui-followup-affected/run-1.txt`, source commit95b205573f). 이전 검증 문서의40자 Git ID 세 곳이 비밀값 검사에 걸렸다. `git cat-file -t`로 두 ID가 실제 commit임을 확인하고 메타데이터 이름을 `base_commit`/`tested_commit`, 본문을 commit 표기로 명확히 했다. 원본 실행 행렬·커밋 값·결과·로그는 그대로이며 파일 표현의 변경 hash와 설명을 원래 기록에 명시했다. scanner 코드·허용 목록·baseline은 변경하지 않았다. 이후108건과 최종3059건으로 거부 경계를 다시 확인했다.
- 저장 검수 캡처는 최종 변환 활성화 assertion 뒤에 찍도록 순서를 보강했다. 오류의 첫 전체 viewport 캡처에는 공통 상단 오류 문구가 화면 밖이어서 증거로 쓰지 않았다. 최종 캡처는 폰트 준비 후 오류를 중앙으로 이동하고 상단바 아래 viewport 좌표를 검사한 다음 요소 crop으로 저장했다. 실제 오류 표시와 회복 기능은 별도 DOM/role/text assertion으로 확인한다.

## 화면과 리뷰

원본 PNG는 `C:/DevTemp/recording-handoff-ui-followup-screenshots/` 아래에 보존하고 커밋하지 않았다. [10개 캡처의 이름·SHA](evidence/manifest.md)를 기록했다. 두 승인된 에이전트가 소스/화면을 독립 검토했고, root가 추가 오류 crop을 직접 확인했다.

- 320/1440px 중첩 검수 제목이 상단바 아래에 있고 초점 테두리가 보인다. 전체 도구에 잘못된 1단계 강조가 없다.
- 320px/light와1440px/dark의 저장 검수 form crop은 선택·긴 식별자·변환 동작을 한 이미지에 담으며 좁은 화면에서 잘리지 않는다. 활성화 자체는 브라우저 assertion 근거로 판정한다.
- 보관 화면은 펼쳐진 준비 제목·선택 자료·고정 버전·원본 보존 문맥이 보인다. Enter 이동/도착 초점/동의 초기화·새로고침 유지·잘못된 revision 거부를 실제 HTTP Chromium으로 확인했다. 기존 E2E도 링크를 실제로 순회했으며 이번에는 키보드 증거를 강화했다.
- 최종 오류 crop에는 `fixture center unavailable`이 읽힌다. crop은 전체 화면 배치를 증명하지 않으며, 조회 실패 상태를 실제로 보여 주는 요소 증거다.

전체 UI 점수나 WCAG 전체 준수 점수는 새로 부여하지 않았다. 실제 스크린리더 낭독·실물 폰/로봇 화면·운영 배포본을 확인한 결과가 아니다. Harness lint는0 errors /45 warnings, source commit030c2fb110까지 size_range는11 commits checked다. warnings는 기존 이력/gate 상태이며 새 현장 수용이 아니다.

## 수용 한계

보관 딥링크는 권한이나 쓰기 승인을 부여하지 않는다. 실제 녹화·교정 UI, 진짜 HF 전송/재다운로드/LeRobot reader, 모델 품질·실물 행동, 설치·배포·main merge/push는 별도다. 이번에는 해당 작업을 실행하지 않았다. CLI/owner의 미연결 범위를 새 UI 완료로 표시하지 않는다. 모든 수정과 증거는 기존 임시 워크트리의 검토 가능한 커밋으로 보존한다.

CE: 해당 없음 — 초점·pending/거절 상태·조회 오류·도착·동기화 판단은 코드·의미 있는 회귀·기존 문서에서 복원할 수 있다. 별도 해결 교훈을 늘리지 않는다.
