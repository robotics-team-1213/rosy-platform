# Robot SSH 작업 결과와 화면 수명

2026-10-29 · `fix/robot-ssh-action-status` · base `62db787222` · runtime `e7256c6299` · 최종 코드/시험 `70d4a0e579`.

## 변경과 범위

`panels/system/security.js`의 임시 비밀번호 발급/끄기 실패가 finally의 현재 상태 조회에 덮였다. 기존 공용 ui-status를 작업 결과용으로 하나 추가해 조회와 분리했다. 다음 명시적 시도만 이전 작업 결과를 바꾼다. 두 버튼은 초기 조회와 쓰기·후속 조회 동안 함께 잠기고, 조회 실패 시 비활성 사유를 유지한다. 화면 해제 뒤 응답은 credential·버튼·상태 DOM을 바꾸거나 후속 GET을 시작하지 않는다.

기존 `/api/v1/host/ssh/password` GET/POST/DELETE와 관리자 권한·no-store·일회성 비밀번호 표시 계약은 그대로다. 토큰 및 안전 정책 편집 로직과 실제 호스트/장치 쓰기는 변경하지 않았다. 새 CSS·토큰·의존성·API는 없다.

## 커밋과 검증

모든 pytest는 커밋 SHA를 승인된 시험 PC에 전달한 원격 실행이다. 로그와 캡처의 SHA-256은 이 폴더의 manifests에 있으며 경로 기준은 로컬 외부 scratch `C:/DevTemp/rosy-ui-standardization/`이다.

| SHA / 로그 | 실행 결과 | 의미 |
|---|---|---|
| `304d48e943`, ssh-red/run-1.txt | 8 failed, 8 deselected | 작업 오류/발급 receipt 소실과 unmount 뒤 DOM 변경 재현. NEW8/known0/flaky0 |
| `e7256c6299`, ssh-green/run-1.txt | 47 passed, 0 skipped | 기존 remaining-workflows 브라우저 파일 전체와 새39경우, 캡처32장 |
| `e7256c6299`, ssh-affected/run-1.txt | 1 failed, 592 passed, 189 skipped, 46 warnings | 새 가짜 credential 문자열을 secret guard가 탐지. 실패를 숨기거나 검사 예외를 추가하지 않음 |
| `70d4a0e579`, ssh-fixture-affected/run-1.txt | 593 passed, 189 skipped, 46 warnings | 기존 허용 시험 credential을 사용한 공식 affected 재검증, NEW0/known0/flaky0 |
| `70d4a0e579`, ssh-fixture-browser/run-1.txt | 47 passed, 0 skipped | 최종 시험 문자열에서도 전체 브라우저 재검증, NEW0/known0/flaky0 |

e725→70은 시험 credential 문자열만 바뀌었고 runtime 파일은 동일하다. 두47을 고유94건으로 합산하지 않는다. native invocation의189 browser skip을 실행 통과로 세지 않는다. 전체 CI/FULL 또는 Android 검증이 아니다. base→70 네 커밋의 size_range와 safety_review PASS.

브라우저는 POST/DELETE 거절 뒤 GET 성공/실패, 다음 명시적 성공, POST 성공 뒤 GET 실패의 일회 credential 보존, storage 비저장, 초기 조회 잠금, 두 action의 후속 조회 잠금, unmount 뒤 GET/POST/DELETE 응답을 검사한다. 오류 조합32개는 폭320/390/768/1440 × dark/light × POST/DELETE × 후속 조회 성공/실패다. Enter/Space로 명시적 쓰기를 수행한다. API는 fixture이며 실제 비밀번호를 발급하지 않는다.

## 독립 검토와 화면 증거

A는 첫 runtime `2f071bd3d8`의 초기 GET 경합 P2를 찾아 e725의 조회 시작 잠금으로 해결됐음을 확인했다. 최종 runtime 범위의 추가 P1/P2는 없다.

B는 `ssh-captures-final/`의 최종32장을 모두 직접 확인했다. 작업 실패와 현재 상태/조회 실패가 별도 행으로 남고, 조회 실패 시 두 버튼의 비활성 사유가 보인다. 320에서는 사유가 늘어난 버튼이 다음 행으로 이동하며, 다른 폭에서는 입력과 나란히 놓인다. 두 테마에서 문구가 화면 안에 줄바꿈되고 겹침은 없다. Root도320 light POST/조회성공,1440 dark DELETE/조회실패 두 장을 직접 확인했다.

이는 단독 panel fixture의 스크롤된 viewport다. 전체 앱 셸·모바일 폼 하단·초점 링·비활성 사유의 접근성 연결 전부를 이미지로 수용한 것은 아니다. 키보드 동작은 브라우저 assertion과 구분한다. 캡처는 JOB TEMP 밖의 전용 scratch에 보존하고 실행 종료 후32장을 복사했다.

## 게이트와 남은 수용

소스 UI 근거만 추가했다. ARTIFACT/DEVICE/FIELD gate를 올리지 않았다. 실제 SSH·비밀번호 발급/해제·네트워크·로봇 명령·라벨·실제 HF·native 빌드·배포·착지·공개 push/merge는 수행하지 않았다. 전체 UI 표준화와 통합 후보 검증은 별도 진행 중이다.

CE: 해당 없음 — 기존 token/safety 결과 분리 관례와 수명 경계가 최종 코드·회귀·이 실패/복구 기록으로 설명된다. 별도 교훈을 중복하지 않는다.
