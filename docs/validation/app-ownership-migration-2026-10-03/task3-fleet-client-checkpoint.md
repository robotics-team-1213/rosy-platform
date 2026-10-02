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
- 전체 Chromium 회귀는 진행 중이며 실패를 포함한다. 첫 안전 행 실패는 HTTP 전환 전 `HEAD`의 Console/install source를 X:에 복제한 baseline에서도 같은 `SAFETY` selector timeout으로 재현했다. 현재 renderer는 `data-fact="safety"`·한국어 이름을 사용한다. 전체 전환 전/후 비교가 끝나기 전까지 전체 브라우저 무회귀를 주장하거나 Task 3 완료로 처리하지 않는다.

## 남은 Task 3 범위

화면 종료·토큰 교체에 Task 2 scope를 연결하는 작업은 아직 하지 않았다. JSON façade만 취소하는 것으로 완료를 선언하지 않는다. map/formation/roster/등록/카메라 callback의 catch/finally와 lease/blob·image decode까지 조사하고, 종료 후 요청·timer·늦은 repaint가 0인지 실제 브라우저로 검증해야 한다. BFCache 복귀에서도 읽기 연결만 다시 세우고 이전 명령을 재전송하지 않는다.

이 체크포인트는 SOURCE/LOCAL HTTP·세션 수용이며 Task 3 전체 출구, 설치 산출물, DEVICE/FIELD 수용이 아니다. Tasks 4–13과 D-413 의존 gate는 계속 남는다.
