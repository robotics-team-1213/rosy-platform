# Task 3: Fleet HTTP client 전환 체크포인트

2026-10-03 Windows Python 3.14.5/Node v24.15.0/Chromium, `refactor/ui-ownership`.

## 변경과 책임

`fleet-client.js`는 Task 2 request 위에서 성공 body와 Fleet `detail.message/code`·status를 해석한다. Console 운용/설치 문서의 기존 `call()`은 이 adapter를 사용하고, 인증 만료의 잠금·성공 시 잠금 해제는 각 문서에 남긴다. `rosy-console-token` sessionStorage, 권한 적용, 선택 기능의 404 gate, 폴링 간격, 명령 의미는 화면이 소유한다. adapter에는 DOM·storage·Mission 성공 판정·재시도를 넣지 않았다.

401의 기존 안내문을 유지하고 status를 추가로 제공한다. 기존 운영 명령은 한 번만 보낸다. 공유 manifest/CMake에 adapter 자산을 함께 등록했다. 카메라 lease/blob/등록 패널의 별도 요청은 아직 이 JSON adapter의 소비자가 아니다.

## 검증

- 구현 전 실제 module 부재로 Node 실패를 확인했다. Fleet adapter·기존 authorization·poll gate Node **18 passed**.
- ownership 시험은 façade의 실제 함수와 실제 Fleet adapter/request를 함께 실행한다. 서버 static/Node/ownership/asset manifest 재검사는 **53 passed**.
- Fleet 전체 첫 실행은 **1584 passed, 7 skipped, 1 failed**였다. 새 static 자산 확인에 필요한 `web_common` 경로를 그 시험 fixture에 명시해 수정했고 위 53개 재검사에 포함했다. 이 첫 전체 실행을 무실패 실행으로 표현하지 않는다.
- 실제 두 HTML/JS를 읽는 Chromium 시험은 같은 origin의 문서 이동, sessionStorage 유지, 401 잠금, 새 토큰 복구, 이전 정지 명령의 자동 재전송 없음, 다른 origin에 token을 보내지 않음을 검사한다. 독점 서버와 현재 source bytes가 같은 X: 사본의 세션/origin **3 passed**를 확인했다. 화면 잠금 호출을 제거하면 실제 Chromium이 실패하고, bytes 복원 후 3개가 다시 통과한다.
- Windows 시험 서버의 SO_REUSEADDR가 다른 병행 fixture의 파일을 반환할 수 있음을 HTTP 응답으로 발견했다. 이전 병행 브라우저 결과는 수용 근거에서 제외했다. 독점 바인딩, 확장한 안전 포트 범위, shutdown/close/join, 요청한 JS와 현재 파일 bytes의 비교로 시험 경계를 보강했다.
- 변이는 현재 source와 bytes가 같은 X: 사본에서만 실행해 병행 회귀를 오염시키지 않는다. Fleet 오류 status 제거는 Node 실패를 만든다. 사본/로그는 `X:/DevTemp/rosy-ui-ownership/task3-mutations/`에 둔다.
- quick·ownership·roles·request/scope·asset 검사 **136 passed**, lint **0 errors, 26 warnings**. 첫 quick 실패는 새 작업 로그의 잘못된 `###` 구분자로 마지막 기존 항목에 붙은 것이었고, 새 미커밋 항목만 `##`와 필수 필드로 바로잡아 재검사했다. 이전 로그 bytes는 보존했다.
- 전체 Chromium 회귀 비교를 완료했다. 전환 전 `51f17c505` Console/install source의 baseline은 **45 passed, 22 failed**, HTTP 전환 체크포인트 `ab40eb56`은 **48 passed, 22 failed**였다. 실패 node ID 집합 22개가 정확히 같고 **new failures 0**이다. 추가 세션/origin 3개는 통과했다. baseline은 같은 나머지 정적 자산·독점 fixture를 사용하고 두 entry source만 HTTP 전환 전 버전으로 대체했다. 비교/실패 목록은 `X:/DevTemp/rosy-ui-ownership/task3-browser-comparison.json`에 있다. 전체 무실패나 Task 3 완료 증거로 표현하지 않는다.
- 최신 main 병합 후 공유 UI/static/ownership/quick 검사 **364 passed, 24 skipped**, lint **0 errors, 26 warnings**를 확인했다. skip은 browser 수용으로 계산하지 않는다.
- 동일하게 재현된 안전 행 시험 2개는 옛 `SAFETY`/`E-STOP` 문구 대신 현재 `data-fact="safety"`·한국어 표시로 연결했다. **2 passed**이며, 목표 버튼의 estop/안전 정보 부재 guard를 제거하면 **2 failed**가 되고 원본 bytes 복원 후 **2 passed**였다. 제품 권한과 안전 규칙은 바꾸지 않았다. 이 2개 외 전체 20개 기존 실패는 후속 화면/브라우저 수용에서 해결해야 한다. 전체 suite를 다시 실행해 50 passed로 계산하지 않는다.

## 남은 Task 3 범위

이 HTTP 체크포인트 당시에는 화면 종료·토큰 교체 scope가 미완료였다. 후속 [Console lifetime 증거](task3-console-lifetime.md)에서 JSON/직접 fetch·panel callback·finally·구독을 함께 연결하고 Node·Chromium·변이 검증을 완료했다. 이전 HTTP 체크포인트의 시험 결과는 당시 범위의 기록으로 보존한다.

이 체크포인트는 SOURCE/LOCAL HTTP·세션 수용이며 Task 3 전체 출구, 설치 산출물, DEVICE/FIELD 수용이 아니다. Tasks 4–13과 D-413 의존 gate는 계속 남는다.
